"""Search Bilibili for top-performing videos by category.

Uses B站 WBI-signed search API (w_rid + wts parameters).
Implements the official img_key/sub_key → mixin_key → MD5 sign flow.
"""

import hashlib
import json
import re
import time
import urllib.request
import urllib.parse
from pathlib import Path

from rag_system.competitive.models import VideoProfile
from rag_system.utils import logger

CATEGORY_SEARCH_QUERIES = {
    "keyboard": ["机械键盘 评测", "磁轴键盘 推荐"],
    "mouse": ["游戏鼠标 评测", "轻量化鼠标"],
    "monitor": ["显示器 评测", "电竞显示器 推荐"],
    "laptop": ["游戏本 评测", "笔记本 推荐"],
    "phone": ["游戏手机 评测", "手机 性能测试"],
    "gpu": ["显卡 评测", "显卡 游戏帧数"],
    "headphone": ["耳机 评测", "降噪耳机 推荐"],
    "desk_chair": ["电竞椅 评测", "升降桌 推荐"],
}

WBI_SEARCH_URL = "https://api.bilibili.com/x/web-interface/wbi/search/type"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52
]

# Cache for WBI keys + buvid3 (valid for ~1 day)
_wbi_cache = {"img_key": "", "sub_key": "", "mixin_key": "", "fetched_at": 0}
_buvid3_cache = {"buvid3": "", "fetched_at": 0}


def _get_buvid3() -> str:
    """Get buvid3 cookie, cached for 12 hours."""
    now = time.time()
    if _buvid3_cache["buvid3"] and (now - _buvid3_cache["fetched_at"]) < 43200:
        return _buvid3_cache["buvid3"]
    try:
        req = urllib.request.Request("https://www.bilibili.com/", headers={"User-Agent": USER_AGENT})
        opener = urllib.request.build_opener()
        resp = opener.open(req, timeout=10)
        for header in resp.headers.get_all("Set-Cookie") or []:
            for part in header.split(";"):
                if "buvid3" in part:
                    _buvid3_cache["buvid3"] = part.split("=")[1].strip()
                    _buvid3_cache["fetched_at"] = now
                    return _buvid3_cache["buvid3"]
    except Exception as e:
        logger.warning(f"Failed to get buvid3: {e}")
    return ""


def _fetch_wbi_keys(buvid3: str = "") -> tuple[str, str]:
    """Fetch img_key and sub_key from B站 nav API. Returns (img_key, sub_key)."""
    now = time.time()
    # Return cached if less than 12 hours old
    if _wbi_cache["mixin_key"] and (now - _wbi_cache["fetched_at"]) < 43200:
        return _wbi_cache["img_key"], _wbi_cache["sub_key"]

    try:
        headers = {"User-Agent": USER_AGENT, "Referer": "https://www.bilibili.com/"}
        if buvid3:
            headers["Cookie"] = f"buvid3={buvid3}"

        req = urllib.request.Request(
            "https://api.bilibili.com/x/web-interface/nav",
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            wbi = data.get("data", {}).get("wbi_img", {})
            img_url = wbi.get("img_url", "")
            sub_url = wbi.get("sub_url", "")
            if not img_url or not sub_url:
                logger.error("WBI keys not found in nav response")
                return "", ""
            img_key = img_url.split("/")[-1].split(".")[0]
            sub_key = sub_url.split("/")[-1].split(".")[0]
            # Compute mixin_key
            raw = img_key + sub_key
            mixin = "".join(raw[i] for i in MIXIN_KEY_ENC_TAB if i < len(raw))[:32]
            _wbi_cache["img_key"] = img_key
            _wbi_cache["sub_key"] = sub_key
            _wbi_cache["mixin_key"] = mixin
            _wbi_cache["fetched_at"] = now
            logger.info(f"WBI keys fetched: {img_key[:8]}... {sub_key[:8]}...")
            return img_key, sub_key
    except Exception as e:
        logger.error(f"Failed to fetch WBI keys: {e}")
        return "", ""


def _wbi_sign(params: dict, buvid3: str = "") -> dict:
    """Add w_rid and wts to params with WBI signature."""
    _fetch_wbi_keys(buvid3)
    mixin_key = _wbi_cache["mixin_key"]
    if not mixin_key:
        return params  # can't sign

    params["wts"] = int(time.time())
    sorted_items = sorted(params.items(), key=lambda x: x[0])
    query_str = urllib.parse.urlencode(sorted_items, quote_via=urllib.parse.quote)
    sign_str = query_str + mixin_key
    params["w_rid"] = hashlib.md5(sign_str.encode("utf-8")).hexdigest()
    return params


def search_bilibili(query: str, top_n: int = 10) -> list[VideoProfile]:
    """Search Bilibili with WBI signature."""
    # Only fetch buvid3 if WBI cache expired (avoids redundant HTTP request)
    buvid3 = _buvid3_cache.get("buvid3", "")
    if not buvid3 or (time.time() - _buvid3_cache.get("fetched_at", 0)) > 43200:
        buvid3 = _get_buvid3()

    params = {"keyword": query, "search_type": "video", "order": "click"}
    params = _wbi_sign(params, buvid3)

    url = f"{WBI_SEARCH_URL}?{urllib.parse.urlencode(params, quote_via=urllib.parse.quote)}"
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://www.bilibili.com/",
    }
    if buvid3:
        headers["Cookie"] = f"buvid3={buvid3}"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.error(f"Search failed: {e}")
        return []

    if data.get("code") != 0:
        logger.error(f"API error {data.get('code')}: {data.get('message', '')}")
        return []

    results = []
    for item in data.get("data", {}).get("result", [])[:top_n]:
        try:
            video = VideoProfile(
                video_id=str(item.get("aid", "")),
                title=_clean_html(item.get("title", "")),
                url=f"https://www.bilibili.com/video/{item.get('bvid', '')}",
                source="bilibili",
                creator_name=item.get("author", ""),
                creator_id=str(item.get("mid", "")),
                duration_sec=_parse_duration(item.get("duration", "0:00")),
                views=item.get("play", 0),
                likes=item.get("favorites", 0),
                comments=item.get("video_review", 0),
                publish_date=_format_date(item.get("pubdate", 0)),
                description=_clean_html(item.get("description", "")),
                tags=_parse_tags(item.get("tag", "")),
            )
            results.append(video)
        except Exception as e:
            logger.warning(f"Parse error: {e}")
            continue

    return results


def search_by_category(category: str, top_n: int = 5, source: str = "bilibili") -> list[VideoProfile]:
    """Search top videos for a product category."""
    queries = CATEGORY_SEARCH_QUERIES.get(category, [f"{category} 评测"])
    all_results = []
    seen_ids = set()

    for query in queries[:2]:
        if source != "bilibili":
            continue
        results = search_bilibili(query, top_n=top_n * 2)
        for r in results:
            if r.video_id not in seen_ids:
                r.category = category
                all_results.append(r)
                seen_ids.add(r.video_id)
        time.sleep(1)

    all_results.sort(key=lambda x: -x.views)
    return all_results[:top_n]


def _clean_html(text: str) -> str:
    return re.sub(r'<[^>]+>', '', text).strip()


def _parse_duration(dur_str: str) -> int:
    parts = dur_str.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    elif len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    return 0


def _format_date(timestamp: int) -> str:
    if not timestamp:
        return ""
    import datetime
    return datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")


def _parse_tags(tag_str: str) -> list[str]:
    return [t.strip() for t in tag_str.split(",") if t.strip()]
