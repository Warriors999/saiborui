"""Metadata extraction from filenames and content.

Extracts: persona, product_name, is_final, revision, category, source_file.
"""

import re
from pathlib import Path

from rag_system.config import CATEGORY_KEYWORDS

CREATOR_LABELS = ["折腾到吐", "好设牛啊", "朋克", "超机懂", "机能疯"]


def extract_metadata(filepath: Path, text: str) -> dict:
    """Extract structured metadata from filename and document text."""
    filename = filepath.name
    stem = filepath.stem

    # Phase 1: filename regex extraction
    persona = _extract_persona(stem)
    product_name = _extract_product_name(stem, persona)
    is_final = bool(re.search(r"定稿", stem))
    revision = _extract_revision(stem)

    # Phase 2: category from text content
    category = _classify_category(text, filename)

    return {
        "persona": persona or "",
        "product_name": product_name or stem,
        "is_final": "true" if is_final else "false",
        "revision": revision or "",
        "category": category,
        "file_type": filepath.suffix.lower().lstrip("."),
        "source_file": filename,
    }


def _extract_persona(stem: str) -> str | None:
    """Extract creator persona from filename."""
    for label in CREATOR_LABELS:
        if label in stem:
            return label
    return None


def _extract_product_name(stem: str, persona: str | None) -> str:
    """Extract clean product name from filename by stripping known patterns."""
    s = stem

    # Remove 【...】 prefixes
    s = re.sub(r"【[^】]*】", "", s)

    # Remove persona labels
    for label in CREATOR_LABELS:
        s = s.replace(label, "")

    # Remove revision markers
    s = re.sub(r"修改\s*v?\d+", "", s)
    s = re.sub(r"v\d+\s*修改版?", "", s)
    s = re.sub(r"v\d+(\.\d+)?", "", s)
    s = re.sub(r"已改[-\s]*", "", s)
    s = re.sub(r"定稿[-\s]*", "", s)

    # Remove parenthesized duplicates and suffixes
    s = re.sub(r"\(\d+\)", "", s)  # (1), (2) file duplicates
    s = re.sub(r"（[^）]*修改[^）]*）", "", s)  # （修改v2）
    s = re.sub(r"（[^）]*v\d+[^）]*）", "", s)  # （v2修改版）

    # Remove trailing version-ish numbers
    s = re.sub(r"1$", "", s)

    # Clean up separators
    s = re.sub(r"[-\s（）\(\)\.]+$", "", s)
    s = s.strip(" -．.（）()　")

    # If nothing left, return original stem
    if not s or len(s) < 2:
        return stem.strip()

    return s


def _extract_revision(stem: str) -> str | None:
    """Extract revision info: v2, v3, etc."""
    m = re.search(r"修改\s*v?(\d+)", stem)
    if m:
        return f"v{m.group(1)}"
    m = re.search(r"[（\(]?v(\d+)[）\)]?", stem)
    if m:
        return f"v{m.group(1)}"
    return None


def _classify_category(text: str, filename: str) -> str:
    """Classify product category based on keyword matching in text and filename."""
    combined = filename + text[:2000]
    scores = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        if category == "other":
            continue
        score = sum(1 for kw in keywords if kw in combined)
        if score > 0:
            scores[category] = score
    if scores:
        return max(scores, key=scores.get)
    return "other"
