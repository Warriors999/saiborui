"""Douyin competitive analysis pipeline — MediaCrawler data → cloud analysis.

Reads real Douyin video data from MediaCrawler JSON outputs, runs the full
cloud analysis chain (keyframes → VLM → DeepSeek), and produces independently
stored results alongside the B站 pipeline.

Learning focus: 钩子设计·节奏控制·转化技巧·情绪曲线
(vs B站's 结构论证·知识框架·分段逻辑)

Usage:
    python -m rag_system.competitive.douyin_search_pipeline              # all categories
    python -m rag_system.competitive.douyin_search_pipeline --category keyboard
"""

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from rag_system.competitive.models import VideoProfile, AnalysisResult
from rag_system.competitive.store import save_douyin_analysis, get_analyzed_douyin_videos
from rag_system.utils import logger

MEDIACRAWLER_DIR = Path("MediaCrawler")
DATA_DIR = MEDIACRAWLER_DIR / "data/douyin"
DOUYIN_SESSIONS_DIR = Path("output/competitive/douyin_sessions")
DOUYIN_PROGRESS_FILE = Path("output/competitive/douyin_pipeline_progress.json")

ALL_CATEGORIES = [
    "keyboard", "mouse", "monitor", "laptop",
    "phone", "gpu", "headphone", "desk_chair",
]

TOP_N = 2  # 每品类只取前2，质量>数量。候选池取5个跑投流检测后筛选

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


# ═══════════════════════════════════════════
# Progress tracking (independent from B站)
# ═══════════════════════════════════════════

def _load_progress() -> dict:
    if DOUYIN_PROGRESS_FILE.exists():
        try:
            return json.loads(DOUYIN_PROGRESS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"completed_videos": [], "completed_categories": []}


def _save_progress(progress: dict):
    DOUYIN_PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    DOUYIN_PROGRESS_FILE.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")


def _mark_video_done(progress: dict, video_id: str):
    if video_id not in progress["completed_videos"]:
        progress["completed_videos"].append(video_id)
    _save_progress(progress)


def _mark_category_done(progress: dict, category: str):
    if category not in progress["completed_categories"]:
        progress["completed_categories"].append(category)
    _save_progress(progress)


# ═══════════════════════════════════════════
# MediaCrawler data reading
# ═══════════════════════════════════════════

def read_mediacrawler_results() -> list[dict]:
    """Read the latest MediaCrawler search_contents JSON."""
    json_dir = DATA_DIR / "json"
    if not json_dir.exists():
        return []

    files = sorted(json_dir.glob("search_contents_*.json"), reverse=True)
    if not files:
        return []

    with open(files[0], "r", encoding="utf-8") as f:
        data = json.load(f)

    logger.info(f"Read {len(data)} videos from {files[0].name}")
    return data


def find_video_file(aweme_id: str) -> Path | None:
    """Find the downloaded video file for a given aweme_id."""
    video_dir = DATA_DIR / "videos" / str(aweme_id)
    if not video_dir.exists():
        return None
    for ext in [".mp4", ".mov", ".webm"]:
        for f in video_dir.glob(f"*{ext}"):
            if f.stat().st_size > 1000:  # skip tiny files
                return f
    return None


# ═══════════════════════════════════════════
# VideoProfile construction
# ═══════════════════════════════════════════

def build_video_profile(raw: dict, category: str) -> VideoProfile:
    """Convert a MediaCrawler raw dict into a VideoProfile dataclass."""
    title = (raw.get("title") or raw.get("desc") or "")[:80]
    aweme_id = str(raw.get("aweme_id", ""))

    # Safe int conversion — avoid 0-or-x short-circuit
    def _safe_int(val, default=0):
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    liked = raw.get("liked_count")
    if liked is None:
        liked = raw.get("digg_count", 0)

    return VideoProfile(
        video_id=aweme_id,
        title=title,
        url=raw.get("aweme_url", "") or raw.get("video_download_url", "") or "",
        source="douyin",
        creator_name=(raw.get("nickname") or "unknown")[:30],
        creator_id=raw.get("sec_uid", ""),
        duration_sec=_safe_int(raw.get("duration", 0)),
        views=_safe_int(raw.get("play_count", 0)),
        likes=_safe_int(liked),
        comments=_safe_int(raw.get("comment_count", 0)),
        shares=_safe_int(raw.get("share_count", 0)),
        publish_date=str(raw.get("create_time", "")),
        category=category,
        tags=raw.get("hashtags", []) or [],
        description=(raw.get("desc") or "")[:500],
    )


# ═══════════════════════════════════════════
# Video download (yt-dlp fallback)
# ═══════════════════════════════════════════

def _download_via_url(video: dict, output_dir: Path) -> Path | None:
    """Download via video URL using yt-dlp."""
    url = video.get("aweme_url", "") or video.get("video_download_url", "")
    if not url:
        return None
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        aweme_id = video.get("aweme_id", "unknown")
        out_path = output_dir / f"{aweme_id}.mp4"
        cmd = [
            "yt-dlp", "-f", "best[height<=720]", "--merge-output-format", "mp4",
            "-o", str(out_path), "--no-playlist", "--socket-timeout", "20", url,
        ]
        subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=60)
        return out_path if out_path.exists() else None
    except Exception:
        return None


# ═══════════════════════════════════════════
# Single video processing
# ═══════════════════════════════════════════

def _process_one_douyin_video(
    video: VideoProfile, raw: dict, category: str,
    idx: int, total: int, progress: dict,
    run_paid_check: bool = True,
) -> dict | None:
    """Process one Douyin video through the cloud analysis chain.

    Steps:
      1. Find/download video file
      2. Extract keyframes (interval=1s for short-form)
      3. Shot detection (ffmpeg)
      4. VLM keyframe analysis
      5. DeepSeek 4-dim deep analysis (Douyin-specific prompt)
      6. Paid traffic detection (if comments available)
      7. Save to douyin store + index to KB
    """
    from rag_system.competitive.downloader import extract_keyframes
    from rag_system.competitive.visual_analyzer import analyze_visual, analyze_keyframes
    from rag_system.competitive.script_analyzer import deep_analyze, analyze_transcript
    from rag_system.competitive.paid_traffic_detector import (
        detect_paid_traffic, extract_comments_from_mediacrawler,
    )

    vid = video.video_id

    if vid in progress.get("completed_videos", []):
        logger.info(f"  [{idx}/{total}] Already completed, skipping")
        return None

    title = video.title[:60]
    creator = video.creator_name
    logger.info(f"[{idx}/{total}] {title} ({creator})")

    date_str = datetime.now().strftime("%Y%m%d")
    safe_creator = "".join(c for c in creator[:15] if c.isalnum() or c in ('_', '-'))
    session_dir = DOUYIN_SESSIONS_DIR / f"{date_str}_{category}_{safe_creator}"
    session_dir.mkdir(parents=True, exist_ok=True)

    # Save metadata
    (session_dir / "metadata.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── Step 1: Find video file ──
    video_path = find_video_file(vid)
    if not video_path:
        logger.info(f"  Video not in MediaCrawler cache, trying yt-dlp...")
        video_path = _download_via_url(raw, session_dir)

    # ── Step 2: Keyframes (1s interval for short-form Douyin videos) ──
    keyframe_paths = []
    if video_path:
        kf_dir = session_dir / "keyframes"
        keyframe_paths = extract_keyframes(video_path, kf_dir, interval_sec=1)
        logger.info(f"  Keyframes: {len(keyframe_paths)}")
    else:
        logger.warning(f"  No video file available for {vid} — analysis will be description-only")

    # ── Step 3: Shot detection ──
    visual = {}
    if video_path:
        visual = analyze_visual(video_path)
        (session_dir / "visual.json").write_text(
            json.dumps(visual, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"  Visual: {visual.get('shot_count', 'N/A')} shots, "
                     f"{visual.get('cuts_per_minute', 'N/A')} cpm")

    # ── Step 4: VLM frame analysis ──
    visual_frames_analysis = ""
    transcript_hint = raw.get("desc", "") or video.title
    if keyframe_paths and len(keyframe_paths) >= 2:
        visual_frames_analysis = analyze_keyframes(
            keyframe_dir=session_dir / "keyframes",
            transcript=transcript_hint,
            category=category,
            video_title=title,
        )
        if visual_frames_analysis:
            (session_dir / "visual_frames_analysis.txt").write_text(
                visual_frames_analysis, encoding="utf-8")

    # ── Step 5: Build transcript ──
    # Douyin doesn't have CC subtitles. Use:
    #   1. VLM frame analysis text (richest signal)
    #   2. Description from MediaCrawler
    #   3. Reconstructed via DeepSeek from visual + description
    if visual_frames_analysis and len(visual_frames_analysis) > 100:
        # VLM analysis is rich enough to serve as transcript hint
        transcript_body = visual_frames_analysis[:3000]
        transcript_source = "vlm_frames"
    else:
        transcript_body = raw.get("desc", f"抖音{category}科普: {title}")
        transcript_source = "description"

    # If we have very little text, try visual reconstruction
    if len(transcript_body) < 200 and video_path:
        try:
            from rag_system.competitive.transcriber import reconstruct_from_visual
            reconstructed = reconstruct_from_visual(
                video_description=transcript_body,
                frame_analyses=visual_frames_analysis,
                category=category,
                video_title=title,
            )
            if reconstructed and len(reconstructed) > len(transcript_body):
                transcript_body = reconstructed
                transcript_source = "visual_reconstruction"
        except Exception as e:
            logger.debug(f"  Visual reconstruction skipped: {e}")

    (session_dir / "transcript.txt").write_text(transcript_body, encoding="utf-8")
    logger.info(f"  Transcript [{transcript_source}]: {len(transcript_body)} chars")

    # ── Step 6: Statistical analysis ──
    result = analyze_transcript(video, transcript_body)
    logger.info(f"  Hook: {result.hook_type} | Spoken: {result.spoken_density:.1f}")

    # ── Step 7: DeepSeek 4-dim deep analysis (Douyin prompt) ──
    logger.info(f"  DeepSeek 4-dim analysis (Douyin platform)...")
    deep = deep_analyze(
        transcript=transcript_body,
        category=category,
        video_title=title,
        hook_type=result.hook_type,
        visual=visual,
        visual_frames_analysis=visual_frames_analysis,
        audio={},
        platform="douyin",
    )
    if deep.get("deep_analysis"):
        result.standout_patterns.append("LLM四维度深度解读已完成")
        result._deep_analysis = deep["deep_analysis"]
        (session_dir / "deep_analysis.txt").write_text(deep["deep_analysis"], encoding="utf-8")
        logger.info(f"  Deep analysis: {len(deep['deep_analysis'])} chars")

    # ── Step 8: Paid traffic detection (non-blocking) ──
    if run_paid_check:
        try:
            comments = extract_comments_from_mediacrawler(vid)
            if comments and len(comments) >= 5:
                paid_result = detect_paid_traffic(
                    video_content=transcript_body,
                    comments=comments,
                    video_title=title,
                )
                if paid_result:
                    result._paid_traffic_check = paid_result
                    if paid_result.is_suspected_paid:
                        logger.warning(
                            f"  ⚠ 疑似投流: {paid_result.related_comment_pct:.0%} 评论相关, "
                            f"{paid_result.rationale[:80]}"
                        )
            else:
                logger.debug(f"  Skipping paid check: insufficient comments ({len(comments) if comments else 0})")
        except Exception as e:
            logger.debug(f"  Paid traffic check skipped (error): {e}")

    # ── Step 9: Store + Index ──
    save_douyin_analysis(result)
    _index_to_knowledge_base(result, video)
    _mark_video_done(progress, vid)

    return {
        "title": video.title,
        "creator": video.creator_name,
        "views": video.views,
        "likes": video.likes,
        "hook_type": result.hook_type,
        "spoken_density": result.spoken_density,
        "patterns": result.standout_patterns,
        "transcript_source": transcript_source,
    }


def _index_to_knowledge_base(result: AnalysisResult, video: VideoProfile):
    """Index analyzed Douyin video into the knowledge base."""
    try:
        from rag_system.embedding.embedder import Embedder
        from rag_system.storage.vector_store import VectorStore
        from rag_system.chunking.splitter import split_text

        chunk_text = f"""【竞品标杆·抖音】{video.title}
创作者: {video.creator_name} | 播放量: {video.views:,} | 点赞: {video.likes:,}
品类: {video.category} | 钩子类型: {result.hook_type}
口语密度: {result.spoken_density:.1f}/百字
亮点模式: {', '.join(result.standout_patterns) if result.standout_patterns else '无'}
口播摘要: {result.transcript[:800]}"""

        chunks = split_text(chunk_text, chunk_size=600, chunk_overlap=60)
        embedder = Embedder()
        store = VectorStore()

        store.upsert_chunks([{
            "id": f"competitive_douyin_{video.video_id}_{ci}",
            "embedding": embedder.embed_documents([chunk])[0],
            "document": chunk,
            "metadata": {
                "source_file": video.title[:50],
                "persona": "competitive",
                "category": video.category,
                "source": "douyin",
                "is_competitive": "true",
                "views": video.views,
                "hook_type": result.hook_type,
            },
        } for ci, chunk in enumerate(chunks)])
        logger.info(f"  KB indexed: {len(chunks)} chunks for {video.title[:30]}...")
    except Exception as e:
        logger.warning(f"  KB indexing failed (non-fatal): {e}")


# ═══════════════════════════════════════════
# Category-level pipeline
# ═══════════════════════════════════════════

def _extract_comments_for_video(raw: dict) -> list[str]:
    """Extract comments for a single video from MediaCrawler data.

    Try the in-memory comments field first (if MediaCrawler embedded them),
    then fall back to the JSON file search.
    """
    # Try embedded comments first
    embedded = raw.get("comments", [])
    if embedded and isinstance(embedded, list):
        texts = []
        for c in embedded:
            if isinstance(c, dict):
                t = c.get("text", "") or c.get("content", "") or ""
            elif isinstance(c, str):
                t = c
            else:
                continue
            if t.strip():
                texts.append(t.strip())
        if texts:
            return texts
    # If embedded is a string (e.g. double-serialized JSON), don't iterate it
    elif embedded and isinstance(embedded, str):
        pass  # Fall through to file search

    # Fall back to JSON file search
    from rag_system.competitive.paid_traffic_detector import extract_comments_from_mediacrawler
    aweme_id = str(raw.get("aweme_id", ""))
    if aweme_id:
        return extract_comments_from_mediacrawler(aweme_id)
    return []


def run_douyin_pipeline(category: str, top_n: int = 2, resume: bool = True) -> list[dict]:
    """Full Douyin competitive pipeline for one category.

    Reads MediaCrawler data, maps videos to the given category, and runs
    the cloud analysis chain on the top N videos by engagement.
    """
    logger.info(f"=== 抖音竞品管线: {category} (Top {top_n}) ===")

    progress = _load_progress() if resume else {"completed_videos": [], "completed_categories": []}

    # Read MediaCrawler data
    all_raw = read_mediacrawler_results()
    if not all_raw:
        logger.warning("No MediaCrawler results found. Run MediaCrawler first:")
        logger.warning("  cd MediaCrawler && uv run python main.py")
        return []

    # Filter to category
    relevant = []
    for raw in all_raw:
        keyword = raw.get("source_keyword", "")
        for cat_kw in DOUYIN_CATEGORY_KEYWORDS.get(category, []):
            if cat_kw in keyword:
                relevant.append(raw)
                break

    if not relevant:
        logger.warning(f"No videos found for category '{category}' in MediaCrawler data. "
                       f"Available keywords: {[k[:30] for k in DOUYIN_CATEGORY_KEYWORDS.get(category, [])]}")
        _mark_category_done(progress, category)
        return []

    # ── Quality gate: recency + engagement ──
    from rag_system.competitive.quality_gate import (
        check_quality, check_recency, pre_filter_paid_traffic, QUALITY_GATES,
    )
    qualified = []
    skipped_low_quality = []
    for r in relevant:
        meta = {
            "liked_count": int(r.get("liked_count", 0)),
            "comment_count": int(r.get("comment_count", 0)),
            "share_count": int(r.get("share_count", 0)),
            "collected_count": int(r.get("collected_count", 0)),
            "create_time": r.get("create_time", ""),
        }
        passed, reason = check_quality(meta, "douyin")
        if not passed:
            skipped_low_quality.append(f"{r.get('title', '?')[:30]} ({reason})")
            continue
        qualified.append(r)

    if skipped_low_quality:
        logger.info(f"  ⚠️ 质量过滤: 跳过 {len(skipped_low_quality)} 个（含超14天旧视频）")
        for skip_msg in skipped_low_quality[:5]:
            logger.info(f"     ✗ {skip_msg}")

    if not qualified:
        logger.warning(f"No qualifying videos for '{category}' after quality filter "
                       f"(门槛: {QUALITY_GATES['douyin']['min_likes']:,}点赞, "
                       f"{QUALITY_GATES['douyin']['min_engagement_pct']}%互动率, "
                       f"≤{QUALITY_GATES['douyin']['max_age_days']}天)")
        _mark_category_done(progress, category)
        return []

    # Sort by engagement descending
    qualified.sort(key=lambda r: int(r.get("liked_count", 0)) + int(r.get("comment_count", 0)), reverse=True)
    logger.info(f"质量过关: {len(qualified)} 个视频（已过滤低质+超14天旧视频）")

    # ── Paid traffic pre-filter: check top 5 candidates ──
    CANDIDATE_POOL = 5
    qualified = pre_filter_paid_traffic(
        candidates=qualified,
        fetch_comments_fn=lambda v: _extract_comments_for_video(v),
        source="douyin",
        max_candidates=CANDIDATE_POOL,
    )

    # Take top_n from remaining clean candidates
    relevant = qualified[:top_n]

    if not relevant:
        logger.warning(f"No videos remain for '{category}' after paid-traffic filter "
                       f"— 所有候选均疑似投流，跳过此品类")
        _mark_category_done(progress, category)
        return []

    logger.info(f"最终选取 {len(relevant)} 个抖音视频分析 {category} "
                f"(从{len(qualified)}个自然流量候选中取top{top_n})")

    results = []
    failures = []
    for i, raw in enumerate(relevant):
        try:
            video = build_video_profile(raw, category)
            r = _process_one_douyin_video(
                video=video, raw=raw, category=category,
                idx=i + 1, total=len(relevant), progress=progress,
                run_paid_check=True,
            )
            if r:
                results.append(r)
                logger.info(f"  ✓ [{r.get('hook_type', '?')}] {r['title'][:40]} | "
                             f"{r['creator']} | {r.get('transcript_source', '?')}")
        except Exception as e:
            logger.error(f"  ✗ Failed: {raw.get('title', '?')[:40]}... — {e}")
            failures.append({"title": raw.get("title", "?"), "creator": raw.get("nickname", "?"), "error": str(e)})
            continue

    if failures:
        logger.warning(f"⚠ {len(failures)}/{len(relevant)} Douyin videos failed: "
                        f"{', '.join(f['title'][:30] for f in failures)}")

    # Wiki compilation
    try:
        sessions = sorted(DOUYIN_SESSIONS_DIR.glob(f"*_{category}_*"),
                         key=lambda p: p.stat().st_mtime, reverse=True)
        if sessions:
            from rag_system.competitive.wiki_compiler import compile_to_wiki
            compile_to_wiki(sessions[0], category)
            logger.info(f"Douyin wiki updated for {category}")
    except Exception as e:
        logger.warning(f"Douyin wiki compile failed for {category}: {e}")

    _mark_category_done(progress, category)
    logger.info(f"=== Douyin {category}: {len(results)}/{len(relevant)} ===")
    return results


# ═══════════════════════════════════════════
# All-categories scheduler
# ═══════════════════════════════════════════

def run_douyin_all_categories(
    resume: bool = True, generate_report: bool = True,
) -> dict:
    """Run Douyin pipeline for all 8 categories sequentially.

    Returns summary dict with per-category results and total stats.
    """
    start_time = time.time()
    progress = _load_progress() if resume else {"completed_videos": [], "completed_categories": []}

    logger.info("=" * 60)
    logger.info("  抖音竞品学习管线 — 全品类顺序调度")
    logger.info(f"  品类: {len(ALL_CATEGORIES)} | 每品类: {TOP_N}视频")
    logger.info(f"  数据源: MediaCrawler → {DATA_DIR}")
    logger.info("=" * 60)

    all_results = {}
    total_success = 0
    failed_categories = []

    for ci, category in enumerate(ALL_CATEGORIES):
        if category in progress.get("completed_categories", []):
            logger.info(f"\n[{ci+1}/{len(ALL_CATEGORIES)}] {category} — 已完成，跳过")
            continue

        logger.info(f"\n{'─' * 50}")
        logger.info(f"[{ci+1}/{len(ALL_CATEGORIES)}] 品类: {category}")
        logger.info(f"{'─' * 50}")

        try:
            results = run_douyin_pipeline(category=category, top_n=TOP_N, resume=resume)
            all_results[category] = results
            total_success += len(results)

            elapsed = time.time() - start_time
            remaining_cats = len(ALL_CATEGORIES) - (ci + 1)
            est_remaining = (elapsed / (ci + 1)) * remaining_cats if ci > 0 else 0
            logger.info(f"  {category}: {len(results)}/{TOP_N} 成功 | "
                         f"耗时: {elapsed/60:.0f}min | 预计剩余: {est_remaining/60:.0f}min")

        except Exception as e:
            logger.error(f"  {category} 品类失败: {e}")
            failed_categories.append(category)
            all_results[category] = []

        if ci < len(ALL_CATEGORIES) - 1:
            time.sleep(3)

    total_time = time.time() - start_time

    # ── Summary ──
    logger.info("\n" + "=" * 60)
    logger.info(f"  抖音全品类竞品分析完成")
    logger.info(f"  MediaCrawler数据: {len(read_mediacrawler_results())}条原始视频")
    logger.info(f"  成功分析: {total_success} 视频")
    logger.info(f"  耗时: {total_time/60:.1f} 分钟")
    if failed_categories:
        logger.info(f"  失败品类: {', '.join(failed_categories)}")
    logger.info("=" * 60)

    # ── Generate report ──
    report_path = None
    if generate_report and total_success > 0:
        try:
            from rag_system.competitive.reporter import generate_docx_report
            logger.info("生成抖音竞品学习周报...")
            report_path = generate_docx_report(period="weekly", source="douyin")
            logger.info(f"抖音周报已保存: {report_path}")
        except Exception as e:
            logger.error(f"Douyin report generation failed: {e}")

    return {
        "categories": ALL_CATEGORIES,
        "total_videos_attempted": len(ALL_CATEGORIES) * TOP_N,
        "total_videos_success": total_success,
        "failed_categories": failed_categories,
        "duration_minutes": round(total_time / 60, 1),
        "report_path": str(report_path) if report_path else None,
        "per_category": {cat: len(results) for cat, results in all_results.items()},
    }


# ═══════════════════════════════════════════
# CLI entry
# ═══════════════════════════════════════════

if __name__ == "__main__":
    resume = "--no-resume" not in sys.argv
    report_only = "--report" in sys.argv

    # Check for --category flag
    category = None
    for i, arg in enumerate(sys.argv):
        if arg == "--category" and i + 1 < len(sys.argv):
            category = sys.argv[i + 1]
            break

    if report_only:
        from rag_system.competitive.reporter import generate_docx_report
        path = generate_docx_report(period="weekly", source="douyin")
        if path:
            print(f"Report: {path}")
    elif category:
        results = run_douyin_pipeline(category=category, top_n=TOP_N, resume=resume)
        print(f"\nDouyin {category}: {len(results)} videos analyzed")
    else:
        summary = run_douyin_all_categories(resume=resume, generate_report=True)
        print("\n" + "=" * 60)
        print("  抖音竞品管线完成")
        print(f"  成功: {summary['total_videos_success']}")
        print(f"  耗时: {summary['duration_minutes']} 分钟")
        if summary["report_path"]:
            print(f"  周报: {summary['report_path']}")
        if summary["failed_categories"]:
            print(f"  失败品类: {', '.join(summary['failed_categories'])}")
        print("=" * 60)
