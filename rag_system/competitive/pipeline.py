"""Orchestrate the full competitive analysis pipeline.

Flow: Search → Download → Transcribe → Analyze → Store → Report
"""

from rag_system.competitive.models import VideoProfile
from rag_system.competitive.searcher import search_by_category
from rag_system.competitive.downloader import download_video
from rag_system.competitive.transcriber import transcribe
from rag_system.competitive.script_analyzer import analyze_transcript
from rag_system.competitive.store import save_analysis
from rag_system.utils import logger


def run_pipeline(category: str, top_n: int = 3, skip_download: bool = False) -> list[dict]:
    """Run the full pipeline: search top videos → analyze → return results.

    Args:
        category: Product category (keyboard/mouse/monitor/...)
        top_n: Number of top videos to analyze
        skip_download: Skip video download (if transcripts already cached)

    Returns:
        List of analysis result dicts
    """
    logger.info(f"=== 竞品分析管线: {category} (Top {top_n}) ===")

    # Step 1: Search
    logger.info(f"搜索B站 {category} 品类热门视频...")
    videos = search_by_category(category, top_n=top_n)
    logger.info(f"找到 {len(videos)} 个视频")

    results = []
    for i, video in enumerate(videos):
        logger.info(f"[{i+1}/{len(videos)}] {video.title[:50]}... ({video.views} 播放)")

        # Step 2: Download (if not skipped)
        if not skip_download:
            audio_path = download_video(video)
            if not audio_path:
                logger.warning(f"下载失败，跳过: {video.title}")
                continue
        else:
            from pathlib import Path
            audio_path = Path(f"output/competitive/videos/{video.video_id}.mp3")
            if not audio_path.exists():
                logger.warning(f"无缓存音频，跳过: {video.title}")
                continue

        # Step 3: Transcribe
        transcript = transcribe(audio_path)
        if not transcript:
            logger.warning(f"转录失败，跳过: {video.title}")
            continue

        # Step 4: Analyze
        logger.info(f"分析脚本 ({len(transcript)} 字)...")
        result = analyze_transcript(video, transcript)

        # Step 5: Store
        save_analysis(result)
        results.append({
            "title": video.title,
            "creator": video.creator_name,
            "views": video.views,
            "hook_type": result.hook_type,
            "spoken_density": result.spoken_density,
            "patterns": result.standout_patterns,
        })

        logger.info(f"  钩子: {result.hook_type} | 口语密度: {result.spoken_density:.1f} | 亮点: {result.standout_patterns}")

    logger.info(f"=== 完成: {len(results)}/{len(videos)} 个视频分析成功 ===")
    return results
