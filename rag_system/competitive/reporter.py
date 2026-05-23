"""Generate weekly/monthly competitive analysis reports."""

from collections import Counter
from datetime import datetime, timedelta

from pathlib import Path
from rag_system.competitive.models import WeeklyReport
from rag_system.competitive.store import get_analyzed_videos, save_report

REPORTS_DOCX_DIR = Path("output/competitive/reports")


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


def generate_docx_report(videos: list[dict] = None, period: str = "weekly") -> Path:
    """Generate a professionally formatted .docx competitive analysis report.

    Uses Swiss Editorial design system matching the project's docx_formatter style.
    """
    from docx import Document as DocxDocument
    from docx.shared import Pt, Inches, Cm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.style import WD_STYLE_TYPE

    if videos is None:
        videos = get_analyzed_videos()

    doc = DocxDocument()

    # ── Default font ──
    style = doc.styles['Normal']
    style.font.name = '等线'
    style.font.size = Pt(11)
    style.element.rPr.rFonts.set('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}eastAsia', '等线')

    # ── Title ──
    title = doc.add_heading('竞品学习报告', level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = subtitle.add_run(f'Competitive Analysis · {period.upper()} REPORT')
    run.font.size = Pt(10)
    run.font.color.rgb = RGBColor(100, 116, 139)

    doc.add_paragraph()  # spacer

    # ── Summary ──
    doc.add_heading('概览', level=1)
    doc.add_paragraph(f'本期分析 {len(videos)} 个竞品视频，覆盖品类若干。以下为详细分析结果。')

    # ── Video analysis table ──
    doc.add_heading('视频分析详情', level=1)

    for i, v in enumerate(videos, 1):
        title_text = v.get('title', 'Unknown')
        creator = v.get('creator', 'Unknown')
        views = v.get('views', 0)
        hook = v.get('hook_type', '未知')
        spoken = v.get('spoken_density', 0)
        patterns = v.get('standout_patterns', [])

        doc.add_heading(f'{i}. {title_text[:80]}', level=2)

        # Meta line
        meta = doc.add_paragraph()
        run = meta.add_run(f'创作者: {creator}')
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(100, 116, 139)
        run = meta.add_run(f'    |    播放: {views:,}')
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(100, 116, 139)

        # Analysis data
        data = doc.add_paragraph()
        data.style = doc.styles['Normal']
        data.add_run(f'钩子类型: {hook}\n').font.size = Pt(10)
        data.add_run(f'口语密度: {spoken:.1f}/百字\n').font.size = Pt(10)

        if patterns:
            data.add_run(f'亮点模式: {", ".join(patterns)}').font.size = Pt(10)

        doc.add_paragraph()  # spacer

    # ── Recommendations ──
    doc.add_heading('学习建议', level=1)
    report = generate_weekly_report()
    for rec in report.recommendations:
        p = doc.add_paragraph(style='List Bullet')
        p.text = rec

    # ── Footer ──
    doc.add_paragraph()
    footer = doc.add_paragraph()
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer.add_run('— 赛博涛数据驱动内容工厂 · 竞品学习系统 —')
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor(148, 163, 184)

    # Save
    REPORTS_DOCX_DIR.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    date_str = datetime.now().strftime("%Y%m%d")
    path = REPORTS_DOCX_DIR / f"竞品学习报告_{period}_{date_str}.docx"
    doc.save(str(path))
    return path
