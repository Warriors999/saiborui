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
            bar = "█" * bar_len
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
            bar = "█" * bar_len
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
            bar = "█" * bar_len
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
