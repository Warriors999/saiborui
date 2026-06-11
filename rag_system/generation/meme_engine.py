"""Hot meme engine — fetch trending topics and weave them into script openings.

Workflow:
  1. Fetch trending memes from web (cached for 3 days)
  2. Match memes to product category/features with MIN_RELEVANCE threshold
  3. Generate natural opening bridging meme → product
  4. Fall back to product-native opening when no meme fits — NEVER force a mismatch

Design principles:
  - Relevance > freshness > cleverness
  - If a meme doesn't naturally connect to the product, don't use it
  - Evergreen phrasing patterns are safer than dated news hooks
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timedelta

from rag_system.utils import logger


MEME_CACHE_PATH = Path("data/meme_cache.json")
MEME_CACHE_TTL_HOURS = 72  # Refresh web cache every 3 days
CORE_MEME_MAX_AGE_DAYS = 30  # Core memes older than this are auto-deprecated
MIN_KEYWORD_OVERLAP = 2  # Minimum shared keywords to consider a meme relevant


@dataclass
class Meme:
    text: str
    source: str
    category: str  # tech / general / gaming / lifestyle
    keywords: list[str] = field(default_factory=list)
    fetched_at: str = ""
    added_date: str = ""  # ISO date when this meme was added to core list


# ============================================================
# Meme database — curated + web-fetched
# ============================================================

# Core memes — curated, evergreen phrasing patterns only.
# RULE: No dated news hooks. No forced tech-gag bridges.
# If a meme is tied to a specific event/person/date, don't add it.
# Each entry MUST have added_date for auto-expiry.
CORE_MEMES = [
    Meme("主打一个XX", "万能结论句式", "general",
         ["主打", "核心", "就一个", "简单", "直接"],
         added_date="2026-06-05"),
    Meme("夯爆了", "太厉害了超燃", "general",
         ["厉害", "强", "炸裂", "性能", "顶"],
         added_date="2026-06-05"),
    Meme("爱你老己", "反内耗自我关怀宣言", "general",
         ["自己", "内耗", "好一点", "值得", "升级", "换新"],
         added_date="2026-06-05"),
]

# Tech → category keyword mapping for meme matching.
# These MUST overlap with meme keywords to pass the relevance check.
CATEGORY_MEME_KEYWORDS = {
    "keyboard": ["手感", "打字", "游戏", "桌面", "外设", "轴体", "声音", "键盘"],
    "mouse": ["手感", "游戏", "重量", "桌面", "外设", "传感器", "鼠标"],
    "monitor": ["画面", "屏幕", "显示", "游戏", "桌面", "刷新"],
    "laptop": ["笔记本", "便携", "性能", "游戏", "办公", "续航"],
    "phone": ["手机", "游戏", "散热", "续航", "充电"],
    "gpu": ["显卡", "游戏", "帧数", "性能", "画质", "DLSS"],
    "headphone": ["耳机", "声音", "降噪", "游戏", "音乐"],
    "desk_chair": ["桌面", "坐", "舒服", "电竞", "RGB"],
    "speaker": ["声音", "音质", "桌面", "游戏", "音乐"],
}


def _load_cache() -> dict:
    if MEME_CACHE_PATH.exists():
        try:
            return json.loads(MEME_CACHE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"memes": [], "fetched_at": ""}


def _save_cache(data: dict):
    MEME_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    MEME_CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_cache_fresh(cache: dict) -> bool:
    fetched = cache.get("fetched_at", "")
    if not fetched:
        return False
    try:
        ft = datetime.fromisoformat(fetched)
        return datetime.now() - ft < timedelta(hours=MEME_CACHE_TTL_HOURS)
    except (ValueError, TypeError):
        return False


def _filter_stale_core_memes(memes: list[Meme]) -> list[Meme]:
    """Remove core memes older than CORE_MEME_MAX_AGE_DAYS."""
    cutoff = datetime.now() - timedelta(days=CORE_MEME_MAX_AGE_DAYS)
    fresh = []
    for m in memes:
        if m.added_date:
            try:
                added = datetime.fromisoformat(m.added_date)
                if added < cutoff:
                    logger.info("Deprecating stale core meme: %s (added %s)", m.text, m.added_date)
                    continue
            except (ValueError, TypeError):
                pass
        fresh.append(m)
    return fresh


def _load_seed_topics() -> list[Meme]:
    """Read trending topics from the seed file as meme candidates.

    The seed file (output/daily/topics_seed.txt) is maintained by the daily topics pipeline.
    Format: title | source | url | summary (one per line, | separated)
    """
    seed_path = Path("output/daily/topics_seed.txt")
    if not seed_path.exists():
        return []

    memes = []
    for line in seed_path.read_text(encoding="utf-8").strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 1 and parts[0]:
            title = parts[0]
            source = parts[1] if len(parts) > 1 else "种子库"
            # Extract keywords: split by common delimiters, then chunk into 2-4 char tokens
            import re as _re
            raw = _re.split(r'[：:，,。！？\s、？!]+', title)
            keywords = []
            for seg in raw:
                seg = seg.strip()
                if len(seg) >= 2:
                    # Also add 2-4 char sliding windows for partial matching
                    for win_size in [2, 3, 4]:
                        for i in range(len(seg) - win_size + 1):
                            chunk = seg[i:i+win_size]
                            if chunk not in keywords:
                                keywords.append(chunk)
            memes.append(Meme(
                text=title,
                source=source,
                category="tech",
                keywords=keywords,
                added_date=datetime.now().strftime("%Y-%m-%d"),
            ))

    logger.info("Loaded %d topics from seed file", len(memes))
    return memes


def get_active_memes(product_category: str = "", product_features: str = "") -> list[Meme]:
    """Get memes relevant to a product.

    Sources (in priority order):
      1. Cached web-fetched memes (if fresh)
      2. Seed file topics (output/daily/topics_seed.txt)
      3. Core memes (evergreen phrasing patterns)

    All sources are filtered by product category relevance with a minimum overlap threshold.
    """
    cache = _load_cache()

    if _is_cache_fresh(cache) and cache.get("memes"):
        memes = [Meme(**m) for m in cache["memes"]]
        logger.info("Using %d cached web memes (fresh)", len(memes))
    else:
        # Merge seed topics + core memes
        seed_memes = _load_seed_topics()
        core = _filter_stale_core_memes(CORE_MEMES)
        memes = seed_memes + core
        logger.info("Using %d seed topics + %d core memes", len(seed_memes), len(core))

    if product_category and memes:
        category_kw = CATEGORY_MEME_KEYWORDS.get(product_category, [])
        feature_kw = [w.strip() for w in product_features.replace(",", " ").split() if len(w.strip()) >= 2]
        all_kw = set(category_kw + feature_kw)

        scored = []
        for m in memes:
            overlap = len(set(m.keywords) & all_kw)
            scored.append((overlap, m))
        scored.sort(key=lambda x: x[0], reverse=True)
        # Two-tier relevance: seed topics (pre-vetted) need 1+ overlap, core memes need 2+
        seed_threshold = 1
        core_threshold = MIN_KEYWORD_OVERLAP  # 2
        relevant = []
        for s, m in scored:
            threshold = seed_threshold if m.source == "种子库" else core_threshold
            if s >= threshold:
                relevant.append((s, m))
        if relevant:
            memes = [m for _, m in relevant[:5]]
            logger.info("Meme relevance filter: %d passed (seed>=1, core>=%d)", len(memes), MIN_KEYWORD_OVERLAP)
        else:
            logger.info("No memes passed relevance threshold, falling back to no-meme opening")
            memes = []

    return memes


def update_meme_cache(memes: list[dict]):
    """Save web-fetched memes to cache."""
    _save_cache({
        "memes": memes,
        "fetched_at": datetime.now().isoformat(),
    })
    logger.info("Meme cache updated: %d memes", len(memes))


def pick_best_meme(product_category: str, product_name: str, product_features: str) -> Meme | None:
    """Pick the single best meme for a product opening. Returns None if nothing fits.

    Relevance is already enforced by get_active_memes (MIN_KEYWORD_OVERLAP threshold).
    If no meme passes, this returns None → caller uses product-native opening.
    """
    memes = get_active_memes(product_category, product_features)
    if not memes:
        return None
    return memes[0]


def meme_opening_prompt(meme: Meme, product_name: str, persona: str) -> str:
    """Generate the prompt snippet that instructs the LLM to use a trending topic opening.

    Two modes depending on the meme source:
      - Seed file topics (source='种子库'): Real industry discussion → natural bridge
      - Core memes (source='万能句式'): Phrasing pattern → use the rhythm, not the literal text
    """
    is_seed_topic = meme.source == "种子库"

    if is_seed_topic:
        return f"""
## 开场要求 — 数码圈正在讨论的热点话题

最近数码圈有一个跟{product_name}相关的话题：「{meme.text}」

你可以用这个话题自然引入。规则：
- 用这个话题作为认知锚点——"最近大家都在讨论XX"或"XX这个话题最近很热"
- 然后自然过渡到{product_name}在这个话题中的位置
- 话题是引子，不是主体——2-3句话点到为止，迅速转入产品
- **禁止**用"养龙虾""AI小龙虾"等跟产品毫无关系的梗
- 全文第一句就是开场，不要用"嗨喽大家好""大家好我是XX"
"""
    else:
        return f"""
## 开场要求（可选热点挂钩）
你可以借用「{meme.text}」这个网络热梗的句式或情绪来开场，但必须遵守以下规则：
- **绝对禁止**说"最近有个梗""最近流行""最近火了"等时效性描述——你把梗当句式用，不是当新闻报
- **禁止生硬桥接**：如果梗和{product_name}之间没有天然的情绪/场景连接，直接放弃，用产品直开
- 正确用法：吸收梗的语气和节奏，不念梗的名字
- 全文第一句就是开场，不要用"嗨喽大家好""大家好我是XX"等传统开场
"""


def no_meme_opening_prompt(persona: str) -> str:
    """Fallback opening instruction when no meme fits. This is the SAFE DEFAULT."""
    return f"""
## 开场要求
- 不要用"嗨喽大家好""大家好我是XX"等传统开场
- 第一句话直接进入主题，从以下四种方式中选一种：
  1. 痛点共鸣：描述一个观众立刻能代入的使用场景/困扰
  2. 大胆断言：一句不可辩驳的产品判断，越具体越好
  3. 反常识提问：一个颠覆观众认知的问题
  4. 价格/参数反差：一个数字让观众停下滑动的手指
- 禁止用与产品无关的网络热点、社会新闻、或过时的梗来开场
"""
