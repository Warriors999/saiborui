"""Video performance tracking — data import, script matching, Direction-B scoring.

Three-level matching:
  L1: auto-match  — product name keyword exact match + ≤7 day window
  L2: fuzzy match — category overlap + partial keyword hit
  L3: unmatched   — logged but not linked, for future manual review

Direction-B scoring (multi-dimensional weighted):
  Effectiveness = w1*reach + w2*retention + w3*engagement + w4*hook
  Weights learnable over time as paired data accumulates.
"""

import json
import re
import threading
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, stdev

from rag_system.utils import logger
from rag_system.config import PROJECT_ROOT

# ── File paths ──
PERF_DIR = PROJECT_ROOT / "output" / "performance"
PERF_DIR.mkdir(parents=True, exist_ok=True)
PERF_STORE = PERF_DIR / "video_performance.json"
MATCH_STORE = PERF_DIR / "script_video_matches.json"
CAT_PROFILES = PERF_DIR / "category_profiles.json"
_lock = threading.Lock()

# ── Product name keyword extraction ──
PRODUCT_BRANDS = {
    "ROG", "AOC", "AGON", "Alienware", "NVIDIA", "英伟达", "AMD", "Intel", "英特尔",
    "机械革命", "华硕", "联想", "微星", "MSI", "雷蛇", "Razer", "罗技", "Logitech",
    "七彩虹", "铭瑄", "红魔", "雷柏", "迈从", "狼蛛", "西伯利亚", "iKF", "觅声",
    "骁骑", "黑白调", "转转", "IQUNIX", "EV63", "NUC", "Mac", "Apple",
}
PRODUCT_MODEL_PATTERN = re.compile(
    r'(?:RTX\s*\d{4}|GTX\s*\d{3,4}|'
    r'[A-Z]\d{2,4}[A-Z]?\d*|'
    r'Ultra\s*\d|i[3579]-\d{4,5}[A-Z]?|'
    r'R[3579]\s*\d{4}[A-Z]?|'
    r'[A-Z]\d{3}[A-Z]{0,2})',
    re.IGNORECASE,
)

# ── Direction-B default weights (learnable) ──
DEFAULT_WEIGHTS = {
    "w_reach": 0.25,       # normalized views
    "w_retention": 0.35,   # composite: 5s_rate + (1 - 2s_drop)
    "w_engagement": 0.25,  # normalized watch time
    "w_hook": 0.15,        # 5s completion rate * 2
}


# ═══════════════════════════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════════════════════════

class VideoPerformance:
    """Single video's performance metrics."""
    __slots__ = ("title", "publish_time", "views", "s5_rate", "s2_drop",
                 "avg_duration", "likes", "comments", "shares", "category",
                 "matched_script")

    def __init__(self, title="", publish_time="", views=0, s5_rate=0.0,
                 s2_drop=0.0, avg_duration=0.0, likes=0, comments=0,
                 shares=0, category="", matched_script=""):
        self.title = title
        self.publish_time = publish_time
        self.views = views
        self.s5_rate = s5_rate
        self.s2_drop = s2_drop
        self.avg_duration = avg_duration
        self.likes = likes
        self.comments = comments
        self.shares = shares
        self.category = category
        self.matched_script = matched_script

    def to_dict(self):
        return {s: getattr(self, s) for s in self.__slots__}

    @staticmethod
    def from_dict(d):
        v = VideoPerformance()
        for k, val in d.items():
            if k in VideoPerformance.__slots__:
                setattr(v, k, val)
        return v

    @property
    def retention_composite(self):
        return (1.0 - self.s2_drop) * 0.5 + self.s5_rate * 0.5

    def effectiveness(self, weights=None):
        w = weights or DEFAULT_WEIGHTS
        reach = min(self.views / 300000.0, 1.0)
        retention = self.retention_composite
        engagement = min(self.avg_duration / 20.0, 1.0)
        hook = min(self.s5_rate * 2.0, 1.0)
        return round(
            w["w_reach"] * reach +
            w["w_retention"] * retention +
            w["w_engagement"] * engagement +
            w["w_hook"] * hook, 4
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Performance Store — load / save / import
# ═══════════════════════════════════════════════════════════════════════════════

def load_performances() -> list[VideoPerformance]:
    if not PERF_STORE.exists():
        return []
    with open(PERF_STORE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [VideoPerformance.from_dict(d) for d in data]


def save_performances(perfs: list[VideoPerformance]):
    with _lock:
        PERF_STORE.write_text(
            json.dumps([p.to_dict() for p in perfs], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def import_from_xlsx(xlsx_path: str) -> int:
    """Import video performance data from xlsx.

    Expected columns: 视频标题, 发布时间, 播放量, 5s完播率, 2s跳出率, 平均播放时长
    Optional: 点赞, 评论, 分享
    """
    import openpyxl
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    wb.close()

    existing = load_performances()
    existing_titles = {p.title for p in existing}
    imported = 0

    for row in rows:
        if not row or not row[0]:
            continue
        title = str(row[0]).strip()
        if title in existing_titles:
            continue
        v = VideoPerformance(
            title=title,
            publish_time=str(row[1]).strip() if len(row) > 1 and row[1] else "",
            views=int(row[2]) if len(row) > 2 and row[2] else 0,
            s5_rate=float(row[3]) if len(row) > 3 and row[3] else 0.0,
            s2_drop=float(row[4]) if len(row) > 4 and row[4] else 0.0,
            avg_duration=float(row[5]) if len(row) > 5 and row[5] else 0.0,
            likes=int(row[6]) if len(row) > 6 and row[6] else 0,
            comments=int(row[7]) if len(row) > 7 and row[7] else 0,
            shares=int(row[8]) if len(row) > 8 and row[8] else 0,
        )
        existing.append(v)
        imported += 1

    save_performances(existing)
    logger.info(f"Imported {imported} new videos (total: {len(existing)})")
    return imported


# ═══════════════════════════════════════════════════════════════════════════════
# Product Name Extraction
# ═══════════════════════════════════════════════════════════════════════════════

def _extract_product_keywords(text: str) -> set[str]:
    """Extract product-identifying keywords from a title or product name."""
    keywords = set()
    # Extract brands
    for brand in PRODUCT_BRANDS:
        if brand.lower() in text.lower():
            keywords.add(brand.lower())
    # Extract model numbers
    for m in PRODUCT_MODEL_PATTERN.finditer(text):
        keywords.add(m.group().lower())
    return keywords


# ═══════════════════════════════════════════════════════════════════════════════
# Script-to-Video Matching Engine
# ═══════════════════════════════════════════════════════════════════════════════

CATEGORY_KEYWORDS_MAP = {
    "keyboard": ["键盘", "键帽", "轴体", "磁轴", "客制化", "机械键盘", "qmk", "via"],
    "monitor": ["显示器", "高刷", "刷新率", "分辨率", "IPS", "HDR", "面板"],
    "mouse": ["鼠标", "轻量化", "传感器", "DPI", "回报率", "无线鼠标"],
    "gpu": ["显卡", "RTX", "GTX", "5060", "5070", "5080", "5090", "DLSS", "帧生成"],
    "laptop": ["笔记本", "游戏本", "轻薄本", "全能本"],
    "headphone": ["耳机", "电竞耳机", "头戴式", "入耳式", "TWS", "降噪"],
    "phone": ["手机", "iPhone", "安卓", "旗舰"],
    "desk_chair": ["电竞椅", "人体工学", "升降桌", "座椅", "S9Game"],
    "speaker": ["音箱", "音响", "电竞音箱"],
}


def _infer_category_from_title(title: str) -> str:
    title_lower = title.lower()
    scores = {}
    for cat, kws in CATEGORY_KEYWORDS_MAP.items():
        score = sum(1 for kw in kws if kw.lower() in title_lower)
        if score > 0:
            scores[cat] = score
    if not scores:
        return "other"
    return max(scores, key=scores.get)


def run_match(interactive: bool = True) -> dict:
    """Match pipeline-generated scripts to published videos.

    Returns summary of matches made.
    """
    from rag_system.generation.analytics import read_events

    # Load existing matches
    matches = _load_matches()
    already_matched_videos = {m["video_title"] for m in matches}
    already_matched_scripts = {m["product"] for m in matches}

    # Load video performances
    perfs = load_performances()
    for p in perfs:
        if not p.category:
            p.category = _infer_category_from_title(p.title)

    # Get pipeline generation events
    events = read_events(days=180)
    gen_events = [e for e in events if e.get("type") == "generate"]

    new_auto = []
    new_fuzzy = []

    for perf in perfs:
        if perf.title in already_matched_videos:
            continue

        perf_kw = _extract_product_keywords(perf.title)

        for ge in gen_events:
            product = ge.get("product", "")
            if product in already_matched_scripts:
                continue

            prod_kw = _extract_product_keywords(product)
            cat = ge.get("category", "")

            # Time window: within 14 days after generation
            try:
                gen_ts = datetime.fromisoformat(ge.get("ts", ""))
                pub_ts = datetime.strptime(perf.publish_time, "%Y-%m-%d %H:%M")
                days_diff = (pub_ts - gen_ts).days
                if days_diff < 0 or days_diff > 14:
                    continue
            except (ValueError, TypeError):
                days_diff = 999

            # Level 1: auto-match — brand/model keyword overlap + time window
            overlap = perf_kw & prod_kw
            if len(overlap) >= 2 and days_diff <= 7:
                confidence = min(1.0, len(overlap) / max(len(perf_kw), 1) + 0.2)
                new_auto.append({
                    "product": product, "video_title": perf.title,
                    "video_views": perf.views, "category": cat,
                    "confidence": round(confidence, 2),
                    "reason": f"产品词匹配: {overlap} | 时间差{days_diff}天",
                })
                perf.matched_script = product
                break

            # Level 2: fuzzy match — category match + partial keyword
            perf_cat = _infer_category_from_title(perf.title)
            if perf_cat == cat or (perf_kw & prod_kw):
                confidence = 0.45 + min(0.35, len(overlap) * 0.1) + (0.2 if perf_cat == cat else 0)
                new_fuzzy.append({
                    "product": product, "video_title": perf.title,
                    "video_views": perf.views, "category": cat,
                    "confidence": round(confidence, 2),
                    "reason": f"品类: {cat} | 时间差{days_diff}天 | 词重合: {overlap}",
                })
                break

    # Process results
    result = {"auto_matched": 0, "fuzzy_confirmed": 0, "unmatched_performances": 0,
              "unmatched_scripts": 0, "matches": []}

    # Auto matches
    for m in new_auto:
        matches.append(m)
        result["auto_matched"] += 1
        result["matches"].append(m)

    # Fuzzy matches — interactive or auto
    if new_fuzzy:
        if interactive:
            print(f"\n  发现 {len(new_fuzzy)} 条候选匹配待确认:\n")
            for i, m in enumerate(new_fuzzy, 1):
                print(f"  [{i}] '{m['product']}' → '{m['video_title'][:50]}...'")
                print(f"      品类:{m['category']} | 播放:{m['video_views']:,} | 置信度:{m['confidence']:.0%}")
                print(f"      依据: {m['reason']}")
                print()
            try:
                choice = input(f"  全部确认? [Y=全部确认 / N=跳过 / 数字逗号分隔=选择]: ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                choice = "n"
        else:
            choice = "y"  # non-interactive: auto-confirm all

        if choice == "y" or choice == "":
            matches.extend(new_fuzzy)
            result["fuzzy_confirmed"] = len(new_fuzzy)
            result["matches"].extend(new_fuzzy)
            for m in new_fuzzy:
                for p in perfs:
                    if p.title == m["video_title"]:
                        p.matched_script = m["product"]
        elif choice != "n":
            # User selected specific indices
            try:
                indices = [int(x.strip()) - 1 for x in choice.split(",")]
                confirmed = [new_fuzzy[i] for i in indices if 0 <= i < len(new_fuzzy)]
                matches.extend(confirmed)
                result["fuzzy_confirmed"] = len(confirmed)
                result["matches"].extend(confirmed)
                for m in confirmed:
                    for p in perfs:
                        if p.title == m["video_title"]:
                            p.matched_script = m["product"]
            except (ValueError, IndexError):
                print("  输入格式错误，跳过模糊匹配。")

    # Save
    _save_matches(matches)
    save_performances(perfs)

    # Count unmatched
    result["unmatched_performances"] = sum(1 for p in perfs
                                            if p.title not in {m["video_title"] for m in matches})
    result["unmatched_scripts"] = sum(1 for ge in gen_events
                                       if ge.get("product", "") not in {m["product"] for m in matches})

    return result


def _load_matches() -> list[dict]:
    if not MATCH_STORE.exists():
        return []
    return json.loads(MATCH_STORE.read_text(encoding="utf-8"))


def _save_matches(matches: list[dict]):
    MATCH_STORE.parent.mkdir(parents=True, exist_ok=True)
    MATCH_STORE.write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
# Direction-B: Multi-dimensional Weighted Scoring
# ═══════════════════════════════════════════════════════════════════════════════

def compute_effectiveness_scores(perfs: list[VideoPerformance] = None,
                                 weights: dict = None) -> list[dict]:
    """Compute direction-B composite scores for all videos."""
    if perfs is None:
        perfs = load_performances()
    w = weights or DEFAULT_WEIGHTS
    results = []
    for p in perfs:
        results.append({
            "title": p.title,
            "views": p.views,
            "s5_rate": p.s5_rate,
            "s2_drop": p.s2_drop,
            "avg_duration": p.avg_duration,
            "category": p.category,
            "matched_script": p.matched_script,
            "score": p.effectiveness(w),
            "reach_score": min(p.views / 300000.0, 1.0),
            "retention_score": p.retention_composite,
            "engagement_score": min(p.avg_duration / 20.0, 1.0),
            "hook_score": min(p.s5_rate * 2.0, 1.0),
        })
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def analyze_best_practices(perfs: list[VideoPerformance] = None,
                           min_score: float = 0.5) -> dict:
    """Mine best practices from top-performing videos.

    For matched videos (those with pipeline scripts), extracts:
    - Which categories perform best
    - Which hook types correlate with high retention
    - Score distributions by category
    """
    if perfs is None:
        perfs = load_performances()

    scored = compute_effectiveness_scores(perfs)
    if not scored:
        return {"error": "no data"}

    # Top vs bottom split
    top10 = scored[:max(1, len(scored) // 4)]
    bottom10 = scored[-max(1, len(scored) // 4):]

    # By category
    cat_scores = defaultdict(list)
    for s in scored:
        cat_scores[s["category"]].append(s["score"])
    cat_analysis = {}
    for cat, scores_list in sorted(cat_scores.items()):
        if len(scores_list) < 2:
            continue
        cat_analysis[cat] = {
            "count": len(scores_list),
            "avg_score": round(mean(scores_list), 3),
            "best_score": round(max(scores_list), 3),
            "stdev": round(stdev(scores_list), 3) if len(scores_list) > 1 else 0,
        }

    # Matched vs unmatched
    matched = [s for s in scored if s["matched_script"]]
    unmatched = [s for s in scored if not s["matched_script"]]
    match_compare = {
        "matched_count": len(matched),
        "matched_avg_score": round(mean([s["score"] for s in matched]), 3) if matched else 0,
        "unmatched_count": len(unmatched),
        "unmatched_avg_score": round(mean([s["score"] for s in unmatched]), 3) if unmatched else 0,
    }

    return {
        "total_videos": len(scored),
        "score_range": {"min": scored[-1]["score"], "max": scored[0]["score"],
                         "median": scored[len(scored)//2]["score"]},
        "top_performers": top10[:5],
        "bottom_performers": bottom10[:5],
        "by_category": cat_analysis,
        "matched_vs_unmatched": match_compare,
    }


def generate_effectiveness_report() -> str:
    """Generate a Direction-B effectiveness report for the CLI."""
    perfs = load_performances()
    if not perfs:
        return "暂无视频表现数据。请先导入数据: saiborui performance import <文件路径>"

    scored = compute_effectiveness_scores(perfs)
    analysis = analyze_best_practices(perfs)

    lines = []
    lines.append("=" * 65)
    lines.append("  Direction-B 多维加权效能报告")
    lines.append("=" * 65)
    lines.append(f"  总视频: {len(scored)} | 已匹配管线脚本: {analysis['matched_vs_unmatched']['matched_count']}")
    lines.append(f"  评分范围: {analysis['score_range']['min']:.3f} ~ {analysis['score_range']['max']:.3f} "
                 f"(中位: {analysis['score_range']['median']:.3f})")
    lines.append("")
    lines.append("  加权公式: 0.25*reach + 0.35*retention + 0.25*engagement + 0.15*hook")
    lines.append("-" * 65)

    # Top 5
    lines.append("\n  ◆ Top 5 最高效能视频:")
    for s in scored[:5]:
        lines.append(f"    分{s['score']:.3f} | {s['views']:,}播放 | "
                     f"5s完{s['s5_rate']:.1%} | {s['avg_duration']:.1f}s | {s['category']}")
        lines.append(f"    {s['title'][:70]}")

    # Category breakdown
    lines.append("\n  ◆ 品类效能排名:")
    cat_sorted = sorted(analysis["by_category"].items(), key=lambda x: x[1]["avg_score"], reverse=True)
    for cat, info in cat_sorted:
        bar = "█" * int(info["avg_score"] * 20)
        lines.append(f"    {cat:10s}: 均分{info['avg_score']:.3f} {bar} ({info['count']}条)")

    # Bottom 3
    lines.append("\n  ◆ 最需改进 (Bottom 3):")
    for s in scored[-3:]:
        issues = []
        if s["hook_score"] < 0.3: issues.append("钩子弱")
        if s["retention_score"] < 0.4: issues.append("留存低")
        if s["engagement_score"] < 0.3: issues.append("时长不足")
        lines.append(f"    分{s['score']:.3f} | {s['views']:,}播放 | 问题: {', '.join(issues) or '综合偏低'}")
        lines.append(f"    {s['title'][:70]}")

    lines.append("\n" + "=" * 65)
    # Weight learning note
    if analysis["matched_vs_unmatched"]["matched_count"] >= 5:
        lines.append("  提示: 配对数据>=5条，可以运行 'saiborui performance learn' 学习最优权重")
    else:
        lines.append("  需要更多管线匹配数据才能学习权重。运行 'saiborui match' 建立配对。")
    lines.append("=" * 65)
    return "\n".join(lines)


def learn_weights() -> dict:
    """Learn optimal Direction-B weights from matched (script, video) pairs.

    Uses simple linear regression: for each matched pair, the target is the
    effectiveness score. Adjusts weights to maximize correlation between
    script audit scores and real video performance.
    """
    matches = _load_matches()
    perfs = load_performances()
    from rag_system.generation.analytics import read_events

    # Only use matched pairs
    matched_perfs = [p for p in perfs if p.matched_script]
    if len(matched_perfs) < 3:
        logger.warning("Need >= 3 matched pairs for weight learning, got %d", len(matched_perfs))
        return DEFAULT_WEIGHTS

    # Find audit events for matched scripts
    events = read_events(days=180)
    pairs = []
    for mp in matched_perfs:
        audit = None
        for e in events:
            if e.get("type") == "audit" and e.get("product") == mp.matched_script:
                audit = e
                break
        if audit:
            pairs.append((mp, audit))

    if len(pairs) < 3:
        logger.warning("Only %d pairs with audit data", len(pairs))
        return DEFAULT_WEIGHTS

    # Grid search for optimal weights
    best_weights = dict(DEFAULT_WEIGHTS)
    best_corr = -1

    for w_reach in [0.1, 0.15, 0.2, 0.25, 0.3, 0.35]:
        for w_retention in [0.25, 0.3, 0.35, 0.4, 0.45]:
            for w_engage in [0.15, 0.2, 0.25, 0.3, 0.35]:
                w_hook = 1.0 - w_reach - w_retention - w_engage
                if w_hook < 0.05 or w_hook > 0.3:
                    continue
                weights = {"w_reach": w_reach, "w_retention": w_retention,
                           "w_engagement": w_engage, "w_hook": w_hook}

                # Score each video
                scores = []
                audit_passes = []
                for mp, audit in pairs:
                    s = mp.effectiveness(weights)
                    scores.append(s)
                    audit_passes.append(audit.get("passed_count", 0) / max(audit.get("total_checks", 1), 1))

                if len(scores) >= 3:
                    try:
                        corr = abs(_pearson_corr(scores, audit_passes))
                        if corr > best_corr:
                            best_corr = corr
                            best_weights = dict(weights)
                    except Exception:
                        continue

    # Save learned weights
    weights_file = PERF_DIR / "learned_weights.json"
    learned = {"weights": best_weights, "correlation_with_audit": round(best_corr, 3),
               "training_pairs": len(pairs), "learned_at": datetime.now().isoformat()}
    weights_file.write_text(json.dumps(learned, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Learned weights: {best_weights} (corr={best_corr:.3f}, n={len(pairs)})")
    return best_weights


def _pearson_corr(x: list, y: list) -> float:
    n = len(x)
    if n < 3: return 0
    mx, my = mean(x), mean(y)
    num = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    den = (sum((xi - mx) ** 2 for xi in x) * sum((yi - my) ** 2 for yi in y)) ** 0.5
    return num / den if den > 0 else 0


def get_learned_weights() -> dict:
    wf = PERF_DIR / "learned_weights.json"
    if wf.exists():
        return json.loads(wf.read_text(encoding="utf-8")).get("weights", DEFAULT_WEIGHTS)
    return dict(DEFAULT_WEIGHTS)
