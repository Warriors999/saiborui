"""Generate weekly/monthly competitive analysis reports."""

from collections import Counter
from datetime import datetime, timedelta

from rag_system.competitive.models import WeeklyReport
from rag_system.competitive.store import get_analyzed_videos, save_report


def generate_weekly_report() -> WeeklyReport:
    """Generate a report for the past 7 days."""
    now = datetime.now()
    week_ago = (now - timedelta(days=7)).isoformat()
    now_iso = now.isoformat()

    all_videos = get_analyzed_videos()
    recent = [v for v in all_videos if v.get("analyzed_at", "") >= week_ago]

    report = WeeklyReport(
        period_start=week_ago[:10],
        period_end=now_iso[:10],
        videos_analyzed=len(recent),
    )

    if not recent:
        report.recommendations = ["本周无新分析的视频。运行 search 命令开始收集。"]
        save_report(report)
        return report

    # Top creators
    creator_counts = Counter(v.get("creator", "unknown") for v in recent)
    report.top_creators = [name for name, _ in creator_counts.most_common(5)]

    # Trending hook types
    hook_counts = Counter(v.get("hook_type", "unknown") for v in recent)
    report.trending_hook_types = dict(hook_counts.most_common())

    # Category insights
    cat_groups = {}
    for v in recent:
        cat = v.get("category", "other")
        if cat not in cat_groups:
            cat_groups[cat] = []
        cat_groups[cat].append(v)
    for cat, vids in cat_groups.items():
        avg_density = sum(v.get("spoken_density", 0) for v in vids) / len(vids)
        top_hook = Counter(v.get("hook_type", "") for v in vids).most_common(1)[0][0]
        report.category_insights[cat] = {
            "count": len(vids),
            "avg_spoken_density": round(avg_density, 2),
            "dominant_hook": top_hook,
        }

    # New patterns
    all_patterns = []
    for v in recent:
        all_patterns.extend(v.get("standout_patterns", []))
    pattern_counts = Counter(all_patterns)
    report.new_patterns_discovered = [p for p, _ in pattern_counts.most_common(5)]

    # Recommendations
    report.recommendations = _generate_recommendations(report)

    save_report(report)
    return report


def _generate_recommendations(report: WeeklyReport) -> list[str]:
    """Generate actionable recommendations from report data."""
    recs = []

    # Hook recommendation
    if report.trending_hook_types:
        top_hook = max(report.trending_hook_types, key=report.trending_hook_types.get)
        recs.append(f"本周最热门钩子类型是「{top_hook}」，建议下期脚本优先尝试该开篇方式")

    # Category gaps
    analyzed_cats = set(report.category_insights.keys())
    all_cats = {"keyboard", "mouse", "monitor", "laptop", "phone", "gpu", "headphone", "desk_chair"}
    missing = all_cats - analyzed_cats
    if missing:
        recs.append(f"以下品类本周无竞品数据: {', '.join(missing)}，建议补充搜索")

    # Top creator
    if report.top_creators:
        recs.append(f"值得关注的创作者: {', '.join(report.top_creators[:3])}")

    return recs
