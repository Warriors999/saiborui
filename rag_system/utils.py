"""Shared utilities: logging, file hashing, text encoding safety."""

import hashlib
import logging
from pathlib import Path

logger = logging.getLogger("rag_system")


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def file_hash(filepath: Path) -> str:
    """SHA-256 of file bytes, used for cache keying."""
    return hashlib.sha256(filepath.read_bytes()).hexdigest()


def safe_text(text: str) -> str:
    """Ensure text is valid UTF-8, replacing any undecodable sequences."""
    return text.encode("utf-8", errors="replace").decode("utf-8")


def cache_path(filepath: Path, cache_dir: Path) -> Path:
    """Deterministic cache file path based on file content hash."""
    fhash = file_hash(filepath)
    return cache_dir / f"{fhash}.txt"


def is_cached(filepath: Path, cache_dir: Path) -> bool:
    """Check if a parsed plaintext cache exists for this file."""
    return cache_path(filepath, cache_dir).exists()


def read_cache(filepath: Path, cache_dir: Path) -> str:
    """Read cached plaintext for a file."""
    return cache_path(filepath, cache_dir).read_text(encoding="utf-8")


def write_cache(filepath: Path, cache_dir: Path, text: str) -> None:
    """Write parsed plaintext to cache."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path(filepath, cache_dir).write_text(text, encoding="utf-8")
