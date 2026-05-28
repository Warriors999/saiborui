"""Test docx parsing — creates minimal docx files and verifies parsing."""

import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from rag_system.generation.script_to_storyboard import parse_docx_script


# ── Helpers to create test docx files ──

def _create_simple_docx(paragraphs: list[str], path: Path) -> None:
    """Create a minimal .docx file with given paragraphs."""
    from docx import Document
    doc = Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    doc.save(str(path))


def _create_script_docx(path: Path) -> None:
    """Create a docx that looks like a formatted script output."""
    _create_simple_docx([
        "封面：ROG龙鳞ACE MINI评测",
        "简介：ROG龙鳞ACE MINI深度评测，到底值不值得买？",
        "嗨喽大家好，这里是折腾到吐。",
        "今天聊ROG龙鳞ACE MINI，54克的轻量化鼠标。",
        "8K回报率，PAW3950传感器。",
        "价格399元起步。（花字：官方价399元）",
        "我是折腾到吐，我们下期再见。",
    ], path)


# ── Tests ──

def test_parse_docx_script_extracts_cover():
    """parse_docx_script extracts cover from the first paragraph."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test_script.docx"
        _create_simple_docx([
            "封面：ROG龙鳞ACE MINI评测",
            "嗨喽大家好，这里是折腾到吐。",
            "今天测一个54克的轻量化鼠标。",
        ], path)

        result = parse_docx_script(path)
        assert "封面" in result["cover"] or "ROG" in result["cover"], \
            f"Cover not extracted correctly: {result['cover']}"


def test_parse_docx_script_extracts_body():
    """parse_docx_script extracts body lines correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test_script.docx"
        _create_simple_docx([
            "封面：ROG鼠标评测",
            "嗨喽大家好，这里是折腾到吐。",
            "今天测一个54克的轻量化鼠标。",
            "价格399元起步。",
        ], path)

        result = parse_docx_script(path)
        assert len(result["body"]) > 0, "Body should not be empty"
        assert isinstance(result["body"], list)


def test_parse_docx_script_full_script_is_string():
    """full_script field is a non-empty string."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test_script.docx"
        _create_simple_docx([
            "封面：测试产品",
            "这是第一段口播文案。",
            "这是第二段口播文案。",
        ], path)

        result = parse_docx_script(path)
        assert isinstance(result["full_script"], str)
        assert len(result["full_script"]) > 0


def test_parse_docx_script_full_script_contains_body():
    """full_script concatenates body lines with newlines."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test_script.docx"
        _create_simple_docx([
            "封面：测试产品",
            "这是第一段口播。",
            "这是第二段口播。",
        ], path)

        result = parse_docx_script(path)
        assert "这是第一段口播" in result["full_script"]
        assert "这是第二段口播" in result["full_script"]


def test_parse_docx_script_returns_expected_keys():
    """parse_docx_script returns dict with expected keys."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test_script.docx"
        _create_simple_docx([
            "封面：测试产品",
            "一段测试口播文案。",
        ], path)

        result = parse_docx_script(path)
        for key in ["cover", "body", "full_script", "huazi_notes", "signature"]:
            assert key in result, f"Missing key: {key}"


def test_parse_docx_script_empty_docx_raises():
    """Empty docx (no paragraphs) raises ValueError."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "empty.docx"
        _create_simple_docx([], path)

        try:
            parse_docx_script(path)
            assert False, "Expected ValueError for empty docx"
        except ValueError as e:
            assert "Empty" in str(e) or "empty" in str(e).lower()


def test_parse_docx_script_huazi_notes_detected():
    """Lines containing 花字 are collected in huazi_notes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test_with_huazi.docx"
        _create_simple_docx([
            "封面：测试产品",
            "这个是正文内容。",
            "价格只要399元。（花字：官方价399元）",
        ], path)

        result = parse_docx_script(path)
        assert result["huazi_notes"] is not None
        # The line with 花字 should be in huazi_notes
        assert len(result["huazi_notes"]) >= 1


def test_parse_docx_script_single_paragraph():
    """Docx with just one paragraph (cover only) should still work."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "single.docx"
        _create_simple_docx(["封面：最小测试"], path)

        result = parse_docx_script(path)
        assert result["cover"] == "封面：最小测试"
        assert result["body"] == []
        assert result["full_script"] == ""


def test_parse_docx_realistic_script():
    """Parse a realistic-looking script docx."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "realistic.docx"
        _create_script_docx(path)

        result = parse_docx_script(path)
        assert "ROG" in result["cover"]
        assert len(result["body"]) > 0
        assert len(result["full_script"]) > 0
        assert any("花字" in line for line in result["huazi_notes"])


if __name__ == "__main__":
    test_parse_docx_script_extracts_cover()
    test_parse_docx_script_extracts_body()
    test_parse_docx_script_full_script_is_string()
    test_parse_docx_script_full_script_contains_body()
    test_parse_docx_script_returns_expected_keys()
    test_parse_docx_script_empty_docx_raises()
    test_parse_docx_script_huazi_notes_detected()
    test_parse_docx_script_single_paragraph()
    test_parse_docx_realistic_script()
    print("All test_parse_docx tests passed.")
