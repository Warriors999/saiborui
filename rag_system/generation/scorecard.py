"""
Unified scoring visualization system.

Used by three subsystems:
  1. 选题评分 — topic scoring (6 dimensions, 0-10 each, total /60)
  2. 文案审核 — script audit (11-15 checks from AuditResult)
  3. 分镜审核 — storyboard audit (14 checks, same structure as script audit)

Output: terminal-friendly Unicode bar charts with ANSI-safe coloring,
         works in both GBK and UTF-8 Chinese terminals.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rag_system.generation.auditor import AuditResult

# ---------------------------------------------------------------------------
# ANSI helpers (safe fallback for terminals without ANSI support)
# ---------------------------------------------------------------------------
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_RED = "\033[91m"
_BOLD = "\033[1m"
_RESET = "\033[0m"

# Simplistic env check: disable ANSI if NO_COLOR or TERM=dumb
import os as _os

if _os.environ.get("NO_COLOR") or _os.environ.get("TERM") == "dumb":
    _GREEN = _YELLOW = _RED = _BOLD = _RESET = ""

# ---------------------------------------------------------------------------
# Check-name -> category mapping
# ---------------------------------------------------------------------------
_CATEGORY_MAP: dict[str, str] = {}

# 内容质量
for _name in [
    "口语化程度", "口语化(口播)",
    "态度密度", "态度(口播)",
    "信息搬运检测",
    "卖点覆盖",
    "花字覆盖率",
    "音效覆盖率",
    "音效具体性",
]:
    _CATEGORY_MAP[_name] = "内容质量"

# 结构节奏
for _name in [
    "口播时长",
    "长短句节奏",
    "流水账检测",
    "镜数",
    "时长分布",
    "转场设计",
    "镜头多样性",
]:
    _CATEGORY_MAP[_name] = "结构节奏"

# 合规检查
for _name in [
    "禁用词", "禁用词(口播)",
    "电商味", "电商味(口播)",
    "价格检测",
    "拉踩检测",
    "口播完整",
    "灯位/机位标注",
]:
    _CATEGORY_MAP[_name] = "合规检查"

# ---------------------------------------------------------------------------
# Bar chart primitive
# ---------------------------------------------------------------------------
def score_bar(value: int, max_val: int, width: int = 20) -> str:
    """Draw a unicode bar chart: ████████░░░░ 8/10

    Args:
        value: Current score (0 <= value <= max_val).
        max_val: Maximum possible score.
        width: Total character width of the bar.

    Returns:
        String like "████████░░░░░░░░░░░░ 08/10"
    """
    if max_val <= 0:
        max_val = 1
    ratio = max(0.0, min(1.0, value / max_val))
    filled = round(ratio * width)
    empty = width - filled
    bar = "#" * filled + "-" * empty
    return f"{bar} {value:02d}/{max_val}"


# ---------------------------------------------------------------------------
# Topic scorecard
# ---------------------------------------------------------------------------
TOPIC_DIMENSIONS = [
    ("热度",     "redang"),
    ("信息差",   "info_gap"),
    ("争议性",   "controversy"),
    ("人设匹配", "persona_fit"),
    ("实操价值", "practical_val"),
    ("差异化空间", "diff_space"),
]
TOPIC_DIM_LABELS = [d[0] for d in TOPIC_DIMENSIONS]
TOPIC_DIM_KEYS   = [d[1] for d in TOPIC_DIMENSIONS]
TOPIC_DIM_COUNT  = len(TOPIC_DIMENSIONS)
TOPIC_BAR_WIDTH  = 10   # compact bars for side-by-side table
TOPIC_MAX_SCORE  = 10


def render_topic_scorecard(topics: list) -> str:
    """Render multi-topic scoring table ranked by total_score descending.

    Each topic is expected to have:
      - title: str
      - scores: dict[str, float]  (keyed by dimension key or label)
      - total_score: float
      - reason: str

    Returns a formatted multi-line string.
    """
    if not topics:
        return "(no topics)"

    # Sort descending by total_score
    sorted_topics = sorted(topics, key=lambda t: getattr(t, "total_score", 0.0), reverse=True)

    lines: list[str] = []
    lines.append(_BOLD + "=" * 72 + _RESET)
    lines.append(_BOLD + "                    选题评分排名" + _RESET)
    lines.append(_BOLD + "=" * 72 + _RESET)
    lines.append("")

    # Header line: rank | title | dim bars ...
    header_cols = ["#", "选题"]
    for label in TOPIC_DIM_LABELS:
        header_cols.append(label)
    header_cols.append("总分")
    header_cols.append("理由")

    # Build header
    header = f"{'#':>2s}  {'选题':<20s}"
    for label in TOPIC_DIM_LABELS:
        header += f" {label:<10s}"
    header += f" {'总分':>4s}"
    lines.append(header)
    lines.append("-" * len(header))

    for idx, topic in enumerate(sorted_topics, 1):
        title = getattr(topic, "title", "???")
        scores = getattr(topic, "scores", {})
        total = getattr(topic, "total_score", 0.0)
        reason = getattr(topic, "reason", "")

        # Truncate long titles
        display_title = title[:18] + ".." if len(title) > 20 else title

        # Build row
        row = f"{idx:>2d}  {display_title:<20s}"
        for dim_label, dim_key in zip(TOPIC_DIM_LABELS, TOPIC_DIM_KEYS):
            val = scores.get(dim_key, scores.get(dim_label, 0))
            val_int = int(round(float(val)))
            bar = score_bar(val_int, TOPIC_MAX_SCORE, width=TOPIC_BAR_WIDTH)
            row += f" {bar}"
        row += f" {total:>4.0f}"

        # Medals for top 3
        if idx == 1:
            row = _BOLD + _GREEN + row + _RESET
        elif idx == 2:
            row = _YELLOW + row + _RESET
        elif idx == 3:
            row = row  # no highlight for bronze

        lines.append(row)
        if reason:
            lines.append(f"    理由: {reason[:80]}")
        lines.append("")

    # Summary footer
    lines.append("-" * 72)
    lines.append(f"共 {len(sorted_topics)} 个选题候选")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Audit scorecard (script + storyboard)
# ---------------------------------------------------------------------------
_CATEGORY_ORDER = ["内容质量", "结构节奏", "合规检查"]


def _categorize_checks(checks: list[dict]) -> dict[str, list[dict]]:
    """Group checks into categories. Unknown checks go to '其他'."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for c in checks:
        cat = _CATEGORY_MAP.get(c.get("name", ""), "其他")
        groups[cat].append(c)
    return dict(groups)


def _status_icon(passed: bool) -> str:
    """Return a colored status icon."""
    if passed:
        return f"{_GREEN}[PASS]{_RESET}"
    else:
        return f"{_RED}[FAIL]{_RESET}"


def render_audit_scorecard(result: "AuditResult", title: str = "") -> str:
    """Render an audit result as a scorecard.

    Groups checks into categories (内容质量/结构节奏/合规检查).
    Color codes: green=pass, yellow=warning, red=fail.
    """
    lines: list[str] = []

    # ---- Header ----
    overall = result.passed
    if overall:
        status_badge = f"{_GREEN}{_BOLD}[  PASS  ]{_RESET}"
    else:
        status_badge = f"{_RED}{_BOLD}[  FAIL  ]{_RESET}"

    header_text = title or "审核结果"
    lines.append(_BOLD + "=" * 64 + _RESET)
    lines.append(f"{_BOLD}  {header_text}  {status_badge}{_RESET}")
    lines.append(_BOLD + "=" * 64 + _RESET)
    lines.append("")

    # ---- Summary line ----
    total = len(result.checks)
    passed_count = sum(1 for c in result.checks if c.get("passed"))
    lines.append(f"  通过: {_GREEN}{passed_count}{_RESET}/{total}  "
                 f"失败: {_RED}{total - passed_count}{_RESET}")
    lines.append("")

    # ---- Checks by category ----
    groups = _categorize_checks(result.checks)

    for cat in _CATEGORY_ORDER:
        if cat not in groups:
            continue
        cat_checks = groups[cat]
        cat_passed = sum(1 for c in cat_checks if c.get("passed"))
        lines.append(f"  {_BOLD}--- {cat} ({cat_passed}/{len(cat_checks)}) ---{_RESET}")

        for c in cat_checks:
            name = c.get("name", "???")
            passed = c.get("passed", False)
            detail = c.get("detail", "")
            icon = _status_icon(passed)
            lines.append(f"    {icon} {name}")
            if detail:
                # Color detail text based on pass/fail
                if passed:
                    lines.append(f"        {detail}")
                else:
                    lines.append(f"        {_YELLOW}{detail}{_RESET}")
        lines.append("")

    # Handle uncategorized checks
    if "其他" in groups:
        other_checks = groups["其他"]
        other_passed = sum(1 for c in other_checks if c.get("passed"))
        lines.append(f"  {_BOLD}--- 其他 ({other_passed}/{len(other_checks)}) ---{_RESET}")
        for c in other_checks:
            name = c.get("name", "???")
            passed = c.get("passed", False)
            detail = c.get("detail", "")
            icon = _status_icon(passed)
            lines.append(f"    {icon} {name}")
            if detail:
                if passed:
                    lines.append(f"        {detail}")
                else:
                    lines.append(f"        {_YELLOW}{detail}{_RESET}")
        lines.append("")

    # ---- Warnings ----
    if result.warnings:
        lines.append(f"  {_BOLD}{_YELLOW}[!] 提醒 ({len(result.warnings)}){_RESET}")
        for w in result.warnings:
            lines.append(f"    {_YELLOW}- {w}{_RESET}")
        lines.append("")

    # ---- Suggestions ----
    if result.suggestions:
        lines.append(f"  {_BOLD}[>>] 建议 ({len(result.suggestions)}){_RESET}")
        for s in result.suggestions:
            lines.append(f"    - {s}")
        lines.append("")

    # ---- Dimension scores (if any) ----
    if result.scores:
        lines.append(f"  {_BOLD}[==] 分项得分{_RESET}")
        for k, v in result.scores.items():
            lines.append(f"    {k}: {v}")
        lines.append("")

    lines.append("-" * 64)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Convenience: quick bar-chart summary for a single topic
# ---------------------------------------------------------------------------
def render_topic_bars(scores: dict) -> str:
    """Render just the 6-dimension bar chart for a single topic."""
    lines: list[str] = []
    for dim_label, dim_key in zip(TOPIC_DIM_LABELS, TOPIC_DIM_KEYS):
        val = scores.get(dim_key, scores.get(dim_label, 0))
        val_int = int(round(float(val)))
        bar = score_bar(val_int, TOPIC_MAX_SCORE, width=30)
        lines.append(f"  {dim_label:<6s} {bar}")
    return "\n".join(lines)
