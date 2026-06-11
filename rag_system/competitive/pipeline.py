"""Competitive analysis pipeline — 100% cloud, zero local model inference.

Flow: Search → CC Subtitles (API) → Cloud ASR → Video(720p) → Keyframes
      → VLM Frame Analysis → 4-Dimension Deep Analysis → Store → Wiki

Local processing: only ffmpeg (hardware decoding, not model inference).
All understanding (ASR, vision, deep analysis) via cloud APIs.
"""

import json
from datetime import datetime
from pathlib import Path

from rag_system.competitive.models import VideoProfile
from rag_system.competitive.searcher import search_by_category
from rag_system.competitive.downloader import (
    download_subtitles, download_video_full, extract_keyframes, download_video,
)
from rag_system.competitive.visual_analyzer import (
    analyze_visual, analyze_keyframes, detect_transitions,
)
from rag_system.competitive.transcriber import transcribe
from rag_system.competitive.script_analyzer import analyze_transcript, deep_analyze
from rag_system.competitive.store import save_analysis
from rag_system.utils import logger

SESSIONS_DIR = Path("output/competitive/sessions")
PROGRESS_FILE = Path("output/competitive/pipeline_progress.json")


# ── Progress tracking ──

def _load_progress() -> dict:
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"completed_videos": [], "completed_categories": []}


def _save_progress(progress: dict):
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_FILE.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")


def _mark_video_done(progress: dict, video_id: str):
    if video_id not in progress["completed_videos"]:
        progress["completed_videos"].append(video_id)
    _save_progress(progress)


def _mark_category_done(progress: dict, category: str):
    if category not in progress["completed_categories"]:
        progress["completed_categories"].append(category)
    _save_progress(progress)


def _index_to_knowledge_base(result, video: VideoProfile):
    try:
        from rag_system.embedding.embedder import Embedder
        from rag_system.storage.vector_store import VectorStore
        from rag_system.chunking.splitter import split_text

        chunk_text = f"""【竞品标杆】{video.title}
创作者: {video.creator_name} | 播放量: {video.views:,}
品类: {video.category} | 钩子类型: {result.hook_type}
口语密度: {result.spoken_density:.1f}/百字 | 态度密度: {result.attitude_density:.1f}/200字
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


# ── Single video processing ──

def _process_one_video(video: VideoProfile, category: str, idx: int, total: int,
                        progress: dict) -> dict | None:
    """Process one video. All understanding via cloud APIs, zero local inference.

    1. Download CC subtitles (B站 API)
    2. Try subtitle parse, fallback to cloud ASR (Gemini/OpenAI Whisper)
    3. Download 720p video + extract keyframes (ffmpeg, hardware only)
    4. Shot detection (ffmpeg, no OpenCV)
    5. VLM keyframe analysis (Gemini/OpenAI Vision)
    6. DeepSeek 4-dimension deep analysis
    7. Store + index
    """
    logger.info(f"[{idx}/{total}] {video.title[:50]}... ({video.views:,} views)")
    vid = video.video_id

    if vid in progress.get("completed_videos", []):
        logger.info(f"  Already completed, skipping")
        return None

    date_str = datetime.now().strftime("%Y%m%d")
    safe_creator = "".join(c for c in video.creator_name if c.isalnum() or c in ('_', '-'))[:20]
    session_dir = SESSIONS_DIR / f"{date_str}_{category}_{safe_creator}"
    session_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: CC subtitles + transcript (API, zero CPU) ──
    sub_path = download_subtitles(video, output_dir=session_dir)
    transcript = None
    transcript_source = "none"

    if sub_path:
        transcript = transcribe(subtitle_path=sub_path)
        if transcript:
            transcript_source = "bilibili_cc"

    if not transcript:
        logger.info(f"  No CC subs, trying cloud ASR...")
        audio_path = download_video(video, output_dir=session_dir)
        if audio_path:
            transcript = transcribe(audio_path=audio_path)
            if transcript:
                transcript_source = "cloud_asr"

    # ── Step 2: Visual data (needed for both transcript modes) ──
    video_path = download_video_full(video, output_dir=session_dir, max_height=720)
    keyframe_dir = session_dir / "keyframes"
    keyframe_paths = []
    if video_path:
        keyframe_paths = extract_keyframes(video_path, output_dir=keyframe_dir, interval_sec=5)

    # ── Step 3: VLM frame analysis (run regardless of transcript status) ──
    visual_frames_analysis = ""
    if keyframe_paths and len(keyframe_paths) >= 2:
        visual_frames_analysis = analyze_keyframes(
            keyframe_dir=keyframe_dir,
            transcript=transcript or "",
            category=category,
            video_title=video.title,
        )
        if visual_frames_analysis:
            (session_dir / "visual_frames_analysis.txt").write_text(
                visual_frames_analysis, encoding="utf-8")

    # ── Step 4: Reconstruct transcript from visual if no audio transcript ──
    if not transcript:
        logger.info(f"  No audio transcript — reconstructing from visual data...")
        from rag_system.competitive.transcriber import reconstruct_from_visual
        transcript = reconstruct_from_visual(
            video_description=video.description or video.title,
            frame_analyses=visual_frames_analysis,
            category=category,
            video_title=video.title,
        )
        if transcript:
            transcript_source = "visual_reconstruction"
        else:
            # Last resort: use description + title as minimal text
            transcript = f"视频: {video.title}\n简介: {video.description or '无'}"
            transcript_source = "metadata_only"

    (session_dir / "transcript.txt").write_text(transcript, encoding="utf-8")
    logger.info(f"  Transcript [{transcript_source}]: {len(transcript)} chars")

    # ── Step 5: Shot detection (ffmpeg, no OpenCV) ──
    visual = {}
    if video_path:
        visual = analyze_visual(video_path)
        (session_dir / "visual.json").write_text(
            json.dumps(visual, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"  Visual (ffmpeg): {visual.get('shot_count', 'N/A')} shots, "
                     f"{visual.get('cuts_per_minute', 'N/A')} cpm")

    # ── Step 6: Script statistical analysis ──
    result = analyze_transcript(video, transcript)
    logger.info(f"  Hook: {result.hook_type} | Spoken: {result.spoken_density:.1f}")

    # ── Step 7: 4-dimension deep analysis (DeepSeek LLM, cloud API) ──
    logger.info(f"  4-dimension deep analysis via DeepSeek...")
    # Build audio context from visual data (no librosa)
    audio_context = {}
    if video_path:
        transitions = visual.get("transitions", {})
        audio_context = {
            "note": "基于剪辑节奏推断音频模式",
            "inferred_bgm_changes": "约" + str(max(1, visual.get("shot_count", 1) // 10)) + "处",
            "inferred_rhythm": transitions.get("dominant", "标准"),
        }

    deep = deep_analyze(
        transcript=transcript,
        category=category,
        video_title=video.title,
        hook_type=result.hook_type,
        visual=visual,
        visual_frames_analysis=visual_frames_analysis,
        audio=audio_context,
    )
    if deep.get("deep_analysis"):
        result.standout_patterns.append("LLM四维度深度解读已完成")
        result._deep_analysis = deep["deep_analysis"]
        (session_dir / "deep_analysis.txt").write_text(deep["deep_analysis"], encoding="utf-8")
        logger.info(f"  Deep analysis: {len(deep['deep_analysis'])} chars")

    # ── Step 8: Store + Index ──
    save_analysis(result)
    _index_to_knowledge_base(result, video)
    _mark_video_done(progress, vid)

    return {
        "title": video.title,
        "creator": video.creator_name,
        "views": video.views,
        "hook_type": result.hook_type,
        "spoken_density": result.spoken_density,
        "patterns": result.standout_patterns,
        "transcript_source": transcript_source,
    }


# ── Pipeline entry ──

def run_pipeline(category: str, top_n: int = 3, resume: bool = True) -> list[dict]:
    """Full cloud competitive pipeline. Zero local model inference."""
    logger.info(f"=== 全云端竞品管线: {category} (Top {top_n}) ===")

    progress = _load_progress() if resume else {"completed_videos": [], "completed_categories": []}

    logger.info(f"搜索B站 {category} 品类...")
    videos = search_by_category(category, top_n=top_n)
    logger.info(f"找到 {len(videos)} 个视频")

    if not videos:
        return []

    results = []
    failures = []
    for i, video in enumerate(videos):
        try:
            r = _process_one_video(video, category, i + 1, len(videos), progress)
            if r:
                results.append(r)
                logger.info(f"  ✓ [{r.get('hook_type', '?')}] {r['title'][:40]} | "
                             f"{r['creator']} | 转录: {r.get('transcript_source', '?')}")
        except Exception as e:
            logger.error(f"  ✗ Failed: {video.title[:40]}... — {e}")
            failures.append({"title": video.title, "creator": video.creator_name, "error": str(e)})
            continue

    if failures:
        logger.warning(f"⚠ {len(failures)}/{len(videos)} videos failed: "
                        f"{', '.join(f['title'][:30] for f in failures)}")

    # Wiki compilation
    try:
        sessions = sorted(SESSIONS_DIR.glob(f"*_{category}_*"),
                         key=lambda p: p.stat().st_mtime, reverse=True)
        if sessions:
            from rag_system.competitive.wiki_compiler import compile_to_wiki
            compile_to_wiki(sessions[0], category)
            logger.info(f"Wiki updated for {category}")
    except Exception as e:
        logger.warning(f"Wiki compile failed for {category}: {e}")
        import traceback
        logger.debug(traceback.format_exc())

    _mark_category_done(progress, category)
    logger.info(f"=== {category}: {len(results)}/{len(videos)} ===")
    return results


def run_pipeline_light(category: str, top_n: int = 3, resume: bool = True) -> list[dict]:
    """Lightweight pipeline: search + transcript + analysis only, no video download/VLM.

    Use when bandwidth is limited or a quick competitive scan is needed.
    Skips full video download and VLM frame analysis — transcript-only deep analysis.
    """
    logger.info(f"=== 轻量竞品管线: {category} (Top {top_n}) ===")

    progress = _load_progress() if resume else {"completed_videos": [], "completed_categories": []}

    logger.info(f"搜索B站 {category} 品类...")
    videos = search_by_category(category, top_n=top_n)
    logger.info(f"找到 {len(videos)} 个视频")

    if not videos:
        return []

    results = []
    failures = []
    for i, video in enumerate(videos):
        try:
            vid = video.video_id
            if vid in progress.get("completed_videos", []):
                logger.info(f"  [{i+1}/{len(videos)}] Already completed, skipping")
                continue

            logger.info(f"[{i+1}/{len(videos)}] {video.title[:50]}... ({video.views:,} views)")

            # Transcript only — try CC first, then cloud ASR on audio-only download
            date_str = datetime.now().strftime("%Y%m%d")
            safe_creator = "".join(c for c in video.creator_name if c.isalnum() or c in ('_', '-'))[:20]
            light_dir = SESSIONS_DIR / f"light_{date_str}_{category}_{safe_creator}"
            light_dir.mkdir(parents=True, exist_ok=True)
            sub_path = download_subtitles(video, output_dir=light_dir)
            transcript = None
            transcript_source = "none"

            if sub_path:
                transcript = transcribe(subtitle_path=sub_path)
                if transcript:
                    transcript_source = "bilibili_cc"

            if not transcript:
                logger.info(f"  No CC subs, trying cloud ASR (audio only)...")
                audio_path = download_video(video)
                if audio_path:
                    transcript = transcribe(audio_path=audio_path)
                    if transcript:
                        transcript_source = "cloud_asr"

            if not transcript:
                transcript = f"视频: {video.title}\n简介: {video.description or '无'}"
                transcript_source = "metadata_only"

            logger.info(f"  Transcript [{transcript_source}]: {len(transcript)} chars")

            # Statistical analysis + deep analysis (no visual/VLM)
            result = analyze_transcript(video, transcript)
            logger.info(f"  Hook: {result.hook_type} | Spoken: {result.spoken_density:.1f}")

            deep = deep_analyze(
                transcript=transcript,
                category=category,
                video_title=video.title,
                hook_type=result.hook_type,
                visual={},
                visual_frames_analysis="",
                audio={},
            )
            if deep.get("deep_analysis"):
                result.standout_patterns.append("LLM四维度深度解读已完成")

            save_analysis(result)
            _mark_video_done(progress, vid)

            results.append({
                "title": video.title,
                "creator": video.creator_name,
                "views": video.views,
                "hook_type": result.hook_type,
                "spoken_density": result.spoken_density,
                "patterns": result.standout_patterns,
                "transcript_source": transcript_source,
                "pipeline": "light",
            })
            logger.info(f"  ✓ [{result.hook_type}] {video.title[:40]} | "
                         f"{video.creator_name} | 转录: {transcript_source}")

        except Exception as e:
            logger.error(f"  ✗ Failed: {video.title[:40]}... — {e}")
            failures.append({"title": video.title, "creator": video.creator_name, "error": str(e)})
            continue

    if failures:
        logger.warning(f"⚠ {len(failures)}/{len(videos)} videos failed: "
                        f"{', '.join(f['title'][:30] for f in failures)}")

    _mark_category_done(progress, category)
    logger.info(f"=== {category} (light): {len(results)}/{len(videos)} ===")
    return results
