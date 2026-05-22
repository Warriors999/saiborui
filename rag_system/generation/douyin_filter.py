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
    "独一无二": "独具特色",
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
