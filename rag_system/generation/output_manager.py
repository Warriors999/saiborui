"""Output registry — tracks every generated artifact via JSONL index.

Provides a lightweight index (output/index.jsonl) that records every
successful generation (scripts, storyboards, covers, audits) with
timestamp, type, path, and metadata for listing, filtering, and cleanup.
"""

import json
import threading
from datetime import datetime, timedelta
from pathlib import Path

from rag_system.utils import logger

INDEX_PATH = Path("output/index.jsonl")
_lock = threading.Lock()

VALID_TYPES = {"script", "storyboard", "cover", "audit"}


def register_output(output_type: str, filepath: str | Path, metadata: dict | None = None) -> Path:
    """Record a generated artifact in the output index.

    Appends one JSON line to ``output/index.jsonl`` with a timestamp, type,
    path, and any caller-supplied metadata (product, persona, category, etc.).

    Parameters
    ----------
    output_type : str
        One of ``script``, ``storyboard``, ``cover``, ``audit``.
    filepath : str or Path
        Absolute or project-relative path to the artifact.
    metadata : dict, optional
        Extra key-value pairs to store alongside the entry (e.g. product, persona).

    Returns
    -------
    Path
        The *filepath* argument unchanged, for use as a pass-through.
    """
    if output_type not in VALID_TYPES:
        raise ValueError(f"Invalid output_type '{output_type}'. Must be one of: {', '.join(sorted(VALID_TYPES))}")

    fp = Path(filepath)
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "type": output_type,
        "path": str(fp),
    }
    if metadata:
        entry.update(metadata)

    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with open(INDEX_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    logger.debug("Output registered: %s | %s", output_type, fp.name)
    return fp


def _read_all() -> list[dict]:
    """Return every entry from the index, newest-first."""
    if not INDEX_PATH.exists():
        return []
    entries = []
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    # Reverse so newest entries come first
    entries.reverse()
    return entries


def list_outputs(
    output_type: str | None = None,
    limit: int = 20,
    product: str | None = None,
) -> list[dict]:
    """Read the output index and return a filtered list of entries.

    Parameters
    ----------
    output_type : str, optional
        Filter by type: ``script``, ``storyboard``, ``cover``, or ``audit``.
    limit : int
        Maximum number of results (default 20).
    product : str, optional
        Fuzzy-match product name (case-insensitive substring search).

    Returns
    -------
    list[dict]
        Matching entries, newest first.
    """
    entries = _read_all()
    result = []

    for e in entries:
        if output_type and e.get("type") != output_type:
            continue
        if product and product.lower() not in str(e.get("product", "")).lower():
            continue
        result.append(e)
        if len(result) >= limit:
            break

    return result


def get_latest(output_type: str | None = None) -> dict | None:
    """Return the most recent output entry, optionally filtered by type.

    Parameters
    ----------
    output_type : str, optional
        Filter by type: ``script``, ``storyboard``, ``cover``, or ``audit``.

    Returns
    -------
    dict or None
        The newest matching entry, or ``None`` if the index is empty.
    """
    results = list_outputs(output_type=output_type, limit=1)
    return results[0] if results else None


def cleanup_old(days: int = 30, dry_run: bool = True) -> list[Path]:
    """List (or delete) output files older than *days*.

    Scans the index and checks whether each registered file still exists and
    was created more than *days* ago.  Never touches the index itself or
    ``dashboard.html``.

    Parameters
    ----------
    days : int
        Age threshold in days (default 30).
    dry_run : bool
        If ``True`` (default), only return the list of candidate paths without
        deleting anything.

    Returns
    -------
    list[Path]
        Absolute paths of files that matched the age threshold.
    """
    cutoff = datetime.now() - timedelta(days=days)
    candidates: list[Path] = []
    protected_names = {"index.jsonl", "dashboard.html"}

    entries = _read_all()
    for e in entries:
        try:
            ts = datetime.fromisoformat(e.get("ts", ""))
        except (ValueError, TypeError):
            continue
        if ts >= cutoff:
            continue

        fp = Path(e.get("path", ""))
        if not fp.is_absolute():
            fp = Path.cwd() / fp
        if not fp.exists():
            continue
        if fp.name.lower() in protected_names:
            continue

        # Avoid duplicate paths (multiple index entries can point to same file)
        if fp not in candidates:
            candidates.append(fp)

    if not dry_run:
        for fp in candidates:
            try:
                fp.unlink()
                logger.debug("Cleaned up: %s", fp)
            except OSError:
                logger.warning("Failed to delete: %s", fp)

    return candidates
