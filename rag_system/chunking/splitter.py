"""Chinese-optimized text splitter.

Splits text into overlapping chunks, respecting paragraph and sentence
boundaries. Character-count based (not token-count based) for Chinese text.
"""

import re

from rag_system.config import CHUNK_OVERLAP, CHUNK_SIZE


def split_text(text: str, chunk_size: int = CHUNK_SIZE, chunk_overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split Chinese text into overlapping chunks respecting natural boundaries.

    Priority order for split points:
      1. Double newline (paragraph break)
      2. Single newline
      3. Chinese sentence-ending punctuation: 。！？；
      4. Chinese clause punctuation: ，、 (last resort)
    """
    if not text or not text.strip():
        return []

    # Step 1: Split into paragraphs first
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    # Step 2: Rejoin very short paragraphs with neighbors
    paragraphs = _merge_short_paragraphs(paragraphs)

    # Step 3: Build chunks from paragraphs
    chunks = []
    current = ""
    for para in paragraphs:
        candidate = para if not current else current + "\n" + para
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            if current:
                chunks.append(current)
            # If this single paragraph exceeds chunk_size, split it by sentences
            if len(para) > chunk_size:
                sub_chunks = _split_long_paragraph(para, chunk_size)
                chunks.extend(sub_chunks[:-1])
                current = sub_chunks[-1] if sub_chunks else ""
            else:
                current = para

    if current.strip():
        chunks.append(current)

    # Step 4: Add overlap between adjacent chunks
    if chunk_overlap > 0 and len(chunks) > 1:
        chunks = _add_overlap(chunks, chunk_overlap)

    return chunks


def _merge_short_paragraphs(paragraphs: list[str], min_len: int = 60) -> list[str]:
    """Merge very short paragraphs with neighbors to avoid over-fragmentation."""
    if not paragraphs:
        return paragraphs
    merged = []
    buf = ""
    for para in paragraphs:
        if buf:
            candidate = buf + "\n" + para
        else:
            candidate = para
        if len(candidate) < min_len:
            buf = candidate
        else:
            if buf:
                merged.append(buf)
            buf = para
    if buf:
        merged.append(buf)
    return merged


def _split_long_paragraph(para: str, chunk_size: int) -> list[str]:
    """Split a single paragraph that exceeds chunk_size using sentence boundaries."""
    sentences = _split_by_punctuation(para, r"[。！？；]")
    if len(sentences) <= 1:
        # Fall through to comma-level splitting
        sentences = _split_by_punctuation(para, r"[，、]")
    if len(sentences) <= 1:
        # Last resort: fixed-size character split
        return _fixed_size_chunks(para, chunk_size)

    chunks = []
    current = ""
    for sent in sentences:
        candidate = current + sent if current else sent
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = sent
    if current.strip():
        chunks.append(current)
    return chunks


def _split_by_punctuation(text: str, pattern: str) -> list[str]:
    """Split text by punctuation, keeping the punctuation with each segment."""
    parts = re.split(f"({pattern})", text)
    segments = []
    buf = ""
    for part in parts:
        buf += part
        if re.match(pattern, part):
            segments.append(buf)
            buf = ""
    if buf.strip():
        segments.append(buf)
    return segments


def _fixed_size_chunks(text: str, size: int) -> list[str]:
    """Fixed-size character split (last resort)."""
    return [text[i:i + size] for i in range(0, len(text), size)]


def _add_overlap(chunks: list[str], overlap: int) -> list[str]:
    """Add context overlap from the end of the previous chunk to each chunk."""
    if not chunks:
        return chunks
    result = [chunks[0]]
    for i in range(1, len(chunks)):
        prev = chunks[i - 1]
        overlap_text = prev[-overlap:] if len(prev) >= overlap else prev
        result.append(overlap_text + "\n...\n" + chunks[i])
    return result
