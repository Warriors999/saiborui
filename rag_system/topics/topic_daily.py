"""选题日报 (Daily Topic Brief) — 柱子哥选题策略的工程化实现.

Every morning at 8:30, AI auto-generates a ranked topic brief from multiple
sources with 6-dimensional scoring.

核心方法论: 信息不值钱，观点值钱。选你有个人经验可讲的。
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from openai import OpenAI

from rag_system.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from rag_system.utils import logger

# ---- Data Structures ----

@dataclass
class TopicCandidate:
    """A single topic candidate with multi-dimensional scores."""
    title: str
    source: str
    url: str = ""
    summary: str = ""
    scores: dict = field(default_factory=dict)
    total_score: float = 0.0
    reason: str = ""


@dataclass
class DailyBrief:
    """A day's ranked topic brief."""
    date: str
    topics: list  # list of TopicCandidate
    generated_at: str


# ---- Seed topics: always-available fallback ----

SEED_TOPICS = [
    # AI / LLM
    {"title": "DeepSeek最新模型发布：开源社区震动，性能逼近GPT-5", "source": "AI社区", "summary": "国产大模型持续发力，开源策略引发行业地震"},
    {"title": "AI Agent落地元年：普通人能用AI做什么赚钱", "source": "科技媒体", "summary": "从写代码到做客服，AI Agent在2026年的真实赚钱案例"},
    {"title": "Apple Intelligence中文版终于上线，实测到底好不好用", "source": "数码圈", "summary": "苹果AI本地化后的真实体验，跟国产AI比几斤几两"},
    # 科技 / 数码
    {"title": "2026年618数码好物前瞻：这些品类值得蹲", "source": "电商平台", "summary": "键盘、鼠标、显示器各品类的价格趋势和必买清单"},
    {"title": "磁轴键盘内卷白热化：从500到1500，到底差在哪", "source": "外设圈", "summary": "磁轴技术下放后的市场乱象——贵的一定好？"},
    {"title": "RTX 5060/5070实测：老黄刀法还能精准几代", "source": "硬件圈", "summary": "50系甜品级显卡真实性能，值不值得从40系升级"},
    {"title": "国产轻量化鼠标大横评：54g以下谁才是真卷王", "source": "外设圈", "summary": "雷柏、达摩鲨、ATK、ROG龙鳞等热门型号全面对比"},
    {"title": "电竞显示器选购终极指南：OLED vs Mini-LED谁才是未来", "source": "数码圈", "summary": "两种面板技术真实体验差距，看完再买不踩坑"},
    {"title": "2026年TWS耳机天花板之争：千元档谁能称王", "source": "音频圈", "summary": "降噪、音质、延迟三方博弈，真实横评避坑指南"},
    # 创业 / 财经
    {"title": "一个人做自媒体，2026年还能不能赚钱", "source": "创业圈", "summary": "平台流量红利消退后，个人创作者的生存现状与出路"},
    {"title": "AI创业泡沫：90%的AI公司会在两年内死掉", "source": "财经媒体", "summary": "硅谷和深圳的AI创业真实图景——钱烧完了然后呢"},
    # 生活方式 / 热点
    {"title": "数码博主的桌面进化史：从混乱到极致生产力", "source": "生活方式", "summary": "桌面setup改造的真实花费和避坑经验"},
    {"title": "二手数码捡漏指南：转转/闲鱼哪些品类值得淘", "source": "数码圈", "summary": "二手市场真实行情，哪些产品跌到位了可以入手"},
]

# ---- Internal client (lazy init, same pattern as generator.py) ----

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """Lazy-init OpenAI client for DeepSeek API."""
    global _client
    if _client is None:
        if not DEEPSEEK_API_KEY:
            raise ValueError("DeepSeek API key not configured. Set DEEPSEEK_API_KEY in .env")
        _client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    return _client


# ============================================================
# Topic scraping
# ============================================================

# Hot-topics API endpoint (60s.viki.moe aggregator)
HOT_TOPICS_API = "https://60s.viki.moe/v2"
LIVE_PLATFORMS = {
    "weibo": f"{HOT_TOPICS_API}/weibo",
    "zhihu": f"{HOT_TOPICS_API}/zhihu",
    "baidu": f"{HOT_TOPICS_API}/baidu/hot",
    "douyin": f"{HOT_TOPICS_API}/douyin",
    "bili": f"{HOT_TOPICS_API}/bili",
}

# Tech keyword filters — same as daily_topics.py
_TECH_CORE = [
    "键盘", "鼠标", "显示器", "耳机", "音响", "外设",
    "显卡", "CPU", "GPU", "RTX", "芯片", "主板", "内存", "SSD", "硬盘",
    "笔记本", "电脑", "手机", "平板", "iPad", "iPhone",
    "苹果", "华为", "小米", "ROG", "索尼", "微软", "英伟达", "NVIDIA",
    "AMD", "Intel", "高通", "联发科", "三星",
    "AI", "人工智能", "大模型", "DeepSeek", "ChatGPT",
    "5G", "WiFi", "蓝牙", "Type-C",
    "游戏", "电竞", "FPS", "机械", "磁轴", "客制化",
    "高刷", "2K", "4K", "HDR", "OLED", "MiniLED",
    "618", "发布", "新品", "降价", "性价比",
    "充电", "续航", "散热", "性能", "跑分", "评测",
    "机器人", "无人机", "自动驾驶", "新能源",
    "赛博", "开源", "程序", "代码", "编程",
]
_TECH_BROAD = ["科技", "数码", "智能", "数据", "二手", "捡漏", "创业", "自媒体"]
_NOISE_KW = ["旅游", "打卡", "美食", "景点", "天气", "房价", "油价", "车价",
             "电视剧", "综艺", "明星", "恋爱", "结婚", "离婚", "出轨",
             "足球", "篮球", "NBA", "世界杯", "特朗普", "拜登", "政治",
             "医院", "疫情", "病毒", "健康", "金价", "股市", "A股", "期货", "基金"]


def _is_tech_topic(title: str) -> bool:
    """Filter: returns True if the title is tech/digital related."""
    for nk in _NOISE_KW:
        if nk in title:
            return False
    for ck in _TECH_CORE:
        if ck in title:
            return True
    hits = sum(1 for bk in _TECH_BROAD if bk in title)
    return hits >= 2


# Shared session for live API — bypasses Windows system proxy, uses browser UA
_live_session = None


def _get_live_session():
    """Create or reuse a requests Session configured to bypass system proxy."""
    global _live_session
    if _live_session is None:
        import requests
        import urllib3
        urllib3.disable_warnings()
        _live_session = requests.Session()
        _live_session.trust_env = False  # bypass Windows system proxy / WPAD
        _live_session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
    return _live_session


def _fetch_live_platform(platform: str, url: str, max_retries: int = 2) -> list[dict]:
    """Fetch hot topics from one platform API with retry.

    Uses a shared session with trust_env=False to bypass Windows
    system proxy that otherwise kills connections to 60s.viki.moe.
    """
    import time
    session = _get_live_session()
    last_error = None
    for attempt in range(max_retries):
        try:
            r = session.get(url, timeout=20, verify=False)
            data = r.json()
            items = data.get("data", [])
            if not items:
                return []
            for item in items:
                if isinstance(item, dict):
                    item.setdefault("rank", 99)
                    item.setdefault("热度", 0)
            logger.info("  %s: %d topics (live)", platform, len(items))
            return items
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(1.5)
    logger.warning("  %s: fetch failed — %s", platform, last_error)
    return []


def _fetch_live_bilibili() -> list[dict]:
    """Fetch B站 hot search from official API, fallback to aggregator."""
    import requests
    session = _get_live_session()
    try:
        url = "https://api.bilibili.com/x/web-interface/wbi/search/square?limit=50"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.bilibili.com/",
        }
        r = session.get(url, headers=headers, timeout=15, verify=False)
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
        return _fetch_live_platform("bili", f"{HOT_TOPICS_API}/bili")


def _fetch_live_baidu_direct() -> list[dict]:
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


def _fetch_live_douyin_direct() -> list[dict]:
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


def _fetch_live_zhihu_direct() -> list[dict]:
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
                "热度": 0,
                "url": "",
            })
        logger.info("  zhihu: %d topics (direct API)", len(result))
        return result
    except Exception as e:
        logger.warning("  zhihu direct: %s", e)
        return []


def _fetch_all_live() -> list[dict]:
    """Fetch live hot topics from all 5 platforms, filter for tech.

    Uses direct platform APIs first, 60s.viki.moe aggregator as fallback.
    Returns list of {title, source, url, summary} dicts.
    """
    all_items: list[dict] = []

    # Weibo: only via 60s.viki.moe (native API is in daily_topics.py)
    weibo_items = _fetch_live_platform("weibo", LIVE_PLATFORMS["weibo"])
    for item in weibo_items:
        item["_platform"] = "weibo"
    all_items.extend(weibo_items)

    # B站: official API first, aggregator fallback
    bili_items = _fetch_live_bilibili()
    for item in bili_items:
        item["_platform"] = "bili"
    all_items.extend(bili_items)

    # Baidu: direct official API first, 60s.viki.moe fallback
    baidu_items = _fetch_live_baidu_direct()
    if baidu_items:
        for item in baidu_items:
            item["_platform"] = "baidu"
        all_items.extend(baidu_items)
    else:
        fallback = _fetch_live_platform("baidu", LIVE_PLATFORMS["baidu"])
        for item in fallback:
            item["_platform"] = "baidu"
        all_items.extend(fallback)

    # Douyin: direct official API first, 60s.viki.moe fallback
    douyin_items = _fetch_live_douyin_direct()
    if douyin_items:
        for item in douyin_items:
            item["_platform"] = "douyin"
        all_items.extend(douyin_items)
    else:
        fallback = _fetch_live_platform("douyin", LIVE_PLATFORMS["douyin"])
        for item in fallback:
            item["_platform"] = "douyin"
        all_items.extend(fallback)

    # Zhihu: direct top_search API first, 60s.viki.moe fallback
    zhihu_items = _fetch_live_zhihu_direct()
    if zhihu_items:
        for item in zhihu_items:
            item["_platform"] = "zhihu"
        all_items.extend(zhihu_items)
    else:
        fallback = _fetch_live_platform("zhihu", LIVE_PLATFORMS["zhihu"])
        for item in fallback:
            item["_platform"] = "zhihu"
        all_items.extend(fallback)

    logger.info("Live fetch: %d total items across 5 platforms", len(all_items))

    # Filter for tech/digital topics
    tech_items = [t for t in all_items if _is_tech_topic(t.get("title", ""))]
    logger.info("Tech filter: %d/%d passed", len(tech_items), len(all_items))

    # Convert to candidate format
    candidates: list[dict] = []
    for t in tech_items:
        candidates.append({
            "title": t.get("title", ""),
            "source": f"{t.get('_platform', '')}热搜",
            "url": t.get("url", ""),
            "summary": "",
        })
    return candidates


def _read_seed_file(seed_path: Path) -> list[dict]:
    """Read candidates from the seed file (offline fallback)."""
    candidates: list[dict] = []
    if seed_path.exists():
        for line in seed_path.read_text(encoding="utf-8").strip().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(" | ")]
            if len(parts) >= 2:
                candidates.append({
                    "title": parts[0],
                    "source": parts[1],
                    "url": parts[2] if len(parts) > 2 else "",
                    "summary": parts[3] if len(parts) > 3 else "",
                })
    return candidates


def _write_seed_file(seed_path: Path, candidates: list[dict]) -> None:
    """Persist live-fetched candidates to the seed file for offline fallback."""
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [
        f"# 选题种子库 — 自动更新于 {today}",
        "# 每日从微博/知乎/百度/抖音/B站热搜实时采集数码相关话题",
        "# 格式: 标题 | 来源 | URL | 摘要",
    ]
    for c in candidates:
        lines.append(f"{c['title']} | {c['source']} | {c.get('url', '')} | {c.get('summary', '')}")
    seed_path.parent.mkdir(parents=True, exist_ok=True)
    seed_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Seed file updated: %s (%d topics)", seed_path, len(candidates))


def scrape_hot_topics(seed_file: str | Path = "output/daily/topics_seed.txt") -> list[dict]:
    """Scrape hot topics from multiple sources.

    Priority order:
      1. LIVE — fetch real-time hot searches from Weibo/Zhihu/Baidu/Douyin/Bilibili
         via 60s.viki.moe aggregator + B站 official API; filter for tech/digital topics
      2. CACHED — fall back to the seed file if all live APIs are unreachable
      3. HARDCODED — last-resort built-in SEED_TOPICS

    Each returned dict has: title, source, url, summary.
    Live results are persisted to the seed file for offline resilience.
    """
    seed_path = Path(seed_file)
    if not seed_path.is_absolute():
        seed_path = Path.cwd() / seed_file

    candidates: list[dict] = []

    # 1. PRIMARY: fetch live hot topics from all 5 platforms
    logger.info("Attempting live hot-topic fetch from 5 platforms...")
    try:
        live_candidates = _fetch_all_live()
        if live_candidates:
            candidates = live_candidates
            logger.info("Live fetch succeeded: %d tech topics", len(candidates))
            # Persist to seed file for offline fallback
            try:
                _write_seed_file(seed_path, candidates)
            except Exception as e:
                logger.warning("Failed to write seed file: %s", e)
    except Exception as e:
        logger.warning("Live fetch failed: %s", e)

    # 2. FALLBACK: read from cached seed file
    if not candidates:
        logger.info("Live fetch empty/failed, falling back to seed file: %s", seed_path)
        candidates = _read_seed_file(seed_path)

    # 3. LAST RESORT: hardcoded built-in topics
    if not candidates:
        logger.info("Seed file also empty, using built-in SEED_TOPICS (%d topics)", len(SEED_TOPICS))
        candidates = [dict(t) for t in SEED_TOPICS]

    # Deduplicate by title (case-insensitive, normalized)
    seen: set[str] = set()
    unique: list[dict] = []
    for c in candidates:
        key = c["title"].strip().lower()
        if key not in seen:
            seen.add(key)
            unique.append(c)
    logger.info("Scraped %d unique topic candidates", len(unique))
    return unique


# ============================================================
# LLM scoring
# ============================================================

SCORING_SYSTEM_PROMPT = """你是选题评分专家，为短视频科技博主评估选题价值。博主风格：硬核技术流，敢说真话，注重实测和真实体验。

为每个候选选题在6个维度上打分(1-10分)：

| 维度 | 含义 | 高分标准 |
|------|------|----------|
| 热度 | 当前是否在风口上？ | 平台热榜话题、行业大事、新品发布期 |
| 信息差 | 是否有非显而易见的洞察？ | 有内行才知道的门道、数据解读、背后逻辑 |
| 争议性 | 能否引发讨论？ | 有不同观点碰撞空间、能打破共识、引发弹幕 |
| 人设匹配 | 是否符合博主风格？ | 硬核技术流、实测拆解、性价比分析、说真话 |
| 实操价值 | 观众看完能不能马上用？ | 选购指南、避坑技巧、省钱攻略、DIY教程 |
| 差异化空间 | 你能讲出和别人不同的角度吗？ | 有个人真实经历可讲、独到见解、一手实测 |

评分原则：
- 基于选题标题和摘要判断，不要凭空猜测
- 不同选题之间相对比较，拉开差距
- 总分=各维度之和，满分60

返回纯JSON数组（不要markdown代码块）：
[{"title": "原标题", "scores": {"热度": 8, "信息差": 7, "争议性": 6, "人设匹配": 9, "实操价值": 8, "差异化空间": 7}, "total_score": 45, "reason": "一句话理由，20字以内"}]"""


def score_topics(
    candidates: list[dict],
    persona: str = "折腾到吐",
    category_focus: str = "tech",
) -> list[TopicCandidate]:
    """Score candidate topics on 6 dimensions via DeepSeek LLM.

    Args:
        candidates: list of {title, source, url, summary} dicts
        persona: creator persona name for persona-fit scoring
        category_focus: tech / finance / ai / auto / all

    Returns:
        list of TopicCandidate with scores populated
    """
    if not candidates:
        logger.warning("No candidates to score")
        return []

    # Build a compact candidate list for the LLM
    candidate_lines = []
    for i, c in enumerate(candidates, 1):
        summary = c.get("summary", "") or ""
        candidate_lines.append(f"{i}. 【{c['title']}】\n   摘要: {summary}\n   来源: {c.get('source', '')}")

    candidates_text = "\n".join(candidate_lines)

    # Augment system prompt with persona + focus context
    persona_note = ""
    if persona == "折腾到吐":
        persona_note = "\n博主人设补充：硬核数码博主，擅长价格对飚和参数翻译。重数据、重实测、敢说缺点。"
    elif persona == "好设牛啊":
        persona_note = "\n博主人设补充：设计美学导向，关注颜值、做工细节和使用体验。"
    elif persona == "朋克":
        persona_note = "\n博主人设补充：游戏宅朋克风，二次元/电竞调性，热血快节奏。"
    elif persona == "超机懂":
        persona_note = "\n博主人设补充：极客懂王，技术深度解说，冷静专业。"

    focus_note = ""
    if category_focus == "ai":
        focus_note = "\n重点关注AI/大模型/智能体相关选题，科技类次之。"
    elif category_focus == "finance":
        focus_note = "\n重点关注财经/创业/商业模式选题，科技变现角度优先。"
    elif category_focus == "auto":
        focus_note = "\n重点关注新能源汽车/智能驾驶选题。"
    # "tech" and "all" — no extra focus bias

    system = SCORING_SYSTEM_PROMPT + persona_note + focus_note

    user = f"""请为以下{len(candidates)}个候选选题打分。\n\n候选选题列表：\n{candidates_text}\n\n直接返回JSON数组，不要其他内容。"""

    logger.info("Scoring %d topics via %s (persona=%s, focus=%s)",
                len(candidates), DEEPSEEK_MODEL, persona, category_focus)

    client = _get_client()
    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.3,  # lower temp for more consistent scoring
        max_tokens=4096,
    )

    raw = response.choices[0].message.content.strip()

    # Parse JSON — the LLM might wrap in ```json ... ```
    if raw.startswith("```"):
        # Strip code fences
        lines = raw.splitlines()
        # Remove first line (```json or ```) and last line (```)
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines)

    try:
        scored_data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM JSON response, raw: %s", raw[:500])
        # Fallback: return candidates with zero scores
        return [TopicCandidate(
            title=c["title"],
            source=c.get("source", ""),
            url=c.get("url", ""),
            summary=c.get("summary", ""),
            reason="评分解析失败，请重试",
        ) for c in candidates]

    # Build TopicCandidate list
    results: list[TopicCandidate] = []
    for item in scored_data:
        tc = TopicCandidate(
            title=item.get("title", ""),
            source="",  # we'll match back from original
            url="",
            summary="",
            scores=item.get("scores", {}),
            total_score=float(item.get("total_score", 0)),
            reason=item.get("reason", ""),
        )
        results.append(tc)

    # Match back original metadata (source/url/summary) by fuzzy title match
    for tc in results:
        for orig in candidates:
            if _titles_match(tc.title, orig["title"]):
                tc.source = orig.get("source", tc.source)
                tc.url = orig.get("url", tc.url)
                tc.summary = orig.get("summary", tc.summary)
                break

    logger.info("Scored %d topics", len(results))
    return results


def _titles_match(a: str, b: str) -> bool:
    """Fuzzy title matching — handles minor LLM rewording."""
    a_clean = a.strip().lower().replace(" ", "").replace("：", ":").replace("，", ",")
    b_clean = b.strip().lower().replace(" ", "").replace("：", ":").replace("，", ",")
    # Exact match after normalization
    if a_clean == b_clean:
        return True
    # One contains the other (LLM might have truncated)
    if len(a_clean) >= 6 and len(b_clean) >= 6:
        if a_clean[:20] == b_clean[:20]:
            return True
        if a_clean in b_clean or b_clean in a_clean:
            return True
    return False


# ============================================================
# Full pipeline
# ============================================================

DIMENSION_LABELS = ["热度", "信息差", "争议性", "人设匹配", "实操价值", "差异化空间"]


def generate_daily_brief(
    persona: str = "折腾到吐",
    category_focus: str = "tech",
    top_n: int = 5,
) -> DailyBrief:
    """Full pipeline: scrape → score → rank → package.

    Args:
        persona: creator persona for scoring bias
        category_focus: tech / finance / ai / auto / all
        top_n: number of top topics to return

    Returns:
        DailyBrief with ranked topics
    """
    logger.info("=== 选题日报 Pipeline Start ===")
    logger.info("Persona: %s | Focus: %s | Top N: %d", persona, category_focus, top_n)

    # Step 1: Scrape candidates
    candidates = scrape_hot_topics()
    if not candidates:
        raise RuntimeError("No topic candidates found — check seed file or network")

    # Step 2: Score via LLM
    scored = score_topics(candidates, persona=persona, category_focus=category_focus)

    # Step 3: Sort by total_score descending
    scored.sort(key=lambda t: t.total_score, reverse=True)

    # Step 4: Take top N
    top_topics = scored[:top_n]

    today = datetime.now().strftime("%Y-%m-%d")
    brief = DailyBrief(
        date=today,
        topics=top_topics,
        generated_at=datetime.now().isoformat(),
    )

    logger.info("=== 选题日报 Pipeline Complete: %d topics ranked ===", len(top_topics))
    return brief


# ============================================================
# Pretty-print
# ============================================================

def format_daily_brief(brief: DailyBrief) -> str:
    """Format a DailyBrief into a readable text report."""
    lines = []
    lines.append("")
    lines.append(f"选题日报 — {brief.date}")
    lines.append("=" * 60)
    lines.append(f"Top {len(brief.topics)} 选题:")
    lines.append("-" * 60)

    for i, topic in enumerate(brief.topics, 1):
        # Build score bar
        dim_parts = []
        for dim in DIMENSION_LABELS:
            val = topic.scores.get(dim, 0)
            dim_parts.append(f"{dim}:{val}")
        dim_line = " | ".join(dim_parts)

        lines.append(f"#{i} [总分: {topic.total_score:.0f}/60] {topic.title}")
        lines.append(f"   {dim_line}")
        if topic.reason:
            lines.append(f"   理由: {topic.reason}")
        if topic.source:
            source_info = topic.source
            if topic.url:
                source_info += f" ({topic.url})"
            lines.append(f"   来源: {source_info}")
        lines.append("-" * 60)

    lines.append("")
    lines.append("=" * 60)
    lines.append("柱子哥提醒: 信息不值钱，观点值钱。选你有个人经验可讲的。")
    lines.append("=" * 60)
    lines.append("")

    return "\n".join(lines)


# ============================================================
# CLI entry point (called from cli.py)
# ============================================================

OUTPUT_DIR = Path("output/daily")
CACHE_PATH = OUTPUT_DIR / "_topic_cache.json"
MAX_CACHE_AGE_DAYS = 7


def _date_prefix(date_str: str) -> str:
    """Convert '2026-06-30' or '2026年06月30日' to '20260630'."""
    import re
    digits = re.sub(r'\D', '', date_str)
    return digits[:8] if len(digits) >= 8 else date_str.replace("-", "")


def _save_reports(brief: DailyBrief, topics_text: str) -> None:
    """Persist daily brief as MD report + HTML report + cache update + file index."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today = brief.date
    prefix = _date_prefix(today)

    report_md = OUTPUT_DIR / f"{prefix}_选题日报.md"
    report_html = OUTPUT_DIR / f"{prefix}_选题日报.html"

    # --- Markdown report (table format) ---
    md_lines = [
        f"# 数码圈每日热点选题报告",
        f"**{today}** | 微博/知乎/百度/抖音/B站热搜 | {len(brief.topics)} 条数码相关",
        "",
        "## TOP 15",
        "",
        "| # | 话题 | 平台 | 排名 | 分 | 选题方向 |",
        "|---|------|------|------|-----|----------|",
    ]
    for i, t in enumerate(brief.topics, 1):
        title = t.title[:45]
        source = t.source.replace("热搜", "") if t.source else "?"
        total = int(t.total_score)
        # Determine format tag
        fmt = "热点评论"
        if any(k in t.title for k in ["评测", "实测", "对比", "推荐", "选购", "盘点"]):
            fmt = "选购指南"
        elif any(k in t.title for k in ["发布", "新品", "上市", "开售"]):
            fmt = "新品速览"
        elif any(k in t.title for k in ["AI", "芯片", "技术", "原理", "大模型"]):
            fmt = "深度解读"
        md_lines.append(f"| {i} | {title} | {source} | #99 | {total} | {fmt} |")
    report_md.write_text("\n".join(md_lines), encoding="utf-8")
    logger.info("MD report saved: %s", report_md)

    # --- HTML report ---
    html = _build_html_report(brief)
    report_html.write_text(html, encoding="utf-8")
    logger.info("HTML report saved: %s (%d chars)", report_html, len(html))

    # --- Cache update ---
    try:
        cache = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else []
    except Exception:
        cache = []
    top_score = max((t.total_score for t in brief.topics), default=0)
    cache.append({"date": today, "count": len(brief.topics), "top_score": top_score})
    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(days=MAX_CACHE_AGE_DAYS)).isoformat()
    cache = [e for e in cache if e.get("date", "") >= cutoff[:10]]
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Cache updated: %s", CACHE_PATH)

    # --- Output file index ---
    try:
        from rag_system.utils.index_writer import write_index
        idx_path = write_index()
        logger.info("File index updated: %s", idx_path)
    except Exception as e:
        logger.warning("Failed to update file index: %s", e)


def _build_html_report(brief: DailyBrief) -> str:
    """Build a rich HTML report for the daily topic brief."""
    topics_json = []
    for i, t in enumerate(brief.topics, 1):
        dims = {}
        for d in DIMENSION_LABELS:
            dims[d] = t.scores.get(d, 0)
        topics_json.append({
            "rank": i, "title": t.title,
            "platform": t.source.replace("热搜", "") if t.source else "",
            "score": int(t.total_score),
            "scores": dims,
            "reason": t.reason,
            "url": t.url,
        })

    data_json = json.dumps({
        "date": brief.date,
        "count": len(topics_json),
        "topScore": max((tp["score"] for tp in topics_json), default=0),
        "topics": topics_json,
    }, ensure_ascii=False, indent=2)

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>数码圈每日热点选题 — {brief.date}</title>
<style>
:root{{--paper:#FAF7F2;--ink:#1C1C1C;--ink-light:#5C5C5C;--ink-muted:#999;--accent:#C03A2B;--gold:#B8960C;--divider:#E5E0D8;--card-bg:#FFFFFF;--tag-bg:#F3F0EA;--tag-text:#6B6258;--bar-bg:#EDE9E2;--weibo:#E6162D;--zhihu:#0066FF;--baidu:#2932E1;--douyin:#1E1E1E;--bili:#FB7299}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:"Noto Sans SC","PingFang SC","Microsoft YaHei",sans-serif;background:#EDE8DE;color:var(--ink);line-height:1.6}}
.container{{max-width:900px;margin:0 auto;padding:48px 24px 64px}}
.paper{{background:var(--card-bg);border-radius:4px;box-shadow:0 1px 3px rgba(0,0,0,.04),0 8px 32px rgba(0,0,0,.06);overflow:hidden}}
.paper::before{{content:'';display:block;height:4px;background:linear-gradient(90deg,var(--accent) 0%,var(--accent) 40%,var(--gold) 40%,var(--gold) 42%,var(--accent) 42%,var(--accent) 100%)}}
.masthead{{padding:44px 48px 28px;border-bottom:2px solid var(--ink)}}
.masthead h1{{font-family:"Noto Serif SC",serif;font-size:34px;font-weight:900;letter-spacing:-.5px;line-height:1.2;margin-bottom:8px}}
.subtitle{{font-size:14px;color:var(--ink-light);font-weight:300}}
.stats-row{{display:flex;gap:32px;margin-top:20px}}
.stat-item{{display:flex;flex-direction:column}}
.stat-num{{font-family:"Noto Serif SC",serif;font-size:28px;font-weight:900;color:var(--accent);line-height:1}}
.stat-label{{font-size:11px;color:var(--ink-muted);letter-spacing:1px;margin-top:2px}}
.content{{padding:36px 48px 48px}}
.section-header{{display:flex;align-items:center;gap:12px;margin:12px 0 24px}}
.section-header h2{{font-family:"Noto Serif SC",serif;font-size:18px;font-weight:700;white-space:nowrap}}
.section-header .rule{{flex:1;height:1px;background:var(--divider)}}
.topic-card{{border:1px solid var(--divider);border-radius:4px;padding:20px 24px;margin-bottom:14px;transition:box-shadow .2s}}
.topic-card:hover{{box-shadow:0 4px 16px rgba(0,0,0,.06)}}
.topic-card-header{{display:flex;align-items:flex-start;gap:16px;margin-bottom:10px}}
.topic-rank{{font-family:"Noto Serif SC",serif;font-size:28px;font-weight:900;width:40px;text-align:center;color:var(--ink-muted);flex-shrink:0;line-height:1.1}}
.topic-card:nth-child(1) .topic-rank{{color:var(--accent)}}
.topic-card:nth-child(2) .topic-rank{{color:#D4683A}}
.topic-card:nth-child(3) .topic-rank{{color:#C08030}}
.topic-title-main{{font-size:16px;font-weight:600;line-height:1.4;flex:1}}
.topic-meta-row{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:6px}}
.platform-badge{{display:inline-flex;align-items:center;padding:2px 10px;border-radius:3px;font-size:11px;font-weight:600}}
.platform-badge.weibo{{background:#FFF0F0;color:var(--weibo)}}
.platform-badge.zhihu{{background:#F0F4FF;color:var(--zhihu)}}
.platform-badge.baidu{{background:#F0F1FF;color:var(--baidu)}}
.platform-badge.douyin{{background:#F5F5F5;color:var(--douyin)}}
.platform-badge.bili{{background:#FFF0F4;color:var(--bili)}}
.score-pill{{font-size:14px;font-weight:700;color:var(--accent)}}
.score-bar{{display:flex;gap:3px;margin-top:8px;flex-wrap:wrap}}
.score-dim{{font-size:10px;padding:3px 8px;border-radius:3px;background:var(--tag-bg);color:var(--tag-text)}}
.score-dim strong{{color:var(--ink)}}
.topic-reason{{margin-top:8px;font-size:12px;color:var(--ink-light);font-style:italic}}
.colophon{{margin-top:48px;padding-top:24px;border-top:1px solid var(--divider);display:flex;justify-content:space-between;font-size:11px;color:var(--ink-muted)}}
@media(max-width:700px){{.container{{padding:16px 12px 32px}}.masthead{{padding:28px 24px 20px}}.masthead h1{{font-size:24px}}.content{{padding:24px 20px 32px}}.topic-card{{padding:16px}}.topic-title-main{{font-size:14px}}}}
</style>
</head>
<body>
<div class="container"><div class="paper">
<div class="masthead">
<h1>数码圈每日热点选题</h1>
<p class="subtitle">聚合微博/知乎/百度/抖音/B站热搜 · AI筛选 · 6维度评分</p>
<div class="stats-row">
<div class="stat-item"><span class="stat-num">{len(topics_json)}</span><span class="stat-label">数码相关话题</span></div>
<div class="stat-item"><span class="stat-num">5</span><span class="stat-label">数据平台</span></div>
<div class="stat-item"><span class="stat-num">{max((tp["score"] for tp in topics_json), default=0)}</span><span class="stat-label">最高评分</span></div>
</div></div>
<div class="content">
<div class="section-header"><h2>热搜话题排行</h2><span class="rule"></span></div>
<div id="cards"></div>
<div class="colophon">
<span>{brief.date} · 每日自动更新</span>
<span>柱子哥 · 选题策略</span>
</div>
</div></div></div>
<script>
var D={data_json};
var PLAT_CN={{"weibo":"微博","zhihu":"知乎","baidu":"百度","douyin":"抖音","bili":"B站"}};
var DIMS=["热度","信息差","争议性","人设匹配","实操价值","差异化空间"];
var c=document.getElementById("cards");
D.topics.forEach(function(t,i){{
  var bw=Math.min(t.score/60*100,100);
  var plat=t.platform||"";
  var dimTags=DIMS.map(function(d){{return'<span class="score-dim">'+d+' <strong>'+(t.scores[d]||0)+'</strong></span>';}}).join("");
  var d=document.createElement("div");
  d.className="topic-card";
  d.innerHTML='<div class="topic-card-header"><span class="topic-rank">'+t.rank+'</span><div class="topic-title-main">'+t.title+'<div class="topic-meta-row"><span class="platform-badge '+plat+'">'+(PLAT_CN[plat]||plat)+'</span><span class="score-pill">'+t.score+'/60分</span></div><div class="score-bar">'+dimTags+'</div>'+(t.reason?'<div class="topic-reason">'+t.reason+'</div>':'')+'</div></div>';
  c.appendChild(d);
}});
</script>
</body>
</html>"""
    return html


def run_topic_daily(
    persona: str = "折腾到吐",
    category_focus: str = "tech",
    top_n: int = 5,
    output: str | None = None,
) -> str:
    """Entry point for the CLI command.

    Returns the formatted text AND writes MD+HTML reports + cache to output/daily/.
    """
    brief = generate_daily_brief(persona=persona, category_focus=category_focus, top_n=top_n)
    text = format_daily_brief(brief)

    # Persist reports to disk
    try:
        _save_reports(brief, text)
    except Exception as e:
        logger.warning("Failed to save reports: %s", e)

    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        logger.info("Daily brief saved to: %s", out_path)

    return text, brief
