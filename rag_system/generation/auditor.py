"""Quality auditor for generated scripts and storyboards.

根本宗旨：取其精华，去其糟粕。

v2 upgrades:
  - Script body extraction (strip metadata before auditing)
  - Token-based fuzzy selling-point matching
  - Deepened attitude detection (6 categories)
  - Sentence particles and rhetorical question detection
  - E-commerce smell detection (电商味)
"""

import re
from dataclasses import dataclass, field
from collections import Counter


# ============================================================
# Constants
# ============================================================

FORBIDDEN_WORDS = [
    "非常", "出色", "为用户带来", "值得拥有", "不容错过",
    "极致体验", "尽享", "尊享", "非凡", "无与伦比",
    "改变生活", "颠覆性", "前所未有的体验",
]

# 拉踩 / competitor bashing phrases (Douyin prohibited)
LACAI_PATTERNS = [
    r"(?:被|让|给).{0,6}(?:吊着打|吊打|碾压|完爆|秒杀|按在地上)",
    r"(?:卡成|卡成狗|卡出|卡到).{0,4}(?:PPT|幻灯片|翔)",
    r"(?:垃圾|废物|辣鸡|乐色)",
    r"(?:就是个?|简直是?|纯属).{0,6}(?:弟弟|废物|笑话|智商税)",
    r"(?:不如|比不上|打不过|干不过).{0,6}(?:一根毛|零头|脚趾)",
    r"(?:送|给).{0,4}(?:都不要|都没人要)",
    r"(?:谁买谁|买就).{0,4}(?:后悔|傻|亏|上当)",
]

# 参数流水账检测——电商详情页句式
SPEC_PARADE_PATTERNS = [
    r"它采用了.{1,20}(?:处理器|显卡|屏幕|电池|传感器|轴体)",
    r"它配备了.{1,20}(?:处理器|显卡|屏幕|电池|传感器|轴体)",
    r"它拥有.{1,20}(?:毫安|英寸|赫兹|核心|线程)",
    r"搭载了.{1,20}(?:处理器|显卡|屏幕|传感器|轴体)",
    r"它用的是.{1,20}(?:处理器|显卡|屏幕|传感器|轴体)",
    r"(?:CPU|GPU|处理器|显卡)(?:是|为).{1,30}(?:，|。)",  # Bare spec listing
]

# E-commerce / press-release smell words
ECOMMERCE_SMELL = [
    "全新升级", "震撼上市", "重磅来袭", "匠心打造", "精心设计",
    "专为...而生", "重新定义", "颠覆想象", "超越期待", "引领",
    "赋能", "极致", "沉浸式", "全方位", "一站式",
]

SPOKEN_MARKERS = [
    "说白了", "简单来说", "懂的都懂", "不吹不黑", "有一说一",
    "你别说", "我跟你说", "兄弟们", "彦祖们", "大伙儿",
    "你品", "你细品", "这就很离谱", "真就", "啧啧",
    "闭眼入", "没谁了", "血赚", "香疯了", "顶", "到位", "靠谱",
    "掀桌", "简直了", "我跟你说", "包不后悔",
]

# Sentence-final spoken particles
SENTENCE_PARTICLES = ["啊", "吧", "呢", "嘛", "哦", "哈", "咯", "呗", "喽"]

ATTITUDE_PATTERNS = {
    "价格判断": [r"这价位", r"这价格", r"性价比", r"值不值", r"亏不亏",
              r"\d+块(?:钱)?(?:就|才|能)", r"(?:便宜|贵)了", r"(?:划算|不划算)"],
    "对比判断": [r"比.{1,8}(?:强|弱|好|差|香|坑|贵|便宜|顶|拉胯)",
              r"(?:不如|完爆|吊打|碾压|秒杀).{1,8}",
              r"同(?:价|级|档|规格).{1,6}(?:比|更|最)"],
    "推荐判断": [r"闭眼入", r"(?:赶紧|快点|马上|现在).{1,4}(?:冲|买|入)",
              r"别(?:碰|买|入|考虑)", r"避坑", r"(?:推荐|建议).{1,4}(?:买|入|冲)"],
    "体验判断": [r"(?:我个人|我实测|我用了|我用过|坐上去|一上手)",
              r"(?:没毛病|有问题|不赖|拉胯|顶|到位|靠谱|离谱)",
              r"(?:好(?:在|用|使|拿|按|听|看)|差(?:在|劲))"],
    "确定性表达": [r"懂的都懂", r"有一说一", r"不吹不黑", r"你自己品",
               r"这就很", r"没谁了", r"真就", r"简直了"],
    "分级判断": [r"T\d", r"毕业", r"退烧", r"一步到位", r"天花板", r"标杆"],
}

# Douyin short video speaking rate: ~290 chars/min ≈ 4.83 chars/sec
# (Faster than general Chinese speech — Douyin pace is 280-300 chars/min)
CHARS_PER_SEC = 290 / 60  # ≈ 4.83


@dataclass
class AuditResult:
    """Structured audit report."""
    passed: bool
    checks: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    scores: dict = field(default_factory=dict)

    def summarize(self) -> str:
        lines = []
        total = len(self.checks)
        passed_count = sum(1 for c in self.checks if c.get("passed"))
        lines.append(f"审核结果: {passed_count}/{total} 通过 {'[PASS]' if self.passed else '[FAIL]'}")

        for c in self.checks:
            icon = "[OK]" if c.get("passed") else "[FAIL]"
            lines.append(f"  {icon} {c['name']}: {c.get('detail', '')}")

        if self.warnings:
            lines.append(f"\n[!] 提醒 ({len(self.warnings)}):")
            for w in self.warnings:
                lines.append(f"  - {w}")

        if self.suggestions:
            lines.append(f"\n[>>] 建议 ({len(self.suggestions)}):")
            for s in self.suggestions:
                lines.append(f"  - {s}")

        if self.scores:
            lines.append(f"\n[==] 分项得分:")
            for k, v in self.scores.items():
                lines.append(f"  {k}: {v}")

        return "\n".join(lines)


# ============================================================
# Helpers
# ============================================================

def _extract_script_body(text: str) -> str:
    """Strip metadata and only keep the voiceover body paragraphs.

    LLM output format:
      封面：title
      简介：summary
      [body text]
      花字：specs
      #hashtags
    """
    lines = text.split("\n")
    body_lines = []
    in_metadata = True
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Skip metadata headers
        if stripped.startswith("封面：") or stripped.startswith("封面:") or stripped.startswith("简介：") or stripped.startswith("简介:"):
            continue
        # Stop at 花字 section
        if stripped.startswith("花字：") or stripped.startswith("花字:") or stripped.startswith("（花字：") or stripped.startswith("(花字："):
            break
        # Stop at hashtags
        if stripped.startswith("#"):
            break
        # Stop at persona signature (end of body)
        if "我们下期再见" in stripped or "我们下期见" in stripped:
            body_lines.append(stripped)
            break
        in_metadata = False
        if stripped:
            body_lines.append(stripped)
    return "".join(body_lines) if body_lines else text


def _tokenize_selling_point(point: str) -> list[str]:
    """Break a selling point into searchable tokens.

    'i7-13620H' -> ['i7', '13620H', 'i7-13620H']
    '16GB内存' -> ['16GB', '16', 'GB', '内存', '16GB内存']
    'Gasket结构' -> ['Gasket', '结构', 'Gasket结构']
    """
    tokens = [point]
    # Split on spaces, hyphens, slashes
    parts = re.split(r'[\s\-/]+', point)
    for p in parts:
        if p and p not in tokens:
            tokens.append(p)
    # Split Chinese+English boundaries
    mixed = re.findall(r'[一-鿿]+|[A-Za-z0-9]+', point)
    for m in mixed:
        if m and m not in tokens:
            tokens.append(m)
    # Numeric suffixes
    num_suffix = re.search(r'(\d+)$', point)
    if num_suffix and num_suffix.group(1) not in tokens:
        tokens.append(num_suffix.group(1))
    return [t for t in tokens if len(t) >= 2]


def _fuzzy_match_selling_point(point: str, text: str) -> bool:
    """Check if a selling point is mentioned in the text using token overlap."""
    tokens = _tokenize_selling_point(point)
    # A selling point is "covered" if at least one significant token appears
    significant = [t for t in tokens if len(t) >= 3]
    for token in significant:
        if token.lower() in text.lower():
            return True
    return False


def _count_attitudes(text: str) -> tuple[int, dict]:
    """Count attitude expressions by category. Returns (total, per_category_count)."""
    per_cat = {}
    total = 0
    for cat, patterns in ATTITUDE_PATTERNS.items():
        count = 0
        for pat in patterns:
            count += len(re.findall(pat, text))
        per_cat[cat] = count
        total += count
    return total, per_cat


# ============================================================
# Script audit
# ============================================================

def audit_script(text: str, key_points: str = "", duration_minutes: float = 2.0) -> AuditResult:
    """Audit a generated script text.

    Args:
        text: The script text to audit.
        key_points: Expected selling points to check coverage.
        duration_minutes: Target video duration in minutes (default 2.0).
    """
    checks = []
    warnings = []
    suggestions = []
    scores = {}

    body = _extract_script_body(text)
    total_chars = len(body)

    # ── Check 1: Duration ──
    est_sec = total_chars / CHARS_PER_SEC
    target_sec = duration_minutes * 60
    # Accept ±35% of target, with practical floor/ceiling
    min_ok = max(30, target_sec * 0.65)
    max_ok = target_sec * 1.35
    duration_ok = min_ok <= est_sec <= max_ok
    checks.append({
        "name": "口播时长",
        "passed": duration_ok,
        "detail": f"{total_chars}字 ≈ {est_sec:.0f}秒 (目标{target_sec:.0f}秒, 可接受{min_ok:.0f}-{max_ok:.0f}秒)",
    })
    if est_sec < min_ok * 0.7:
        warnings.append(f"脚本偏短 ({est_sec:.0f}秒 vs 目标{target_sec:.0f}秒)，内容不够")
        suggestions.append("补充1-2个卖点的深挖段落，或加实测体验环节")
    elif est_sec > max_ok * 1.2:
        warnings.append(f"脚本偏长 ({est_sec:.0f}秒 vs 目标{target_sec:.0f}秒)，超时掉人风险")
        suggestions.append("精简次要卖点到花字，或砍掉一个深挖段落")
    scores["时长"] = min(100, max(30, int((1.0 - abs(est_sec - target_sec) / target_sec) * 100)))

    # ── Check 2: Forbidden words ──
    found_forbidden = [w for w in FORBIDDEN_WORDS if w in body]
    checks.append({
        "name": "禁用词",
        "passed": len(found_forbidden) == 0,
        "detail": f"发现 {len(found_forbidden)} 个: {found_forbidden}" if found_forbidden else "未发现",
    })
    for w in found_forbidden:
        suggestions.append(f"'{w}' → 换成口语表达")
    scores["禁用词"] = max(0, 100 - len(found_forbidden) * 25)

    # ── Check 3: E-commerce smell ──
    found_smell = [w for w in ECOMMERCE_SMELL if w in body]
    smell_ok = len(found_smell) <= 1
    checks.append({
        "name": "电商味",
        "passed": smell_ok,
        "detail": f"发现 {len(found_smell)} 个电商/新闻稿词汇: {found_smell}" if found_smell else "未发现",
    })
    if len(found_smell) >= 2:
        warnings.append(f"读起来像电商详情页——'{found_smell[0]}''{found_smell[1]}'这些词你的脚本里不会出现")
        suggestions.append("去掉新闻稿腔调：'全新升级''震撼上市'这类词全部删除")
    scores["电商味"] = max(0, 100 - len(found_smell) * 30)

    # ── Check 3b: 参数流水账检测 ──
    found_parade = []
    for pat in SPEC_PARADE_PATTERNS:
        matches = re.findall(pat, body)
        found_parade.extend(matches)
    parade_ok = len(found_parade) <= 1
    checks.append({
        "name": "流水账检测",
        "passed": parade_ok,
        "detail": f"发现 {len(found_parade)} 处参数流水账: {found_parade[:5]}" if found_parade else "未发现",
    })
    if len(found_parade) >= 2:
        warnings.append(f"参数流水账——像电商详情页: {found_parade[:3]}")
        suggestions.append("把参数翻译成体验：不说'它采用了XX处理器'，说'你拿它剪4K不卡顿'")
    scores["流水账"] = max(0, 100 - len(found_parade) * 25)

    # ── Check 3c: 价格检测（口播禁止具体价格） ──
    price_pattern = re.findall(r'\d{2,5}\s*元', body)
    price_ok = len(price_pattern) == 0
    checks.append({
        "name": "价格检测",
        "passed": price_ok,
        "detail": f"发现 {len(price_pattern)} 处具体价格: {price_pattern}" if price_pattern else "口播未提具体价格",
    })
    if price_pattern:
        warnings.append(f"口播里出现了具体价格: {price_pattern}——价格只能放花字")
        suggestions.append("把具体价格数字移到花字，口播只说'这个价位''便宜好几百'")
    scores["价格"] = max(0, 100 - len(price_pattern) * 35)

    # ── Check 3d: 拉踩检测 ──
    found_lacai = []
    for pat in LACAI_PATTERNS:
        matches = re.findall(pat, body)
        found_lacai.extend(matches)
    lacai_ok = len(found_lacai) == 0
    checks.append({
        "name": "拉踩检测",
        "passed": lacai_ok,
        "detail": f"发现 {len(found_lacai)} 处拉踩: {found_lacai[:5]}" if found_lacai else "未发现",
    })
    if found_lacai:
        warnings.append(f"包含拉踩表达——抖音禁止贬低竞品: {found_lacai[:5]}")
        suggestions.append("改为客观对比：'XX竞品在A方面更强，但它便宜一半'而不是'XX就是个弟弟'")
    scores["拉踩"] = max(0, 100 - len(found_lacai) * 30)

    # ── Check 4: Spoken language ──
    marker_count = sum(body.count(m) for m in SPOKEN_MARKERS)
    particle_count = sum(body.count(p) for p in SENTENCE_PARTICLES)
    # Rhetorical questions
    rhetorical = len(re.findall(r"(?:是不是|难道|你说|对吧|不是吗|搞什么|凭什么)", body))
    combined_markers = marker_count + particle_count * 0.5 + rhetorical * 2
    density = combined_markers / (total_chars / 100)
    spoken_ok = density >= 1.0
    checks.append({
        "name": "口语化程度",
        "passed": spoken_ok,
        "detail": f"{marker_count}标志词 + {particle_count}语气词 + {rhetorical}反问句, 综合密度={density:.1f}/百字 (阈值1.0)",
    })
    if not spoken_ok:
        if marker_count < 2:
            warnings.append("缺少口语标志词——'兄弟们''说白了''懂的都懂'这些一个都没出现")
        if particle_count < 3:
            warnings.append("缺少语气词(啊/吧/呢/嘛)——书面语痕迹重")
        suggestions.append("加'兄弟们'开场，中间穿插'你品''懂的都懂'，句尾多用'吧/呢/嘛'")
    scores["口语化"] = min(100, int(density / 2.0 * 100))

    # ── Check 5: Attitude density ──
    attitude_total, att_categories = _count_attitudes(body)
    att_density = attitude_total / (total_chars / 200)
    att_ok = att_density >= 2.0
    cat_detail = ", ".join(f"{k}:{v}" for k, v in att_categories.items() if v > 0)
    checks.append({
        "name": "态度密度",
        "passed": att_ok,
        "detail": f"{attitude_total}个主观判断, 密度={att_density:.1f}/200字 (阈值2.0) | {cat_detail}",
    })
    if att_density < 1.0:
        warnings.append("严重缺乏主观态度——读起来像产品参数表，不像兄弟推荐")
        suggestions.append("每个卖点讲完必须说'好在哪''和谁比''适合谁'")
    elif att_density < 2.0:
        warnings.append("态度偏弱——再多加些主观判断：这价位值不值? 和竞品谁更香?")
    if att_categories.get("体验判断", 0) == 0:
        suggestions.append("加一句自己的使用感受——'我实测''一上手''坐上去'这种")
    if att_categories.get("对比判断", 0) == 0:
        suggestions.append("加对比判断——和同价位竞品或国际大厂比一下")
    scores["态度"] = min(100, int(att_density / 4.0 * 100))

    # ── Check 6: Sentence rhythm ──
    sentences = re.split(r"[。！？\n]", body)
    sentences = [s.strip() for s in sentences if s.strip()]
    if sentences:
        short_s = [s for s in sentences if len(s) <= 15]
        long_s = [s for s in sentences if len(s) >= 50]
        short_ratio = len(short_s) / len(sentences)
        long_ratio = len(long_s) / len(sentences)
        rhythm_ok = 0.22 <= short_ratio <= 0.48 and long_ratio >= 0.20
        checks.append({
            "name": "长短句节奏",
            "passed": rhythm_ok,
            "detail": f"{len(sentences)}句: 短(≤15字){short_ratio:.0%}, 长(≥50字){long_ratio:.0%} (目标短22-48%, 长≥20%)",
        })
        if short_ratio < 0.18:
            warnings.append("短句太少——全是长句一口气念不下来，观众也喘不过气")
            suggestions.append("在2-3处长句之间插入短句(5-15字)，如'真就离谱''但这还没完'")
        elif short_ratio > 0.55:
            warnings.append("短句太多——信息碎片化，缺乏信息轰炸的爽感")
            suggestions.append("把2-3个相邻短句合并成长句(50-80字)")
        scores["节奏"] = min(100, int((1.0 - abs(short_ratio - 0.35) * 2.2) * 100))
    else:
        checks.append({"name": "长短句节奏", "passed": True, "detail": "无法解析句子"})

    # ── Check 7: Selling point coverage ──
    if key_points:
        points = [p.strip() for p in key_points.replace("，", ",").split(",") if p.strip()]
        covered = []
        missed = []
        missed_detail = []
        for p in points:
            if _fuzzy_match_selling_point(p, body):
                covered.append(p)
            else:
                missed.append(p)
                tokens = _tokenize_selling_point(p)
                missed_detail.append(f"{p} (tokenized: {tokens[:4]})")
        coverage = len(covered) / max(len(points), 1)
        coverage_ok = coverage >= 0.7
        checks.append({
            "name": "卖点覆盖",
            "passed": coverage_ok,
            "detail": f"已覆盖{len(covered)}/{len(points)}: {covered}" + (f" | 缺失: {missed}" if missed else ""),
        })
        if missed:
            warnings.append(f"以下卖点未在脚本中提及: {', '.join(missed)}")
            suggestions.append("确认这些卖点是故意略过(如次要卖点放花字)还是遗漏。甲方强制要求的必须补上")
        scores["卖点覆盖"] = int(coverage * 100)
    else:
        checks.append({"name": "卖点覆盖", "passed": True, "detail": "未提供卖点列表，跳过"})

    # ── Final assessment ──
    all_passed = all(c.get("passed", True) for c in checks)
    overall_pass = all_passed and len(warnings) <= 2

    return AuditResult(
        passed=overall_pass,
        checks=checks,
        warnings=warnings,
        suggestions=suggestions,
        scores=scores,
    )


# ============================================================
# Storyboard audit
# ============================================================

def audit_storyboard(storyboard: dict, key_points: str = "", duration_minutes: float = 2.0) -> AuditResult:
    """Audit a generated storyboard (JSON dict).

    Args:
        storyboard: The storyboard dict with 'shots' list.
        key_points: Expected selling points to check coverage.
        duration_minutes: Target video duration in minutes.
    """
    checks = []
    warnings = []
    suggestions = []
    scores = {}

    shots = storyboard.get("shots", [])

    # ── Shot count ──
    shot_count = len(shots)
    shot_ok = 28 <= shot_count <= 45
    checks.append({
        "name": "镜数",
        "passed": shot_ok,
        "detail": f"{shot_count} 镜 (目标30-45)",
    })
    if shot_count < 25:
        suggestions.append("镜数不足——扩充细节B-roll和产品角度")
    elif shot_count > 50:
        suggestions.append("镜数过多，合并相似镜头，减少冗余切镜")

    # ── Voiceover ──
    all_vo = "".join(s.get("voiceover", "") for s in shots)
    vo_chars = len(all_vo)
    est_sec = vo_chars / CHARS_PER_SEC
    target_sec = duration_minutes * 60
    min_ok = max(30, target_sec * 0.65)
    max_ok = target_sec * 1.35
    vo_ok = min_ok <= est_sec <= max_ok
    checks.append({
        "name": "口播时长",
        "passed": vo_ok,
        "detail": f"{vo_chars}字 ≈ {est_sec:.0f}秒 (目标{target_sec:.0f}秒, 可接受{min_ok:.0f}-{max_ok:.0f}秒)",
    })
    scores["时长"] = min(100, max(30, int((1.0 - abs(est_sec - target_sec) / target_sec) * 100)))

    # ── Huazi coverage (点睛 not 铺满) ──
    huazi_shots = sum(1 for s in shots if s.get("huazi", "").strip())
    huazi_ratio = huazi_shots / max(shot_count, 1)
    huazi_ok = 0.20 <= huazi_ratio <= 0.35
    checks.append({
        "name": "花字覆盖率",
        "passed": huazi_ok,
        "detail": f"{huazi_shots}/{shot_count} 镜有花字 ({huazi_ratio:.0%}) (目标20-35%)",
    })
    if huazi_ratio > 0.40:
        warnings.append(f"花字过多 ({huazi_ratio:.0%})——花字是点睛，不是铺满，只在核心规格处标注")
        suggestions.append("减少花字: 只保留规格数据、价格对比、技术名词三类的花字")
    elif huazi_ratio < 0.15:
        warnings.append("花字偏少——关键规格数据没有画面标注")
    scores["花字"] = min(100, int((1.0 - abs(huazi_ratio - 0.28) / 0.2) * 100))

    # ── Audio coverage (点睛 not 铺满) ──
    audio_shots = sum(1 for s in shots if s.get("audio", "").strip())
    audio_ratio = audio_shots / max(shot_count, 1)
    audio_ok = audio_ratio <= 0.30
    checks.append({
        "name": "音效覆盖率",
        "passed": audio_ok,
        "detail": f"{audio_shots}/{shot_count} 镜有音效 ({audio_ratio:.0%}) (目标≤30%)",
    })
    if audio_ratio > 0.35:
        warnings.append(f"音效过多 ({audio_ratio:.0%})——音效是画龙点睛，不是背景填充，多数镜头不需要音效")
        suggestions.append("减少音效: 只在产品亮相、数据弹出、材质特写、转场处保留音效")
    elif audio_ratio > 0.25:
        warnings.append(f"音效偏多 ({audio_ratio:.0%})——检查是否有泛用'转场音''氛围音'")

    # ── Audio specificity ──
    generic_audio = ["转场音", "氛围音", "音效", "转场", "特效音"]
    generic_count = sum(1 for s in shots
                        if any(g == (s.get("audio", "").strip()) for g in generic_audio))
    audio_specific_ok = generic_count <= 2
    checks.append({
        "name": "音效具体性",
        "passed": audio_specific_ok,
        "detail": f"{generic_count}个泛用音效描述 (允许≤2) —— 描述必须具体(如'金属敲击声'不是'转场音')",
    })
    if not audio_specific_ok:
        warnings.append(f"{generic_count}个音效描述太泛——混音师无法执行，改为具体拟音或删除")
        suggestions.append("改泛用音效为具体描述: '金属敲击声''网布摩擦声''按键咔嗒声''叮'等")

    # ── Transition design ──
    trans_count = sum(1 for s in shots
                      if s.get("transition", "") not in ("硬切", "开场", ""))
    trans_ratio = trans_count / max(len(shots) - 1, 1)
    trans_ok = trans_ratio >= 0.25
    checks.append({
        "name": "转场设计",
        "passed": trans_ok,
        "detail": f"{trans_count}/{len(shots)-1}镜有设计转场 ({trans_ratio:.0%}) (目标≥25%)",
    })
    if not trans_ok:
        warnings.append(f"设计转场不足 ({trans_ratio:.0%})——全程硬切导致视觉疲劳")
        suggestions.append("在关键位置增加转场设计: 动作匹配、遮挡转场、声音先入等")

    # ── Shot type variety ──
    jingbies = Counter(s.get("jingbie", "") for s in shots)
    yunjings = Counter(s.get("yunjing", "") for s in shots)
    unique_jb = len(jingbies)
    unique_yj = len(yunjings)
    variety_ok = unique_jb >= 3 and unique_yj >= 3
    checks.append({
        "name": "镜头多样性",
        "passed": variety_ok,
        "detail": f"{unique_jb}种景别 (Top: {jingbies.most_common(2)}), {unique_yj}种运镜 (Top: {yunjings.most_common(2)})",
    })
    if unique_yj <= 2:
        warnings.append("运镜类型太少")
        suggestions.append("增加摇/推/拉/环绕等运镜变化")
    scores["多样性"] = min(100, (unique_jb * 12 + unique_yj * 12))

    # ── Duration distribution (not just variety count) ──
    durs = [s.get("duration", "") for s in shots]
    dur_int = []
    for d in durs:
        try:
            dur_int.append(int(d.replace("s", "").strip()))
        except (ValueError, AttributeError):
            dur_int.append(0)
    short_count = sum(1 for d in dur_int if 1 <= d <= 2)
    long_count = sum(1 for d in dur_int if d >= 6)
    dur_dist_ok = short_count >= 2 and long_count >= 2
    checks.append({
        "name": "时长分布",
        "passed": dur_dist_ok,
        "detail": f"短切(1-2s):{short_count}镜, 长镜(≥6s):{long_count}镜 (各需≥2镜)",
    })
    if not dur_dist_ok and short_count < 2:
        suggestions.append("增加1-2s快切镜头，制造紧张节奏")
    if not dur_dist_ok and long_count < 2:
        warnings.append("缺少长镜(≥6s)——产品亮相或材质特写需要呼吸空间")
        suggestions.append("将产品亮相/360°展示改为6-10s长镜，镜头内部有运镜变化")

    # ── A-roll + B-roll pairing: every shot must have voiceover ──
    no_vo_shots = sum(1 for s in shots if not s.get("voiceover", "").strip())
    vo_pair_ok = no_vo_shots == 0
    checks.append({
        "name": "口播完整",
        "passed": vo_pair_ok,
        "detail": "每镜都有口播" if vo_pair_ok else f"{no_vo_shots}镜缺少口播——A-roll画面和B-roll口播必须成对",
    })
    if not vo_pair_ok:
        warnings.append(f"{no_vo_shots}镜没有口播——画面(A-roll)和口播(B-roll)必须成对出现")
        suggestions.append("给缺少口播的镜头分配对应文案")

    # ── Voiceover quality (on concatenated VO) ──
    if all_vo:
        found = [w for w in FORBIDDEN_WORDS if w in all_vo]
        checks.append({
            "name": "禁用词(口播)",
            "passed": len(found) == 0,
            "detail": "未发现" if not found else f"发现: {found}",
        })

        smell = [w for w in ECOMMERCE_SMELL if w in all_vo]
        checks.append({
            "name": "电商味(口播)",
            "passed": len(smell) <= 1,
            "detail": "未发现" if not smell else f"发现: {smell}",
        })

        marker_cnt = sum(all_vo.count(m) for m in SPOKEN_MARKERS)
        density = marker_cnt / (max(vo_chars, 1) / 100)
        checks.append({
            "name": "口语化(口播)",
            "passed": density >= 0.5,
            "detail": f"{marker_cnt}标志词, 密度={density:.1f}/百字",
        })
        scores["口语化"] = min(100, int(density / 1.5 * 100))

        att_total, _ = _count_attitudes(all_vo)
        att_dens = att_total / (vo_chars / 200)
        checks.append({
            "name": "态度(口播)",
            "passed": att_dens >= 1.5,
            "detail": f"{att_total}个主观判断, 密度={att_dens:.1f}/200字",
        })

        # Lighting/camera completeness (soft check)
        light_count = sum(1 for s in shots if s.get("lighting", "").strip())
        cam_count = sum(1 for s in shots if s.get("camera_setup", "").strip())
        light_cam_ok = light_count >= 3 and cam_count >= 3
        checks.append({
            "name": "灯位/机位标注",
            "passed": light_cam_ok,
            "detail": f"灯位:{light_count}镜, 机位:{cam_count}镜 (建议各≥3镜用于关键镜)",
        })
        if not light_cam_ok:
            if light_count < 3:
                suggestions.append("在关键镜(产品亮相/特写/换场景)标注灯光布置")
            if cam_count < 3:
                suggestions.append("在关键镜标注机位+焦段+光圈")

    all_passed = all(c.get("passed", True) for c in checks)
    overall_pass = all_passed and len(warnings) <= 3

    return AuditResult(
        passed=overall_pass,
        checks=checks,
        warnings=warnings,
        suggestions=suggestions,
        scores=scores,
    )


# ============================================================
# Shootability audit + auto-fix
# ============================================================

UNFILMABLE_PATTERNS = {
    "鱼眼": "需要鱼眼镜头——替换为广角微距",
    "航拍": "需要无人机——替换为高角度俯拍",
    "升格": "需要高速摄影机——替换为慢动作后期",
    "逐格": "需要逐格摄影设备——替换为快切剪辑",
    "热成像": "需要热成像仪——替换为手掌感知温度",
    "一镜到底": "需要斯坦尼康或稳定器+复杂调度——拆分为2-3个连贯镜头",
}


def audit_shootability(storyboard: dict) -> dict:
    """Review storyboard for filmability and shot transitions. Auto-fix unfilmable shots."""
    shots = storyboard.get("shots", [])
    issues = []
    transition_issues = []

    for shot in shots:
        sn = shot.get("shot_number", "?")
        yunjing = shot.get("yunjing", "")
        jingbie = shot.get("jingbie", "")
        visual = shot.get("visual", "")
        combined = f"{yunjing} {jingbie} {visual}"

        for pattern, fix_hint in UNFILMABLE_PATTERNS.items():
            if pattern in combined:
                parts = fix_hint.split("——")
                issues.append({
                    "shot": sn, "problem": parts[0],
                    "suggestion": parts[1] if len(parts) > 1 else fix_hint,
                    "severity": "high",
                })
                break

        if "俯拍" in combined and "仰拍" in combined:
            issues.append({
                "shot": sn, "problem": "一个镜头不能同时俯视和仰视",
                "suggestion": "拆成两个镜头或只保留一个角度", "severity": "high",
            })

    # Check shot transitions
    for i in range(len(shots) - 1):
        s1, s2 = shots[i], shots[i + 1]
        jb1, jb2 = s1.get("jingbie", ""), s2.get("jingbie", "")
        yj1, yj2 = s1.get("yunjing", ""), s2.get("yunjing", "")

        if i >= 2:
            jb0 = shots[i - 2].get("jingbie", "")
            if jb0 == jb1 == jb2 and jb1 not in ("图文形式动画",):
                transition_issues.append({
                    "shots": f"{shots[i-2].get('shot_number')}→{s1.get('shot_number')}→{s2.get('shot_number')}",
                    "problem": f"连续3镜相同景别'{jb1}'——视觉单调",
                    "suggestion": "中间镜改用不同景别",
                })

        if jb1 == jb2 and yj1 == "固定镜头" and yj2 == "固定镜头":
            transition_issues.append({
                "shots": f"{s1.get('shot_number')}→{s2.get('shot_number')}",
                "problem": "同景别+同固定镜头，可能产生跳切",
                "suggestion": f"改变机位角度至少30度，或加一个不同景别的过渡镜",
            })

    passed = len([i for i in issues if i["severity"] == "high"]) == 0

    # Auto-fix unfilmable shots
    fixed_shots = _auto_fix_shots(shots, issues)

    return {
        "issues": issues,
        "transition_issues": transition_issues,
        "fixed_shots": fixed_shots,
        "passed": passed,
    }


def _auto_fix_shots(shots: list[dict], issues: list[dict]) -> list[dict]:
    """Redesign unfilmable shots into practical alternatives."""
    import copy
    high_issue_shots = {i["shot"] for i in issues if i["severity"] == "high"}
    # Fixes for yunjing field
    yunjing_fixes = {
        "鱼眼微距": ("广角微距", "广角凑近拍——同样夸张变形"),
        "鱼眼": ("广角近景", "广角代替鱼眼"),
        "一镜到底": ("跟拍长镜", "手持跟拍连续记录"),
    }
    # Fixes for visual description field
    visual_fixes = {
        "热成像": "手掌悬停感知温度",
        "热成像仪": "手掌悬停感知温度",
        "升格慢动作": "后期慢动作",
    }
    result = []
    for shot in shots:
        sn = shot.get("shot_number")
        if sn not in high_issue_shots:
            result.append(shot)
            continue
        fixed = copy.deepcopy(shot)
        yj = shot.get("yunjing", "")
        vis = shot.get("visual", "")

        # Fix yunjing
        for old, (new_val, note) in yunjing_fixes.items():
            if old in yj:
                fixed["yunjing"] = yj.replace(old, new_val)
                fixed["notes"] = f'{shot.get("notes", "")} [auto-fix: {note}]'.strip()
                break

        # Fix visual
        for old, new_val in visual_fixes.items():
            if old in vis:
                fixed["visual"] = vis.replace(old, new_val)
                note = f"替换{old}为{new_val}"
                existing = shot.get("notes", "")
                if "[auto-fix" not in existing:
                    fixed["notes"] = f"{existing} [auto-fix: {note}]".strip()
                break

        # Fix contradictory angles
        if "俯拍" in vis and "仰拍" in vis:
            fixed["visual"] = vis.replace("仰拍", "平视")
            fixed["notes"] = f'{shot.get("notes", "")} [auto-fix: 矛盾角度]'.strip()

        result.append(fixed)
    return result
