"""Test audit functions (no LLM needed, local text analysis only)."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from rag_system.generation.auditor import (
    audit_script,
    AuditResult,
    FORBIDDEN_WORDS,
    ECOMMERCE_SMELL,
)


# ── Basic smoke tests ──

def test_audit_script_returns_audit_result():
    """audit_script returns an AuditResult with correct fields."""
    result = audit_script("这是一个测试口播文案。产品很不错。推荐购买。")
    assert isinstance(result, AuditResult)
    assert isinstance(result.passed, bool)
    assert isinstance(result.checks, list)
    assert isinstance(result.warnings, list)
    assert isinstance(result.suggestions, list)
    assert isinstance(result.scores, dict)


def test_audit_script_has_expected_checks():
    """All expected check categories are present."""
    result = audit_script(
        "这是一个测试口播文案。产品很不错。推荐购买。",
        key_points="测试卖点A,测试卖点B",
    )
    check_names = [c["name"] for c in result.checks]
    expected = [
        "口播时长",
        "禁用词",
        "电商味",
        "流水账检测",
        "价格检测",
        "拉踩检测",
        "口语化程度",
        "态度密度",
        "长短句节奏",
        "卖点覆盖",
    ]
    for name in expected:
        assert name in check_names, f"Missing check: {name}"


# ── E-commerce smell detection ──

def test_ecommerce_smell_detected():
    """Text containing e-commerce smell words fails the check."""
    # "极致" is in ECOMMERCE_SMELL
    text = "这款产品带来极致体验，全新升级的设计，震撼上市不容错过。"
    result = audit_script(text)
    ecommerce_check = _find_check(result, "电商味")
    assert ecommerce_check is not None
    assert ecommerce_check["passed"] is False, \
        f"Expected e-commerce check to fail, but got: {ecommerce_check}"


def test_ecommerce_smell_single_word_passes():
    """One e-commerce word is tolerated (len <= 1 passes)."""
    text = "这款产品的极致体验让人印象深刻。"
    result = audit_script(text)
    ecommerce_check = _find_check(result, "电商味")
    # len(found_smell) == 1, should pass
    assert ecommerce_check["passed"] is True, \
        f"Single smell word should pass, got: {ecommerce_check}"


# ── Forbidden words detection ──

def test_forbidden_words_detected():
    """Text containing forbidden words fails the check."""
    # "非常" is in FORBIDDEN_WORDS
    text = "这是一款非常出色的产品，为用户带来极致体验。"
    result = audit_script(text)
    forbidden_check = _find_check(result, "禁用词")
    assert forbidden_check is not None
    assert forbidden_check["passed"] is False, \
        f"Expected forbidden words check to fail, got: {forbidden_check}"


def test_no_forbidden_words_passes():
    """Clean text passes forbidden words check."""
    text = "这是一款不错的产品，用起来很顺手。"
    result = audit_script(text)
    forbidden_check = _find_check(result, "禁用词")
    assert forbidden_check["passed"] is True


# ── Empty / edge case ──

def test_audit_empty_text_does_not_crash():
    """Empty text should not crash the auditor."""
    result = audit_script("")
    assert isinstance(result, AuditResult)
    # Empty text returns early with a warning, no checks
    assert result.passed is True
    assert len(result.warnings) > 0


def test_audit_very_short_text_does_not_crash():
    """Very short text should not crash."""
    result = audit_script("好。")
    assert isinstance(result, AuditResult)


# ── Price detection ──

def test_price_detected_in_voiceover():
    """Specific prices in voiceover text are detected."""
    text = "这款产品价格只要399元，非常划算。"
    result = audit_script(text)
    price_check = _find_check(result, "价格检测")
    assert price_check is not None
    # Should fail because price is in voiceover
    assert price_check["passed"] is False


def test_no_price_in_text_passes():
    """Text without explicit prices passes price check."""
    text = "这款产品性价比很高，值得考虑。"
    result = audit_script(text)
    price_check = _find_check(result, "价格检测")
    assert price_check["passed"] is True


# ── summarize method ──

def test_summarize_returns_non_empty_string():
    """result.summarize() returns a non-empty string."""
    result = audit_script("这是一个测试口播文案。产品很不错。推荐购买。")
    summary = result.summarize()
    assert summary
    assert isinstance(summary, str)
    assert len(summary) > 0
    assert "审核结果" in summary


def test_summarize_mentions_checks():
    """Summary includes check names."""
    result = audit_script("这是一个测试口播文案，兄弟们，懂的都懂。产品很不错。推荐购买。")
    summary = result.summarize()
    assert "口播时长" in summary or "禁用词" in summary


# ── Helpers ──

def _find_check(result: AuditResult, name: str) -> dict | None:
    """Find a specific check by name in the audit result."""
    for c in result.checks:
        if c["name"] == name:
            return c
    return None


if __name__ == "__main__":
    test_audit_script_returns_audit_result()
    test_audit_script_has_expected_checks()
    test_ecommerce_smell_detected()
    test_ecommerce_smell_single_word_passes()
    test_forbidden_words_detected()
    test_no_forbidden_words_passes()
    test_audit_empty_text_does_not_crash()
    test_audit_very_short_text_does_not_crash()
    test_price_detected_in_voiceover()
    test_no_price_in_text_passes()
    test_summarize_returns_non_empty_string()
    test_summarize_mentions_checks()
    print("All test_auditor tests passed.")
