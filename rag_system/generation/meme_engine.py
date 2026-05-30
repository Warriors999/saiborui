"""Hot meme engine — fetch trending topics and weave them into script openings.

Workflow:
  1. Fetch trending memes from web (cached for 3 days)
  2. Match memes to product category/features
  3. Generate natural opening bridging meme → product
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timedelta

from rag_system.utils import logger


MEME_CACHE_PATH = Path("data/meme_cache.json")
MEME_CACHE_TTL_HOURS = 72  # Refresh every 3 days


@dataclass
class Meme:
    text: str
    source: str
    category: str  # tech / general / gaming / lifestyle
    keywords: list[str] = field(default_factory=list)
    fetched_at: str = ""


# ============================================================
# Meme database — curated + web-fetched
# ============================================================

# Core memes — manually curated, high-quality, always available
CORE_MEMES = [
    Meme("养龙虾/AI小龙虾", "科技圈OpenClaw梗", "tech",
         ["AI", "自动", "干活", "摸鱼", "龙虾", "靠谱", "替代"]),
    Meme("三代禁学计算机", "程序员圈集体自嘲", "tech",
         ["程序员", "IT", "计算机", "内卷", "35岁", "行业", "劝退"]),
    Meme("能工智人", "打工人自嘲是人肉AI", "tech",
         ["打工人", "AI", "智能", "人工", "替代", "摸鱼"]),
    Meme("半开笔记本电脑", "AI任务不能断的新怪象", "tech",
         ["笔记本", "电脑", "AI", "便携", "移动", "任务"]),
    Meme("爱你老己", "反内耗自我关怀宣言", "general",
         ["自己", "内耗", "好一点", "值得", "升级", "换新"]),
    Meme("硅基文明复读机", "AI内容全在重复", "tech",
         ["AI", "重复", "复读", "模板", "智能", "真正"]),
    Meme("主打一个XX", "万能结论句式", "general",
         ["主打", "核心", "就一个", "简单", "直接"]),
    Meme("夯爆了", "太厉害了超燃", "general",
         ["厉害", "强", "炸裂", "性能", "顶"]),
    Meme("赛博文艺复兴", "老东西突然翻红", "tech",
         ["复古", "翻红", "经典", "回归", "老"]),
    Meme("精神离职", "人在工位心在远方", "general",
         ["上班", "工位", "摸鱼", "效率", "不想干"]),
    Meme("狗出大事了没空跟你解释", "摆烂万能借口", "general",
         ["出大事", "来不及", "紧急", "快", "直接"]),
]

# Tech → category keyword mapping for meme matching
CATEGORY_MEME_KEYWORDS = {
    "keyboard": ["手感", "打字", "游戏", "桌面", "外设", "轴体", "声音"],
    "mouse": ["手感", "游戏", "重量", "桌面", "外设", "传感器"],
    "monitor": ["画面", "屏幕", "显示", "游戏", "桌面", "刷新"],
    "laptop": ["笔记本", "便携", "性能", "游戏", "办公", "续航"],
    "phone": ["手机", "游戏", "散热", "续航", "充电"],
    "gpu": ["显卡", "游戏", "帧数", "性能", "画质", "DLSS"],
    "headphone": ["耳机", "声音", "降噪", "游戏", "音乐"],
    "desk_chair": ["桌面", "坐", "舒服", "电竞", "RGB"],
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


def get_active_memes(product_category: str = "", product_features: str = "") -> list[Meme]:
    """Get memes relevant to a product.

    Uses cached web-fetched memes if fresh, otherwise falls back to core memes.
    Filters by product category relevance.
    """
    cache = _load_cache()

    if _is_cache_fresh(cache) and cache.get("memes"):
        memes = [Meme(**m) for m in cache["memes"]]
        logger.info("Using %d cached web memes (fresh)", len(memes))
    else:
        memes = CORE_MEMES
        logger.info("Using %d core memes (cache stale or empty)", len(memes))

    if product_category:
        category_kw = CATEGORY_MEME_KEYWORDS.get(product_category, [])
        feature_kw = [w.strip() for w in product_features.replace(",", " ").split() if len(w.strip()) >= 2]
        all_kw = set(category_kw + feature_kw)

        scored = []
        for m in memes:
            overlap = len(set(m.keywords) & all_kw)
            scored.append((overlap, m))
        scored.sort(key=lambda x: x[0], reverse=True)
        memes = [m for _, m in scored[:5]]

    return memes


def update_meme_cache(memes: list[dict]):
    """Save web-fetched memes to cache."""
    _save_cache({
        "memes": memes,
        "fetched_at": datetime.now().isoformat(),
    })
    logger.info("Meme cache updated: %d memes", len(memes))


def pick_best_meme(product_category: str, product_name: str, product_features: str) -> Meme | None:
    """Pick the single best meme for a product opening. Returns None if nothing fits."""
    memes = get_active_memes(product_category, product_features)
    if not memes:
        return None
    return memes[0]


def meme_opening_prompt(meme: Meme, product_name: str, persona: str) -> str:
    """Generate the prompt snippet that instructs the LLM to use a meme opening."""
    return f"""
## 开场要求
用近期网络热梗「{meme.text}」自然引入。不要生硬念梗——先提到这个梗在数码圈/网络上的传播，然后自然过渡到{product_name}。
- 第一句话必须提到梗，但不能说"最近有个梗叫..."
- 梗和产品之间必须有逻辑关联
- 全文第一句就是开场，不要先自我介绍
- 不要用"嗨喽大家好""大家好我是XX"等传统开场
"""


def no_meme_opening_prompt(persona: str) -> str:
    """Fallback opening instruction when no meme fits."""
    return f"""
## 开场要求
- 不要用"嗨喽大家好""大家好我是XX"等传统开场
- 第一句话直接进入主题：痛点共鸣/大胆断言/反常识提问/价格反差
- 用一个观众能立刻共鸣的场景或问题开头
"""
