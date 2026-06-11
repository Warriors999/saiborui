"""Douyin competitive analysis pipeline — short-form vertical video learning.

Uses agent-browser for search (with saved auth state) + yt-dlp for download.
Reuses the cloud analysis pipeline: GLM-4V for vertical frame analysis,
DeepSeek for Douyin-specific 4-dimension deep analysis.

Prerequisite: Run `douyin_setup.py` once to save 抖音 login state.
"""

import json, subprocess
from datetime import datetime
from pathlib import Path

from rag_system.utils import logger

DOUYIN_SESSIONS_DIR = Path("output/competitive/douyin_sessions")
DOUYIN_DATA_FILE = Path("output/competitive/analyzed_douyin_videos.json")
AUTH_STATE = Path("output/competitive/douyin_auth.json")

DOUYIN_KEYWORDS = {
    "keyboard": ["机械键盘推荐", "磁轴键盘", "键盘评测"],
    "mouse": ["游戏鼠标推荐", "轻量化鼠标"],
    "monitor": ["显示器推荐", "电竞显示器"],
    "laptop": ["游戏本推荐", "笔记本推荐"],
    "phone": ["手机推荐", "旗舰手机测评"],
    "gpu": ["显卡推荐", "游戏显卡"],
    "headphone": ["耳机推荐", "降噪耳机"],
    "desk_chair": ["电竞椅推荐", "升降桌"],
}


def search_douyin(category: str, top_n: int = 3) -> list[dict]:
    """Search Douyin for top videos using agent-browser.

    Requires douyin_setup.py to have been run first (saved auth state).
    Falls back to cookie-less search if no auth state.
    """
    keywords = DOUYIN_KEYWORDS.get(category, [f"{category} 推荐"])
    all_results = []
    seen_ids = set()

    for kw in keywords[:2]:
        import urllib.parse as _up; encoded = _up.quote(kw)
        url = f"https://www.douyin.com/search/{encoded}?type=general"

        try:
            # Use agent-browser with saved auth if available
            state_args = ["--state", str(AUTH_STATE)] if AUTH_STATE.exists() else []
            subprocess.run(
                ["agent-browser", *state_args, "open", url],
                capture_output=True, encoding="utf-8", errors="replace", timeout=20,
            )

            # Wait for content to load
            subprocess.run(["agent-browser", "wait", "--load", "networkidle"],
                          capture_output=True, encoding="utf-8", errors="replace", timeout=15)

            # Get snapshot to extract video data
            result = subprocess.run(
                ["agent-browser", "get", "text", "body"],
                capture_output=True, encoding="utf-8", errors="replace", timeout=10,
            )
            text = result.stdout[:5000]

            # Extract video-like entries from page text
            entries = _parse_douyin_search_results(text)
            for entry in entries[:top_n]:
                vid = entry.get("title", "")[:30]
                if vid not in seen_ids:
                    entry["category"] = category
                    entry["source"] = "douyin"
                    all_results.append(entry)
                    seen_ids.add(vid)

        except subprocess.TimeoutExpired:
            logger.warning(f"Douyin search timeout for '{kw}'")
        except Exception as e:
            logger.warning(f"Douyin search error for '{kw}': {e}")

    all_results.sort(key=lambda x: -x.get("views", 0))
    return all_results[:top_n]


def _parse_douyin_search_results(text: str) -> list[dict]:
    """Parse Douyin search page text into video entries.

    Extracts: title fragments, author mentions, view counts, URLs.
    This is a best-effort parser — Douyin's dynamic rendering makes
    precise extraction difficult without full browser automation.
    """
    results = []
    lines = text.split("\n")
    current = {}

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Heuristic: lines with numbers followed by "万" or "w" are likely view counts
        if any(marker in line for marker in ["万", "w播放", "次播放", "播放"]):
            try:
                nums = "".join(c for c in line if c.isdigit() or c in ".万w")
                if "万" in nums:
                    current["views"] = int(float(nums.replace("万", "")) * 10000)
                elif "w" in nums.lower():
                    current["views"] = int(float(nums.lower().replace("w", "")) * 10000)
                else:
                    current["views"] = int(nums) if nums else 0
            except ValueError:
                current["views"] = 0

        # Lines with "@" are likely author names
        if "@" in line and len(line) < 30:
            current["creator_name"] = line.replace("@", "").strip()

        # Lines that look like video titles (longer, descriptive)
        if len(line) > 10 and len(line) < 80 and not line.startswith(("@", "http", "#", "·")):
            if "title" not in current:
                current["title"] = line

        # Build result when we have enough data
        if len(current) >= 2 and "video_id" not in current:
            current["video_id"] = str(hash(current.get("title", "")) % 10**15)
            current["url"] = ""
            current["likes"] = 0
            current["comments"] = 0
            current["description"] = current.get("title", "")
            current["duration_sec"] = 0
            results.append(dict(current))
            current = {}

    return results


# ── Video download & analysis ──

def download_douyin_video(video: dict, output_dir: Path) -> Path | None:
    """Download Douyin video via yt-dlp."""
    output_dir.mkdir(parents=True, exist_ok=True)
    video_path = output_dir / f"{video.get('video_id', 'unknown')}.mp4"
    if video_path.exists():
        return video_path

    url = video.get("url", "") or video.get("video_play_url", "")
    if not url or not url.startswith("http"):
        logger.warning(f"No URL for {video.get('title', '?')[:30]}")
        return None

    try:
        cmd = ["yt-dlp", "-f", "best[height<=720]", "--merge-output-format", "mp4",
               "-o", str(video_path), "--no-playlist", "--socket-timeout", "20", url]
        subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=60)
        return video_path if video_path.exists() else None
    except Exception as e:
        logger.warning(f"Douyin download failed: {e}")
        return None


def run_douyin_pipeline(category: str, top_n: int = 3) -> list[dict]:
    """Full cloud Douyin competitive analysis pipeline.

    Uses agent-browser for search, yt-dlp for download,
    GLM-4V for vertical frame analysis, DeepSeek for deep analysis.
    """
    from rag_system.competitive.downloader import extract_keyframes
    from rag_system.competitive.visual_analyzer import analyze_visual, analyze_keyframes
    from rag_system.competitive.script_analyzer import deep_analyze

    # Check auth state
    if not AUTH_STATE.exists():
        logger.warning("=" * 50)
        logger.warning("  抖音认证状态未初始化！")
        logger.warning(f"  请先运行: python -m rag_system.competitive.douyin_setup")
        logger.warning("=" * 50)

    logger.info(f"=== 抖音竞品管线: {category} (Top {top_n}) ===")

    # Step 1: Search
    logger.info(f"搜索抖音 {category} 品类...")
    videos = search_douyin(category, top_n=top_n)
    logger.info(f"找到 {len(videos)} 个视频")

    if not videos:
        logger.warning(f"未找到抖音 {category} 视频，跳过")
        return []

    results = []
    for i, v in enumerate(videos):
        title = v.get("title", "?")[:40]
        creator = v.get("creator_name", "?")
        views = v.get("views", 0)
        logger.info(f"[{i+1}/{len(videos)}] {title} ({creator}, {views:,}播放)")

        date_str = datetime.now().strftime("%Y%m%d")
        safe = "".join(c for c in creator[:15] if c.isalnum() or c in ('_', '-'))
        session_dir = DOUYIN_SESSIONS_DIR / f"{date_str}_{category}_{safe}"
        session_dir.mkdir(parents=True, exist_ok=True)

        # Save metadata
        (session_dir / "metadata.json").write_text(
            json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")

        # Download video
        video_path = download_douyin_video(v, session_dir)
        if not video_path:
            logger.warning(f"  下载失败，跳过")
            continue

        # Keyframes
        kf_dir = session_dir / "keyframes"
        kf_paths = extract_keyframes(video_path, kf_dir, interval_sec=1)
        logger.info(f"  关键帧: {len(kf_paths)}")

        # Shot detection
        visual = analyze_visual(video_path)
        (session_dir / "visual.json").write_text(
            json.dumps(visual, ensure_ascii=False, indent=2), encoding="utf-8")

        # VLM frame analysis
        frame_analysis = analyze_keyframes(
            keyframe_dir=kf_dir,
            transcript=v.get("description", ""),
            category=category,
            video_title=v.get("title", ""),
        )
        if frame_analysis:
            (session_dir / "visual_frames_analysis.txt").write_text(frame_analysis, encoding="utf-8")

        # Deep analysis
        transcript = v.get("description", f"抖音{category}: {title}")
        deep = deep_analyze(
            transcript=transcript, category=category,
            video_title=v.get("title", ""), hook_type="抖音短视频",
            visual=visual, visual_frames_analysis=frame_analysis,
        )
        if deep.get("deep_analysis"):
            (session_dir / "deep_analysis.txt").write_text(deep["deep_analysis"], encoding="utf-8")
            logger.info(f"  深度分析: {len(deep['deep_analysis'])}字")

        results.append({"title": title, "creator": creator,
                        "views": views, "likes": v.get("likes", 0)})

    logger.info(f"=== 抖音 {category}: {len(results)}/{len(videos)} ===")
    return results
