"""Data models for competitive video analysis."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class VideoProfile:
    video_id: str
    title: str
    url: str
    source: str                    # "bilibili" or "douyin"
    creator_name: str
    creator_id: str = ""
    duration_sec: int = 0
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    publish_date: str = ""
    category: str = ""             # keyboard/mouse/monitor/...
    tags: list[str] = field(default_factory=list)
    description: str = ""
    thumbnail_url: str = ""


@dataclass
class AnalysisResult:
    video: VideoProfile
    transcript: str = ""           # full voiceover text
    transcript_chars: int = 0

    # Hook analysis
    hook_type: str = ""            # 情绪爆发/热梗共鸣/数字冲击/场景痛点/反常识
    hook_text: str = ""            # first 3 seconds of transcript
    hook_effectiveness: float = 0.0  # 0-1 score

    # Narrative structure
    narrative_arc: str = ""        # detected 6-part arc
    act_boundaries: list[int] = field(default_factory=list)  # character offsets

    # Writing quality (from auditor)
    spoken_density: float = 0.0    # colloquial markers per 100 chars
    attitude_density: float = 0.0  # subjective judgments per 200 chars
    short_sentence_pct: float = 0.0
    long_sentence_pct: float = 0.0
    forbidden_word_count: int = 0
    ecommerce_smell_count: int = 0

    # Visual analysis
    shot_count: int = 0            # detected scene changes
    avg_shot_duration: float = 0.0 # seconds per shot
    shot_rhythm_variance: float = 0.0  # variance in shot duration

    # Key learnings
    standout_patterns: list[str] = field(default_factory=list)  # unique techniques
    applicable_to_categories: list[str] = field(default_factory=list)

    analyzed_at: str = ""


@dataclass
class WeeklyReport:
    period_start: str
    period_end: str
    videos_analyzed: int = 0
    top_creators: list[str] = field(default_factory=list)
    trending_hook_types: dict = field(default_factory=dict)
    category_insights: dict = field(default_factory=dict)
    new_patterns_discovered: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
