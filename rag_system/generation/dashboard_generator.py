"""Dynamic dashboard data collector and HTML generator.

Scans project state (vector store, file system, git) and produces
a populated dashboard.html with live metrics.
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path

from rag_system.config import PROJECT_ROOT
from rag_system.utils import logger

# Color palette for category bars (cycles through these)
_BAR_COLORS = ["green", "blue", "amber", "purple"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def collect_data() -> dict:
    """Scan the project and return a dict of all dashboard metrics.

    Returns keys:
        kb_chunks, kb_sources, kb_categories,
        persona_breakdown, category_breakdown,
        scripts_count, storyboards_count, audits_count,
        competitive_count, deep_sessions,
        wiki_pages, code_lines, code_modules,
        git_commits, git_total_commits, version.
    """
    data: dict = {}
    _collect_kb_stats(data)
    _collect_output_stats(data)
    _collect_competitive_stats(data)
    _collect_wiki_stats(data)
    _collect_code_stats(data)
    _collect_git_stats(data)
    _collect_version(data)
    return data


def generate_dashboard(data: dict, output_path: Path | None = None) -> Path:
    """Read dashboard.html template, substitute live data, write output.

    Args:
        data: Dict from collect_data().
        output_path: Where to write the populated HTML.
                     Defaults to overwriting output/dashboard.html.

    Returns:
        Path to the written file.
    """
    template_path = PROJECT_ROOT / "output" / "dashboard.html"
    template = template_path.read_text(encoding="utf-8")

    # ---- simple key-value substitutions ----
    subs = {
        "{{KB_CHUNKS}}":            str(data.get("kb_chunks", 0)),
        "{{KB_SOURCES}}":           str(data.get("kb_sources", 0)),
        "{{KB_CATEGORIES}}":        str(data.get("kb_categories", 0)),
        "{{SCRIPTS_COUNT}}":        str(data.get("scripts_count", 0)),
        "{{STORYBOARDS_COUNT}}":    str(data.get("storyboards_count", 0)),
        "{{AUDITS_COUNT}}":         str(data.get("audits_count", 0)),
        "{{COMPETITIVE_COUNT}}":    str(data.get("competitive_count", 0)),
        "{{DEEP_SESSIONS}}":        str(data.get("deep_sessions", 0)),
        "{{WIKI_PAGES}}":           str(data.get("wiki_pages", 0)),
        "{{CODE_LINES}}":           _fmt_lines(data.get("code_lines", 0)),
        "{{CODE_MODULES}}":         str(data.get("code_modules", 0)),
        "{{GIT_COMMITS}}":          str(data.get("git_total_commits", 0)),
        "{{VERSION}}":              data.get("version", "0.0.0"),
        "{{GENERATED_AT}}":         datetime.now().strftime("%Y-%m-%d"),
    }
    for marker, value in subs.items():
        template = template.replace(marker, value)

    # ---- dynamic HTML sections ----
    template = template.replace("{{CATEGORY_BARS}}", _build_category_bars(data))
    template = template.replace("{{COMMIT_ROWS}}",  _build_commit_rows(data))

    # ---- write ----
    if output_path is None:
        output_path = template_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(template, encoding="utf-8")
    logger.info("Dashboard written to %s", output_path)
    return output_path


# ---------------------------------------------------------------------------
# Data collectors
# ---------------------------------------------------------------------------

def _collect_kb_stats(data: dict) -> None:
    """Populate kb_chunks, kb_sources, kb_categories,
    persona_breakdown, category_breakdown from the vector store."""
    try:
        from rag_system.storage.vector_store import VectorStore

        vs = VectorStore()
        data["kb_chunks"] = vs.count()

        metadatas = vs.get_all_metadata()
        sources: set[str] = set()
        categories: set[str] = set()
        persona_map: dict[str, int] = {}
        category_map: dict[str, int] = {}

        for m in metadatas:
            src = m.get("source_file", "")
            if src:
                sources.add(src)

            cat = m.get("category", "other")
            if cat:
                categories.add(cat)
                category_map[cat] = category_map.get(cat, 0) + 1

            persona = m.get("persona", "")
            if persona:
                persona_map[persona] = persona_map.get(persona, 0) + 1

        data["kb_sources"] = len(sources)
        data["kb_categories"] = len(categories)
        data["persona_breakdown"] = dict(
            sorted(persona_map.items(), key=lambda x: x[1], reverse=True)
        )
        data["category_breakdown"] = dict(
            sorted(category_map.items(), key=lambda x: x[1], reverse=True)
        )
    except Exception as e:
        logger.warning("VectorStore unavailable, KB stats defaulted to 0: %s", e)
        data.setdefault("kb_chunks", 0)
        data.setdefault("kb_sources", 0)
        data.setdefault("kb_categories", 0)
        data.setdefault("persona_breakdown", {})
        data.setdefault("category_breakdown", {})


def _collect_output_stats(data: dict) -> None:
    """Count scripts (.docx), storyboards (.xlsx), audits (all files)."""
    scripts_dir     = PROJECT_ROOT / "output" / "scripts"
    storyboards_dir = PROJECT_ROOT / "output" / "storyboards"
    audits_dir      = PROJECT_ROOT / "output" / "audits"

    data["scripts_count"]      = _count_files(scripts_dir, [".docx"], exclude_temp=True)
    data["storyboards_count"]  = _count_files(storyboards_dir, [".xlsx"], exclude_temp=True)
    data["audits_count"]       = _count_files(audits_dir, None, exclude_temp=False)


def _collect_competitive_stats(data: dict) -> None:
    """Count analyzed videos (from JSON store) and deep-analysis sessions."""
    # Analyzed videos from the canonical cumulative JSON
    videos_json = PROJECT_ROOT / "output" / "competitive" / "analyzed_videos.json"
    try:
        if videos_json.exists():
            entries = json.loads(videos_json.read_text(encoding="utf-8"))
            data["competitive_count"] = len(entries) if isinstance(entries, list) else 0
        else:
            data["competitive_count"] = 0
    except Exception as e:
        logger.warning("Failed to read analyzed_videos.json: %s", e)
        data["competitive_count"] = 0

    # Deep sessions count (one subdirectory per session)
    sessions_dir = PROJECT_ROOT / "output" / "competitive" / "sessions"
    try:
        if sessions_dir.exists():
            data["deep_sessions"] = sum(1 for d in sessions_dir.iterdir() if d.is_dir())
        else:
            data["deep_sessions"] = 0
    except Exception as e:
        logger.debug("Dashboard collector skipped: %s", e)
        data["deep_sessions"] = 0


def _collect_wiki_stats(data: dict) -> None:
    """Count .md files in wiki/ recursively."""
    wiki_dir = PROJECT_ROOT / "wiki"
    try:
        if wiki_dir.exists():
            data["wiki_pages"] = sum(1 for _ in wiki_dir.rglob("*.md"))
        else:
            data["wiki_pages"] = 0
    except Exception as e:
        logger.debug("Dashboard collector skipped: %s", e)
        data["wiki_pages"] = 0


def _collect_code_stats(data: dict) -> None:
    """Count .py files and total lines in rag_system/."""
    rag_dir = PROJECT_ROOT / "rag_system"
    py_files: list[Path] = []
    try:
        py_files = [
            f for f in rag_dir.rglob("*.py")
            if "__pycache__" not in f.parts
        ]
    except Exception as e:
        logger.debug("Dashboard collector skipped: %s", e)
        pass

    data["code_modules"] = len(py_files)
    total_lines = 0
    for f in py_files:
        try:
            total_lines += len(f.read_text(encoding="utf-8").splitlines())
        except Exception as e:
            logger.debug("Dashboard collector skipped: %s", e)
    data["code_lines"] = total_lines


def _collect_git_stats(data: dict) -> None:
    """Retrieve last 7 commits and total commit count via git CLI."""
    commits: list[dict] = []
    total = 0

    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-7"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(PROJECT_ROOT),
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    parts = line.split(" ", 1)
                    commit_hash = parts[0]
                    message = parts[1] if len(parts) > 1 else ""
                    commits.append({"hash": commit_hash, "message": message})
    except Exception as e:
        logger.warning("git log failed: %s", e)

    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(PROJECT_ROOT),
        )
        if result.returncode == 0:
            total = int(result.stdout.strip())
    except Exception as e:
        logger.debug("Dashboard collector skipped: %s", e)
        pass

    data["git_commits"] = commits
    data["git_total_commits"] = total


def _collect_version(data: dict) -> None:
    """Read version from VERSION file."""
    version_path = PROJECT_ROOT / "VERSION"
    try:
        data["version"] = version_path.read_text(encoding="utf-8").strip()
    except Exception as e:
        logger.debug("Dashboard collector skipped: %s", e)
        data["version"] = "0.0.0"


# ---------------------------------------------------------------------------
# Dynamic HTML builders
# ---------------------------------------------------------------------------

def _build_category_bars(data: dict) -> str:
    """Generate <div class="bar-wrap"> rows from category_breakdown."""
    breakdown: dict = data.get("category_breakdown", {})
    if not breakdown:
        return '<div class="bar-wrap"><div class="bar-label"><span>—</span><span>no data</span></div></div>'

    max_count = max(breakdown.values()) if breakdown else 1
    rows: list[str] = []
    for i, (cat, count) in enumerate(breakdown.items()):
        pct = max(5, int(count / max(max_count, 1) * 100))
        color = _BAR_COLORS[i % len(_BAR_COLORS)]
        rows.append(
            f'<div class="bar-wrap">'
            f'<div class="bar-label"><span>{cat}</span><span>{count} chunks</span></div>'
            f'<div class="bar-track"><div class="bar-fill" '
            f'style="width:{pct}%;background:var(--{color})"></div></div>'
            f'</div>'
        )
    return "\n".join(rows)


def _build_commit_rows(data: dict) -> str:
    """Generate <tr> rows for the recent commits table."""
    commits: list = data.get("git_commits", [])
    if not commits:
        return '<tr><td colspan="2">No commits found</td></tr>'

    rows: list[str] = []
    for i, c in enumerate(commits):
        # First (latest) commit gets the green "ok" tag
        tag_class = ' class="tag ok"' if i == 0 else ""
        rows.append(
            f"<tr><td><span{tag_class}>{c['hash']}</span></td>"
            f"<td>{c['message']}</td></tr>"
        )
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_files(
    directory: Path,
    extensions: list[str] | None,
    exclude_temp: bool = False,
) -> int:
    """Count files in a directory (top-level only), optionally filtered by extension.

    Args:
        directory: Directory to scan.
        extensions: If given, only count files whose suffix is in this list.
        exclude_temp: If True, skip files starting with '~$'.
    """
    try:
        if not directory.exists():
            return 0
        count = 0
        for f in directory.iterdir():
            if not f.is_file():
                continue
            if exclude_temp and f.name.startswith("~$"):
                continue
            if extensions is not None and f.suffix.lower() not in extensions:
                continue
            count += 1
        return count
    except Exception as e:
        logger.debug("Dashboard collector skipped: %s", e)
        return 0


def _fmt_lines(n: int) -> str:
    """Format line count compactly: 6447 -> '6.4k', 350 -> '350'."""
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)
