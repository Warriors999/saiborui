"""Paid traffic detection — implement D先生's comment-content similarity rule.

Rule from 选题批注原文.md §84:
  "扒取爆款时要关注评论——如果评论和视频内容高度一致就可以直接扒取；
   如果大部分评论与视频内容关联不相干，就要考虑是不是投流的结果，
   那么就要考虑选题真实的吸引度"

Strategy:
  1. Fetch up to N comments from the video
  2. Use DeepSeek to classify each as related/unrelated to video content
  3. If <30% comments are related → flag as suspected paid traffic
  4. Non-blocking: failures are logged but don't stop the pipeline
"""

import json
import hashlib
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from rag_system.utils import logger

MEDIACRAWLER_DIR = Path("MediaCrawler")
DOUYIN_DATA_DIR = MEDIACRAWLER_DIR / "data/douyin"


@dataclass
class PaidTrafficResult:
    """Result of paid traffic detection for one video."""
    is_suspected_paid: bool = False
    similarity_score: float = 0.0          # 0.0-1.0, average semantic similarity
    related_comment_pct: float = 0.0        # % of comments judged related to video
    unrelated_comment_pct: float = 0.0      # % judged unrelated
    rationale: str = ""
    sample_unrelated: list[str] = field(default_factory=list)
    sample_related: list[str] = field(default_factory=list)
    checked_at: str = ""


def detect_paid_traffic(
    video_content: str,
    comments: list[str],
    video_title: str = "",
    max_comments: int = 30,
    similarity_threshold: float = 0.3,
) -> PaidTrafficResult:
    """Detect if a video likely used paid promotion based on comment-content similarity.

    Args:
        video_content: Transcript or description of the video
        comments: List of comment text strings
        video_title: Video title for context
        max_comments: Maximum number of comments to sample
        similarity_threshold: Fraction below which content is flagged (default 0.3)

    Returns:
        PaidTrafficResult with classification and evidence
    """
    result = PaidTrafficResult(checked_at=datetime.now().isoformat())

    if not comments:
        result.rationale = "No comments available for analysis"
        return result

    # Sample comments
    sample = comments[:max_comments]
    if len(sample) < 5:
        result.rationale = f"Too few comments ({len(sample)}) for reliable classification"
        return result

    # Prepare content summary (title + first 600 chars of transcript)
    content_summary = f"标题: {video_title}\n内容: {video_content[:600]}"

    # Use DeepSeek to classify each comment
    try:
        classification = _classify_comments_via_llm(content_summary, sample)
    except Exception as e:
        logger.warning(f"Paid traffic LLM classification failed: {e}")
        result.rationale = f"Classification error: {e}"
        return result

    if not classification:
        result.rationale = "LLM returned empty classification"
        return result

    related = [c for c in classification if c.get("related")]
    unrelated = [c for c in classification if not c.get("related")]

    total = len(classification)
    result.related_comment_pct = len(related) / total
    result.unrelated_comment_pct = len(unrelated) / total
    result.similarity_score = result.related_comment_pct
    result.is_suspected_paid = result.related_comment_pct < similarity_threshold

    result.sample_related = [c["text"][:100] for c in related[:5]]
    result.sample_unrelated = [c["text"][:100] for c in unrelated[:5]]

    if result.is_suspected_paid:
        result.rationale = (
            f"仅 {result.related_comment_pct:.0%} 的评论与视频内容相关，"
            f"远低于阈值 {similarity_threshold:.0%}。大部分评论为通用模板/表情/无关话题，"
            f"高度疑似投流（付费推广）数据。该选题的真实吸引力存疑。"
        )
    else:
        result.rationale = (
            f"{result.related_comment_pct:.0%} 评论与内容相关，"
            f"评论-内容一致性正常，大概率是自然流量。"
        )

    logger.info(
        f"  投流检测: {'⚠ 疑似投流' if result.is_suspected_paid else '✓ 自然流量'} "
        f"({result.related_comment_pct:.0%} 相关, {total}条评论)"
    )
    return result


def _classify_comments_via_llm(content_summary: str, comments: list[str]) -> list[dict]:
    """Use DeepSeek to classify each comment as related/unrelated to video content.

    Single API call classifies all comments at once for efficiency.
    """
    from openai import OpenAI
    from rag_system.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DeepSeek API key not configured")

    # Build numbered comment list
    numbered = "\n".join(f"{i+1}. {c[:200]}" for i, c in enumerate(comments))

    prompt = f"""你是社交媒体内容审核员。判断每条评论是否与视频内容相关。

视频内容摘要:
{content_summary}

以下30条评论，逐条判断"相关"或"无关"：
{numbered}

判断标准:
- "相关": 评论讨论视频内容、提出问题、补充信息、表达认同/反对观点、分享相关经历
- "无关": 纯表情/符号、模板式回复(如"学到了""打卡""第一")、与视频主题完全无关的闲聊、明显的机器人评论

输出严格JSON数组，不要额外文字:
[{{"id": 1, "text": "评论原文", "related": true, "reason": "一句话理由"}}, ...]"""

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=2000,
    )

    text = response.choices[0].message.content.strip()

    # Extract JSON array from response
    json_start = text.find("[")
    json_end = text.rfind("]") + 1
    if json_start >= 0 and json_end > json_start:
        return json.loads(text[json_start:json_end])

    raise ValueError(f"Cannot parse LLM response as JSON array: {text[:200]}")


# ── B站 comment fetching (WBI-signed API) ──

# WBI mixin key table (same as searcher.py)
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

_wbi_cache: dict = {"img_key": "", "sub_key": "", "expires": 0}
_BUVID_CACHE: dict = {"buvid3": "", "expires": 0}


def _get_mixin_key() -> str:
    """Get WBI mixin key, reusing cached keys when valid."""
    now = time.time()
    if _wbi_cache["expires"] > now:
        return _hash_mixin(_wbi_cache["img_key"], _wbi_cache["sub_key"])

    try:
        req = urllib.request.Request(
            "https://api.bilibili.com/x/web-interface/nav",
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            wbi = data["data"]["wbi_img"]
            _wbi_cache["img_key"] = wbi["img_url"].split("/")[-1].split(".")[0]
            _wbi_cache["sub_key"] = wbi["sub_url"].split("/")[-1].split(".")[0]
            _wbi_cache["expires"] = now + 3600  # 1 hour
    except Exception as e:
        logger.warning(f"WBI key fetch failed: {e}")
        return ""

    return _hash_mixin(_wbi_cache["img_key"], _wbi_cache["sub_key"])


def _hash_mixin(img_key: str, sub_key: str) -> str:
    """Compute mixin key from img_key + sub_key."""
    s = img_key + sub_key
    return "".join(s[i] for i in MIXIN_KEY_ENC_TAB if i < len(s))[:32]


def _sign_params(params: dict) -> dict:
    """WBI-sign a parameter dict."""
    mixin_key = _get_mixin_key()
    if not mixin_key:
        return params

    params["wts"] = str(int(time.time()))
    sorted_params = sorted(params.items(), key=lambda x: x[0])
    query = "&".join(f"{k}={v}" for k, v in sorted_params)
    sign_str = query + mixin_key
    params["w_rid"] = hashlib.md5(sign_str.encode()).hexdigest()
    return params


def fetch_bilibili_comments(video_id: str, max_comments: int = 30) -> list[str]:
    """Fetch B站 video comments via WBI-signed API.

    Args:
        video_id: B站 aid (av号) or bvid
        max_comments: Maximum comments to fetch

    Returns:
        List of comment text strings
    """
    try:
        # Determine oid: if video_id is numeric, it's aid; otherwise bvid
        oid = video_id
        params = {"type": "1", "oid": oid, "ps": str(max_comments), "sort": "1"}
        params = _sign_params(params)

        query = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"https://api.bilibili.com/x/v2/reply?{query}"

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.bilibili.com/",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if data.get("code") != 0:
            logger.debug(f"B站 comment API returned code {data.get('code')}: {data.get('message')}")
            return []

        replies = data.get("data", {}).get("replies", [])
        comments = []
        for r in replies:
            msg = r.get("content", {}).get("message", "")
            if msg and len(msg) > 1:
                comments.append(msg)

        logger.info(f"  Fetched {len(comments)} B站 comments for {video_id}")
        return comments

    except Exception as e:
        logger.debug(f"B站 comment fetch failed for {video_id}: {e}")
        return []


def extract_comments_from_mediacrawler(aweme_id: str) -> list[str]:
    """Extract comment text for a specific aweme_id from MediaCrawler comment JSON.

    Searches the latest search_comments_*.json file for matching aweme_id.
    """
    json_dir = DOUYIN_DATA_DIR / "json"
    if not json_dir.exists():
        return []

    comment_files = sorted(json_dir.glob("search_comments_*.json"), reverse=True)
    if not comment_files:
        return []

    try:
        with open(comment_files[0], "r", encoding="utf-8") as f:
            data = json.load(f)

        comments = []
        # Data may be a list of videos with their comments
        items = data if isinstance(data, list) else data.get("data", [])
        for item in items:
            if str(item.get("aweme_id", "")) == str(aweme_id):
                # Comment list varies by MediaCrawler version
                for c in item.get("comments", []) or []:
                    text = c.get("text", "") or c.get("content", "") or ""
                    if text.strip():
                        comments.append(text.strip())
                break

        if comments:
            logger.info(f"  Found {len(comments)} MediaCrawler comments for {aweme_id}")
        return comments

    except Exception as e:
        logger.debug(f"MediaCrawler comment read failed for {aweme_id}: {e}")
        return []
