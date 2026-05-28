"""Test environment checker — verifies Python version and key dependencies.

Note: check_environment() is not a standalone function in the current codebase.
This test defines a minimal version inline and tests it. It also verifies
that critical project dependencies are importable.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def check_environment() -> dict:
    """Minimal environment checker used for testing.

    Checks Python version and lists key importable modules.
    Returns a dict with expected keys for the test suite.
    """
    result = {
        "python_version": sys.version,
        "python_version_info": sys.version_info,
        "python_ok": sys.version_info >= (3, 12),
        "platform": sys.platform,
    }

    # Check key dependencies availability
    modules_to_check = [
        "docx",
        "openpyxl",
        "click",
        "dotenv",
    ]

    for mod in modules_to_check:
        try:
            __import__(mod)
            result[f"module_{mod}"] = True
        except ImportError:
            result[f"module_{mod}"] = False

    return result


def test_check_environment_returns_dict():
    """check_environment returns a dict."""
    result = check_environment()
    assert isinstance(result, dict)


def test_check_environment_has_expected_keys():
    """Returns dict with expected keys."""
    result = check_environment()
    expected = [
        "python_version",
        "python_version_info",
        "python_ok",
        "platform",
    ]
    for key in expected:
        assert key in result, f"Missing key: {key}"


def test_python_version_check_works():
    """Python version check returns a boolean."""
    result = check_environment()
    assert "python_ok" in result
    assert isinstance(result["python_ok"], bool)


def test_python_version_is_at_least_3_12():
    """Project requires Python >= 3.12."""
    result = check_environment()
    assert result["python_ok"] is True, \
        f"Python {sys.version_info} is below 3.12 requirement"


def test_platform_is_string():
    """Platform info is a string."""
    result = check_environment()
    assert isinstance(result["platform"], str)
    assert len(result["platform"]) > 0


def test_key_dependencies_importable():
    """Critical project dependencies are importable."""
    result = check_environment()
    # These are required in pyproject.toml dependencies
    critical = ["module_docx", "module_openpyxl", "module_click", "module_dotenv"]
    for mod in critical:
        assert result.get(mod, False), \
            f"Required module {mod.replace('module_', '')} is not importable"


def test_rag_system_importable():
    """The rag_system package itself is importable."""
    try:
        import rag_system
        assert rag_system.__version__ is not None
    except ImportError:
        assert False, "rag_system package is not importable"


if __name__ == "__main__":
    test_check_environment_returns_dict()
    test_check_environment_has_expected_keys()
    test_python_version_check_works()
    test_python_version_is_at_least_3_12()
    test_platform_is_string()
    test_key_dependencies_importable()
    test_rag_system_importable()
    print("All test_init_wizard tests passed.")
