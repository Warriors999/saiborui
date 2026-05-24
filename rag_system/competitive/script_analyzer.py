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


def deep_analyze(transcript: str, category: str, video_title: str, hook_type: str, visual: dict = None) -> dict:
    """Use LLM to extract actionable creative learnings from a competitor script.

    Returns structured insights a content creator can directly apply.
    """
    if not DEEPSEEK_API_KEY:
        return {"error": "DeepSeek API key not configured"}

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    visual_context = ""
    if visual and not visual.get("error"):
        visual_context = f"""
视频视觉/剪辑数据:
- 检测到镜头数: {visual.get('shot_count', 'N/A')}
- 视频时长: {visual.get('duration_sec', 'N/A')}秒
- 平均镜头时长: {visual.get('avg_shot_sec', 'N/A')}秒
- 剪辑频率: {visual.get('cuts_per_minute', 'N/A')}次/分钟
- 短镜头(≤2s)占比: {visual.get('short_shots_pct', 'N/A')}%
- 中镜头(2-5s)占比: {visual.get('medium_shots_pct', 'N/A')}%
- 长镜头(>5s)占比: {visual.get('long_shots_pct', 'N/A')}%
"""

    prompt = f"""你是一位顶级短视频创作分析师，精通文案和视觉两方面的拆解。请深度分析以下竞品视频，提取可操作的创作学习点。

视频: {video_title} | 品类: {category} | 检测到的钩子类型: {hook_type}

口播脚本:
{transcript[:3000]}

{visual_context}
请从以下7个维度输出结构化的学习要点（每点1-3句话，直接可用）:

1. 脚本结构拆解
   - 这个脚本分几段？每段讲什么？时间占比大概多少？

2. 开场钩子分析
   - 为什么这个开头能让观众不划走？（具体的心理机制）
   - D先生如果写同品类开头，可以怎么借鉴？

3. 值得学习的句式/技巧（带原文摘录）
   - 找出3-5个具体的句子或过渡手法，解释为什么有效
   - 标注是哪种技巧（数字锚定/类比简化/痛点共鸣/权威背书/等等）

4. 改编建议
   - 如果D先生（硬核技术流数码博主，口语化极强，常用"兄弟们""我滴妈""有一说一"）
   - 来写同品类产品脚本，应该怎么改编这个脚本的结构和风格？

5. 可复制模式
   - 这个创作者有什么可以被系统化复制的创作模式？
6. 视觉与剪辑节奏分析
   - 根据剪辑数据（如果提供了），分析这个视频的视觉节奏
   - 快慢切是如何配合口播内容的？哪个段落节奏最快/最慢？
   - 如果D先生做同品类分镜，应该用什么样的镜头节奏？
7. 拍摄手法推断
   - 从口播内容推断可能的拍摄手法（比如念到材质时可能是微距特写，念到尺寸对比时可能是俯拍桌面对比）
   - 推测画面与口播的对应关系

请直接输出中文，每条前用数字+标题标注。不要写"分析结论"之类的套话。"""

    try:
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=2000,
        )
        text = response.choices[0].message.content.strip()
        return {"deep_analysis": text, "status": "ok"}
    except Exception as e:
        return {"error": str(e)}
