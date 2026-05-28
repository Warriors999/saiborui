"""Pipeline analytics — structured event logging and aggregated reports.

Tracks every script generation and storyboard creation via JSONL event log,
and provides analytics reports for pipeline monitoring and throughput analysis.
"""

import json
import threading
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

    lines.append("=" * 55)
    return "\n".join(lines)
