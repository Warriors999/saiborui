"""Transcribe audio to text using cloud ASR APIs — zero local model inference.

Providers (env-configured):
  - ZHIPU_API_KEY    → 智谱 GLM ASR (OpenAI-compatible)
  - GEMINI_API_KEY   → Google Gemini Audio (free tier)
  - OPENAI_API_KEY   → OpenAI Whisper API

No local Whisper. CPU: ~0.
"""

from pathlib import Path
from rag_system.utils import logger


def transcribe_zhipu(audio_path: Path) -> str | None:
    """Transcribe via 智谱 ASR API (OpenAI-compatible endpoint).

    Limits: 25MB file size, 30 min duration.
    Auto-compresses + truncates to fit within limits.
    """
    import os, subprocess
    api_key = os.getenv("ZHIPU_API_KEY", "")
    if not api_key:
        return None

    try:
        send_path = _prepare_audio_for_asr(audio_path)
        if not send_path:
            return None

        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url="https://open.bigmodel.cn/api/paas/v4/")
        with open(send_path, "rb") as f:
            result = client.audio.transcriptions.create(
                model="whisper-1", file=f,
                language="zh", response_format="text",
            )
        text = result.strip() if isinstance(result, str) else str(result)
        logger.info(f"智谱 ASR: {len(text)} chars")
        return text
    except Exception as e:
        logger.warning(f"智谱 ASR failed: {e}")
        return None


def _prepare_audio_for_asr(audio_path: Path, max_mb: int = 24, max_min: int = 28) -> Path | None:
    """Compress + truncate audio to fit cloud ASR limits. Uses ffmpeg (NOT model inference)."""
    import subprocess

    # Get duration
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(audio_path)],
        capture_output=True, encoding="utf-8", errors="replace", timeout=10,
    )
    duration = float(result.stdout.strip()) if result.stdout.strip() else 0
    file_mb = audio_path.stat().st_size / (1024 * 1024)

    needs_truncate = duration > max_min * 60
    needs_compress = file_mb > max_mb

    if not needs_truncate and not needs_compress:
        return audio_path

    prepared = audio_path.with_suffix(".asr_ready.mp3")
    cmd = ["ffmpeg", "-y", "-i", str(audio_path)]

    if needs_truncate:
        cmd += ["-t", str(max_min * 60)]  # take first N minutes (contains hook + key content)
        logger.info(f"Truncating audio: {duration/60:.0f}min -> {max_min}min")

    cmd += ["-ac", "1", "-ar", "16000", "-b:a", "32k", str(prepared)]

    subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=30)
    if prepared.exists():
        new_mb = prepared.stat().st_size / (1024 * 1024)
        logger.info(f"Audio prepared: {file_mb:.0f}MB/{duration/60:.0f}min -> {new_mb:.1f}MB")
        return prepared
    return None


def transcribe_gemini(audio_path: Path) -> str | None:
    """Transcribe via Google Gemini Audio API."""
    import os, base64, urllib.request, json
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return None
    try:
        with open(audio_path, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode("utf-8")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        body = {"contents": [{"parts": [
            {"inline_data": {"mime_type": "audio/mp3", "data": audio_b64}},
            {"text": "请将这段音频完整转写成中文文字，只输出转写结果。"},
        ]}]}
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            logger.info(f"Gemini transcribed: {len(text)} chars")
            return text
    except Exception as e:
        logger.warning(f"Gemini ASR failed: {e}")
        return None


def transcribe_openai_whisper(audio_path: Path) -> str | None:
    """Transcribe via OpenAI Whisper API."""
    import os
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        with open(audio_path, "rb") as f:
            result = client.audio.transcriptions.create(
                model="whisper-1", file=f,
                language="zh", response_format="text",
            )
        text = result.strip() if isinstance(result, str) else str(result)
        logger.info(f"OpenAI Whisper transcribed: {len(text)} chars")
        return text
    except Exception as e:
        logger.warning(f"OpenAI Whisper failed: {e}")
        return None


def transcribe_from_subs(subtitle_path: Path) -> str | None:
    """Extract text from B站 CC subtitle JSON file."""
    try:
        import json
        data = json.loads(subtitle_path.read_text(encoding="utf-8"))
        body = data.get("body", data)
        if isinstance(body, list):
            lines = [item.get("content", "") for item in body if isinstance(item, dict)]
            text = "".join(lines)
        elif isinstance(body, dict):
            lines = [item.get("content", "") for item in body.get("subtitles", body.get("list", []))]
            text = "".join(lines)
        else:
            text = str(body)
        if text.strip():
            logger.info(f"CC字幕解析: {len(text)} chars from {subtitle_path.name}")
            return text
    except Exception as e:
        logger.warning(f"CC字幕解析失败: {e}")
    return None


def transcribe(audio_path: Path = None, subtitle_path: Path = None) -> str | None:
    """Get transcript — CC subs first, then try cloud ASR.

    Priority: B站 CC subs > 智谱 ASR (short audio only) > Gemini > OpenAI
    All cloud, zero local model.
    """
    # 1st: B站 CC subtitles (API)
    if subtitle_path and subtitle_path.exists():
        text = transcribe_from_subs(subtitle_path)
        if text:
            return _restore_punctuation(text)

    # 2nd: Cloud ASR (only works for short audio)
    if audio_path and audio_path.exists():
        for fn in (transcribe_zhipu, transcribe_gemini, transcribe_openai_whisper):
            text = fn(audio_path)
            if text:
                return _restore_punctuation(text)

    logger.error("No transcript source available")
    return None


def reconstruct_from_visual(video_description: str, frame_analyses: str,
                            category: str, video_title: str) -> str:
    """When no transcript is available, reconstruct content structure from visual data.

    Uses DeepSeek LLM to synthesize a content description from:
      - B站 video description (from search metadata)
      - GLM-4V keyframe descriptions
      - Category/product context

    This is NOT a word-for-word transcript, but a structured content flow that
    enables meaningful competitive analysis of structure, pacing, and angle.
    """
    try:
        from openai import OpenAI
        from rag_system.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

        prompt = f"""你是一位资深视频内容分析师。这条{category}测评视频没有字幕文本，请根据以下信息重建其内容结构：

视频标题: {video_title}
品类: {category}

视频简介:
{video_description[:500]}

关键帧画面分析:
{frame_analyses[:1500]}

请输出一个结构化的内容流程（不是逐字稿，而是内容段落描述）:
1. 开场钩子方式（根据第一帧判断是怎么抓住观众的）
2. 产品介绍顺序（先说外观？直接上参数？开箱？对比？）
3. 核心卖点论证方式（数据说话？体验描述？对比测试？）
4. 视频节奏变化点（根据帧变化推测哪里信息密度最高）
5. 结尾方式（购买建议？总结？下期预告？）

每点1-2句，用中文。标注这是[基于画面的内容重建]。"""
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6, max_tokens=600,
        )
        text = response.choices[0].message.content.strip()
        logger.info(f"Visual content reconstruction: {len(text)} chars")
        return text
    except Exception as e:
        logger.warning(f"Content reconstruction failed: {e}")
        return None


def _restore_punctuation(text: str) -> str:
    """Add Chinese punctuation via LLM API call."""
    if not text or len(text) < 50:
        return text
    try:
        from openai import OpenAI
        from rag_system.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
        chunk = text[:800]
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": f"给以下中文文本添加标点符号（。，！？），不要修改任何文字，只加标点，直接输出：\n\n{chunk}"}],
            temperature=0.1, max_tokens=1200,
        )
        restored = response.choices[0].message.content.strip()
        if len(text) > 800:
            restored += text[800:]
        return restored
    except Exception:
        return text
