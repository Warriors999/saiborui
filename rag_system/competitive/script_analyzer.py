"""Analyze competitor video scripts using our existing auditor + prompt patterns."""

from openai import OpenAI

from rag_system.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from rag_system.generation.auditor import (
    audit_script, SPOKEN_MARKERS, FORBIDDEN_WORDS,
    ECOMMERCE_SMELL, _count_attitudes,
)
from rag_system.generation.prompts import PERSONA_PROFILES, CATEGORY_CONTEXT
from rag_system.competitive.models import VideoProfile, AnalysisResult


def analyze_transcript(video: VideoProfile, transcript: str) -> AnalysisResult:
    """Run full script analysis on a competitor's transcribed voiceover."""
    result = AnalysisResult(video=video, transcript=transcript)
    result.transcript_chars = len(transcript)

    # 1. Run existing auditor
    audit = audit_script(transcript, key_points="", duration_minutes=3.0)
    result.spoken_density = audit.scores.get("口语化", 0) / 100 * 2.0
    result.attitude_density = _count_attitudes(transcript)[0] / (len(transcript) / 200)
    result.forbidden_word_count = sum(1 for w in FORBIDDEN_WORDS if w in transcript)
    result.ecommerce_smell_count = sum(1 for w in ECOMMERCE_SMELL if w in transcript)

    # 2. Detect hook type
    result.hook_type, result.hook_text = _detect_hook(transcript)

    # 3. Estimate narrative arc
    result.narrative_arc, result.act_boundaries = _estimate_arc(transcript)

    # 4. Sentence rhythm
    sentences = [s.strip() for s in transcript.replace("！", "。").replace("？", "。").split("。") if s.strip()]
    if sentences:
        short = sum(1 for s in sentences if len(s) <= 15)
        long = sum(1 for s in sentences if len(s) >= 50)
        result.short_sentence_pct = short / len(sentences) * 100
        result.long_sentence_pct = long / len(sentences) * 100

    # 5. Identify standout patterns
    result.standout_patterns = _find_patterns(transcript, video.category)
    result.applicable_to_categories = [video.category] if video.category else []

    return result


def _detect_hook(transcript: str) -> tuple[str, str]:
    """Detect which of 5 hook types is used, return (type, hook_text)."""
    # Take first ~30 chars as hook text
    hook = transcript[:60].strip() if len(transcript) > 60 else transcript.strip()

    patterns = {
        "情绪爆发": ["我滴妈", "好家伙", "你敢信", "没看错吧", "掀桌", "太炸裂了"],
        "热梗共鸣": ["玩烂了", "都知道", "跟风", "卷", "以前总说"],
        "数字冲击": [r"^\d+帧", r"^\d+万", r"^\d+元", r"^\d+个", r"^\d+%"],
        "场景痛点": ["有没有", "你是不是", "为什么", "每个人都", "难受", "困扰"],
        "反常识": ["居然", "没想到", "不敢相信", "违反常识", "怎么可能"],
    }

    import re
    for hook_type, keywords in patterns.items():
        for kw in keywords:
            if re.search(kw, hook):
                return hook_type, hook

    return "情绪爆发", hook  # default


def _estimate_arc(transcript: str) -> tuple[str, list[int]]:
    """Estimate narrative arc boundaries from transcript."""
    total = len(transcript)
    boundaries = []
    arc_type = "钩-展-收 (三段式)"

    # Find transition keywords to estimate act boundaries
    transitions = {
        "reveal": ["设计说完", "先看外观", "包装", "开箱", "打开"],
        "deep_dive": ["核心", "配置", "性能", "重点", "卖点"],
        "proof": ["实测", "跑分", "游戏", "帧率", "数据"],
        "summary": ["总结", "最后", "有一说一", "整体", "值得", "推荐"],
    }

    for act, keywords in transitions.items():
        for kw in keywords:
            idx = transcript.find(kw)
            if idx > 0:
                boundaries.append(idx)
                break

    boundaries.sort()
    return arc_type, boundaries


def _find_patterns(transcript: str, category: str) -> list[str]:
    """Identify standout writing patterns in the transcript."""
    patterns = []

    # Check for unique techniques
    if "你品" in transcript or "你细品" in transcript:
        patterns.append("品字句节奏")
    if "说白了" in transcript or "简单来说" in transcript:
        patterns.append("口语化过渡")
    if transcript.count("？") >= 3:
        patterns.append("高密度反问句式")
    if any(kw in transcript for kw in ["兄弟们", "彦祖", "大伙儿"]):
        patterns.append("直接称呼建立亲近感")
    if any(kw in transcript for kw in ["有一说一", "不吹不黑"]):
        patterns.append("公正客观信号词")

    # Category-specific
    cat_patterns = {
        "keyboard": ["麻将音", "HIFI", "轴体", "Gasket", "填充"],
        "mouse": ["模具", "握持", "传感器", "微动", "GPW"],
        "monitor": ["面板", "刷新率", "GTG", "色域", "HDR"],
    }
    if category in cat_patterns:
        found = [kw for kw in cat_patterns[category] if kw in transcript]
        if found:
            patterns.append(f"{category}专业术语: {', '.join(found[:3])}")

    return patterns


def deep_analyze(transcript: str, category: str, video_title: str, hook_type: str,
                 visual: dict = None, visual_frames_analysis: str = "",
                 audio: dict = None) -> dict:
    """Four-dimension deep analysis: script + visual composition + editing + VFX.

    Accepts data from all pipeline stages and produces an integrated learning report
    covering what a content creator needs: copywriting, cinematography, editing, and
    post-production techniques.
    """
    if not DEEPSEEK_API_KEY:
        return {"error": "DeepSeek API key not configured"}

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    # ── Build comprehensive context ──

    # Shot data
    visual_context = ""
    if visual and not visual.get("error"):
        transitions = visual.get("transitions", {})
        visual_context = f"""
【剪辑数据】
- 镜头数: {visual.get('shot_count', 'N/A')}
- 视频时长: {visual.get('duration_sec', 'N/A')}秒
- 平均镜头时长: {visual.get('avg_shot_sec', 'N/A')}秒
- 剪辑频率: {visual.get('cuts_per_minute', 'N/A')}次/分钟
- 短镜头(≤2s)占比: {visual.get('short_shots_pct', 'N/A')}%
- 中镜头(2-5s)占比: {visual.get('medium_shots_pct', 'N/A')}%
- 长镜头(>5s)占比: {visual.get('long_shots_pct', 'N/A')}%
- 剪辑节奏类型: {transitions.get('dominant', 'N/A')}
"""

    # Frame-level visual analysis
    frames_context = ""
    if visual_frames_analysis and "失败" not in visual_frames_analysis:
        frames_context = f"""
【画面构图分析（基于关键帧）】
{visual_frames_analysis}
"""

    # Audio data
    audio_context = ""
    if audio and not audio.get("error"):
        audio_context = f"""
【音频数据】
- BGM变化次数: {audio.get('bgm_changes', 'N/A')}
- 音效估计: ~{audio.get('sfx_estimated', 'N/A')}个
- 静音占比: {audio.get('silent_ratio', 'N/A')}%
- 平均音量: {audio.get('avg_volume_db', 'N/A')}dB
"""

    prompt = f"""你是顶级短视频战略分析师，专门从"爆款归因"角度拆解竞品。你的核心任务不是描述"这个视频做了什么"，而是回答"它为什么能爆？解决了用户什么需求？我选题时能学到什么？"

视频: {video_title}
品类: {category}
钩子类型: {hook_type}

【口播脚本】
{transcript[:3000]}

{visual_context}
{frames_context}
{audio_context}

═══════════════════════════════════════
零、爆款归因与选题策略 ⚠️ 最重要
═══════════════════════════════════════

1. 爆款原因归因 — 这条视频为什么能火？
   - 不要浮于表面（"因为标题党"），要追溯到用户心理底层机制
   - 具体到这个视频：是制造了信息差？身份认同？情感共鸣？损失厌恶？社交货币？
   - 播放量/互动数据背后，到底是什么心理驱动了传播？

2. 核心用户需求 — 它解决了什么深层需求？
   - 不是"用户想买XX产品"这种表面需求
   - 而是：选择焦虑需要一个确定答案？价格敏感需要"占了便宜"的确认感？信息过载需要一个简洁决策依据？身份焦虑需要"看懂参数"的安全感？
   - 具体到这个品类、这个价位段，用户真实痛点是什么？视频怎么精准戳中？

3. 内容解决方案 — 它用什么方式满足了需求？
   - 内容结构+表达手法+信息节奏，每个维度为什么有效？
   - 换一种方式（比如纯参数罗列/纯情感渲染）为什么不行？
   - 关键说服逻辑是怎样层层递进的？

4. 选题策略启示 — 我能学到什么？
   - 时机选择：为什么在这个时间点发？跟品类周期/产品发布/消费节点/平台趋势有什么关系？
   - 角度选择：同类选题有无数切入点，为什么这个角度能赢？差异化在哪？
   - 受众选择：瞄准哪类用户？新手/进阶/极客/价格敏感/颜值党/参数党？
   - 冲突设计：有没有设计认知冲突或信息差？冲突的张力是什么？

5. 选题优秀点 — 多维度评分（每项1-10分，附一句话理由）
   - 选题角度独特性：
   - 用户需求匹配度：
   - 信息增量价值：
   - 情绪张力/传播力：
   - 可复制性/可系列化：
   - 时效性窗口把握：

6. D先生选题改编方案：
   - 基于这个选题策略，D先生用什么角度重新切入？（不是模仿原视频！）
   - 提取选题策略本质，用更专业、更高信息密度、更有技术说服力的方式重做
   - 示例：如果原选题是"XX价位最值得买的显卡"，D先生可以做成"XX价位显卡为什么只有它能做到这三点——供应链逻辑拆解"

═══════════════════════════════════════
一、文案拆解 — 怎么说的
═══════════════════════════════════════
1. 脚本结构: 分几段？每段分别讲什么？（这条视频的实际段落，不是通用模板）
2. 开场钩子: 第一句话/第一个画面为什么让人不划走？（心理机制：信息差/身份代入/反常识/损失厌恶/社交货币？）
3. 句式技巧: 摘录3-5个原文句子，标注技巧类型（数字锚定/类比简化/痛点共鸣/权威背书/认知反差/身份代入/悬念前置等），解释为什么在这个视频语境下有效
4. D先生改编方案

═══════════════════════════════════════
二、视觉构图 — 怎么拍的
═══════════════════════════════════════
1. 产品呈现方式: 居中桌拍/手持/场景化/拆解特写/对比排列？段落间变化？
2. 灯光方案: 硬光/柔光？RGB氛围灯？色温？
3. 拍摄角度序列
4. D先生可复用拍摄模板

═══════════════════════════════════════
三、剪辑节奏 — 怎么切的
═══════════════════════════════════════
1. 整体节奏与口播配合
2. 转场手法与剪辑点设计
3. 段落节奏分布
4. D先生分镜节奏建议

═══════════════════════════════════════
四、特效包装 — 怎么包装的
═══════════════════════════════════════
1. 花字/文字叠加的样式、位置、时机
2. 动画效果
3. 音效卡点与BGM配合
4. D先生可复用包装模板

直接输出中文分析。每个维度之间用═══分隔。不写"分析结论""总结"套话。每个观点必须基于本条视频具体内容，禁止套通用模板。"""

    try:
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=2500,
        )
        text = response.choices[0].message.content.strip()
        return {"deep_analysis": text, "status": "ok"}
    except Exception as e:
        return {"error": str(e)}
