"""Douyin/TikTok prohibited words filter.

Filters content before output to avoid platform compliance issues.
Replaces prohibited terms with safer alternatives rather than just removing them.
"""

import re

# Phrases that MUST be replaced (exact match, whole word/phrase)
PROHIBITED_PHRASES: dict[str, str] = {
    # ---- Absolute / extreme claims ----
    "第一品牌": "一线品牌",
    "行业第一": "行业领先",
    "销量第一": "销量领先",
    "全国第一": "行业前列",
    "全网第一": "全网领先",
    "全球第一": "全球领先",
    "第一名": "头部队列",
    "首选品牌": "推荐品牌",
    "不二之选": "不错之选",
    "最佳选择": "理想选择",
    "最好的": "出色的",
    "最强的": "强劲的",
    "最大": "大型",
    "最小": "紧凑",
    "最高": "顶配",
    "最低价": "好价",
    "顶级性能": "旗舰性能",
    "顶级配置": "旗舰配置",
    "最强性能": "旗舰性能",
    "唯一": "独有",
    "独有": "特有",
    "独一份": "少见",
    "独一无二": "独具特色",
    "天花板": "顶级水准",
    "封神": "出色",
    "毕业级": "一步到位级",
    "毕业": "一步到位",
    "独家": "特有",
    "绝无仅有": "少见",
    "史无前例": "前所未有",
    "前无古人": "突破性",
    "全能": "多功能",
    "万能": "多用途",
    "完美": "出色",
    "极致体验": "出色体验",
    "极致性能": "满血性能",
    "极致": "出色",
    # ---- Numerical / percentage claims ----
    "100%": "近乎全部",
    "百分百": "近乎全部",
    "百分之百": "近乎全部",
    "0风险": "低风险",
    "零风险": "低风险",
    "零差评": "好评如潮",
    "零延迟": "极低延迟",
    # ---- Permanence / guarantee claims ----
    "永不": "长久",
    "永久免费": "长期免费",
    "永久": "长期",
    "终身保修": "长期质保",
    "终身": "长期",
    # ---- Competitor disparagement ----
    "完爆": "优于",
    "秒杀": "超越",
    "碾压": "领先",
    "吊打": "强过",
    "垃圾产品": "低端产品",
    "智商税": "不划算",
    # ---- Investment / money claims ----
    "稳赚": "划算",
    "稳赚不赔": "很划算",
    "包赚": "超值",
    "必赚": "值得入手",
    "收益最高": "收益可观",
    "收益保证": "收益预期",
    "躺着赚钱": "轻松省钱",
    "一夜暴富": "大幅提升",
    # ---- Medical / health claims ----
    "治疗": "缓解",
    "治愈": "改善",
    "特效药": "有效产品",
    "药效": "效果",
    "疗效": "效果",
    "包治": "有效缓解",
    # ---- Superstition ----
    "开光": "加持",
    "转运": "改变运势",
    "招财": "寓意吉祥",
    "辟邪": "守护平安",
}

# Regex patterns for context-sensitive replacements
PROHIBITED_PATTERNS: list[tuple[str, str]] = [
    # "最XX" but NOT "最近" / "最新" / "最终" / "最初" / "最为" / "最XX的"
    (r"(?<![最])最(?!近|新|终|初|为|后|多|少|大|小|高|低|快|慢|好|差|强|弱)", "更"),
    # "全网" patterns
    (r"全网最低", "全网低价"),
    (r"全网最高", "全网高配"),
    # "绝对" patterns
    (r"绝对(优势|领先|第一|最好|最强)", r"明显\1"),
    # "国家级" / "世界级"
    (r"国家级", "行业级"),
    # "首家" / "首发"
    (r"首家", "率先"),
]


def filter_prohibited(text: str) -> tuple[str, list[str]]:
    """Filter prohibited words from text.
    Returns (filtered_text, list_of_replacements_made).
    """
    changes: list[str] = []
    result = text

    # Phase 1: Exact phrase replacement
    for prohibited, replacement in PROHIBITED_PHRASES.items():
        if prohibited in result:
            result = result.replace(prohibited, replacement)
            changes.append(f"「{prohibited}」→「{replacement}」")

    # Phase 2: Regex pattern replacement
    for pattern, replacement in PROHIBITED_PATTERNS:
        matches = re.findall(pattern, result)
        if matches:
            result = re.sub(pattern, replacement, result)
            for m in matches[:3]:
                changes.append(f"「{m}」(正则) → 已替换")

    return result, changes


def validate_no_prohibited(text: str) -> list[str]:
    """Check text for remaining prohibited words. Returns list of violations found."""
    violations = []
    for phrase in PROHIBITED_PHRASES:
        if phrase in text:
            violations.append(phrase)
    return violations


# ── Filler phrase density reducer ──
# These are "口头禅" that the competitive wiki marks as 应避免的低级套路.
# They add no information and make the speaker sound uncertain.
# Strategy: remove standalone instances, reduce consecutive clusters to at most 1.

FILLER_PHRASES = [
    "说实话", "有一说一", "不吹不黑", "懂的都懂",
    "我个人觉得", "我个人感觉", "你品", "你细品",
    "真就绝了", "没谁了", "你自己品",
]

# Patterns where a filler is the ENTIRE sentence (just the filler + optional punctuation)
FILLER_STANDALONE = re.compile(
    r'(?:^|\n)(' + '|'.join(re.escape(f) for f in FILLER_PHRASES) + r')(?:[。！？，,\.\s]*(?:\n|$))',
    re.MULTILINE,
)

# Filler clusters: 2+ fillers in a row (with optional whitespace/punctuation between)
FILLER_CLUSTER = re.compile(
    r'(' + '|'.join(re.escape(f) for f in FILLER_PHRASES) + r')'
    r'(?:[。！？，,\s]{0,4}'
    r'(' + '|'.join(re.escape(f) for f in FILLER_PHRASES) + r'))+',
)

# "我用下来" / "我用下来发现" — keep at most 1 per paragraph.
# First pass: mark paragraphs, then limit to 1 instance per paragraph.
OVERUSED_I_USED = re.compile(r'我用下来[发现]?[。，]?')


def reduce_filler_phrases(text: str) -> tuple[str, int]:
    """Reduce filler phrase density in generated scripts.

    Competitive wiki analysis shows that phrases like 说实话/有一说一/不吹不黑
    are the #2 most common quality issue in tech review scripts (72% violation rate).

    Returns (filtered_text, number_of_removals).
    """
    removals = 0
    result = text

    # Step 1: Remove standalone filler "sentences" (filler + period + newline)
    new_result = FILLER_STANDALONE.sub('', result)
    removals += len(result) - len(new_result)
    result = new_result

    # Step 2: Collapse filler clusters to single instance
    def _collapse_cluster(m):
        nonlocal removals
        # Keep only the first filler in the cluster
        parts = m.group(0).split()
        removals += 1
        return m.group(1)  # just the first filler

    # Don't auto-collapse — just remove redundant fillers in obvious clusters
    for filler in FILLER_PHRASES:
        # Remove filler when it appears right before another filler
        for other in FILLER_PHRASES:
            if filler != other:
                pattern = re.escape(filler) + r'[。！？，,\s]{0,4}' + re.escape(other)
                if re.search(pattern, result):
                    result = re.sub(pattern, other, result)
                    removals += 1

    # Step 3: Limit "我用下来" to once per paragraph
    paragraphs = result.split('\n\n')
    cleaned_paras = []
    for para in paragraphs:
        matches = list(OVERUSED_I_USED.finditer(para))
        if len(matches) > 1:
            # Keep first, remove rest
            for m in matches[1:]:
                para = para[:m.start()] + para[m.end():]
                removals += 1
        cleaned_paras.append(para)
    result = '\n\n'.join(cleaned_paras)

    # Step 4: Clean up double punctuation from removals
    result = re.sub(r'[。！？]{2,}', '。', result)
    result = re.sub(r'\n{3,}', '\n\n', result)
    result = re.sub(r'  +', ' ', result)

    return result, removals
