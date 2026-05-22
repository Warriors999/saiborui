"""Download videos using yt-dlp."""

import subprocess
from pathlib import Path

from rag_system.competitive.models import VideoProfile
from rag_system.utils import logger

OUTPUT_DIR = Path("output/competitive/videos")


def download_video(video: VideoProfile, output_dir: Path = OUTPUT_DIR) -> Path | None:
    """Download a video and extract audio. Returns path to audio file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_path = output_dir / f"{video.video_id}.mp3"

    if audio_path.exists():
        logger.info(f"Audio already exists: {audio_path}")
        return audio_path

    try:
        # Download best audio only, convert to mp3
        cmd = [
            "yt-dlp",
            "-x", "--audio-format", "mp3",
            "--audio-quality", "0",
            "-o", str(output_dir / f"{video.video_id}.%(ext)s"),
            "--no-playlist",
            "--socket-timeout", "30",
            video.url,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            logger.error(f"yt-dlp failed: {result.stderr[:200]}")
            return None

        # yt-dlp may name the file with the original extension
        mp3_path = output_dir / f"{video.video_id}.mp3"
        if mp3_path.exists():
            logger.info(f"Downloaded: {mp3_path} ({mp3_path.stat().st_size} bytes)")
            return mp3_path

        # Check for other extensions
        for ext in [".m4a", ".opus", ".webm"]:
            alt = output_dir / f"{video.video_id}{ext}"
            if alt.exists():
                logger.info(f"Downloaded (alt format): {alt}")
                return alt

        logger.warning(f"No audio file found after download for {video.video_id}")
        return None

    except subprocess.TimeoutExpired:
        logger.error(f"yt-dlp timeout for {video.url}")
        return None
    except FileNotFoundError:
        logger.error("yt-dlp not found. Install: pip install yt-dlp")
        return None
    except Exception as e:
        logger.error(f"Download failed: {e}")
        return None
