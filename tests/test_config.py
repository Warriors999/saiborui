"""Test that config loads correctly from environment and .env file."""

import os
import sys
from pathlib import Path

# Ensure the project root is on sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def test_deepseek_api_key():
    """DEEPSEEK_API_KEY is read from .env (may be empty if not set, but should exist as key)."""
    from rag_system.config import DEEPSEEK_API_KEY
    # It should at least be a string (empty or non-empty)
    assert isinstance(DEEPSEEK_API_KEY, str)


def test_deepseek_model_has_value():
    """DEEPSEEK_MODEL has a default value (deepseek-chat)."""
    from rag_system.config import DEEPSEEK_MODEL
    assert DEEPSEEK_MODEL
    assert isinstance(DEEPSEEK_MODEL, str)
    assert len(DEEPSEEK_MODEL) > 0


def test_project_root_is_valid_path():
    """PROJECT_ROOT is a valid Path and points to the project directory."""
    from rag_system.config import PROJECT_ROOT as cfg_root
    assert isinstance(cfg_root, Path)
    # The project root should contain rag_system directory
    assert (cfg_root / "rag_system").exists()


def test_expected_config_keys_exist():
    """All expected config keys exist on the module."""
    import rag_system.config as cfg

    expected_keys = [
        "PROJECT_ROOT",
        "DOCS_DIR",
        "DATA_DIR",
        "CHROMA_DIR",
        "CACHE_DIR",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL",
        "EMBEDDING_MODEL",
        "EMBEDDING_DEVICE",
        "CHUNK_SIZE",
        "CHUNK_OVERLAP",
        "DEFAULT_TOP_K",
        "SUPPORTED_EXTENSIONS",
        "CATEGORY_KEYWORDS",
    ]
    for key in expected_keys:
        assert hasattr(cfg, key), f"Missing config key: {key}"


def test_supported_extensions_is_set():
    """SUPPORTED_EXTENSIONS is a set of file extensions."""
    from rag_system.config import SUPPORTED_EXTENSIONS
    assert isinstance(SUPPORTED_EXTENSIONS, set)
    assert ".docx" in SUPPORTED_EXTENSIONS
    assert ".xlsx" in SUPPORTED_EXTENSIONS


def test_category_keywords_has_expected_categories():
    """CATEGORY_KEYWORDS has the expected product categories."""
    from rag_system.config import CATEGORY_KEYWORDS
    assert isinstance(CATEGORY_KEYWORDS, dict)
    assert "keyboard" in CATEGORY_KEYWORDS
    assert "mouse" in CATEGORY_KEYWORDS
    assert "monitor" in CATEGORY_KEYWORDS
    assert "gpu" in CATEGORY_KEYWORDS
    assert "laptop" in CATEGORY_KEYWORDS


def test_chunk_size_and_overlap_are_integers():
    """Chunking config values are integers."""
    from rag_system.config import CHUNK_SIZE, CHUNK_OVERLAP
    assert isinstance(CHUNK_SIZE, int)
    assert isinstance(CHUNK_OVERLAP, int)
    assert CHUNK_SIZE > 0
    assert CHUNK_OVERLAP >= 0


if __name__ == "__main__":
    test_deepseek_api_key()
    test_deepseek_model_has_value()
    test_project_root_is_valid_path()
    test_expected_config_keys_exist()
    test_supported_extensions_is_set()
    test_category_keywords_has_expected_categories()
    test_chunk_size_and_overlap_are_integers()
    print("All test_config tests passed.")
