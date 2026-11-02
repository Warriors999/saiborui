"""Quality gate for competitive video selection — filter before analysis, not after.

Shared by scheduler.py and douyin_search_pipeline.py. Keep it simple to avoid circular imports.

Weekly-hot prioritization: filters out old videos (>14 days), prioritizes recent
high-engagement content over historical evergreen.

Paid-traffic pre-filter: runs comment-content similarity check BEFORE deep analysis,
so we don't waste resources analyzing promoted videos.
"""

from datetime import datetime, timedelta

# Minimum thresholds per platform. Videos below these are skipped entirely.
# Note: MediaCrawler Douyin data does NOT include play_count. Use likes as proxy.
QUALITY_GATES: dict[str, dict[str, float]] = {
    "douyin": {
        "min_likes": 500,            # 最低点赞数（无播放量数据，用点赞代理热度）
        "min_engagement_pct": 3.0,    # 最低互动率 (评论+分享+收藏)/点赞 * 100
        "max_age_days": 14,           # 只看近两周发布的视频
    },
    "bilibili": {
        "min_views": 1_000,         # 周热门门槛：近14天B站视频达到4位数播放即有关注度
        "min_engagement_pct": 0.8,   # 互动率(收藏+弹幕)/播放（搜索API无私有点赞，用收藏代理；周热门允许偏低）
        "max_age_days": 14,           # 只看近两周发布的视频
    },
}

# Paid traffic detection threshold — if < this fraction of comments relate
# to video content, the video is flagged as likely paid promotion
PAID_TRAFFIC_SIMILARITY_THRESHOLD = 0.3


def check_quality(video_meta: dict, source: str) -> tuple[bool, str]:
    """Check if a video meets quality thresholds. Returns (passed, reason).

    Handles both MediaCrawler field names and standard field names.
    Douyin: no play_count → uses liked_count as heat proxy.
    Bilibili: uses views/play_count as primary heat signal.

    Also checks recency: rejects videos older than max_age_days.
    """
    gate = QUALITY_GATES.get(source)
    if not gate:
        return True, ""

    views = int(video_meta.get("views", video_meta.get("play_count", 0)))
    likes = int(video_meta.get("likes", video_meta.get("liked_count", 0)))
    comments = int(video_meta.get("comments", video_meta.get("comment_count", 0)))
    shares = int(video_meta.get("shares", video_meta.get("share_count", 0)))
    collects = int(video_meta.get("collected_count", 0))

    # ── Recency check (shared) ──
    max_age = gate.get("max_age_days", 14)
    pub_date_str = str(video_meta.get("publish_date", video_meta.get("create_time", "")))
    if pub_date_str and max_age > 0:
        try:
            pub_date = _parse_date(pub_date_str)
            if pub_date:
                age_days = (datetime.now() - pub_date).days
                if age_days > max_age:
                    return False, f"发布时间{age_days}天前 > 门檻{max_age}天"
        except (ValueError, TypeError):
            pass  # Can't parse date, let it through

    if source == "douyin":
        # Douyin: use likes as primary signal (no play_count in MediaCrawler data)
        if likes < gate.get("min_likes", 0):
            return False, f"点赞{likes} < 门槛{gate['min_likes']}"
        engagement = (comments + shares + collects) / max(likes, 1) * 100
        if engagement < gate.get("min_engagement_pct", 0):
            return False, f"互动率{engagement:.1f}% < 门槛{gate['min_engagement_pct']}%"
        return True, f"点赞{likes:,} 互动率{engagement:.1f}%"

    # Bilibili: use views as primary signal
    if views < gate.get("min_views", 0):
        return False, f"播放量{views:,} < 门槛{gate['min_views']:,}"
    engagement = (likes + comments + shares) / max(views, 1) * 100
    if engagement < gate.get("min_engagement_pct", 0):
        return False, f"互动率{engagement:.1f}% < 门槛{gate['min_engagement_pct']}%"

    return True, f"播放{views:,} 互动率{engagement:.1f}%"


def check_recency(publish_date_str: str, max_age_days: int = 14) -> tuple[bool, str]:
    """Check if a video was published within max_age_days. Returns (is_recent, reason)."""
    if not publish_date_str:
        return True, "无发布日期，放行"
    try:
        pub_date = _parse_date(publish_date_str)
        if not pub_date:
            return True, "日期解析失败，放行"
        age_days = (datetime.now() - pub_date).days
        if age_days <= max_age_days:
            return True, f"{age_days}天前发布，在{max_age_days}天内"
        return False, f"{age_days}天前发布，超过{max_age_days}天门檻"
    except (ValueError, TypeError):
        return True, "日期格式异常，放行"


def pre_filter_paid_traffic(
    candidates: list[dict],
    fetch_comments_fn,
    source: str = "douyin",
    max_candidates: int = 5,
) -> list[dict]:
    """Pre-filter candidates by running paid-traffic detection BEFORE deep analysis.

    For the top `max_candidates` candidates (by engagement), fetches comments and
    runs LLM-based paid traffic detection. Videos flagged as likely paid are excluded.

    Args:
        candidates: List of video metadata dicts, sorted by engagement descending
        fetch_comments_fn: Function(video_meta) -> list[str] to get comments
        source: "douyin" or "bilibili"
        max_candidates: How many top candidates to check (default 5)

    Returns:
        Filtered list with suspected paid videos removed (or marked as _suspected_paid)
    """
    from rag_system.utils import logger

    try:
        from rag_system.competitive.paid_traffic_detector import detect_paid_traffic
    except ImportError as e:
        logger.warning(f"投流检测模块导入失败，跳过预过滤: {e}")
        return candidates

    if not candidates:
        return candidates

    check_pool = candidates[:max_candidates]
    logger.info(f"  投流前置检测: 对前{len(check_pool)}个候选视频进行评论-内容一致性检查...")

    paid_flags = {}  # video_id -> bool
    for i, video in enumerate(check_pool):
        vid = str(video.get("aweme_id", video.get("video_id", "")))
        title = str(video.get("title", ""))[:40]

        try:
            comments = fetch_comments_fn(video)
            if not comments or len(comments) < 5:
                logger.info(f"    [{i+1}/{len(check_pool)}] {title} — 评论不足，跳过检测")
                continue

            result = detect_paid_traffic(
                video_content=str(video.get("desc", video.get("description", title))),
                comments=comments,
                video_title=title,
                max_comments=30,
                similarity_threshold=PAID_TRAFFIC_SIMILARITY_THRESHOLD,
            )

            if result.is_suspected_paid:
                paid_flags[vid] = True
                logger.warning(
                    f"    [{i+1}/{len(check_pool)}] ⚠ {title} — 疑似投流 "
                    f"(评论相关度{result.related_comment_pct:.0%}），从候选池移除"
                )
            else:
                logger.info(
                    f"    [{i+1}/{len(check_pool)}] ✓ {title} — 自然流量 "
                    f"(评论相关度{result.related_comment_pct:.0%})"
                )
        except Exception as e:
            logger.debug(f"    投流检测异常 {title}: {e}")

    # Filter out suspected paid from the full list
    clean = []
    for v in candidates:
        vid = str(v.get("aweme_id", v.get("video_id", "")))
        if vid in paid_flags:
            continue  # Skip suspected paid
        clean.append(v)

    removed = len(candidates) - len(clean)
    if removed > 0:
        logger.info(f"  投流过滤: 移除了 {removed} 个疑似投流视频，剩余 {len(clean)} 个候选")

    return clean


def _parse_date(date_str: str) -> datetime | None:
    """Parse a date string in various formats to datetime."""
    if not date_str:
        return None
    s = str(date_str).strip()
    # Unix timestamp (int/float as string)
    try:
        ts = float(s)
        if ts > 1_000_000_000:  # Looks like a unix timestamp
            return datetime.fromtimestamp(ts)
    except (ValueError, TypeError):
        pass
    # ISO formats — try each, using exact length match
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y%m%d"]:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None
