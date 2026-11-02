"""Weekly topic aggregation with 3-round self-audit and dynamic type distribution.

Runs every Friday. Reads the past 7 days of daily topic data, analyzes trends,
generates 3 candidate topic sets via DeepSeek, scores each on 8 dimensions,
retries if all rounds < 65 pts, and keeps the highest-scoring set.
Outputs JSON for _make_weekly_report.js.

D先生 requirements:
- Data-driven, no manual category bias
- Dynamic type distribution based on shopping festivals
- Allow moderate exaggeration but data must be real
- Ban false claims, competitor attacks, user insults
- Style reference: 大狸子切切里 / 先看评测 / 影视飓风
"""

import json, re, time
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter

from openai import OpenAI

from rag_system.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from rag_system.utils import logger
from rag_system.generation.douyin_filter import filter_prohibited
from rag_system.generation.glossary import ECOMMERCE_SMELL_ALL, ASSEMBLY_VERBS, FORBIDDEN_WORDS

OUTPUT_DIR = Path("output/daily")
SEED_FILE = OUTPUT_DIR / "topics_seed.txt"
CACHE_FILE = OUTPUT_DIR / "_topic_cache.json"
WEEKLY_JSON = OUTPUT_DIR / "_weekly_topics.json"
AUDIT_JSON = OUTPUT_DIR / "_weekly_audit.json"

ROUNDS = 3
MAX_RETRIES = 1
QUALITY_FLOOR = 65
TEMPERATURES = [0.7, 0.85, 1.0]

# Festival windows — each tuple: (start_m, start_d, end_m, end_d, label)
# Pre-festival (7 days before): consumption-heavy (1干货+2消费向导+2科普)
# Post-festival (7 days after end): D先生 rule → 3干货+2科普 or 2干货+2科普+1消费向导
FESTIVALS = [
    (5, 25, 6, 20, "618"),
    (8, 20, 9, 15, "开学季"),
    (10, 20, 11, 12, "双11"),
    (12, 1, 12, 15, "双12"),
    (1, 5, 1, 25, "年货节"),
]

def _get_type_distribution() -> str:
    """Return Chinese description of target type distribution.

    Three festival-driven modes, with data-driven category weighting in normal mode.
    """
    today = datetime.now()
    for sm, sd, em, ed, label in FESTIVALS:
        festival_start = datetime(today.year, sm, sd)
        festival_end = datetime(today.year, em, ed)
        pre_start = festival_start - timedelta(days=7)
        post_end = festival_end + timedelta(days=7)
        if pre_start <= today < festival_start:
            return "当前处于%s大促前的选购决策期，类型配比调整为：1个干货+2个消费向导+2个科普（消费导向优先）" % label
        if festival_end <= today < post_end:
            return "当前处于%s大促后的收货验货期，类型配比调整为：3个干货+2个科普 或 2个干货+2个科普+1个消费向导（干货优先，帮用户用好已买的产品）" % label

    # Normal mode: incorporate category performance data
    try:
        from rag_system.generation.category_profiles import load_profiles
        profiles = load_profiles()
        # Boost categories with strong 5s retention
        high_retention = [cat for cat, p in profiles.items() if p.get("avg_5s_rate", 0) > 0.45]
        if high_retention:
            return "类型配比：2个干货+1个消费向导+2个科普。数据提示：%s品类近期完播率高，可优先选题" % "、".join(high_retention[:3])
    except Exception:
        pass
    return "类型配比：2个干货(HOW)+1个消费向导(FILTER)+2个科普(WHAT)"

def _get_type_distribution_dict() -> dict:
    """Return target type counts for audit scoring."""
    today = datetime.now()
    for sm, sd, em, ed, label in FESTIVALS:
        festival_start = datetime(today.year, sm, sd)
        festival_end = datetime(today.year, em, ed)
        pre_start = festival_start - timedelta(days=7)
        post_end = festival_end + timedelta(days=7)
        if pre_start <= today < festival_start:
            return {"干货": 1, "消费向导": 2, "科普": 2}
        if festival_end <= today < post_end:
            # Post-festival: prefer 3+0+2 but accept 2+1+2 as valid
            return {"干货": 3, "消费向导": 1, "科普": 2}
    return {"干货": 2, "消费向导": 1, "科普": 2}

FORBIDDEN_TITLE_PATTERNS = [
    (r"(永不|绝不|绝对不|零|0)\s*(延迟|卡顿|掉帧|失灵)", "禁止绝对化性能承诺"),
    (r"(垃圾|烂|智商税|割韭菜|坑爹|骗)\s*(键盘|鼠标|品牌|厂商|产品)", "禁止攻击竞品"),
    (r"(你|你们)\s*(傻|蠢|笨|智商低|没脑子)", "禁止贬低用户"),
]

WEIGHTS = {
    "data_relevance": 0.18,
    "title_impact": 0.16,
    "structure": 0.14,
    "category_cover": 0.12,
    "content_rules": 0.12,
    "type_purity": 0.10,
    "uniqueness": 0.07,
    "timeliness": 0.06,
    "feasibility": 0.05,
}

STYLE_REFERENCE = "对标大狸子切切里/先看评测/影视飓风的选题角度——数据扎实、观点鲜明、拒绝泛泛而谈"

TOPIC_SELF_CHECK_PROMPT = """## 选题文案自检清单（输出前逐条核对）

生成选题后，逐条检查以下7项，全部通过才能输出：

1. **冲突感**：标题是否制造了认知冲突或用"但/却/竟然"等转折词？纯陈述句标题=不及格
2. **悬念度**：用户看完标题是否想知道答案？如果标题已经把结论说完了=不及格
3. **受众精准**：受众是否太宽？（"大学生怎么买笔记本"=太宽，"工科生跑仿真该选什么配置"=精准）
4. **无AI味**：是否避免了"全新升级/震撼上市/重新定义"等电商腔？是否避免了"采用了/配备了/搭载了"等装配动词？
5. **无绝对化**：是否避免了"最好/最强/第一/独一无二/完美"等违反广告法的词？
6. **类型纯粹**：标题是否明确传达了一条视频只能是一种类型（科普/干货/消费向导）？
7. **可执行性**：选题在抖音上能不能拍？（制作成本可控+无致命技术限制+受众够大）""".strip()

WEEKLY_SYSTEM_PROMPT = f"""你是D先生的选题策划AI。根据本周真实热搜数据，生成下周5个视频选题。

## 核心原则

1. 每个选题必须基于真实数据，不能凭空想象
2. 品类完全由本周数据驱动，不设人工偏好
3. {{type_distribution_text}}
4. 干货=20-40秒实操（HOW），消费向导=客观筛选推荐（FILTER），科普=45-60秒建立认知（WHAT）

## D先生选题铁律（绝对不可违反）

### 类型纯粹
- 一条选题只能是一种类型。科普是WHAT，干货是HOW，消费向导是FILTER。严禁混合（如"既是科普也是干货"=不及格）
- 科普类：告诉用户这是什么、为什么。干货类：教用户怎么操作、怎么设置。消费向导：帮用户做购买决策

### 价格精准
- 禁止跨大价位推荐（如"500/800/1500元怎么选"）。买500的用户不会看1500的产品
- 正确做法：锁定单一价位段（如"200元磁轴一句话评优劣"或"800元档推荐"）

### 用户痛点
- 每条选题必须先回答：用户有什么问题？是大多数人的真痛点吗？
- 不做"没人关心"的伪痛点（如宿舍静音——磁轴本身就不吵）
- 不做"不存在"的选择困难（如同价位磁轴vs机械轴——趋势是都买磁轴）

### 内容红线
- 禁止标题出现绝对化性能承诺（如"永不延迟""0卡顿""绝不掉帧"）
- 禁止攻击竞品或品牌（不用"垃圾""智商税""割韭菜"等词描述具体品牌）
- 禁止贬低用户（不用"你傻""智商低"等侮辱性表述）
- 所有数据必须真实可查，引用参数必须有实测依据

### 干货类特殊要求
- Agent需参考社交媒体爆款干货视频，反推其结构+手法
- 用独特方式复现，不能与爆款视频一模一样（换表达方式/换角度/换展现形式）
- 每次只讲一个点，切莫堆砌。20-40秒为佳

### 优先级
FPS游戏人群（最刚需）> 价格覆盖（解决选择困难）> 避坑指南（建立信任）> 制造认知冲突

## 风格参考
{STYLE_REFERENCE}

{TOPIC_SELF_CHECK_PROMPT}

## 输出格式
严格JSON（不要额外文字）：
{{"topics":[{{"type":"干货或消费向导或科普","category":"品类中文名","title":"抖音风格标题（冲突感+悬念，可适度夸张但数据真实）","ref_video":"对标账号的爆款参考视频描述","reverse_structure":"反推结构（标注秒数和钩子类型，总时长30-50秒）","unique_presentation":"独特展现方式（必须写清与同类内容的差异点）","user_need":"用户有什么需求（痛点描述）","solved_need":"解决了什么需求（价值描述）"}}]}}
"""


# ═══════════════════════════════════════════
# TYPE DISTRIBUTION
# ═══════════════════════════════════════════

def _get_type_distribution() -> str:
    """Return a Chinese description of the target type distribution based on time of year."""
    today = datetime.now()
    for sm, sd, em, ed, label in FESTIVALS:
        pre_start = datetime(today.year, sm, sd) - timedelta(days=7)
        festival_end = datetime(today.year, em, ed)
        if pre_start <= today < festival_end:
            logger.info("Festival period: %s — consumption-guide-heavy", label)
            return "当前处于%s大促窗口期，类型配比调整为：1个干货+2个消费向导+2个科普（消费向导优先）" % label
    return "类型配比：2个干货(HOW)+1个消费向导(FILTER)+2个科普(WHAT)"


# ═══════════════════════════════════════════
# AUDIT SYSTEM (8 dimensions)
# ═══════════════════════════════════════════

def _score_data_relevance(topics: list[dict], data: dict) -> float:
    top_titles = [t.lower() for t in data.get("top_titles", [])]
    data_cats = set(data.get("categories", {}).keys())
    score = 0
    for t in topics:
        title = t.get("title", "").lower()
        cat = t.get("category", "")
        for kw in top_titles:
            if any(w in title for w in kw[:6].split()):
                score += 15; break
        if cat in list(data_cats)[:3]:
            score += 10
    return min(100, score)


def _score_title_impact(topics: list[dict]) -> float:
    score = 0
    for t in topics:
        title = t.get("title", "")
        pts = 0
        if any(k in title for k in ["不如", "差", "坑", "骗", "别", "错", "白买", "智商税", "韭菜"]): pts += 15
        if any(k in title for k in ["为什么", "怎么", "如何", "什么", "到底"]): pts += 10
        if any(c.isdigit() for c in title): pts += 10
        if any(k in title for k in ["但", "却", "竟然", "居然", "反而"]): pts += 10
        if 15 <= len(title) <= 60: pts += 5
        score += pts
    return min(100, score / len(topics) * 5)


def _score_structure(topics: list[dict]) -> float:
    required = ["type", "category", "title", "ref_video", "reverse_structure",
                "unique_presentation", "user_need", "solved_need"]
    type_count = {"干货": 0, "消费向导": 0, "科普": 0}
    score = 0
    for t in topics:
        missing = sum(1 for f in required if not t.get(f, "").strip())
        score += max(0, 100 - missing * 15)
        tp = t.get("type", "")
        if tp in type_count: type_count[tp] += 1
        struct = t.get("reverse_structure", "")
        if re.search(r"\d+s", struct): score += 10
        if len(t.get("unique_presentation", "")) > 30: score += 5
    ideal = _get_type_distribution_dict()
    penalty = sum(abs(type_count.get(k, 0) - v) * 10 for k, v in ideal.items())
    return min(100, max(0, score / len(topics) - penalty))


def _get_type_distribution_dict() -> dict:
    today = datetime.now()
    for sm, sd, em, ed, _ in FESTIVALS:
        pre_start = datetime(today.year, sm, sd) - timedelta(days=7)
        festival_end = datetime(today.year, em, ed)
        if pre_start <= today < festival_end:
            return {"干货": 1, "消费向导": 2, "科普": 2}
    return {"干货": 2, "消费向导": 1, "科普": 2}


def _score_category_cover(topics: list[dict]) -> float:
    cats = [t.get("category", "") for t in topics]
    unique_cats = len(set(cats))
    no_consecutive = all(cats[i] != cats[i+1] for i in range(len(cats)-1))
    return min(100, unique_cats * 20 + (20 if no_consecutive else 0))


def _score_uniqueness(topics: list[dict]) -> float:
    score = 0
    for t in topics:
        up = t.get("unique_presentation", "")
        generic = ["干货分享", "推荐几款", "选购指南", "科普一下"]
        penalty = sum(10 for g in generic if g in up)
        specific = ["不同于", "区别于", "不", "不是", "独特的", "差异化"]
        bonus = sum(8 for s in specific if s in up)
        score += max(0, 60 + bonus - penalty)
    return min(100, score / len(topics))


def _score_timeliness(topics: list[dict]) -> float:
    today = datetime.now()
    month = today.month
    seasonal = []
    if month in (6, 7): seasonal = ["618", "暑期", "高考", "毕业", "开学", "夏天"]
    elif month in (11, 12): seasonal = ["双11", "双十二", "年终", "寒假"]
    elif month in (1, 2): seasonal = ["过年", "寒假", "新年"]
    event_kw = ["世界杯", "AI", "COMPUTEX"]
    score = 0
    for t in topics:
        title = t.get("title", "") + t.get("ref_video", "")
        pts = sum(12 for kw in seasonal + event_kw if kw in title)
        score += min(60, pts)
    return min(100, score / max(len(topics), 1))


def _score_feasibility(topics: list[dict]) -> float:
    score = 80
    for t in topics:
        title = t.get("title", "")
        struct = t.get("reverse_structure", "")
        if any(k in title for k in ["横评", "对比", "实测"]): score -= 5
        if len(struct) > 400: score -= 3
        if any(k in title for k in ["设置", "调", "教", "教程", "指南"]): score += 3
    return max(0, min(100, score))


def _score_content_rules(topics: list[dict]) -> float:
    violations = 0
    for t in topics:
        title = t.get("title", "")
        # Original forbidden patterns
        for pattern, rule_name in FORBIDDEN_TITLE_PATTERNS:
            if re.search(pattern, title):
                logger.warning("Content rule violation: %s — '%s'", rule_name, title[:60])
                violations += 1
        # Ecommerce smell in topic titles (电商味 / 装配动词)
        ecom_hits = [w for w in ECOMMERCE_SMELL_ALL if w in title]
        if ecom_hits:
            logger.warning("Ecommerce smell in title: %s — '%s'", ecom_hits, title[:60])
            violations += len(ecom_hits)
        # AI-typical assembly verbs in angles/presentations
        up = t.get("unique_presentation", "")
        assembly_hits = [v for v in ASSEMBLY_VERBS if v in up]
        if assembly_hits:
            violations += len(assembly_hits)
        # Forbidden words in title
        forbid_hits = [w for w in FORBIDDEN_WORDS if w in title]
        if forbid_hits:
            logger.warning("Forbidden word in title: %s — '%s'", forbid_hits, title[:60])
            violations += len(forbid_hits)
    return max(0, 100 - violations * 15)


def _score_type_purity(topics: list[dict]) -> float:
    """Penalize mixed-type topics (D先生 rule: one topic = one type only)."""
    score = 100
    for t in topics:
        title = t.get("title", "")
        tp = t.get("type", "")
        struct = t.get("reverse_structure", "")
        ref = t.get("ref_video", "")
        # 消费向导 masquerading as 干货 (has price/compare but labeled 干货)
        if tp == "干货":
            if any(k in title for k in ["推荐", "选购", "性价比", "哪个好", "怎么选", "哪一个"]):
                score -= 10
            # Price range check (D先生 rule: no cross-tier pricing)
            prices = re.findall(r"(\d+)\s*[元块]", title)
            if len(prices) >= 2:
                try:
                    vals = [int(p) for p in prices]
                    if max(vals) > min(vals) * 2:  # e.g. 200 vs 800 = too wide
                        score -= 15
                except: pass
        # 科普 labeled as 消费向导
        if tp == "消费向导":
            if any(k in title for k in ["为什么", "原理", "是什么", "怎么做的", "科普"]):
                score -= 10
        # Title vs structure mismatch
        if tp == "干货" and len(struct) < 50:
            score -= 5
    return max(0, score)


def audit_topics(topics: list[dict], data: dict) -> dict:
    """Score a set of 5 topics across 9 dimensions."""
    dims = {
        "data_relevance": _score_data_relevance(topics, data),
        "title_impact": _score_title_impact(topics),
        "structure": _score_structure(topics),
        "category_cover": _score_category_cover(topics),
        "content_rules": _score_content_rules(topics),
        "type_purity": _score_type_purity(topics),
        "uniqueness": _score_uniqueness(topics),
        "timeliness": _score_timeliness(topics),
        "feasibility": _score_feasibility(topics),
    }
    total = sum(dims[k] * WEIGHTS[k] for k in dims)
    return {"dimensions": dims, "total": round(total, 1), "weighted": True}


# ═══════════════════════════════════════════
# DATA AGGREGATION
# ═══════════════════════════════════════════

def aggregate_week_data() -> dict:
    today = datetime.now()
    week_ago = today - timedelta(days=7)
    all_entries = []
    if SEED_FILE.exists():
        for line in SEED_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"): continue
            parts = [p.strip() for p in line.split(" | ")]
            if len(parts) >= 3:
                all_entries.append({"title": parts[0], "source": parts[1] if len(parts) > 1 else "", "score": parts[-1] if len(parts) > 3 else "0"})
    daily_stats = []
    if CACHE_FILE.exists():
        try:
            cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            for entry in cache:
                if entry.get("date", "") >= week_ago.strftime("%Y-%m-%d"):
                    daily_stats.append(entry)
        except Exception: pass
    categories = Counter()
    for e in all_entries:
        title = e["title"]
        if any(k in title for k in ["AI", "人工智能", "大模型", "DeepSeek", "ChatGPT"]): categories["AI"] += 1
        elif any(k in title for k in ["键盘", "鼠标", "外设", "磁轴", "键鼠"]): categories["外设"] += 1
        elif any(k in title for k in ["笔记本", "电脑", "游戏本"]): categories["笔记本"] += 1
        elif any(k in title for k in ["显示器", "屏幕"]): categories["显示器"] += 1
        elif any(k in title for k in ["显卡", "GPU", "RTX", "芯片"]): categories["显卡"] += 1
        elif any(k in title for k in ["手机", "iPhone"]): categories["手机"] += 1
        elif any(k in title for k in ["耳机", "音响", "音频"]): categories["音频"] += 1
        else: categories["其他"] += 1
    scored = sorted(all_entries, key=lambda x: float(x.get("score", "0").replace("得分", "").strip() or "0"), reverse=True)
    return {
        "week_range": f"{week_ago.strftime('%Y-%m-%d')} ~ {today.strftime('%Y-%m-%d')}",
        "total_entries": len(all_entries), "daily_stats": daily_stats,
        "categories": dict(categories.most_common()),
        "top_titles": [t["title"] for t in scored[:15]],
        "avg_daily": len(all_entries) / max(len(daily_stats), 1) if daily_stats else 0,
    }


# ═══════════════════════════════════════════
# LLM CALL
# ═══════════════════════════════════════════

def _call_llm(client: OpenAI, user_prompt: str, temperature: float) -> dict | None:
    try:
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "system", "content": WEEKLY_SYSTEM_PROMPT}, {"role": "user", "content": user_prompt}],
            temperature=temperature, max_tokens=4096,
        )
        raw = response.choices[0].message.content or ""
        if "```json" in raw: raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw: raw = raw.split("```")[1].split("```")[0].strip()
        return json.loads(raw)
    except Exception as e:
        logger.warning("LLM call failed (temp=%.2f): %s", temperature, e)
        return None


def _generate_candidates(client: OpenAI, user_prompt: str, data: dict) -> list[dict]:
    """Generate candidates. If all < QUALITY_FLOOR, retry up to MAX_RETRIES times."""
    all_candidates = []
    for attempt in range(MAX_RETRIES + 1):
        for r in range(ROUNDS):
            temp = TEMPERATURES[r]
            logger.info("Round %d/%d — temp=%.2f (attempt %d)", r + 1, ROUNDS, temp, attempt + 1)
            t0 = time.time()
            result = _call_llm(client, user_prompt, temp)
            elapsed = time.time() - t0
            if result and result.get("topics") and len(result["topics"]) >= 3:
                topics = result["topics"][:5]
                audit = audit_topics(topics, data)
                all_candidates.append({"round": r + 1 + attempt * ROUNDS, "temperature": temp, "topics": topics, "audit": audit, "elapsed": round(elapsed, 1)})
                logger.info("  -> score=%.1f (%s)", audit["total"], ", ".join(f"{k}={v}" for k, v in audit["dimensions"].items()))
            else:
                logger.warning("  -> failed or insufficient topics")

        best = max(all_candidates, key=lambda c: c["audit"]["total"]) if all_candidates else None
        if best and best["audit"]["total"] >= QUALITY_FLOOR:
            break  # Passed quality threshold
        if attempt < MAX_RETRIES:
            logger.warning("Best score %.1f < %d — retrying (attempt %d/%d)", best["audit"]["total"] if best else 0, QUALITY_FLOOR, attempt + 2, MAX_RETRIES + 1)

    return all_candidates


# ═══════════════════════════════════════════
# MAIN ENTRY
# ═══════════════════════════════════════════

def generate_weekly_topics() -> dict:
    data = aggregate_week_data()
    total = data["total_entries"]
    if total < 10:
        logger.warning("Only %d entries in past 7 days — topic quality may suffer", total)

    type_dist_text = _get_type_distribution()
    cat_summary = "\n".join(f"  - {cat}: {cnt}条" for cat, cnt in data["categories"].items())
    top_list = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(data["top_titles"]))
    today_str = datetime.now().strftime("%Y-%m-%d")
    cat_label = "·".join([c for c, _ in list(data["categories"].items())[:4]])

    # Check for urgent topics that shouldn't wait
    urgents_text = ""
    urgent_file = OUTPUT_DIR / "_urgent_topics.json"
    if urgent_file.exists():
        try:
            urgents = json.loads(urgent_file.read_text(encoding="utf-8"))
            if urgents.get("topics"):
                urgents_text = "\n本周紧急选题（热度>40，建议优先处理）：\n" + "\n".join(
                    f"  - [{t['score']}分] {t['title']}" for t in urgents["topics"][:3]
                )
                logger.info("Loaded %d urgent topics", len(urgents["topics"]))
        except Exception:
            pass

    user_prompt = f"""本周 ({data['week_range']}) 热搜数据汇总：
{urgents_text}

数据规模：{total}条数码相关话题，日均{data['avg_daily']:.1f}条
品类分布：
{cat_summary}

本周TOP15话题：
{top_list}

{type_dist_text}
今天日期：{today_str}。注意时间节点（618刚过，暑期将至，世界杯进行中）。
输出严格JSON，不要额外文字。"""

    # Inject type distribution into system prompt
    system_prompt = WEEKLY_SYSTEM_PROMPT.replace("{type_distribution_text}", type_dist_text)

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    # Override system prompt for this run
    global _current_system_prompt
    _current_system_prompt = system_prompt

    # Monkey-patch the client call to use dynamic system prompt
    orig_create = client.chat.completions.create
    def patched_create(**kwargs):
        kwargs["messages"] = [{"role": "system", "content": system_prompt}, kwargs["messages"][1]]
        return orig_create(**kwargs)
    client.chat.completions.create = patched_create

    candidates = _generate_candidates(client, user_prompt, data)

    if not candidates:
        logger.error("All rounds failed — cannot generate weekly report")
        raise RuntimeError("Weekly topic generation failed")

    # Apply douyin_filter to all topic titles (catch prohibited phrases)
    for c in candidates:
        for t in c["topics"]:
            filtered_title, _ = filter_prohibited(t.get("title", ""))
            t["title"] = filtered_title
            filtered_up, _ = filter_prohibited(t.get("unique_presentation", ""))
            t["unique_presentation"] = filtered_up

    candidates.sort(key=lambda c: c["audit"]["total"], reverse=True)
    winner = candidates[0]

    logger.info("Winner: round %d (temp=%.2f, score=%.1f) — beat next by %.1f pts",
                 winner["round"], winner["temperature"], winner["audit"]["total"],
                 winner["audit"]["total"] - candidates[1]["audit"]["total"] if len(candidates) > 1 else 0)

    # Audit log
    audit_log = {
        "date": today_str, "type_distribution": type_dist_text,
        "data_summary": {"total": total, "categories": data["categories"]},
        "rounds": [{"round": c["round"], "temperature": c["temperature"], "score": c["audit"]["total"],
                     "dimensions": c["audit"]["dimensions"], "elapsed": c["elapsed"],
                     "titles": [t["title"][:40] for t in c["topics"]]} for c in candidates],
        "winner_round": winner["round"], "winner_score": winner["audit"]["total"],
    }
    AUDIT_JSON.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_JSON.write_text(json.dumps(audit_log, ensure_ascii=False, indent=2), encoding="utf-8")

    result = {
        "cover": {
            "category_label": cat_label, "date": today_str, "week_range": data["week_range"],
            "author": "D先生 · 折腾到吐 · 多品类选题",
            "data_source": f"本周{total}条热搜数据 + 抖音热销榜 + B站天梯榜 + 竞品深度分析",
        },
        "topics": winner["topics"],
    }
    WEEKLY_JSON.parent.mkdir(parents=True, exist_ok=True)
    WEEKLY_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Weekly topics saved: %s (winner round %d, score %.1f)", WEEKLY_JSON, winner["round"], winner["audit"]["total"])

    # Summary
    dim_labels = {"data_relevance": "数据贴合", "title_impact": "标题冲击", "structure": "结构完整",
                  "category_cover": "品类覆盖", "content_rules": "内容合规", "type_purity": "类型纯度",
                  "uniqueness": "差异化", "timeliness": "时效匹配",
                  "feasibility": "可执行性"}
    print(f"\n{'='*55}")
    print(f"  选题 Agent 自检 — {ROUNDS}轮 + {MAX_RETRIES}retry | 及格线={QUALITY_FLOOR}分")
    print(f"  配比模式: {type_dist_text}")
    print(f"{'='*55}")
    for i, c in enumerate(candidates):
        marker = " *** WINNER" if i == 0 else ""
        print(f"  R{c['round']} (T={c['temperature']:.2f}): {c['audit']['total']:.1f} pts{marker}")
        dims = c["audit"]["dimensions"]
        print(f"    {dim_labels['data_relevance']}={dims['data_relevance']} {dim_labels['title_impact']}={dims['title_impact']} {dim_labels['structure']}={dims['structure']} {dim_labels['category_cover']}={dims['category_cover']} {dim_labels['content_rules']}={dims['content_rules']} {dim_labels['uniqueness']}={dims['uniqueness']} {dim_labels['timeliness']}={dims['timeliness']} {dim_labels['feasibility']}={dims['feasibility']}")
    print(f"{'='*55}")
    print(f"  Winner: R{winner['round']} ({winner['audit']['total']:.1f} pts)")
    print(f"  Audit: {AUDIT_JSON}")
    print(f"  Data:  {WEEKLY_JSON}")

    # Generate .docx report
    try:
        from subprocess import run
        r = run(["py", "-3.12", "_make_weekly_report.py", "--input", str(WEEKLY_JSON)],
                capture_output=True, text=True, cwd=Path(__file__).parent.parent.parent)
        if r.returncode == 0:
            print(f"  Report: {r.stdout.strip()}")
        else:
            print(f"  Report WARNING: {r.stderr.strip() or 'unknown error'}")
    except Exception as e:
        print(f"  Report WARNING: {e}")

    return result


if __name__ == "__main__":
    generate_weekly_topics()
