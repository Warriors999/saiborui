"""Download videos, subtitles, and extract keyframes using yt-dlp + ffmpeg.

CPU-friendly: B站 API CC subtitles replace Whisper, 720p replaces 1080p,
keyframe extraction at scene-change boundaries instead of full-frame scan.

B站 subtitle flow uses official WBI-signed API (no login / cookies needed):
  view API -> cid -> player API -> subtitle URL -> download JSON
"""

import hashlib
import json
import re
import subprocess
import time
import urllib.request
import urllib.parse
from pathlib import Path

from rag_system.competitive.models import VideoProfile
from rag_system.utils import logger

OUTPUT_DIR = Path("output/competitive/videos")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# WBI signing (same mechanism as searcher.py)
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52
]
_wbi_cache = {"img_key": "", "sub_key": "", "mixin_key": "", "fetched_at": 0}
_buvid3_cache = {"buvid3": "", "fetched_at": 0}


def _get_buvid3() -> str:
    now = time.time()
    if _buvid3_cache["buvid3"] and (now - _buvid3_cache["fetched_at"]) < 43200:
        return _buvid3_cache["buvid3"]
    try:
        req = urllib.request.Request("https://www.bilibili.com/", headers={"User-Agent": USER_AGENT})
        opener = urllib.request.build_opener()
        resp = opener.open(req, timeout=10)
        for header in resp.headers.get_all("Set-Cookie") or []:
            for part in header.split(";"):
                if "buvid3" in part:
                    _buvid3_cache["buvid3"] = part.split("=")[1].strip()
                    _buvid3_cache["fetched_at"] = now
                    return _buvid3_cache["buvid3"]
    except Exception as e:
        logger.warning(f"Failed to get buvid3: {e}")
    return ""


def _fetch_wbi_keys() -> tuple[str, str]:
    now = time.time()
    if _wbi_cache["mixin_key"] and (now - _wbi_cache["fetched_at"]) < 43200:
        return _wbi_cache["img_key"], _wbi_cache["sub_key"]

    try:
        buvid3 = _get_buvid3()
        headers = {"User-Agent": USER_AGENT, "Referer": "https://www.bilibili.com/"}
        if buvid3:
            headers["Cookie"] = f"buvid3={buvid3}"
        req = urllib.request.Request("https://api.bilibili.com/x/web-interface/nav", headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            wbi = data.get("data", {}).get("wbi_img", {})
            img_url = wbi.get("img_url", "")
            sub_url = wbi.get("sub_url", "")
            if not img_url or not sub_url:
                return "", ""
            img_key = img_url.split("/")[-1].split(".")[0]
            sub_key = sub_url.split("/")[-1].split(".")[0]
            raw = img_key + sub_key
            mixin = "".join(raw[i] for i in MIXIN_KEY_ENC_TAB if i < len(raw))[:32]
            _wbi_cache["img_key"] = img_key
            _wbi_cache["sub_key"] = sub_key
            _wbi_cache["mixin_key"] = mixin
            _wbi_cache["fetched_at"] = now
            return img_key, sub_key
    except Exception as e:
        logger.error(f"Failed to fetch WBI keys: {e}")
        return "", ""


def _wbi_sign(params: dict) -> dict:
    mixin_key = _wbi_cache.get("mixin_key", "")
    if not mixin_key:
        _fetch_wbi_keys()
        mixin_key = _wbi_cache.get("mixin_key", "")
    if not mixin_key:
        return params
    params["wts"] = int(time.time())
    sorted_items = sorted(params.items(), key=lambda x: x[0])
    query_str = urllib.parse.urlencode(sorted_items, quote_via=urllib.parse.quote)
    sign_str = query_str + mixin_key
    params["w_rid"] = hashlib.md5(sign_str.encode("utf-8")).hexdigest()
    return params


# ── Subtitle download via B站 API (no login needed) ──

def download_subtitles(video: VideoProfile, output_dir: Path) -> Path | None:
    """Download B站 auto-generated CC subtitles via official API (WBI-signed).

    Flow: bvid -> view API (cid) -> player API (subtitle list) -> download JSON.
    No login/cookies required. CPU: ~0 (network I/O only).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    sub_path = output_dir / "subtitles.json"

    if sub_path.exists():
        logger.info(f"Subtitles already cached: {sub_path}")
        return sub_path

    # Extract bvid from URL
    bvid_match = re.search(r'BV[\w]+', video.url)
    if not bvid_match:
        logger.warning(f"Cannot extract bvid from URL: {video.url}")
        return _download_subtitles_ytdlp(video, output_dir)

    bvid = bvid_match.group(0)

    try:
        # Step 1: Get cid (first page's content id)
        cid = _get_cid(bvid)
        if not cid:
            logger.warning(f"Cannot get cid for {bvid}")
            return _download_subtitles_ytdlp(video, output_dir)

        # Step 2: Get subtitle list from player API
        subtitle_url = _get_subtitle_url(bvid, cid)
        if not subtitle_url:
            logger.info(f"No CC subtitles available for {video.title[:40]}...")
            return None

        # Step 3: Download and save subtitle JSON
        req = urllib.request.Request(subtitle_url, headers={
            "User-Agent": USER_AGENT,
            "Referer": "https://www.bilibili.com/",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            sub_data = resp.read().decode("utf-8")

        # Parse and normalize to our standard format
        sub_json = json.loads(sub_data)
        normalized = _normalize_bilibili_subs(sub_json)
        sub_path.write_text(json.dumps(normalized, ensure_ascii=False), encoding="utf-8")
        logger.info(f"Subtitles downloaded via API: {sub_path} ({sub_path.stat().st_size} bytes)")
        return sub_path

    except Exception as e:
        logger.warning(f"B站 API subtitle failed: {e}, trying yt-dlp fallback...")
        return _download_subtitles_ytdlp(video, output_dir)


def _get_cid(bvid: str) -> int | None:
    """Get the cid (content ID) for a B站 video."""
    try:
        url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT, "Referer": "https://www.bilibili.com/",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            cid = data.get("data", {}).get("cid", 0)
            if cid:
                return cid
            # Try pages[0].cid
            pages = data.get("data", {}).get("pages", [])
            if pages:
                return pages[0].get("cid", 0)
    except Exception as e:
        logger.warning(f"Failed to get cid for {bvid}: {e}")
    return None


def _get_subtitle_url(bvid: str, cid: int) -> str | None:
    """Get the best Chinese subtitle download URL from player API."""
    try:
        params = _wbi_sign({"bvid": bvid, "cid": cid})
        url = f"https://api.bilibili.com/x/player/v2?{urllib.parse.urlencode(params, quote_via=urllib.parse.quote)}"
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT, "Referer": "https://www.bilibili.com/",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            subtitles = data.get("data", {}).get("subtitle", {}).get("subtitles", [])
            if not subtitles:
                return None
            # Prefer Chinese (zh-CN, zh-Hans), then any
            for sub in subtitles:
                lang = sub.get("lan_doc", "").lower()
                if "中文" in lang or "zh" in lang or "chinese" in lang:
                    return "https:" + sub["sub_url"] if sub["sub_url"].startswith("//") else sub["sub_url"]
            # Fallback: first available
            sub_url = subtitles[0].get("sub_url", "")
            if sub_url:
                return "https:" + sub_url if sub_url.startswith("//") else sub_url
    except Exception as e:
        logger.warning(f"Failed to get subtitle URL: {e}")
    return None


def _normalize_bilibili_subs(raw: dict) -> dict:
    """Normalize B站 subtitle JSON to standard format: {"body": [{"from":..., "to":..., "content":...}]}."""
    body = raw.get("body", [])
    if body:
        return {"body": body}
    # Some formats use a different structure
    return raw


def _download_subtitles_ytdlp(video: VideoProfile, output_dir: Path) -> Path | None:
    """Fallback: yt-dlp subtitle download (may require login for B站)."""
    try:
        cmd = [
            "yt-dlp",
            "--write-auto-subs",
            "--sub-lang", "zh-CN,zh-Hans,zh,en",
            "--skip-download",
            "-o", str(output_dir / "%(id)s.%(ext)s"),
            "--no-playlist",
            "--socket-timeout", "30",
            video.url,
        ]
        subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=60)

        for pattern in ["*.json", "*.json3", "*.srt", "*.vtt"]:
            for f in output_dir.glob(pattern):
                if f.stat().st_size > 100:
                    sub_path = output_dir / "subtitles.json"
                    if f != sub_path:
                        f.rename(sub_path)
                    return sub_path
    except Exception as e:
        logger.warning(f"yt-dlp subtitle fallback failed: {e}")
    return None


# ── Keyframe extraction ──

def extract_keyframes(video_path: Path, output_dir: Path, interval_sec: int = 5) -> list[Path]:
    """Extract keyframes from video at scene changes + periodic interval.

    Uses ffmpeg to detect scene changes and extract 1 frame per cut point.
    Also extracts a frame every `interval_sec` seconds as fallback coverage.
    Returns list of extracted frame paths.

    CPU: ~10-30 seconds for a 10-min 720p video (ffmpeg scene detect).
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Already extracted?
    existing = sorted(output_dir.glob("frame_*.jpg"))
    if len(existing) >= 3:
        logger.info(f"Keyframes already extracted: {len(existing)} frames")
        return existing

    frame_paths = []

    try:
        # Step 1: Scene-change keyframes via ffmpeg scene detect
        # Output frames at detected scene cuts (I-frames with significant visual change)
        scene_cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", "select='gt(scene,0.3)',scale=640:-1",
            "-vsync", "vfr",
            "-frame_pts", "1",
            str(output_dir / "scene_%03d.jpg"),
        ]
        subprocess.run(scene_cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=60)

        # Collect scene frames
        scene_frames = sorted(output_dir.glob("scene_*.jpg"))
        frame_paths.extend(scene_frames)
        logger.info(f"Scene-change keyframes: {len(scene_frames)}")

        # Step 2: Periodic keyframes (every interval_sec)
        periodic_cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", f"fps=1/{interval_sec},scale=640:-1",
            "-frame_pts", "1",
            str(output_dir / "periodic_%03d.jpg"),
        ]
        subprocess.run(periodic_cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=60)

        periodic_frames = sorted(output_dir.glob("periodic_*.jpg"))
        frame_paths.extend(periodic_frames)
        logger.info(f"Periodic keyframes (every {interval_sec}s): {len(periodic_frames)}")

        # Rename all to unified naming
        all_frames = sorted(set(frame_paths))
        for i, fp in enumerate(all_frames):
            new_name = output_dir / f"frame_{i:03d}.jpg"
            if fp != new_name:
                fp.rename(new_name)

        final_frames = sorted(output_dir.glob("frame_*.jpg"))
        logger.info(f"Total keyframes: {len(final_frames)}")
        return final_frames

    except subprocess.TimeoutExpired:
        logger.error("Keyframe extraction timeout")
        return frame_paths
    except Exception as e:
        logger.error(f"Keyframe extraction failed: {e}")
        return frame_paths


# ── Video download (720p default) ──

def download_video_full(video: VideoProfile, output_dir: Path = None,
                        max_height: int = 720) -> Path | None:
    """Download full video for visual analysis. Default 720p to save bandwidth/CPU.

    Args:
        video: VideoProfile with URL
        output_dir: Where to save (defaults to OUTPUT_DIR)
        max_height: Max video height (720 = HD-ready, 1080 = full HD)
    """
    if output_dir is None:
        output_dir = OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    video_path = output_dir / f"{video.video_id}.mp4"

    if video_path.exists():
        logger.info(f"Video already cached: {video_path}")
        return video_path

    try:
        cmd = [
            "yt-dlp",
            "-f", f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]",
            "--merge-output-format", "mp4",
            "-o", str(output_dir / f"{video.video_id}.%(ext)s"),
            "--no-playlist",
            "--socket-timeout", "30",
            video.url,
        ]
        result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=300)
        if result.returncode != 0:
            # Fallback: download best single format
            cmd_fallback = [
                "yt-dlp", "-f", "best", "--merge-output-format", "mp4",
                "-o", str(output_dir / f"{video.video_id}.%(ext)s"),
                "--no-playlist", video.url,
            ]
            subprocess.run(cmd_fallback, capture_output=True, encoding="utf-8", errors="replace", timeout=300)

        if video_path.exists():
            logger.info(f"Video downloaded: {video_path} ({video_path.stat().st_size // 1024 // 1024}MB)")
            return video_path
        # Check alt extensions
        for ext in [".mkv", ".webm", ".flv"]:
            alt = output_dir / f"{video.video_id}{ext}"
            if alt.exists():
                return alt
        return None
    except Exception as e:
        logger.error(f"Video download failed: {e}")
        return None


def download_video(video: VideoProfile, output_dir: Path = None) -> Path | None:
    """Download audio-only from video. Used as fallback when CC subs not available.

    Kept for backward compatibility — the primary pipeline now uses
    download_subtitles() for text and download_video_full() for visual.
    """
    if output_dir is None:
        output_dir = OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_path = output_dir / f"{video.video_id}.mp3"

    if audio_path.exists():
        logger.info(f"Audio already exists: {audio_path}")
        return audio_path

    try:
        cmd = [
            "yt-dlp",
            "-x", "--audio-format", "mp3",
            "--audio-quality", "0",
            "-o", str(output_dir / f"{video.video_id}.%(ext)s"),
            "--no-playlist",
            "--socket-timeout", "30",
            video.url,
        ]
        result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=120)
        if result.returncode != 0:
            logger.error(f"yt-dlp failed: {result.stderr[:200]}")
            return None

        for ext in [".mp3", ".m4a", ".opus", ".webm"]:
            alt = output_dir / f"{video.video_id}{ext}"
            if alt.exists():
                logger.info(f"Audio downloaded ({alt.stat().st_size} bytes)")
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
