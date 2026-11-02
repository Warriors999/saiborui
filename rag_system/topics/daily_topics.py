"""Daily trending topics pipeline — fetch, score, report, seed.

Uses hot-topics API (60s.viki.moe) for Weibo/Zhihu/Baidu/Douyin hot searches.
Generates: markdown report + HTML report (template-based) + topics seed file.
"""

import json, re, sys, time
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

from openai import OpenAI

from rag_system.config import BING_SEARCH_API_KEY, BING_SEARCH_MKT, DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from rag_system.utils import logger, setup_logging
setup_logging()

OUTPUT_DIR = Path("output/daily")
SEED_FILE = OUTPUT_DIR / "topics_seed.txt"
CACHE_FILE = OUTPUT_DIR / "_topic_cache.json"
MAX_CACHE_AGE_DAYS = 7

HOT_TOPICS_API = "https://60s.viki.moe/v2"

# Proxy config for international sources (Clash Verge default port)
_HTTP_PROXY = "http://127.0.0.1:7897"


def _get_proxied_session():
    """Return a requests session configured with local proxy.
    Uses verify=False to avoid TLS compatibility issues with Clash Verge.
    Falls back gracefully if proxy is unreachable."""
    import requests
    import urllib3
    urllib3.disable_warnings()
    session = requests.Session()
    session.proxies = {"http": _HTTP_PROXY, "https": _HTTP_PROXY}
    session.verify = False
    return session
PLATFORMS = {
    "weibo": f"{HOT_TOPICS_API}/weibo",
    "zhihu": f"{HOT_TOPICS_API}/zhihu",
    "baidu": f"{HOT_TOPICS_API}/baidu/hot",
    "douyin": f"{HOT_TOPICS_API}/douyin",
    "bili": f"{HOT_TOPICS_API}/bili",
}

TECH_CORE = [
    # 中文硬件/外设
    "键盘", "鼠标", "显示器", "耳机", "音响", "外设",
    "显卡", "CPU", "GPU", "RTX", "芯片", "主板", "内存", "SSD", "硬盘", "存储",
    "笔记本", "电脑", "手机", "平板", "iPad", "iPhone",
    # 品牌
    "苹果", "华为", "小米", "ROG", "索尼", "微软", "英伟达", "NVIDIA",
    "AMD", "Intel", "高通", "联发科", "三星",
    # AI / 技术
    "AI", "人工智能", "大模型", "DeepSeek", "ChatGPT",
    "5G", "WiFi", "蓝牙", "Type-C",
    # 电竞 / 外设
    "电竞", "FPS", "机械", "磁轴", "客制化",
    "高刷", "2K", "4K", "HDR", "OLED", "MiniLED",
    # 新品 / 价格
    "新品", "降价", "性价比", "评测",
    "充电", "续航", "散热", "性能", "跑分",
    # ---- 英文关键词 (Reddit / HackerNews) ----
    # 硬件
    "Nintendo", "Switch", "PlayStation", "Xbox", "Steam Deck", "console",
    "laptop", "notebook", "desktop", "ThinkPad", "ThinkBook",
    "battery", "SSD", "NVMe", "DRAM", "NAND", "YMTC",
    "GPU", "CPU", "RTX", "Radeon", "GeForce", "processor",
    "monitor", "display", "keyboard", "mouse", "headphone",
    "smartphone", "iPhone", "Android", "Pixel", "Galaxy",
    "camera", "sensor", "lens", "drone",
    # 科技公司
    "Apple", "Google", "Microsoft", "Meta", "Amazon", "Tesla",
    "SpaceX", "Starlink", "OpenAI", "Anthropic",
    "Samsung", "Lenovo", "Motorola", "Qualcomm", "TSMC",
    "NVIDIA", "AMD", "Intel", "Broadcom", "ASML",
    # 技术概念
    "AI", "LLM", "GPT", "Copilot", "Gemini", "machine learning",
    "robot", "robotics", "automation", "autonomous",
    "semiconductor", "chip", "fab", "node",
    "cyber", "security", "ransomware", "hack", "vulnerability",
    "privacy", "surveillance", "encryption",
    "cloud", "SaaS", "API", "open source",
    "electric vehicle", "EV", "self-driving",
    # 科技话题
    "tech", "startup", "layoff", "acquisition", "IPO",
    "regulation", "antitrust", "lawsuit",
    "disc", "digital", "streaming", "subscription",
]
TECH_BROAD = ["科技", "数码", "智能", "数据", "二手", "捡漏", "创业", "自媒体",
              "game", "gaming", "software", "hardware", "device", "app",
              "update", "release", "beta", "launch"]
# 泛化词 — 很多非科技内容也会用，不作为唯一通过条件
TECH_GENERIC = ["发布", "游戏", "设备", "系统", "平台", "网络", "数据", "智能",
                "review", "best", "new", "top", "how to", "guide"]
NOISE_KW = ["旅游", "打卡", "美食", "景点", "天气", "房价", "油价", "车价",
            "电视剧", "综艺", "明星", "恋爱", "结婚", "离婚", "出轨",
            "足球", "篮球", "NBA", "世界杯", "特朗普", "拜登", "政治",
            "医院", "疫情", "病毒", "健康", "金价", "股市", "A股", "期货", "基金",
            "水库", "险情", "谣言", "通报",  # 地方政务类假阳性
            "football", "basketball", "soccer", "celebrity", "dating",
            "recipe", "travel", "vlog", "makeup", "fashion"]


def _fetch_platform(platform, url, max_retries=3):
    """Fetch hot topics from a platform API with retry on transient errors."""
    import requests
    last_error = None
    for attempt in range(max_retries):
        try:
            r = requests.get(url, timeout=10)
            data = r.json()
            items = data.get("data", [])
            if not items:
                return []
            for item in items:
                if isinstance(item, dict):
                    item.setdefault("rank", 99)
                    item.setdefault("热度", 0)
                    try:
                        item["热度"] = int(str(item["热度"]).replace(",", ""))
                    except Exception:
                        item["热度"] = 0
            logger.info("  %s: %d topics", platform, len(items))
            return items
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                logger.warning("  %s: retry %d/%d after %.0fs — %s", platform, attempt + 1, max_retries, wait, e)
                time.sleep(wait)
    logger.warning("  %s: all %d retries exhausted — %s", platform, max_retries, last_error)
    return []


def _fetch_bilibili():
    """Fetch B站 hot search topics. Primary: official API, fallback: 60s.viki.moe."""
    items = _fetch_bilibili_official()
    if items:
        return items
    logger.info("  bili: official API returned 0, falling back to aggregator")
    return _fetch_platform("bili", f"{HOT_TOPICS_API}/bili")


def _fetch_bilibili_official():
    """Fetch from B站 official hot search square API (no WBI sign required)."""
    import requests
    try:
        url = "https://api.bilibili.com/x/web-interface/wbi/search/square?limit=50"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.bilibili.com/",
        }
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        if data.get("code") != 0:
            logger.warning("  bili official API error: code=%s", data.get("code"))
            return []
        trending = data.get("data", {}).get("trending", {})
        raw_items = trending.get("list", [])
        result = []
        for i, item in enumerate(raw_items):
            keyword = item.get("keyword", "")
            show_name = item.get("show_name", "")
            result.append({
                "title": show_name or keyword,
                "rank": i + 1,
                "热度": item.get("heat_score", 0),
                "url": "https://search.bilibili.com/all?keyword=%s" % requests.utils.quote(keyword or show_name),
            })
        logger.info("  bili: %d topics (official API)", len(result))
        return result
    except Exception as e:
        logger.warning("  bili official: %s", e)
        return []


def _fetch_weibo_native():
    """Fetch Weibo hot search from native API (no auth required, domestic direct access)."""
    import requests
    try:
        url = "https://weibo.com/ajax/side/hotSearch"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Referer": "https://weibo.com/",
        }
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        if data.get("ok") != 1:
            logger.warning("  weibo native API: ok=%s", data.get("ok"))
            return []
        realtime = data.get("data", {}).get("realtime", [])
        result = []
        for item in realtime:
            word = item.get("word", "")
            # Strip hashtags from display but keep original for matching
            word_clean = word.strip("#")
            result.append({
                "title": word_clean,
                "word_raw": word,
                "rank": item.get("realpos", item.get("rank", 99)),
                "热度": int(item.get("num", 0)),
                "url": "https://s.weibo.com/weibo?q=%s" % requests.utils.quote(word),
            })
        logger.info("  weibo: %d topics (native API)", len(result))
        return result
    except Exception as e:
        logger.warning("  weibo native: %s", e)
        return []


def _fetch_baidu_direct():
    """Fetch Baidu hot search from official board API (no auth, domestic direct)."""
    import requests
    try:
        url = "https://top.baidu.com/api/board?platform=wise&tab=realtime"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://top.baidu.com/",
        }
        r = requests.get(url, headers=headers, timeout=15)
        r.encoding = "utf-8"
        data = r.json()
        cards = data.get("data", {}).get("cards", [])
        result = []
        seen = set()
        for card in cards:
            for section in card.get("content", []):
                for item in section.get("content", []):
                    if not isinstance(item, dict):
                        continue
                    word = item.get("word", "").strip()
                    if not word or word in seen:
                        continue
                    seen.add(word)
                    result.append({
                        "title": word,
                        "rank": item.get("index", len(result) + 1),
                        "热度": int(item.get("hotScore", 0)),
                        "url": item.get("url", ""),
                    })
        logger.info("  baidu: %d topics (direct API)", len(result))
        return result
    except Exception as e:
        logger.warning("  baidu direct: %s", e)
        return []


def _fetch_douyin_direct():
    """Fetch Douyin hot search from official web API (no auth, domestic direct)."""
    import requests
    try:
        url = "https://www.douyin.com/aweme/v1/web/hot/search/list/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.douyin.com/",
        }
        r = requests.get(url, headers=headers, timeout=15)
        r.encoding = "utf-8"
        data = r.json()
        word_list = data.get("data", {}).get("word_list", [])
        result = []
        for item in word_list:
            word = item.get("word", "").strip()
            if not word:
                continue
            result.append({
                "title": word,
                "rank": item.get("position", len(result) + 1),
                "热度": int(item.get("hot_value", 0)),
                "url": "",
            })
        logger.info("  douyin: %d topics (direct API)", len(result))
        return result
    except Exception as e:
        logger.warning("  douyin direct: %s", e)
        return []


def _fetch_zhihu_direct():
    """Fetch Zhihu hot search from top_search API (no auth, domestic direct)."""
    import requests
    try:
        url = "https://www.zhihu.com/api/v4/search/top_search/tabs/hot/items"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "x-api-version": "3.0.40",
            "x-requested-with": "fetch",
        }
        r = requests.get(url, headers=headers, timeout=15)
        r.encoding = "utf-8"
        data = r.json()
        items = data.get("data", [])
        result = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = item.get("query_display", "").strip()
            if not title:
                continue
            result.append({
                "title": title,
                "rank": item.get("index", len(result) + 1),
                "热度": 0,  # Zhihu tab API doesn't provide heat scores
                "url": "",
            })
        logger.info("  zhihu: %d topics (direct API)", len(result))
        return result
    except Exception as e:
        logger.warning("  zhihu direct: %s", e)
        return []


def _fetch_reddit_tech():
    """Fetch hot posts from Reddit r/technology + r/hardware + r/gadgets.
    Uses multi-subreddit RSS via curl subprocess — Python's requests library
    has intermittent SSL/TLS compatibility issues with Clash Verge proxy."""
    import xml.etree.ElementTree as ET
    import subprocess
    import tempfile
    all_posts = []
    ATOM_NS = "http://www.w3.org/2005/Atom"

    try:
        url = "https://www.reddit.com/r/technology+hardware+gadgets/.rss?limit=30"
        # curl through proxy is consistently reliable where Python requests isn't
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            result = subprocess.run([
                "curl", "-s", "-L",
                "--proxy", _HTTP_PROXY,
                "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                "-H", "Accept: application/atom+xml,application/xml",
                "--connect-timeout", "15",
                "--max-time", "30",
                "-o", tmp_path,
                url,
            ], capture_output=True, text=True, timeout=35)
            if result.returncode != 0:
                logger.warning("  reddit: curl failed (rc=%d): %s", result.returncode, result.stderr[:200])
                return []
            rss_text = Path(tmp_path).read_text(encoding="utf-8")
        finally:
            try: Path(tmp_path).unlink()
            except: pass

        if not rss_text or not rss_text.strip().startswith("<?xml"):
            logger.warning("  reddit: empty or non-XML response (%d bytes)", len(rss_text))
            return []

        root = ET.fromstring(rss_text)

        # Track per-subreddit counts
        sub_counts = {}
        rss_pos = 0
        for entry in root.findall(f"{{{ATOM_NS}}}entry"):
            rss_pos += 1
            title_el = entry.find(f"{{{ATOM_NS}}}title")
            link_el = entry.find(f"{{{ATOM_NS}}}link")
            content_el = entry.find(f"{{{ATOM_NS}}}content")

            title = title_el.text.strip() if title_el is not None and title_el.text else ""
            if not title:
                continue

            # Subreddit from <category> tag
            sub_name = "unknown"
            for cat in entry.findall(f"{{{ATOM_NS}}}category"):
                if cat.attrib.get("label", "").startswith("r/"):
                    sub_name = cat.attrib.get("term", "unknown")
                    break

            permalink = link_el.attrib.get("href", "") if link_el is not None else ""
            # Extract selftext from content HTML (strip tags)
            selftext = ""
            if content_el is not None and content_el.text:
                selftext = re.sub(r"<[^>]+>", " ", content_el.text).strip()[:300]
                # Collapse whitespace
                selftext = re.sub(r"\s+", " ", selftext)

            # RSS feed is in Reddit "hot" order — position ≈ rank
            estimated_rank = min(rss_pos, 50)
            all_posts.append({
                "title": title,
                "rank": estimated_rank,
                "热度": 50,
                "url": permalink,
                "selftext": selftext,
            })
            sub_counts[sub_name] = sub_counts.get(sub_name, 0) + 1

        for sub, cnt in sub_counts.items():
            logger.info("  reddit r/%s: %d posts (RSS)", sub, cnt)
        logger.info("  reddit multi-RSS: %d total posts from 1 request", len(all_posts))

    except Exception as e:
        logger.warning("  reddit: %s", e)

    # Dedup by title prefix
    seen = set()
    unique = []
    for p in all_posts:
        key = p["title"][:40]
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique[:15]


def _fetch_hackernews():
    """Fetch top stories from Hacker News (public Firebase API, no auth)."""
    import requests
    session = _get_proxied_session()
    try:
        top_url = "https://hacker-news.firebaseio.com/v0/topstories.json"
        r = session.get(top_url, timeout=10)
        ids = r.json()[:20]
        posts = []
        for sid in ids:
            try:
                item_url = f"https://hacker-news.firebaseio.com/v0/item/{sid}.json"
                item = session.get(item_url, timeout=5).json()
                if item and item.get("title"):
                    # HN score is upvotes (higher=better), convert to rank-style (lower=better)
                    hn_score = item.get("score", 0) or 0
                    hn_comments = item.get("descendants", 0) or 0
                    engagement = hn_score + hn_comments * 3
                    # Map HN score to ~rank: 300+→1, 100+→5, 30+→15, rest→30
                    if hn_score >= 300: estimated_rank = 1
                    elif hn_score >= 100: estimated_rank = 5
                    elif hn_score >= 30: estimated_rank = 15
                    else: estimated_rank = 30
                    posts.append({
                        "title": item.get("title", ""),
                        "rank": estimated_rank,
                        "热度": engagement,
                        "url": item.get("url", f"https://news.ycombinator.com/item?id={sid}"),
                        "hn_discussion_url": f"https://news.ycombinator.com/item?id={sid}",
                        "article_url": item.get("url", ""),
                    })
            except Exception:
                continue
        logger.info("  hackernews: %d posts", len(posts))
        return posts[:15]
    except Exception as e:
        logger.warning("  hackernews: %s", e)
        return []


def _is_cjk(ch):
    """Check if a character is in the CJK Unicode range."""
    cp = ord(ch)
    return (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or
            0x20000 <= cp <= 0x2A6DF or 0xF900 <= cp <= 0xFAFF or
            0x3040 <= cp <= 0x309F or 0x30A0 <= cp <= 0x30FF or  # Hiragana/Katakana
            0xAC00 <= cp <= 0xD7AF)  # Hangul


def _contains_keyword(text_lower, kw_lower):
    """Match keyword in text. English keywords require word boundaries
    to avoid false positives (e.g. 'api' inside 'papi').
    CJK/ASCII script transitions count as word boundaries."""
    if kw_lower[0].isascii():
        idx = text_lower.find(kw_lower)
        while idx != -1:
            before_ch = text_lower[idx - 1] if idx > 0 else ''
            after_ch = text_lower[idx + len(kw_lower)] if idx + len(kw_lower) < len(text_lower) else ''
            # Before: ok if start of string, non-alnum, or CJK (script boundary)
            before_ok = (idx == 0 or not before_ch.isalnum() or _is_cjk(before_ch))
            # After: ok if end of string, non-alnum, or CJK (script boundary)
            after_ok = (after_ch == '' or not after_ch.isalnum() or _is_cjk(after_ch))
            if before_ok and after_ok:
                return True
            idx = text_lower.find(kw_lower, idx + 1)
        return False
    else:
        return kw_lower in text_lower


def _is_tech(title):
    """Case-insensitive tech relevance check. English + Chinese keywords.
    English keywords use word-boundary matching to avoid substring traps."""
    t = title.lower()
    # Noise filter
    for nk in NOISE_KW:
        if _contains_keyword(t, nk.lower()):
            return False
    # Core tech keyword — one match is enough
    for ck in TECH_CORE:
        if _contains_keyword(t, ck.lower()):
            return True
    # Broad tech keywords — need 2+
    broad_hits = sum(1 for bk in TECH_BROAD if _contains_keyword(t, bk.lower()))
    if broad_hits >= 2:
        return True
    # Generic keywords — only as support for broad hits
    generic_hits = sum(1 for gk in TECH_GENERIC if _contains_keyword(t, gk.lower()))
    if broad_hits >= 1 and generic_hits >= 1:
        return True
    return False


def _score(topic, platform):
    title = topic.get("title", "")
    t = title.lower()
    core_matches = sum(1 for kw in TECH_CORE if _contains_keyword(t, kw.lower()))
    broad_matches = sum(1 for kw in TECH_BROAD if _contains_keyword(t, kw.lower()))
    kw_score = core_matches * 10 + broad_matches * 3

    rank = topic.get("rank", 99)
    rank_score = max(0, (100 - min(rank, 100)) / 2)

    # Platform weights: international sources carry information arbitrage premium
    # NOTE: kept moderate so they don't bury all Chinese platform topics
    pw = {"douyin": 1.5, "bili": 1.3, "zhihu": 1.2, "weibo": 1.0, "baidu": 0.8,
          "reddit": 1.5, "hackernews": 1.6}
    platform_bonus = pw.get(platform, 1.0) * 5

    content_bonus = 0
    if any(_contains_keyword(t, k) for k in ["评测", "实测", "对比", "推荐", "选购", "盘点",
                                                "review", "vs", "comparison", "benchmark"]):
        content_bonus += 8
    if any(_contains_keyword(t, k) for k in ["发布", "新品", "上市", "开售", "announce", "launch",
                                                "release", "leak", "rumor", "new"]):
        content_bonus += 5
    if any(_contains_keyword(t, k) for k in ["键盘", "鼠标", "显示器", "耳机", "外设",
                                                "keyboard", "mouse", "monitor", "headphone"]):
        content_bonus += 10
    # International information arbitrage — moderate premium, not overwhelming
    if platform in ("reddit", "hackernews"):
        content_bonus += 5
    return round(kw_score + rank_score + platform_bonus + content_bonus, 1)


def _suggest_format(title):
    t = title.lower()
    # 实测/上手体验
    if any(k in t for k in ["键盘", "鼠标", "显示器", "耳机", "外设",
                              "keyboard", "mouse", "monitor", "headphone",
                              "review", "hands-on", "unboxing", "teardown"]):
        return "实测体验"
    # 选购指南
    if any(k in t for k in ["推荐", "选购", "618", "降价", "性价比", "对比",
                              "best", "vs", "comparison", "buying guide",
                              "worth it", "recommend"]):
        return "选购指南"
    # 盘点排名
    if any(k in t for k in ["盘点", "排行", "top", "ranking", "tier list"]):
        return "盘点排名"
    # 新品速览
    if any(k in t for k in ["发布", "新品", "上市", "开售",
                              "announced", "launch", "released", "leak",
                              "rumor", "new", "unveil"]):
        return "新品速览"
    # 深度解读
    if any(k in t for k in ["AI", "芯片", "技术", "原理",
                              "deep dive", "explained", "how", "why",
                              "analysis", "breakdown"]):
        return "深度解读"
    # 技巧教学
    if any(k in t for k in ["技巧", "教学", "设置", "优化",
                              "tutorial", "guide", "how to", "tips", "tricks"]):
        return "技巧教学"
    return "热点评论"


def _is_english_title(title):
    """Detect if a title is primarily English (non-CJK)."""
    cjk_count = sum(1 for ch in title if _is_cjk(ch))
    alpha_count = sum(1 for ch in title if ch.isascii() and ch.isalpha())
    # If CJK chars < 30% and latin letters > 0, treat as English
    total = len(title) or 1
    return cjk_count / total < 0.3 and alpha_count > 3


def _translate_english_titles(topics, timeout=45):
    """Batch-translate English titles to Chinese via DeepSeek LLM.
    Stores result in _title_zh field. Preserves original title."""
    need_trans = [(i, t) for i, t in enumerate(topics) if _is_english_title(t.get("title", ""))]
    if not need_trans:
        return

    topic_list = "\n".join(
        f"{j+1}. {t.get('title','')}"
        for j, (_, t) in enumerate(need_trans)
    )
    prompt = (
        "将以下英文科技新闻标题翻译为中文。要求：\n"
        "1. 保留产品名/品牌名原文（如 RTX 5060、AMD、NVIDIA）\n"
        "2. 中文表达自然，像国内科技媒体会用的标题\n"
        "3. 每行一个翻译，不要编号，不要多余解释\n\n"
        f"{topic_list}"
    )

    try:
        client = _get_llm_client()
        logger.info("  LLM: translating %d English titles to Chinese via %s", len(need_trans), DEEPSEEK_MODEL)
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "你是专业科技翻译。只输出翻译结果，每行一个，不要编号。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2, max_tokens=2048, timeout=timeout,
        )
        raw = response.choices[0].message.content.strip()
        translations = [line.strip() for line in raw.split("\n") if line.strip()]

        if len(translations) == len(need_trans):
            for (idx, t), zh_title in zip(need_trans, translations):
                t["_title_zh"] = zh_title.strip()[:80]
            logger.info("  LLM: %d titles translated", len(translations))
        else:
            logger.warning("  LLM translation count mismatch: expected %d, got %d", len(need_trans), len(translations))
            # Best-effort: assign whatever we got
            for j, (idx, t) in enumerate(need_trans):
                if j < len(translations):
                    t["_title_zh"] = translations[j].strip()[:80]
    except Exception as e:
        logger.warning("  LLM title translation failed: %s", e)


def _display_title(topic):
    """Return Chinese display title: prefer translated, fallback to original."""
    zh = topic.get("_title_zh", "")
    if zh:
        return zh
    return topic.get("title", "")


def _truncate_title(title, max_len):
    """Truncate title at a natural break point, avoiding mid-word cuts."""
    if len(title) <= max_len:
        return title
    # Try to find a natural break: Chinese/English punctuation or space
    breaks = "。！？，、；：. !?,;:）)）」》>"
    for i in range(max_len - 1, max_len // 2, -1):
        if title[i] in breaks:
            return title[:i]
    # If no break found, check for CJK character boundary (no half-char issues in Python3)
    return title[:max_len]


def _content_angles(title, platform, fmt):
    angles = []
    tech_hook = ""
    urgency = "中"
    difficulty = "中"

    # International sources → information arbitrage angles
    if platform in ("reddit", "hackernews"):
        angles = [
            "信息差解读：" + _truncate_title(title, 22) + "国内还没人聊的角度",
            "趋势预判：" + _truncate_title(title, 20) + "会不会在国内火起来",
            "本土化改编：" + _truncate_title(title, 20) + "中国市场的不同逻辑",
        ]
        tech_hook = "国际热点=信息差优势，国内用户还没被同质内容轰炸"
        urgency = "中"
        return {"angles": angles, "tech_hook": tech_hook, "urgency": urgency, "difficulty": difficulty}

    if any(k in title for k in ["键盘", "鼠标", "外设", "磁轴", "机械"]):
        angles = [
            "上手实测：" + _truncate_title(title, 20) + "到底值不值",
            "同价位对比：" + _truncate_title(title, 18) + "跟竞品差在哪",
            "技术解读：" + _truncate_title(title, 18) + "背后的供应链逻辑",
        ]
        tech_hook = "直接做实测/对比视频，上手体验就是内容"
        urgency, difficulty = "高", "低（有产品就能拍）"
    elif any(k in title for k in ["显示器", "屏幕", "高刷", "2K", "4K", "MiniLED", "OLED"]):
        angles = [
            "选购指南：" + _truncate_title(title, 20) + "适合什么人",
            "实测对比：" + _truncate_title(title, 18) + " vs 同价位VA/IPS",
            "避坑指南：买" + _truncate_title(title, 14) + "前必须知道的3个参数",
        ]
        tech_hook = "显示器是数码博主最稳定的流量品类，选购指南永远有人看"
        urgency, difficulty = "高", "中（需要实拍画面）"
    elif any(k in title for k in ["显卡", "GPU", "RTX", "NVIDIA", "英伟达", "芯片"]):
        angles = [
            "深度解读：" + _truncate_title(title, 20) + "对普通人意味着什么",
            "历史对比：从上一代到这一代，进步有多大",
            "购买建议：" + _truncate_title(title, 18) + "值得等还是直接入手",
        ]
        tech_hook = "芯片/显卡话题永远是数码圈最大流量池，观点可以差异化"
        urgency, difficulty = "高", "中（需要专业知识储备）"
    elif any(k in title for k in ["笔记本", "电脑", "MacBook"]):
        angles = [
            "选购指南：" + _truncate_title(title, 20) + "怎么选",
            "长期使用报告：" + _truncate_title(title, 18) + "用了一年的真实感受",
            "对比评测：" + _truncate_title(title, 18) + " vs 同价位竞品",
        ]
        tech_hook = "笔记本选购是常青内容，可以做成系列"
    elif any(k in title for k in ["手机", "iPhone"]) or \
         (any(k in title for k in ["华为", "小米", "OPPO", "vivo", "三星"]) and \
          not any(k in title for k in ["高层", "人事", "调整", "财报", "起诉", "汽车", "交付", "智行"])):
        angles = [
            "新品速评：" + _truncate_title(title, 20) + "值得升级吗",
            "功能挖掘：" + _truncate_title(title, 18) + "中90%人不知道的隐藏功能",
        ]
        tech_hook = "手机话题流量大但竞争激烈，需找到差异化角度"
        urgency = "高"
    elif any(k in title for k in ["AI", "人工智能", "大模型", "DeepSeek"]):
        if "如何看待" in title or "怎么" in title or "如何评价" in title:
            angles = [
                "观点评论：" + _truncate_title(title, 22) + "我这样看",
                "通俗解读：" + _truncate_title(title, 20) + "背后的技术逻辑",
            ]
        else:
            angles = [
                "通俗解读：" + _truncate_title(title, 20) + "到底是怎么做到的",
                "实际测试：" + _truncate_title(title, 20) + "实际效果出乎意料",
            ]
        tech_hook = "AI话题需要翻译——把技术语言变成普通人能懂的比喻"
        urgency, difficulty = "高", "高（需要准确理解技术原理）"
    elif any(k in title for k in ["618", "降价", "性价比", "推荐", "选购"]):
        angles = [
            "实时比价：" + _truncate_title(title, 20) + "当前最低价是多少",
            "避坑指南：" + _truncate_title(title, 14) + "这些型号千万别买",
        ]
        tech_hook = "价格敏感型内容在促销季流量极高，时效性窗口短"
        urgency = "极高"
    elif any(k in title for k in ["游戏", "电竞", "FPS"]):
        # Distinguish: specific game → gear/settings angles; industry news → commentary
        is_specific_game = any(k in title for k in ["FPS", "LOL", "英雄联盟", "王者荣耀", "原神", "CS", "DOTA"])
        if is_specific_game:
            angles = [
                "装备推荐：打" + _truncate_title(title, 12) + "用什么外设",
                "设置优化：" + _truncate_title(title, 12) + "职业选手的游戏设置",
            ]
            tech_hook = "游戏内容转外设推荐是自然转化路径"
        else:
            angles = [
                "行业分析：" + _truncate_title(title, 22) + "对玩家意味着什么",
                "热点评论：" + _truncate_title(title, 20) + "背后的产业逻辑",
            ]
            tech_hook = "游戏产业新闻受众广，可延伸到硬件/平台格局分析"
    elif any(k in title for k in ["索尼"]):
        # Sony is broad: gaming (光盘/PS5/游戏), electronics, entertainment
        if any(k in title for k in ["光盘", "PS5", "PlayStation", "游戏"]):
            angles = [
                "行业分析：" + _truncate_title(title, 22) + "对玩家意味着什么",
                "热点评论：" + _truncate_title(title, 20) + "游戏产业的数字化趋势",
            ]
            tech_hook = "游戏产业新闻受众广，可延伸到硬件/平台格局分析"
        else:
            angles = [
                "热点解读：" + _truncate_title(title, 20) + "到底怎么回事",
                "深度分析：" + _truncate_title(title, 18) + "背后的行业逻辑",
            ]
            tech_hook = "索尼业务横跨消费电子/娱乐/半导体，找到与数码相关的切入点"
    else:
        angles = [
            "热点解读：" + _truncate_title(title, 20) + "到底怎么回事",
            "深度分析：" + _truncate_title(title, 18) + "背后的行业逻辑",
            "观点评论：我对" + _truncate_title(title, 18) + "的看法",
        ]
        tech_hook = "需要找到一个数码/科技角度来切入这个话题"

    return {"angles": angles, "tech_hook": tech_hook, "urgency": urgency, "difficulty": difficulty}


def _fetch_page_description(url, timeout=8):
    """Try to extract a meta description or summary from a URL.
    Returns empty string on any failure — never blocks the pipeline."""
    import requests as req
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        r = req.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        html = r.text[:200000]  # Only look at first 200KB
        # Try og:description first, then meta description
        for pattern in [
            r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        ]:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                desc = match.group(1)
                # Clean HTML entities
                desc = desc.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                desc = desc.replace("&quot;", "\"").replace("&#x27;", "'").replace("&#39;", "'")
                return desc.strip()[:200]
    except Exception:
        pass
    return ""


def _bing_search_description(query, timeout=8):
    """Search via Bing Web Search API and return the top snippet.
    Free tier: 1000 req/month. Returns empty string if API key not set or error."""
    if not BING_SEARCH_API_KEY:
        return ""
    import requests as req
    try:
        url = "https://api.bing.microsoft.com/v7.0/search"
        headers = {"Ocp-Apim-Subscription-Key": BING_SEARCH_API_KEY}
        params = {"q": query, "count": 1, "mkt": BING_SEARCH_MKT, "textFormat": "Raw"}
        r = req.get(url, headers=headers, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        pages = data.get("webPages", {}).get("value", [])
        if pages:
            return pages[0].get("snippet", "")[:200]
    except Exception as e:
        logger.warning("  Bing search error for '%s': %s", query[:30], e)
    return ""


# ---- LLM description fallback (DeepSeek) ----

_llm_client: OpenAI | None = None


def _get_llm_client() -> OpenAI:
    """Lazy-init DeepSeek client (reuses project config)."""
    global _llm_client
    if _llm_client is None:
        if not DEEPSEEK_API_KEY:
            raise ValueError("DeepSeek API key not configured")
        _llm_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    return _llm_client


def _generate_llm_descriptions(topics, timeout=30):
    """Batch-call DeepSeek to generate 1-sentence descriptions for topics.
    Only processes topics that still lack _description. Writes results in-place."""
    need_desc = [(i, t) for i, t in enumerate(topics) if not t.get("_description", "")]
    if not need_desc:
        return

    # Build numbered topic list for the prompt
    topic_list = "\n".join(
        f"{j+1}. {t.get('title','')} [来源: {t.get('_platform','')}]"
        for j, (_, t) in enumerate(need_desc)
    )
    prompt = (
        "以下是今日中文数码科技热搜话题列表。请为每个话题写一句简短的事件描述（不超过60字），"
        "说明具体发生了什么事，让不了解的人看完描述就能明白发生了什么。\n"
        "如果你不知道具体事件，根据标题和你的知识合理推断。\n"
        "返回严格JSON数组，每个元素是字符串，不要markdown包裹。\n\n"
        f"{topic_list}"
    )

    try:
        client = _get_llm_client()
        logger.info("  LLM: generating descriptions for %d topics via %s", len(need_desc), DEEPSEEK_MODEL)
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "你是一个熟悉中文科技新闻的编辑。严格按JSON数组格式返回，每个元素是一个字符串描述。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3, max_tokens=2048, timeout=timeout,
        )
        raw = response.choices[0].message.content.strip()

        # Parse JSON — may be wrapped in ```json ... ```
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            if raw.endswith("```"):
                raw = raw[:-3]
        descriptions = json.loads(raw)

        if isinstance(descriptions, list) and len(descriptions) == len(need_desc):
            for (idx, t), desc in zip(need_desc, descriptions):
                if isinstance(desc, str) and desc.strip():
                    t["_description"] = desc.strip()[:200]
            logger.info("  LLM: %d descriptions generated", len(descriptions))
        else:
            logger.warning("  LLM: unexpected response format, got %s", type(descriptions).__name__)
    except Exception as e:
        logger.warning("  LLM description generation failed: %s", e)


def _enrich_descriptions(topics, max_topics=15):
    """Fill _description for each topic from native data or URL scraping.
    Only fetches URLs for platforms without built-in descriptions (HN only).
    B站/微博/抖音 search-result URLs are NOT article pages and will be skipped.
    """
    # Generic site-level descriptions to filter out
    _GENERIC_DESC_PATTERNS = [
        "bilibili是国内知名的视频弹幕网站",
        "bilibili是国内知名",
        "微博是一款", "新浪微博",
        "抖音是一个", "抖音-记录美好生活",
        "知乎是一个", "知乎，中文互联网",
        "百度一下", "全球最大的中文搜索引擎",
    ]

    def _is_generic(desc):
        for pattern in _GENERIC_DESC_PATTERNS:
            if pattern in desc:
                return True
        return False

    for t in topics[:max_topics]:
        plat = t.get("_platform", "")
        title = t.get("title", "")

        # 1. 百度: 聚合器原生 desc 字段
        if plat == "baidu":
            desc = t.get("desc", "")
            if desc and not _is_generic(desc):
                t["_description"] = desc.strip()
                continue

        # 2. 知乎: 聚合器原生 detail 字段
        if plat == "zhihu":
            detail = t.get("detail", "")
            if detail and not _is_generic(detail):
                t["_description"] = detail.strip()[:200]
                continue

        # 3. Reddit: selftext (已在 fetch 阶段抓取)
        if plat == "reddit":
            selftext = t.get("selftext", "")
            if selftext:
                t["_description"] = selftext.strip()[:200]
                continue

        # 4. Hacker News: 抓取原文 meta description (文章页，非搜索页)
        if plat == "hackernews":
            article_url = t.get("article_url", "")
            if article_url:
                logger.info("  fetching HN article desc: %s", article_url[:60])
                desc = _fetch_page_description(article_url, timeout=8)
                if desc and not _is_generic(desc):
                    t["_description"] = desc.strip()[:200]
                    continue

        # 5. B站 / 微博 / 抖音: URL 是搜索聚合页，不是文章页，跳过 URL 抓取
        #    这些平台的热搜本质是关键词聚合，没有单篇摘要可提取

        # 兜底: 无描述 (下面会用 Bing Search 补)
        t["_description"] = ""

    # 6. Final fallback: Bing Search (if key set) → then DeepSeek LLM for any remaining
    if BING_SEARCH_API_KEY:
        for t in topics[:max_topics]:
            if not t.get("_description", ""):
                desc = _bing_search_description(t.get("title", ""), timeout=8)
                if desc:
                    t["_description"] = desc.strip()[:200]

    # 7. DeepSeek LLM batch fallback — covers anything still without description
    _generate_llm_descriptions(topics[:max_topics])

    # Log summary
    with_desc = sum(1 for t in topics[:max_topics] if t.get("_description", ""))
    logger.info("Descriptions enriched: %d/%d have descriptions", with_desc, min(len(topics), max_topics))


def _generate_rich_html(scored_topics, date_str, prefix):
    """Generate rich HTML report by injecting JSON data into the template."""
    # Build topics JSON with content briefs
    topics_json = []
    for i, t in enumerate(scored_topics[:15], 1):
        title = _display_title(t)
        raw_title = t.get("title", "")
        fmt = _suggest_format(title)
        brief = _content_angles(title, t.get("_platform", ""), fmt)
        topics_json.append({
            "rank": i, "title": title,
            "title_raw": raw_title,
            "platform": t.get("_platform", ""),
            "rank_orig": t.get("rank", 99),
            "score": t.get("_score", 0), "format": fmt,
            "effect": "high" if t.get("_score", 0) > 20 else "medium",
            "angles": brief["angles"], "tech_hook": brief["tech_hook"],
            "urgency": brief["urgency"], "difficulty": brief["difficulty"],
            "description": t.get("_description", ""),
        })

    data_json = json.dumps({
        "date": date_str,
        "count": len(topics_json),
        "topScore": max((t["score"] for t in topics_json), default=0),
        "topics": topics_json,
    }, ensure_ascii=False, indent=2)

    # Chinese weekday
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    try:
        dt = datetime.fromisoformat(date_str)
        date_display = "%d年%d月%d日 · %s · 晨间简报" % (dt.year, dt.month, dt.day, weekdays[dt.weekday()])
    except:
        date_display = date_str

    # Rich HTML with inline styles and angles/tech_hook rendering
    template_path = Path(__file__).parent / "template.html"
    html = template_path.read_text(encoding="utf-8")

    # Replace placeholders
    html = html.replace("__DATE__", date_str)
    html = html.replace("__DATE_DISPLAY__", date_display)
    html = html.replace("__COUNT__", str(len(topics_json)))
    html = html.replace("__TOPSCORE__", str(max((t["score"] for t in topics_json), default=0)))
    html = html.replace("__DATA__", data_json)

    html_path = OUTPUT_DIR / f"{prefix}_选题日报.html"
    html_path.write_text(html, encoding="utf-8")
    return html_path


def run_daily_pipeline():
    today = datetime.now().strftime("%Y-%m-%d")
    logger.info("Daily topics pipeline: %s", today)

    # 1. Fetch — native APIs first, 60s.viki.moe as fallback
    all_items = []

    # Weibo: native API (domestic direct, no proxy needed)
    weibo_items = _fetch_weibo_native()
    if weibo_items:
        for item in weibo_items:
            item["_platform"] = "weibo"
        all_items.extend(weibo_items)
    else:
        # Fallback to aggregator
        fallback = _fetch_platform("weibo", f"{HOT_TOPICS_API}/weibo")
        for item in fallback:
            item["_platform"] = "weibo"
        all_items.extend(fallback)

    # B站: official API first, then aggregator
    bili_items = _fetch_bilibili()
    for item in bili_items:
        item["_platform"] = "bili"
    all_items.extend(bili_items)

    # Baidu: direct official API first, 60s.viki.moe as fallback
    baidu_items = _fetch_baidu_direct()
    if baidu_items:
        for item in baidu_items:
            item["_platform"] = "baidu"
        all_items.extend(baidu_items)
    else:
        fallback = _fetch_platform("baidu", f"{HOT_TOPICS_API}/baidu/hot")
        for item in fallback:
            item["_platform"] = "baidu"
        all_items.extend(fallback)

    # Douyin: direct official API first, 60s.viki.moe as fallback
    douyin_items = _fetch_douyin_direct()
    if douyin_items:
        for item in douyin_items:
            item["_platform"] = "douyin"
        all_items.extend(douyin_items)
    else:
        fallback = _fetch_platform("douyin", f"{HOT_TOPICS_API}/douyin")
        for item in fallback:
            item["_platform"] = "douyin"
        all_items.extend(fallback)

    # Zhihu: direct top_search API first, 60s.viki.moe as fallback
    zhihu_items = _fetch_zhihu_direct()
    if zhihu_items:
        for item in zhihu_items:
            item["_platform"] = "zhihu"
        all_items.extend(zhihu_items)
    else:
        fallback = _fetch_platform("zhihu", f"{HOT_TOPICS_API}/zhihu")
        for item in fallback:
            item["_platform"] = "zhihu"
        all_items.extend(fallback)

    # International sources: Reddit + Hacker News (public APIs, no auth)
    reddit_posts = _fetch_reddit_tech()
    for item in reddit_posts:
        item["_platform"] = "reddit"
    all_items.extend(reddit_posts)

    hn_posts = _fetch_hackernews()
    for item in hn_posts:
        item["_platform"] = "hackernews"
    all_items.extend(hn_posts)

    logger.info("Fetched %d total items", len(all_items))

    # 2. Filter tech
    tech_items = [t for t in all_items if _is_tech(t.get("title", ""))]
    logger.info("Tech filter: %d/%d passed", len(tech_items), len(all_items))

    # 3. Score
    for t in tech_items:
        t["_score"] = _score(t, t.get("_platform", ""))
    tech_items.sort(key=lambda x: x["_score"], reverse=True)

    # 4. Dedup — CJK for Chinese titles, first 60 chars for English
    seen = set()
    unique = []
    for t in tech_items:
        title = t.get("title", "")
        # Extract CJK chars for Chinese dedup, fallback to lowercase prefix for English
        cjk_key = re.sub(r"[^一-鿿]", "", title)[:20]
        key = cjk_key if cjk_key else title.lower()[:60]
        if key and key not in seen:
            seen.add(key)
            unique.append(t)

    # 4.5 Enrich descriptions from native data / URL scraping
    _enrich_descriptions(unique)

    # 4.6 Translate English titles to Chinese (so the report is readable)
    _translate_english_titles(unique)

    # 5. Markdown report
    lines = [
        "# 数码圈每日热点选题报告",
        "**%s** | 微博/知乎/百度/抖音/B站热搜 | %d 条数码相关" % (today, len(unique)),
        "",
        "## TOP 15",
        "",
        "| # | 话题 | 平台 | 排名 | 分 | 选题方向 | 内容概要 |",
        "|---|------|------|------|-----|----------|----------|",
    ]
    for i, t in enumerate(unique[:15], 1):
        title = _display_title(t)[:45]
        raw_title = t.get("title", "")[:60]
        plat = t.get("_platform", "?")
        rank = t.get("rank", "?")
        score = t.get("_score", 0)
        fmt = _suggest_format(_display_title(t))
        desc = t.get("_description", "")[:80]
        # If translated, append original English title in parens
        if t.get("_title_zh", "") and t.get("title", "") != t.get("_title_zh", ""):
            title_display = "%s (%s)" % (title, raw_title)
        else:
            title_display = title
        lines.append("| %d | %s | %s | #%s | %.0f | %s | %s |" % (i, title_display, plat, rank, score, fmt, desc))
    prefix = today.replace("-", "")
    report_md = OUTPUT_DIR / f"{prefix}_选题日报.md"
    report_md.parent.mkdir(parents=True, exist_ok=True)
    report_md.write_text("\n".join(lines), encoding="utf-8")

    # 6. Rich HTML report
    report_html = _generate_rich_html(unique, today, prefix)
    logger.info("HTML report: %s", report_html)

    # 7. Seed file
    seed_lines = [
        "# 选题种子库 — 自动更新于 %s" % today,
        "# 每日从微博/知乎/百度/抖音/B站热搜提取数码相关话题",
        "# 格式: 标题 | 来源 | URL | 备注",
    ]
    for t in unique[:15]:
        if t.get("_score", 0) > 5:
            seed_lines.append("%s | %s热搜 | %s | 得分%.0f" % (
                _display_title(t), t.get("_platform", ""),
                t.get("url", ""), t.get("_score", 0)
            ))
    if SEED_FILE.exists():
        old_lines = SEED_FILE.read_text(encoding="utf-8").splitlines()
        for line in old_lines:
            if line.startswith("#") and line not in seed_lines:
                seed_lines.insert(2, line)
    SEED_FILE.write_text("\n".join(seed_lines), encoding="utf-8")
    logger.info("Seed file updated: %s", SEED_FILE)

    # 8. Cache & cleanup
    try:
        cache = json.loads(CACHE_FILE.read_text(encoding="utf-8")) if CACHE_FILE.exists() else []
    except:
        cache = []
    cache.append({"date": today, "count": len(unique), "top_score": unique[0]["_score"] if unique else 0})
    cutoff = (datetime.now() - timedelta(days=MAX_CACHE_AGE_DAYS)).isoformat()
    cache = [e for e in cache if e.get("date", "") >= cutoff[:10]]
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"topics": unique, "count": len(unique),
            "report_md": str(report_md), "report_html": str(report_html), "seed": str(SEED_FILE)}


if __name__ == "__main__":
    result = run_daily_pipeline()
    print("\n" + "=" * 50)
    print("  数码圈每日热点选题 — %s" % datetime.now().strftime("%Y-%m-%d"))
    print("  %d 条数码相关话题" % result["count"])
    print("=" * 50)
    for i, t in enumerate(result["topics"][:10], 1):
        score = t.get("_score", 0)
        title = _display_title(t)[:50]
        platform = t.get("_platform", "")
        fmt = _suggest_format(_display_title(t))
        print("  %2d. [%.0f分] [%s] %s" % (i, score, platform, title))
        print("      -> %s" % fmt)
    print("\n  报告: %s" % result["report_md"])
    print("  HTML: %s" % result["report_html"])
    print("  种子: %s" % result["seed"])
