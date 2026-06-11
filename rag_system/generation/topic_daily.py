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

def scrape_hot_topics(seed_file: str | Path = "output/daily/topics_seed.txt") -> list[dict]:
    """Scrape hot topics from multiple accessible sources.

    Priority order:
      1. User-maintained seed file (output/daily/topics_seed.txt)
      2. Hardcoded SEED_TOPICS as fallback

    Each returned dict has: title, source, url, summary

    The user can update the seed file manually or via any external
    scraper/WebSearch. The format is one topic per line:
        title | source | url | summary
    Fields are separated by " | " (space-pipe-space).
    """
    candidates: list[dict] = []

    # 1. Try reading from user-maintained seed file
    seed_path = Path(seed_file)
    if not seed_path.is_absolute():
        seed_path = Path.cwd() / seed_file

    if seed_path.exists():
        logger.info("Reading seed topics from: %s", seed_path)
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

    # 2. Fall back to hardcoded seeds if file is empty or missing
    if not candidates:
        logger.info("No seed file found or empty, using built-in SEED_TOPICS (%d topics)", len(SEED_TOPICS))
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

def run_topic_daily(
    persona: str = "折腾到吐",
    category_focus: str = "tech",
    top_n: int = 5,
    output: str | None = None,
) -> str:
    """Entry point for the CLI command.

    Returns the formatted text and optionally saves to file.
    """
    brief = generate_daily_brief(persona=persona, category_focus=category_focus, top_n=top_n)
    text = format_daily_brief(brief)

    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        logger.info("Daily brief saved to: %s", out_path)

    return text
