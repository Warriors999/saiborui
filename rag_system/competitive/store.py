"""Persist competitive analysis results as JSON reports."""

import json
from datetime import datetime
from pathlib import Path

from rag_system.competitive.models import VideoProfile, AnalysisResult, WeeklyReport
from rag_system.utils import logger

REPORTS_DIR = Path("output/competitive/reports")
DATA_FILE = Path("output/competitive/analyzed_videos.json")
DOUYIN_DATA_FILE = Path("output/competitive/analyzed_douyin_videos.json")


def _save_analysis_to(data_file: Path, result: AnalysisResult) -> Path:
    """Shared helper: append analysis result to a cumulative JSON file."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    result.analyzed_at = datetime.now().isoformat()

    existing = []
    if data_file.exists():
        try:
            existing = json.loads(data_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = []

    deep_text = getattr(result, '_deep_analysis', '')
    paid_check = getattr(result, '_paid_traffic_check', None)
    if paid_check and hasattr(paid_check, '__dict__'):
        paid_check = paid_check.__dict__

    entry = {
        "video_id": result.video.video_id,
        "title": result.video.title,
        "url": result.video.url,
        "source": result.video.source,
        "creator": result.video.creator_name,
        "category": result.video.category,
        "views": result.video.views,
        "likes": result.video.likes,
        "comments": result.video.comments,
        "shares": result.video.shares,
        "hook_type": result.hook_type,
        "hook_text": result.hook_text,
        "spoken_density": round(result.spoken_density, 2),
        "attitude_density": round(result.attitude_density, 2),
        "short_sentence_pct": round(result.short_sentence_pct, 1),
        "standout_patterns": result.standout_patterns,
        "deep_analysis": deep_text,
        "transcript_preview": result.transcript[:500] if result.transcript else "",
        "paid_traffic_check": paid_check,
        "analyzed_at": result.analyzed_at,
    }

    existing.append(entry)
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Saved analysis for {result.video.title[:30]}... -> {data_file.name}")
    return data_file


def save_analysis(result: AnalysisResult) -> Path:
    """Save a B站 analysis result, appending to the cumulative JSON file."""
    return _save_analysis_to(DATA_FILE, result)


def save_douyin_analysis(result: AnalysisResult) -> Path:
    """Save a Douyin analysis result to its own cumulative JSON file."""
    return _save_analysis_to(DOUYIN_DATA_FILE, result)


def get_analyzed_videos(category: str = "") -> list[dict]:
    """Get all B站 analyzed videos, optionally filtered by category."""
    if not DATA_FILE.exists():
        return []
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    if category:
        return [d for d in data if d.get("category") == category]
    return data


def get_analyzed_douyin_videos(category: str = "") -> list[dict]:
    """Get all Douyin analyzed videos, optionally filtered by category."""
    if not DOUYIN_DATA_FILE.exists():
        return []
    data = json.loads(DOUYIN_DATA_FILE.read_text(encoding="utf-8"))
    if category:
        return [d for d in data if d.get("category") == category]
    return data


def save_report(report: WeeklyReport) -> Path:
    """Save a weekly/monthly report."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"report_{report.period_start}_{report.period_end}.json"
    path = REPORTS_DIR / filename

    data = {
        "period": f"{report.period_start} ~ {report.period_end}",
        "videos_analyzed": report.videos_analyzed,
        "top_creators": report.top_creators,
        "trending_hook_types": report.trending_hook_types,
        "category_insights": report.category_insights,
        "new_patterns": report.new_patterns_discovered,
        "recommendations": report.recommendations,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Report saved: {path}")
    return path
