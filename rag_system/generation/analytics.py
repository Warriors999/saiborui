"""Pipeline analytics — structured event logging and aggregated reports.

Tracks every script generation and storyboard creation via JSONL event log,
and provides analytics reports for pipeline monitoring and throughput analysis.
"""

import json
import threading
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from rag_system.utils import logger

EVENTS_LOG = Path("output/analytics_events.jsonl")
_lock = threading.Lock()


def log_event(event_type: str, **kwargs) -> None:
    ts = datetime.now().isoformat(timespec="seconds")
    event = {"ts": ts, "type": event_type, **kwargs}
    EVENTS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with open(EVENTS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    logger.debug("Analytics event: %s | %s", event_type, kwargs.get("product", ""))


def read_events(days: int = 0) -> list[dict]:
    if not EVENTS_LOG.exists():
        return []
    cutoff = datetime.now() - timedelta(days=days) if days > 0 else None
    events = []
    with open(EVENTS_LOG, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if cutoff:
                try:
                    event_ts = datetime.fromisoformat(event.get("ts", ""))
                    if event_ts < cutoff:
                        continue
                except (ValueError, TypeError):
                    continue
            events.append(event)
    return events


def generate_report(days: int = 30) -> dict:
    events = read_events(days=days)

    total_generations = 0
    total_storyboards = 0
    by_persona: dict[str, dict] = {}
    by_category: dict[str, dict] = {}
    by_format: dict[str, int] = {}
    total_output_chars = 0
    total_shots = 0

    for e in events:
        etype = e.get("type", "")
        persona = e.get("persona", "unknown")
        category = e.get("category", "unknown")

        if etype == "generate":
            total_generations += 1
            total_output_chars += e.get("char_count", 0)
            fmt = e.get("format", "review")
            by_format[fmt] = by_format.get(fmt, 0) + 1

            if persona not in by_persona:
                by_persona[persona] = {"scripts": 0, "storyboards": 0, "total_vo_chars": 0}
            by_persona[persona]["scripts"] += 1

            if category not in by_category:
                by_category[category] = {"scripts": 0, "storyboards": 0}
            by_category[category]["scripts"] += 1

        elif etype == "storyboard":
            total_storyboards += 1
            total_shots += e.get("shot_count", 0)
            vo_chars = e.get("vo_chars", 0)

            if persona not in by_persona:
                by_persona[persona] = {"scripts": 0, "storyboards": 0, "total_vo_chars": 0}
            by_persona[persona]["storyboards"] += 1
            by_persona[persona]["total_vo_chars"] += vo_chars

            if category not in by_category:
                by_category[category] = {"scripts": 0, "storyboards": 0}
            by_category[category]["storyboards"] += 1

    # Velocity: avg generations per day over last 7 days
    recent = read_events(days=7)
    gen_count_7d = sum(1 for e in recent if e.get("type") == "generate")
    velocity_7d = round(gen_count_7d / 7.0, 1)

    now = datetime.now()
    period_start = (now - timedelta(days=days)).isoformat(timespec="seconds")
    period_end = now.isoformat(timespec="seconds")

    recent_events = events[-20:] if len(events) > 20 else events

    # Persona x Category cross-effectiveness recommendations
    matrix_data = persona_category_matrix(days=days)
    recommendations = matrix_data.get("best_persona_per_category", {})

    return {
        "total_generations": total_generations,
        "total_storyboards": total_storyboards,
        "by_persona": by_persona,
        "by_category": by_category,
        "by_format": by_format,
        "total_output_chars": total_output_chars,
        "total_shots": total_shots,
        "velocity_7d": velocity_7d,
        "recent_events": recent_events,
        "period_start": period_start,
        "period_end": period_end,
        "recommendations": recommendations,
    }


def format_report(report: dict) -> str:
    lines = []
    lines.append("=" * 55)
    lines.append(f"  Pipeline Analytics Report")
    lines.append(f"  Period: {report['period_start'][:10]} -> {report['period_end'][:10]}")
    lines.append("=" * 55)
    lines.append(f"  Total Generations:   {report['total_generations']:>5}")
    lines.append(f"  Total Storyboards:   {report['total_storyboards']:>5}")
    lines.append(f"  Total Output Chars:  {report['total_output_chars']:>5}")
    lines.append(f"  Total Shots:         {report['total_shots']:>5}")
    lines.append(f"  Velocity (7d avg):   {report['velocity_7d']:>5.1f} gens/day")

    bp = report["by_persona"]
    if bp:
        lines.append("")
        lines.append("  By Persona:")
        sorted_bp = sorted(
            bp.items(),
            key=lambda x: x[1]["scripts"] + x[1]["storyboards"],
            reverse=True,
        )
        for name, counts in sorted_bp:
            total = counts["scripts"] + counts["storyboards"]
            bar_len = min(total, 30)
            bar = "#" * bar_len
            lines.append(
                f"    {name:<20} {counts['scripts']:>3}s + {counts['storyboards']:>3}b = {total:>3}  {bar}"
            )

    bc = report["by_category"]
    if bc:
        lines.append("")
        lines.append("  By Category:")
        sorted_bc = sorted(
            bc.items(),
            key=lambda x: x[1]["scripts"] + x[1]["storyboards"],
            reverse=True,
        )
        for name, counts in sorted_bc:
            total = counts["scripts"] + counts["storyboards"]
            bar_len = min(total, 30)
            bar = "#" * bar_len
            lines.append(
                f"    {name:<20} {counts['scripts']:>3}s + {counts['storyboards']:>3}b = {total:>3}  {bar}"
            )

    bf = report["by_format"]
    if bf:
        lines.append("")
        lines.append("  By Format:")
        sorted_bf = sorted(bf.items(), key=lambda x: x[1], reverse=True)
        for fmt, count in sorted_bf:
            bar_len = min(count, 30)
            bar = "#" * bar_len
            lines.append(f"    {fmt:<20} {count:>5}  {bar}")

    # Recommendations: best persona per category
    recommendations = report.get("recommendations", {})
    if recommendations:
        lines.append("")
        lines.append("  Recommendations (best persona per category):")
        for cat, persona in sorted(recommendations.items()):
            lines.append(f"    {cat:<20} -> {persona}")

    lines.append("=" * 55)
    return "\n".join(lines)


def persona_category_matrix(days: int = 90) -> dict:
    """Build a persona x category cross-effectiveness matrix from analytics events.

    Queries both "generate" and "audit" events to compute composite effectiveness
    scores for every persona-category pairing, implementing the "含潘量"
    methodology — data-driven persona selection for each product category.

    Parameters
    ----------
    days : int
        Lookback window in days (default 90).

    Returns
    -------
    dict
        {
            "matrix": [ {persona, category, total_generations, avg_chars,
                         audit_pass_rate, top_failed_checks, effectiveness_score}, ... ],
            "best_persona_per_category": { "keyboard": "折腾到吐", ... }
        }
    """
    events = read_events(days=days)

    # Aggregate by (persona, category)
    agg: dict[tuple[str, str], dict] = {}

    for e in events:
        persona = e.get("persona", "unknown")
        category = e.get("category", "unknown")
        key = (persona, category)

        if key not in agg:
            agg[key] = {
                "persona": persona,
                "category": category,
                "total_generations": 0,
                "total_chars": 0,
                "audit_count": 0,
                "audit_passed": 0,
                "total_failed_checks": 0,
                "failed_check_counter": Counter(),
            }

        entry = agg[key]
        etype = e.get("type", "")

        if etype == "generate":
            entry["total_generations"] += 1
            entry["total_chars"] += e.get("char_count", 0)
        elif etype == "audit":
            entry["audit_count"] += 1
            if e.get("passed"):
                entry["audit_passed"] += 1
            failed = e.get("failed_checks", [])
            entry["total_failed_checks"] += len(failed)
            for check_name in failed:
                entry["failed_check_counter"][check_name] += 1

    # Build output matrix
    matrix = []
    best_per_category: dict[str, tuple[str, float]] = {}

    for entry in agg.values():
        persona = entry["persona"]
        category = entry["category"]
        total_gens = entry["total_generations"]

        avg_chars = round(entry["total_chars"] / total_gens) if total_gens > 0 else 0

        # Audit pass rate
        if entry["audit_count"] > 0:
            audit_pass_rate = round(entry["audit_passed"] / entry["audit_count"], 2)
            avg_failures = entry["total_failed_checks"] / entry["audit_count"]
        else:
            audit_pass_rate = 0.0
            avg_failures = 0.0

        # Top failed checks (most frequent across all audits for this combo)
        top_failed = [name for name, _ in entry["failed_check_counter"].most_common(3)]

        # Composite effectiveness score (0-10)
        # base 5.0 + audit_pass_rate*3 + (1 - avg_failures/5)*2
        score = 5.0
        score += audit_pass_rate * 3.0
        score += (1.0 - min(avg_failures, 5.0) / 5.0) * 2.0
        score = max(0.0, min(10.0, score))
        score = round(score, 1)

        row = {
            "persona": persona,
            "category": category,
            "total_generations": total_gens,
            "avg_chars": avg_chars,
            "audit_pass_rate": audit_pass_rate,
            "top_failed_checks": top_failed,
            "effectiveness_score": score,
        }
        matrix.append(row)

        # Track best persona per category by effectiveness score
        if category not in best_per_category or score > best_per_category[category][1]:
            best_per_category[category] = (persona, score)

    # Sort matrix by effectiveness_score descending
    matrix.sort(key=lambda x: x["effectiveness_score"], reverse=True)

    return {
        "matrix": matrix,
        "best_persona_per_category": {
            cat: persona for cat, (persona, _) in best_per_category.items()
        },
    }


def format_matrix_report(matrix: dict) -> str:
    """Pretty-print the persona x category cross-effectiveness matrix.

    Parameters
    ----------
    matrix : dict
        Output of persona_category_matrix().

    Returns
    -------
    str
        Formatted table string.
    """
    rows = matrix.get("matrix", [])
    if not rows:
        return "  (no data)"

    lines = []
    lines.append("  人设×品类交叉效能矩阵")
    lines.append("=" * 60)
    lines.append(
        f"  {'人设':<12} {'品类':<12} {'生成数':>6} {'均字数':>6} {'通过率':>6} {'效能分':>6}  高频失败"
    )
    lines.append("-" * 60)

    for row in rows:
        persona = row["persona"]
        category = row["category"]
        gens = row["total_generations"]
        avg_chars = row["avg_chars"]
        pass_rate = f"{int(row['audit_pass_rate'] * 100)}%"
        score = row["effectiveness_score"]
        failed = ",".join(row["top_failed_checks"]) if row["top_failed_checks"] else "-"

        lines.append(
            f"  {persona:<12} {category:<12} {gens:>6} {avg_chars:>6} {pass_rate:>6} {score:>6.1f}  {failed}"
        )

    lines.append("=" * 60)
    return "\n".join(lines)


# ---- Insight Report: data-driven improvement suggestions ----

def generate_insight_report(days: int = 30) -> str:
    """Analyze historical audit data and generate actionable improvement suggestions.

    Reads audit events, finds patterns by persona/category, detects trends,
    and returns a structured improvement report.
    """
    events = read_events(days=days)
    audit_events = [e for e in events if e.get("type") == "audit"]

    if not audit_events:
        return "暂无足够数据生成洞察报告。请先运行几次 generate 命令积累数据。"

    from collections import Counter, defaultdict

    lines = ["", "=" * 60, "  数据洞察报告 — 反推文案/剪辑/拍摄改进", "=" * 60]
    lines.append(f"  分析周期: 最近 {days} 天 | 审计记录: {len(audit_events)} 条")
    lines.append("-" * 60)

    # 1. Overall quality trend
    lines.append("\n[1] 整体质量趋势")
    recent_scores = []
    for ae in sorted(audit_events, key=lambda e: e.get("ts", ""))[-10:]:
        passed = ae.get("passed_count", 0)
        total = ae.get("total_checks", 11)
        ts = ae.get("ts", "")[:10]
        recent_scores.append((ts, passed, total))
    if len(recent_scores) >= 3:
        first_avg = sum(s[1] for s in recent_scores[:3]) / max(len(recent_scores[:3]), 1)
        last_avg = sum(s[1] for s in recent_scores[-3:]) / max(len(recent_scores[-3:]), 1)
        trend = "↑ 改善中" if last_avg > first_avg else ("↓ 下降中" if last_avg < first_avg else "→ 持平")
        lines.append(f"  近期趋势: {trend} (前3次均分 {first_avg:.1f}/11 → 近3次均分 {last_avg:.1f}/11)")
        for ts, p, t in recent_scores[-5:]:
            bar = "#" * p + "-" * (t - p)
            lines.append(f"    {ts}  {bar}  {p}/{t}")

    # 2. High-frequency failures by category
    lines.append("\n[2] 各品类高频失败项 — 针对性改进方向")
    cat_fails: dict[str, Counter] = defaultdict(Counter)
    for ae in audit_events:
        cat = ae.get("category", "unknown")
        for fname in ae.get("failed_checks", []):
            cat_fails[cat][fname] += 1

    FIX_SUGGESTIONS = {
        "信息搬运检测": "文案: 每个产品段落加入具体的体验结论（如「暗光下终于不糊了」），不是加口头禅。拍摄: 加入真人出镜讲述个人体验的镜头。",
        "态度密度": "文案: 每段至少1处明确态度。拍摄: 增加博主面对镜头直接表态的画面。",
        "长短句节奏": "文案: 长短句交替，长句≤25字，短句≤10字。剪辑: 切换节奏——数据段快切，体验段慢推。",
        "口播时长": "文案: 精简口播，删冗余修饰词。剪辑: 加速B-roll，用画面代替口播信息。",
        "电商味": "文案: 避免促销用语，用体验描述代替。拍摄: 减少价格弹窗频率，多拍产品使用场景。",
        "口语化程度": "文案: 多用短句和语气词（吧、啊、呢）。剪辑: 保留自然停顿和语气，不要过度剪辑。",
        "卖点覆盖": "文案: 确保每个核心卖点有对应段落。拍摄: 每个卖点配至少1个特写镜头。",
        "流水账检测": "文案: 避免'首先/然后/接着'结构，用钩子开场。剪辑: 每30秒一个视觉转折点。",
    }

    for cat, fails in sorted(cat_fails.items()):
        top3 = fails.most_common(3)
        if top3:
            lines.append(f"\n  [{cat}]")
            for fname, count in top3:
                fix = FIX_SUGGESTIONS.get(fname, "请检查此项")
                lines.append(f"    {fname} (失败{count}次)")
                lines.append(f"      → {fix}")

    # 3. Cross-reference: what the data says about content quality
    lines.append("\n[3] 综合建议（基于 {0} 天数据）".format(days))
    generate_events = [e for e in events if e.get("type") == "generate"]
    if generate_events:
        avg_chars = sum(e.get("char_count", 0) for e in generate_events) // max(len(generate_events), 1)
        lines.append(f"  平均脚本字数: {avg_chars} (目标: 800-1200)")
        if avg_chars < 700:
            lines.append("    → 字数偏低，可能信息密度不足。建议增加产品细节和体验描述。")
        elif avg_chars > 1300:
            lines.append("    → 字数偏高，注意口播时长。建议精简非核心内容，把部分信息移到花字。")

    overall_fails = Counter()
    for ae in audit_events:
        for fname in ae.get("failed_checks", []):
            overall_fails[fname] += 1
    total_audits = len(audit_events)
    if total_audits > 0 and overall_fails:
        lines.append(f"\n  全局最高频失败项 (TOP 3):")
        for fname, count in overall_fails.most_common(3):
            rate = count / total_audits
            lines.append(f"    - {fname}: {count}/{total_audits}次 ({rate:.0%})")
            fix = FIX_SUGGESTIONS.get(fname, "")
            if fix:
                lines.append(f"      → {fix}")

    lines.append("\n" + "=" * 60)
    lines.append("  提示: 将以上洞察注入下次生成的 --perspective 参数，效果更好。")
    lines.append("=" * 60)
    return "\n".join(lines)
