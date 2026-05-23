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
