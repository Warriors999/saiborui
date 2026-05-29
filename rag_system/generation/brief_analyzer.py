"""Brief → 卖点取舍引擎。

Parses client brief documents, extracts selling points with priorities,
cross-references RAG data for historical audience interest patterns,
and outputs structured editorial recommendations.

Output format:
  - Priority-ranked selling points
  - Deep-dive vs mention-only vs huazi-only classification
  - Client must-mentions (enforced)
  - Content DON'Ts (warnings to inject into generation prompt)
  - Recommended narrative structure with time allocation
"""

import re
from dataclasses import dataclass, field
from collections import Counter


@dataclass
class SellingPoint:
    name: str                    # e.g., "第五代骁龙8至尊领先版"
    priority: int = 5            # 1-10, 10=highest
    proportion: float = 0        # time allocation %, e.g., 0.35
    must_mention: bool = False   # client enforced
    hook_candidate: bool = False # could be the opening hook
    deep_dive: bool = True       # detailed treatment vs quick mention
    key_phrases: list[str] = field(default_factory=list)  # phrases to include
    avoid_phrases: list[str] = field(default_factory=list) # DO NOT say


@dataclass
class BriefAnalysis:
    product_name: str
    category: str = ""           # detected product category
    target_duration: str = ""    # e.g., "3-5分钟"
    publish_time: str = ""
    selling_points: list[SellingPoint] = field(default_factory=list)
    must_mentions: list[str] = field(default_factory=list)
    content_donts: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    cover_suggestion: str = ""
    total_proportion: float = 0


def parse_brief(framework_text: str, detail_text: str = "") -> BriefAnalysis:
    """Parse one or two brief documents into structured analysis.

    Args:
        framework_text: The creative brief with proportions/framework
        detail_text: The detailed spec guide (optional, for deep reference)
    """
    combined = framework_text + "\n" + detail_text
    analysis = BriefAnalysis(
        product_name=_extract_product_name(combined),
        category=_detect_category(combined),
        target_duration=_extract_duration(combined),
        publish_time=_extract_publish_time(combined),
    )

    # ── Parse selling points from framework ──
    analysis.selling_points = _extract_selling_points(framework_text)

    # ── Detect must-mentions ──
    analysis.must_mentions = _extract_must_mentions(combined)
    for sp in analysis.selling_points:
        if any(m in sp.name for m in analysis.must_mentions):
            sp.must_mention = True

    # ── Detect content DON'Ts ──
    analysis.content_donts = _extract_donts(combined)

    # ── Hashtags ──
    analysis.hashtags = _extract_hashtags(combined)

    # ── Cover suggestion ──
    analysis.cover_suggestion = _extract_cover_suggestion(combined)

    # ── Determine hook candidates (highest priority + most unique) ──
    hook_keywords = ["首发", "行业首次", "独家", "百里挑一", "最强", "第一"]
    for sp in analysis.selling_points:
        if any(kw in sp.name for kw in hook_keywords):
            sp.hook_candidate = True
            break

    return analysis


def generate_recommendation(analysis: BriefAnalysis, persona: str = "折腾到吐") -> str:
    """Generate editorial recommendation from brief analysis.

    Outputs a structured guide for the content creator:
      - What to make the hook
      - Deep dive order
      - What to mention only briefly
      - Client enforced items
      - What NOT to say
    """
    lines = []
    lines.append(f"## {analysis.product_name} — 卖点取舍建议")
    lines.append(f"目标时长：{analysis.target_duration} | 人设：{persona}")
    lines.append(f"发布时间：{analysis.publish_time}")
    lines.append("")

    # Sort by priority
    sps = sorted(analysis.selling_points, key=lambda s: (-s.priority, -s.proportion))

    # ── Hook ──
    hook = next((s for s in sps if s.hook_candidate), sps[0] if sps else None)
    if hook:
        lines.append(f"### 推荐 Hook")
        lines.append(f"用「{hook.name}」开场——{', '.join(hook.key_phrases[:3]) if hook.key_phrases else '直接说最炸的点'}")
        lines.append("")

    # ── Deep Dive (priority >= 7 OR proportion >= 20%) ──
    deep = [s for s in sps if s.deep_dive or s.priority >= 7 or s.proportion >= 0.15]
    if deep:
        lines.append(f"### 深挖卖点（{len(deep)}个，占主要时长）")
        for i, sp in enumerate(deep, 1):
            must = " [必提]" if sp.must_mention else ""
            pct = f"{sp.proportion*100:.0f}%" if sp.proportion else ""
            lines.append(f"{i}. {sp.name}{must} {pct}")
            if sp.key_phrases:
                lines.append(f"   关键词：{' | '.join(sp.key_phrases[:5])}")
            if sp.avoid_phrases:
                lines.append(f"   避雷：{' / '.join(sp.avoid_phrases[:3])}")
        lines.append("")

    # ── Mention only (lower priority, one sentence or huazi) ──
    mention = [s for s in sps if s not in deep and s.priority >= 3]
    if mention:
        lines.append(f"### 一笔带过（{len(mention)}个，放在花字或一句话）")
        for sp in mention:
            lines.append(f"- {sp.name} → 花字标注 + 口播一句话")
        lines.append("")

    # ── Must-mentions (client enforced) ──
    if analysis.must_mentions:
        lines.append(f"### ⚠ 甲方强制要求（必须出现在脚本中）")
        for m in analysis.must_mentions:
            lines.append(f"- {m}")
        lines.append("")

    # ── Content DON'Ts ──
    if analysis.content_donts:
        lines.append(f"### 🚫 禁止")
        for d in analysis.content_donts[:6]:
            lines.append(f"- {d}")
        lines.append("")

    # ── Hashtags ──
    if analysis.hashtags:
        lines.append(f"### 话题标签")
        lines.append(" ".join(analysis.hashtags))
        lines.append("")

    # ── Cover ──
    if analysis.cover_suggestion:
        lines.append(f"### 封面建议")
        lines.append(analysis.cover_suggestion)

    return "\n".join(lines)


# ============================================================
# Parsing helpers
# ============================================================

def _detect_category(text: str) -> str:
    """Detect product category from brief keywords."""
    CATEGORY_KEYWORDS = {
        "keyboard": ["键盘", "键帽", "轴体", "磁轴", "机械键盘", "Gasket", "键位"],
        "mouse": ["鼠标", "轻量化", "DPI", "传感器", "微动", "PAW", "回报率", "滚轮"],
        "laptop": ["笔记本", "游戏本", "轻薄本", "处理器", "独显", "RTX"],
        "headphone": ["耳机", "降噪", "头戴式", "TWS", "入耳"],
        "monitor": ["显示器", "屏幕", "HDR", "分辨率", "刷新率", "IPS", "VA"],
        "phone": ["手机", "骁龙", "iPhone", "安卓"],
        "gpu": ["显卡", "GPU", "显存", "RTX", "GTX"],
        "desk_chair": ["桌椅", "电竞椅", "人体工学", "升降桌"],
        "speaker": ["音箱", "音响"],
    }
    scores = {}
    for cat, kws in CATEGORY_KEYWORDS.items():
        scores[cat] = sum(1 for kw in kws if kw in text)
    best = max(scores, key=scores.get)
    return best if scores[best] >= 2 else "other"


def _extract_product_name(text: str) -> str:
    # Try explicit patterns first
    patterns = [
        r'(?:产品名称|产品名|产品)[：:]\s*(.+?)(?:\n|$)',
        r'^(.+?)(?:新品信息|产品信息|Brief|brief)',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.MULTILINE)
        if m:
            name = m.group(1).strip()
            if len(name) >= 3 and len(name) <= 40:
                return name
    # Fallback: first non-empty line as product name
    first_line = text.strip().split("\n")[0].strip()
    return first_line[:40] if len(first_line) >= 2 else "新产品"


def _extract_duration(text: str) -> str:
    m = re.search(r'(?:时长|正片|视频).{0,5}(\d+[-~]\d+\s*分)', text)
    return m.group(1) if m else "3-5分钟"


def _extract_publish_time(text: str) -> str:
    m = re.search(r'(?:发布时间|解禁时间).{0,10}?(\d{4}年\d{1,2}月\d{1,2}日.{0,8}(?:\d{1,2}:\d{2}))', text)
    return m.group(1) if m else ""


def _extract_selling_points(text: str) -> list[SellingPoint]:
    """Extract selling points from framework brief.

    Matches patterns like '性能（占比35%）' using known section names.
    """
    # Known section names → canonical display name
    SECTION_NAMES = [
        (["性能"], "性能"),
        (["游戏体验", "游戏"], "游戏体验"),
        (["散热系统", "散热"], "散热系统"),
        (["全面屏展现", "全面屏", "屏幕"], "全面屏展现"),
        (["赛事合作", "赛事"], "赛事合作"),
        (["续航"], "续航"),
        (["触控"], "触控"),
        (["美学", "设计"], "美学设计"),
        (["AI", "智慧"], "AI智慧"),
    ]

    # Find all (占比N%) markers and their positions in text
    markers = list(re.finditer(r'[（(]\s*(?:占比\s*)?(\d+)\s*%\s*([^）)]*)[）)]', text))

    points = []
    for i, m in enumerate(markers):
        pct = int(m.group(1))
        extra = m.group(2)  # e.g., "，必带"
        must = "必带" in extra
        pos = m.start()

        # Find the nearest known section name BEFORE this marker
        preceding = text[max(0, pos-30):pos]
        best_name = ""
        for keywords, canonical in SECTION_NAMES:
            for kw in keywords:
                if kw in preceding:
                    best_name = canonical
                    break
            if best_name:
                break
        if not best_name:
            continue

        # Extract content between this marker and the next
        start = m.end()
        end = markers[i+1].start() if i+1 < len(markers) else min(start + 600, len(text))
        content = text[start:end]

        sp = SellingPoint(
            name=best_name,
            proportion=pct / 100,
            priority=_proportion_to_priority(pct),
            must_mention=must,
            deep_dive=(pct >= 15),
            key_phrases=_extract_key_phrases(content),
            hook_candidate=("首发" in content or "行业首次" in content or "独家" in content or "最强" in content or "百里挑一" in content),
        )
        points.append(sp)

    if points and len(points) >= 2:
        return points
    # Low yield from structured format — try natural-language extraction
    natural = _extract_from_natural_brief(text)
    return natural if natural and len(natural) >= 2 else (points or _extract_selling_points_fallback(text))


def _extract_from_natural_brief(text: str) -> list[SellingPoint]:
    """Extract selling points from natural-language briefs without (占比%) markers.

    Handles briefs structured with numbered sections, bullet points, or
    product-name headers. Prioritizes specs, features, and unique attributes.
    """
    points = []
    # Split by numbered sections or product headers
    sections = re.split(r'\n(?=(?:\d+[.、）\)]\s*|[①②③④⑤⑥⑦⑧⑨⑩])|(?:产品信息|视频需求|核心卖点))', text)

    for sec in sections:
        sec = sec.strip()
        if not sec or len(sec) < 20:
            continue

        # Extract section header as selling point name
        header_match = re.match(r'(?:[\d一二三四五六七八九十]+[.、）\)]\s*)?(.+?)(?:\n|：)', sec)
        name = header_match.group(1).strip() if header_match else ""
        if not name or len(name) > 40:
            name = "核心产品"

        # Score the section for keyword density
        spec_keywords = [
            "磁轴", "回报率", "精度", "传感器", "DPI", "RGB", "ARGB", "灯效",
            "轻量化", "续航", "延迟", "响应", "驱动", "Gasket", "结构",
            "铝合金", "阳极", "丝印", "纳米", "定制", "旗舰", "8K", "4K",
            "无线", "双模", "蓝牙", "2.4G", "欧姆龙", "TTC", "原相", "PAW",
            "Nordic", "处理器", "CPU", "GPU", "RTX", "Hz", "分辨率", "亮度",
            "色域", "散热", "接口", "生态", "协同", "互联",
        ]
        content = sec[len(name):] if name != "核心产品" else sec
        kw_count = sum(1 for kw in spec_keywords if kw in content)

        # Skip meta sections that aren't real products
        if any(skip in name for skip in ["视频需求", "发布时间", "注意事项", "参考", "备注"]):
            continue

        if kw_count >= 1:
            max_pct = min(35, max(10, kw_count * 8))
            sp = SellingPoint(
                name=name[:30],
                proportion=max_pct / 100,
                priority=min(9, 3 + kw_count // 2),
                deep_dive=(kw_count >= 5),
                key_phrases=_extract_key_phrases(content),
                hook_candidate=("首发" in sec or "旗舰" in sec or "最强" in sec or "极致" in sec),
            )
            points.append(sp)

    # Sort by priority
    points.sort(key=lambda p: (-p.priority, -p.proportion))
    return points


def _extract_selling_points_fallback(text: str) -> list[SellingPoint]:
    """Fallback: extract selling points by scanning for key feature names."""
    features = [
        ("性能", ["芯片", "骁龙", "CPU", "GPU", "跑分", "帧率"]),
        ("游戏体验", ["游戏", "3A", "Steam", "PC", "掌机", "手柄"]),
        ("散热", ["散热", "风扇", "水冷", "VC", "温度"]),
        ("屏幕", ["屏幕", "全面屏", "挖孔", "高刷", "HDR"]),
        ("赛事合作", ["赛事", "比赛", "电竞", "职业", "认证"]),
    ]
    points = []
    for name, kws in features:
        score = sum(text.count(kw) for kw in kws)
        if score >= 2:
            sp = SellingPoint(name=name, priority=min(9, score))
            sp.key_phrases = [kw for kw in kws if kw in text][:4]
            sp.must_mention = ("赛事" in name or "必带" in text)
            sp.deep_dive = score >= 5
            points.append(sp)
    return points


def _proportion_to_priority(pct: int) -> int:
    if pct >= 30: return 9
    if pct >= 20: return 7
    if pct >= 10: return 5
    return 3


def _extract_key_phrases(text: str) -> list[str]:
    """Extract key selling phrases from brief text."""
    phrases = []
    # Match quoted terms
    quoted = re.findall(r'[「「]([^」」]+)[」」]', text)
    phrases.extend(quoted)
    # Match bold/special terms
    special = re.findall(r'(?:极致|最强|行业首次|首发|独家|领先|百里挑一|唯一|全新|突破)[^\n。，]{0,20}', text)
    phrases.extend(special)
    return phrases[:8]


def _extract_must_mentions(text: str) -> list[str]:
    """Detect client enforced must-mentions."""
    must = []
    patterns = [
        r'(?:必带|必须|务必|需要).{0,10}(?:提到|包含|带|说|强调|展现)([^\n。，]{5,40})',
        r'(?:请注意|请确保|请在.{0,10}上).{0,5}([^\n。，]{10,60})',
        r'赛事.{0,5}(?:指定|认证|合作)([^\n。，]{0,20})',
    ]
    for pat in patterns:
        matches = re.findall(pat, text)
        must.extend(m.strip() for m in matches)
    # Deduplicate
    seen = set()
    result = []
    for m in must:
        if m not in seen and len(m) >= 4:
            result.append(m)
            seen.add(m)
    return result[:8]


def _extract_donts(text: str) -> list[str]:
    """Extract content warnings and prohibited phrases."""
    donts = []
    # Look for "不要" "避免" "勿" patterns
    patterns = [
        r'(?:不要|避免|勿|不能|不可|禁止|规避).{0,5}([^\n。，；]{8,60})',
    ]
    for pat in patterns:
        matches = re.findall(pat, text)
        donts.extend(m.strip() for m in matches)
    return donts[:10]


def _extract_hashtags(text: str) -> list[str]:
    """Extract required hashtags (max 5 chars after # to avoid capturing full sentences)."""
    tags = re.findall(r'#([\w一-鿿]{2,20})', text)
    seen = set()
    result = []
    for t in tags:
        if t not in seen and not t.startswith(' ') and len(t) >= 2:
            result.append(f'#{t}')
            seen.add(t)
    return result[:6]


def _extract_cover_suggestion(text: str) -> str:
    """Extract cover/thumbnail suggestions."""
    m = re.search(r'封面.{0,10}(?:建议|展现|推荐).{0,10}[：:]\s*([^\n]{10,80})', text)
    if m:
        return m.group(1).strip()
    m = re.search(r'(?:展现|醒目).{0,5}(?:文字|位置).{0,5}["“]([^"”]{5,30})["”]', text)
    return m.group(1).strip() if m else ""


# ============================================================
# Integration: generate a brief-aware system prompt addition
# ============================================================

def brief_to_prompt_context(analysis: BriefAnalysis) -> str:
    """Convert brief analysis into a prompt context block for the LLM."""
    sps = sorted(analysis.selling_points, key=lambda s: -s.priority)

    lines = ["## 甲方Brief核心要求（必须遵守）"]
    lines.append(f"产品：{analysis.product_name}")
    lines.append(f"时长：{analysis.target_duration}")
    lines.append("")

    # Deep-dive points
    deep = [s for s in sps if s.priority >= 7]
    lines.append("### 重点展开（多花篇幅）")
    for s in deep:
        lines.append(f"- {s.name}：{'; '.join(s.key_phrases[:3])}" if s.key_phrases else f"- {s.name}")
    lines.append("")

    # Must mentions
    if analysis.must_mentions:
        lines.append("### 甲方强制要求（必须出现）")
        for m in analysis.must_mentions[:5]:
            lines.append(f"- {m}")
        lines.append("")

    # DON'Ts
    if analysis.content_donts:
        lines.append("### 甲方禁止（绝对不能写）")
        for d in analysis.content_donts[:6]:
            lines.append(f"- {d}")
        lines.append("")

    return "\n".join(lines)
