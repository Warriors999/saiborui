"""Analyze competitor video scripts using our existing auditor + prompt patterns."""

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
