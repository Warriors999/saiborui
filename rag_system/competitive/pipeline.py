"""Orchestrate the full competitive analysis pipeline.

Flow: Search → Download → Transcribe → Visual Analyze → Deep Analyze → Store → Report
All files saved to: output/competitive/sessions/{date}_{category}_{creator}/
"""

from datetime import datetime
from pathlib import Path

from rag_system.competitive.models import VideoProfile
from rag_system.competitive.searcher import search_by_category
from rag_system.competitive.downloader import download_video, download_video_full
from rag_system.competitive.visual_analyzer import analyze_visual
from rag_system.competitive.audio_analyzer import analyze_audio
from rag_system.competitive.transcriber import transcribe
from rag_system.competitive.script_analyzer import analyze_transcript, deep_analyze
from rag_system.competitive.store import save_analysis
from rag_system.utils import logger

SESSIONS_DIR = Path("output/competitive/sessions")


def _index_to_knowledge_base(result, video: VideoProfile):
    """Index competitive analysis into ChromaDB for RAG retrieval.

    Creates a structured text chunk with analysis metadata so the
    generation pipeline can retrieve competitor insights when writing
    scripts for the same category.
    """
    try:
        from rag_system.embedding.embedder import Embedder
        from rag_system.storage.vector_store import VectorStore
        from rag_system.chunking.splitter import split_text

        chunk_text = f"""【竞品标杆】{video.title}
创作者: {video.creator_name} | 播放量: {video.views:,}
品类: {video.category} | 钩子类型: {result.hook_type}
口语密度: {result.spoken_density:.1f}/百字 | 态度密度: {result.attitude_density:.1f}/200字
叙事弧线: {result.narrative_arc}
亮点模式: {', '.join(result.standout_patterns) if result.standout_patterns else '无'}
口播脚本摘要: {result.transcript[:800]}"""

        chunks = split_text(chunk_text, chunk_size=600, chunk_overlap=60)
        embedder = Embedder()
        store = VectorStore()

        store.upsert_chunks([{
            "id": f"competitive_{video.video_id}_{ci}",
            "embedding": embedder.embed_documents([chunk])[0],
            "document": chunk,
            "metadata": {
                "source_file": video.title[:50],
                "persona": "competitive",
                "category": video.category,
                "is_competitive": "true",
                "views": video.views,
                "hook_type": result.hook_type,
            },
        } for ci, chunk in enumerate(chunks)])
        logger.info(f"Indexed {len(chunks)} chunks for {video.title[:30]}...")
    except Exception as e:
        logger.warning(f"KB indexing failed (non-fatal): {e}")


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

        # Create session folder
        date_str = datetime.now().strftime("%Y%m%d")
        safe_creator = "".join(c for c in video.creator_name if c.isalnum() or c in ('_', '-'))[:20]
        session_dir = SESSIONS_DIR / f"{date_str}_{category}_{safe_creator}"
        session_dir.mkdir(parents=True, exist_ok=True)

        # Step 2: Download (if not skipped)
        if not skip_download:
            audio_path = download_video(video, output_dir=session_dir)
            if not audio_path:
                logger.warning(f"下载失败，跳过: {video.title}")
                continue
        else:
            audio_path = session_dir / "audio.mp3"
            if not audio_path.exists():
                logger.warning(f"无缓存音频，跳过: {video.title}")
                continue

        # Step 3: Transcribe → save to session
        transcript = transcribe(audio_path)
        if not transcript:
            logger.warning(f"转录失败，跳过: {video.title}")
            continue
        (session_dir / "transcript.txt").write_text(transcript, encoding="utf-8")

        # Step 4: Visual analysis → save to session
        visual = {}
        if not skip_download:
            video_path = download_video_full(video, output_dir=session_dir)
            if video_path:
                visual = analyze_visual(video_path)
                import json
                (session_dir / "visual.json").write_text(json.dumps(visual, ensure_ascii=False, indent=2), encoding="utf-8")
                logger.info(f"视觉分析: {visual.get('shot_count', 'N/A')} 镜, {visual.get('avg_shot_sec', 'N/A')}s/镜")

        # Step 5: Analyze (statistical + LLM deep analysis)
        logger.info(f"分析脚本 ({len(transcript)} 字)...")
        result = analyze_transcript(video, transcript)
        logger.info(f"LLM深度解读...")
        deep = deep_analyze(transcript, category, video.title, result.hook_type, visual)
        if deep.get("deep_analysis"):
            result.standout_patterns.append("LLM深度解读已完成")
            result._deep_analysis = deep["deep_analysis"]
            (session_dir / "deep_analysis.txt").write_text(deep["deep_analysis"], encoding="utf-8")

        # Step 5: Store to JSON
        save_analysis(result)

        # Step 6: Index into knowledge base for RAG retrieval
        _index_to_knowledge_base(result, video)
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
