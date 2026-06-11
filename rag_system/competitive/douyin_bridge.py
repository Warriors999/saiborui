"""Bridge MediaCrawler Douyin output -> cloud analysis pipeline.

After MediaCrawler scrapes douyin videos, this module:
  1. Reads the saved JSON + video files
  2. Runs GLM-4V visual analysis on keyframes
  3. Runs DeepSeek 4-dimension deep analysis
  4. Stores results alongside B站 data

Usage:
  cd MediaCrawler && uv run python main.py    # First: scrape douyin
  python -m rag_system.competitive.douyin_bridge  # Then: analyze
"""

import json, subprocess, sys, io
from datetime import datetime
from pathlib import Path

MEDIACRAWLER_DIR = Path("MediaCrawler")
DATA_DIR = MEDIACRAWLER_DIR / "data/douyin"
DOUYIN_SESSIONS_DIR = Path("output/competitive/douyin_sessions")

DOUYIN_CATEGORY_KEYWORDS = {
    "keyboard": ["机械键盘", "键盘推荐", "磁轴键盘"],
    "mouse": ["游戏鼠标", "轻量化鼠标", "鼠标推荐"],
    "monitor": ["显示器推荐", "电竞显示器", "显示器评测"],
    "laptop": ["游戏本", "笔记本推荐", "笔记本电脑"],
    "phone": ["手机推荐", "旗舰手机", "手机评测"],
    "gpu": ["显卡推荐", "游戏显卡", "显卡评测"],
    "headphone": ["耳机推荐", "降噪耳机", "电竞耳机"],
    "desk_chair": ["电竞椅", "升降桌", "人体工学椅"],
}


def read_mediacrawler_results() -> list[dict]:
    """Read the latest MediaCrawler search results JSON."""
    json_dir = DATA_DIR / "json"
    if not json_dir.exists():
        return []

    files = sorted(json_dir.glob("search_contents_*.json"), reverse=True)
    if not files:
        return []

    with open(files[0], "r", encoding="utf-8") as f:
        return json.load(f)


def find_video_file(aweme_id: str) -> Path | None:
    """Find the downloaded video file for a given aweme_id."""
    video_dir = DATA_DIR / "videos" / str(aweme_id)
    if not video_dir.exists():
        return None
    for ext in [".mp4", ".mov", ".webm"]:
        for f in video_dir.glob(f"*{ext}"):
            if f.stat().st_size > 1000:
                return f
    return None


def analyze_douyin_video(video: dict, category: str) -> dict | None:
    """Run full cloud analysis on one Douyin video."""
    from rag_system.competitive.downloader import extract_keyframes
    from rag_system.competitive.visual_analyzer import analyze_visual, analyze_keyframes
    from rag_system.competitive.script_analyzer import deep_analyze
    from rag_system.utils import logger

    title = video.get("title", "")[:60]
    creator = video.get("nickname", "unknown")
    aweme_id = str(video.get("aweme_id", ""))

    logger.info(f"Analyzing: {title} ({creator})")

    date_str = datetime.now().strftime("%Y%m%d")
    safe_creator = "".join(c for c in creator[:15] if c.isalnum() or c in ('_', '-'))
    session_dir = DOUYIN_SESSIONS_DIR / f"{date_str}_{category}_{safe_creator}"
    session_dir.mkdir(parents=True, exist_ok=True)

    # Save metadata
    (session_dir / "metadata.json").write_text(
        json.dumps(video, ensure_ascii=False, indent=2), encoding="utf-8")

    # Find video file
    video_path = find_video_file(aweme_id)
    if not video_path:
        logger.warning(f"  Video file not found for {aweme_id}")
        video_path = _download_via_url(video, session_dir)

    if not video_path:
        return None

    # Keyframes
    kf_dir = session_dir / "keyframes"
    kf_paths = extract_keyframes(video_path, kf_dir, interval_sec=1)
    logger.info(f"  Keyframes: {len(kf_paths)}")

    # Shot detection
    visual = analyze_visual(video_path)
    (session_dir / "visual.json").write_text(
        json.dumps(visual, ensure_ascii=False, indent=2), encoding="utf-8")

    # VLM frame analysis
    frame_analysis = analyze_keyframes(
        keyframe_dir=kf_dir,
        transcript=video.get("desc", ""),
        category=category,
        video_title=title,
    )
    if frame_analysis:
        (session_dir / "visual_frames_analysis.txt").write_text(frame_analysis, encoding="utf-8")

    # 4-dimension deep analysis
    transcript = video.get("desc", f"抖音{category}: {title}")
    deep = deep_analyze(
        transcript=transcript, category=category,
        video_title=title, hook_type="抖音短视频",
        visual=visual, visual_frames_analysis=frame_analysis,
    )
    if deep.get("deep_analysis"):
        (session_dir / "deep_analysis.txt").write_text(deep["deep_analysis"], encoding="utf-8")
        logger.info(f"  Deep analysis: {len(deep['deep_analysis'])} chars")

    return {
        "aweme_id": aweme_id,
        "title": title,
        "creator": creator,
        "likes": video.get("liked_count", 0),
        "comments": video.get("comment_count", 0),
        "shares": video.get("share_count", 0),
        "category": category,
    }


def _download_via_url(video: dict, output_dir: Path) -> Path | None:
    """Download via video URL using yt-dlp."""
    url = video.get("aweme_url", "") or video.get("video_download_url", "")
    if not url:
        return None
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"{video.get('aweme_id', 'unknown')}.mp4"
        cmd = ["yt-dlp", "-f", "best[height<=720]", "--merge-output-format", "mp4",
               "-o", str(out_path), "--no-playlist", "--socket-timeout", "20", url]
        subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=60)
        return out_path if out_path.exists() else None
    except Exception:
        return None


def process_all_mediacrawler_results() -> list[dict]:
    """Process all MediaCrawler results through cloud analysis pipeline.

    Reads the latest search results, groups by keyword->category,
    and runs GLM-4V + DeepSeek analysis on each video.
    """
    videos = read_mediacrawler_results()
    if not videos:
        print("No MediaCrawler results found. Run MediaCrawler first:")
        print("  cd MediaCrawler && uv run python main.py")
        return []

    # Map videos to categories based on search keyword
    results = []
    for video in videos:
        keyword = video.get("source_keyword", "")
        category = "other"
        for cat, kws in DOUYIN_CATEGORY_KEYWORDS.items():
            if any(kw in keyword for kw in kws):
                category = cat
                break

        result = analyze_douyin_video(video, category)
        if result:
            results.append(result)

    print(f"\nDouyin analysis complete: {len(results)}/{len(videos)} videos")
    return results


if __name__ == "__main__":
    # Fix stdout encoding
    if sys.stdout and hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    process_all_mediacrawler_results()
