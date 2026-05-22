"""Transcribe audio to text using Whisper or DeepSeek API."""

import subprocess
import tempfile
from pathlib import Path

from rag_system.utils import logger

WHISPER_MODEL = "medium"  # tiny/base/small/medium/large — medium best for Chinese


def transcribe_whisper_local(audio_path: Path) -> str | None:
    """Transcribe audio using local Whisper model."""
    try:
        import whisper
        model = whisper.load_model(WHISPER_MODEL)
        result = model.transcribe(
            str(audio_path),
            language="zh",
            task="transcribe",
            verbose=False,
        )
        text = result.get("text", "").strip()
        logger.info(f"Whisper transcribed: {len(text)} chars")
        return text
    except ImportError:
        logger.error("openai-whisper not installed. pip install openai-whisper")
        return None
    except Exception as e:
        logger.error(f"Whisper transcription failed: {e}")
        return None


def transcribe_deepseek(audio_path: Path) -> str | None:
    """Transcribe using DeepSeek API (OpenAI-compatible). Falls back if Whisper fails."""
    import base64
    from openai import OpenAI
    from rag_system.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL

    if not DEEPSEEK_API_KEY:
        logger.error("DeepSeek API key not configured")
        return None

    try:
        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

        # For large audio files, use ffmpeg to split
        with open(audio_path, "rb") as f:
            audio_data = f.read()

        # DeepSeek doesn't have native audio API — use ffmpeg to extract segments
        # For now, return None and let the caller handle
        logger.warning("DeepSeek audio transcription not yet implemented, use Whisper")
        return None
    except Exception as e:
        logger.error(f"DeepSeek transcription failed: {e}")
        return None


def transcribe(audio_path: Path) -> str | None:
    """Transcribe audio to text. Tries Whisper first, falls back to DeepSeek."""
    if not audio_path.exists():
        logger.error(f"Audio file not found: {audio_path}")
        return None

    # Try Whisper first
    text = transcribe_whisper_local(audio_path)
    if text:
        return text

    # Fallback to DeepSeek
    return transcribe_deepseek(audio_path)
