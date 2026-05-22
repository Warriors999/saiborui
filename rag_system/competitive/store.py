"""Persist competitive analysis results as JSON reports."""

import json
from datetime import datetime
from pathlib import Path

from rag_system.competitive.models import VideoProfile, AnalysisResult, WeeklyReport
from rag_system.utils import logger

REPORTS_DIR = Path("output/competitive/reports")
DATA_FILE = Path("output/competitive/analyzed_videos.json")


def save_analysis(result: AnalysisResult) -> Path:
    """Save a single analysis result, appending to the cumulative JSON file."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    result.analyzed_at = datetime.now().isoformat()

    # Load existing data
    existing = []
    if DATA_FILE.exists():
        try:
            existing = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = []

    # Serialize
    entry = {
        "video_id": result.video.video_id,
        "title": result.video.title,
        "url": result.video.url,
        "source": result.video.source,
        "creator": result.video.creator_name,
        "category": result.video.category,
        "views": result.video.views,
        "hook_type": result.hook_type,
        "hook_text": result.hook_text,
        "spoken_density": round(result.spoken_density, 2),
        "attitude_density": round(result.attitude_density, 2),
        "short_sentence_pct": round(result.short_sentence_pct, 1),
        "standout_patterns": result.standout_patterns,
        "analyzed_at": result.analyzed_at,
    }

    existing.append(entry)
    DATA_FILE.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Saved analysis for {result.video.title[:30]}...")
    return DATA_FILE


def get_analyzed_videos(category: str = "") -> list[dict]:
    """Get all analyzed videos, optionally filtered by category."""
    if not DATA_FILE.exists():
        return []
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
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
