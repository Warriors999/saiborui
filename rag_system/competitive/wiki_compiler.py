"""Karpathy-style LLM Wiki compiler — knowledge compounding from competitive analysis.

After each competitive analysis, the LLM reads the deep analysis and updates
relevant wiki pages, cross-references, and detects contradictions.
Knowledge compounds instead of re-discovering on every query.
"""

from pathlib import Path
from datetime import datetime

from openai import OpenAI

from rag_system.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from rag_system.utils import logger

from rag_system.config import PROJECT_ROOT as _PRJ
WIKI_DIR = _PRJ / "wiki"

# ── Wiki page templates for each category ──
WIKI_PAGES = {
    "钩子模式": "{category}/钩子模式.md",
    "剪辑节奏": "{category}/剪辑节奏.md",
    "BGM_音效": "{category}/BGM_音效.md",
    "产品拍摄角度": "{category}/产品拍摄角度.md",
    "竞品创作者模式": "competitive/创作者模式.md",
    "跨品类通用技巧": "competitive/跨品类通用技巧.md",
    "铁律验证": "writing/铁律验证.md",
    "运镜手法": "shooting/运镜手法.md",
}


def compile_to_wiki(session_dir: Path, category: str):
    """After competitive analysis, compile learnings into wiki pages.

    Reads deep_analysis.txt, visual.json, audio.json from the session folder,
    and uses the LLM to update relevant wiki knowledge pages.
    """
    deep_file = session_dir / "deep_analysis.txt"
    visual_file = session_dir / "visual.json"
    audio_file = session_dir / "audio.json"

    if not deep_file.exists():
        logger.warning(f"No deep analysis found in {session_dir}")
        return

    deep = deep_file.read_text(encoding="utf-8")
    visual = visual_file.read_text(encoding="utf-8") if visual_file.exists() else ""
    audio = audio_file.read_text(encoding="utf-8") if audio_file.exists() else ""

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    # Determine which pages to update based on category
    pages_to_update = _get_pages_for_category(category)

    for page_name, page_path in pages_to_update.items():
        page_file = WIKI_DIR / page_path
        existing = page_file.read_text(encoding="utf-8") if page_file.exists() else "（新页面，暂无内容）"

        prompt = f"""你是赛博瑞知识库的高级策展人。你的任务不是搬运信息，而是做知识蒸馏——从竞品分析中提取【可以内化进工程的创作方法论】，同时标记【应该避免的低级套路】。

## 当前Wiki页面内容
{existing[:2000]}

## 新竞品分析结果
{deep[:3000]}

## 视觉数据
{visual[:500]}

## 音频数据
{audio[:500]}

## 任务 — 知识蒸馏，不是信息搬运

请更新Wiki页面 "{page_name}"，严格按照以下结构：

### ✅ 可内化的高级技巧
从新分析中提取【真正有价值】的创作方法。标准：
- 结构层面的创新（分段逻辑、信息密度设计、节奏控制）
- 视觉层面的具体手法（构图模式、灯光方案、镜头序列）
- 剪辑层面的规律（快慢切分布、转场时机、段落节奏）
- 排除以下低级内容：情绪宣泄式开头（我滴妈/好家伙）、空洞的称呼套近乎（兄弟们）、廉价的"有一说一"口头禅
- 每条注明来源（创作者+视频+日期）

### ⚠️ 应避免的低级套路
从竞品中识别出【不应模仿】的模式，并解释为什么：
- 情绪宣泄式开头——短期吸睛但损害专业人设
- 空洞口头禅填充——暴露内容密度不足
- 过度夸张的标题党——提高跳出率
- 任何让观众觉得"你在演"而不是"你真懂"的表达方式

### 📐 可复用的结构模板
提取可跨品类复用的内容结构模板（如：价格锚定开场→分类递进→实测验证→购买建议）
每个模板一句话描述+适用品类

### 🔗 与其他Wiki页面的交叉引用
标注这个知识点和哪些其他Wiki页面有关联

直接输出更新后的完整Wiki页面。"""

        try:
            response = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=3000,
            )
            updated = response.choices[0].message.content.strip()

            # Ensure directory exists
            page_file.parent.mkdir(parents=True, exist_ok=True)
            page_file.write_text(updated, encoding="utf-8")
            logger.info(f"Wiki updated: {page_path}")

        except Exception as e:
            logger.error(f"Wiki update failed for {page_path}: {e}")

    # Update log
    _update_log(session_dir, category)

    # Update index if needed
    _update_index(category)


def _get_pages_for_category(category: str) -> dict:
    """Return wiki pages relevant to a product category."""
    pages = {
        "钩子模式": WIKI_PAGES["钩子模式"].format(category=category),
        "剪辑节奏": WIKI_PAGES["剪辑节奏"].format(category=category),
        "BGM_音效": WIKI_PAGES["BGM_音效"].format(category=category),
        "产品拍摄角度": WIKI_PAGES["产品拍摄角度"].format(category=category),
        "竞品创作者模式": WIKI_PAGES["竞品创作者模式"],
        "跨品类通用技巧": WIKI_PAGES["跨品类通用技巧"],
    }
    # Filter to only relevant pages (those that exist in template)
    return {k: v for k, v in pages.items() if "{category}" not in v or category in v}


def _update_log(session_dir: Path, category: str):
    """Append operation to log.md."""
    log_file = WIKI_DIR / "log.md"
    entry = f"- {datetime.now().strftime('%Y-%m-%d %H:%M')} | {category} | 分析完成 → 更新wiki | {session_dir.name}\n"

    if log_file.exists():
        content = log_file.read_text(encoding="utf-8")
    else:
        content = "# 操作日志\n\n"
    log_file.write_text(content + entry, encoding="utf-8")


def _update_index(category: str):
    """Ensure the category has a link in index.md."""
    index_file = WIKI_DIR / "index.md"
    if not index_file.exists():
        return
    # Index is manually maintained for now
    pass


def load_wiki_context(category: str, product_features: str = "") -> str:
    """Load relevant wiki pages as context for script/storyboard generation.

    Returns concatenated wiki knowledge for the given category.
    Uses section-level extraction: keeps sections that match the product features,
    plus always keeps structural templates and anti-patterns.
    """
    pages = _get_pages_for_category(category)
    context_parts = ["## Wiki知识库（编译后的竞品学习成果）\n"]

    # Extract feature keywords for relevance matching
    feature_kw = set()
    if product_features:
        feature_kw = set(
            w.strip() for w in product_features.replace(",", " ").replace("，", " ").split()
            if len(w.strip()) >= 2
        )

    for page_name, page_path in pages.items():
        page_file = WIKI_DIR / page_path
        if page_file.exists():
            content = page_file.read_text(encoding="utf-8")
            # Extract the most relevant sections instead of blind truncation
            extracted = _extract_relevant_sections(content, feature_kw, max_chars=5000)
            context_parts.append(f"### {page_name}\n{extracted}\n")

    # Add competitor patterns — full content, this is core competitive intelligence
    comp_file = WIKI_DIR / WIKI_PAGES["竞品创作者模式"]
    if comp_file.exists():
        comp_content = comp_file.read_text(encoding="utf-8")
        context_parts.append(f"### 竞品创作者模式\n{comp_content[:4000]}\n")

    # Cross-category techniques
    cross_file = WIKI_DIR / WIKI_PAGES.get("跨品类通用技巧", "")
    if cross_file and cross_file.exists():
        cross_content = cross_file.read_text(encoding="utf-8")
        context_parts.append(f"### 跨品类通用技巧\n{cross_content[:2000]}\n")

    return "\n---\n".join(context_parts)


def _extract_relevant_sections(content: str, feature_kw: set, max_chars: int = 5000) -> str:
    """Extract wiki sections most relevant to the product features.

    Strategy:
      - Always include the first section (overview/概述)
      - Sections with matching keywords get full inclusion
      - Sections without matches get truncated to their heading + first 2 lines
      - If total exceeds max_chars, trim non-matching sections first
    """
    import re

    # Split content by markdown headings (## or ###)
    sections = re.split(r'\n(?=#{2,3}\s)', content)

    if len(sections) <= 1:
        # Short page, no section splitting needed
        return content[:max_chars]

    scored = []
    for sec in sections:
        heading = sec.split('\n')[0] if sec else ''
        body = '\n'.join(sec.split('\n')[1:]) if '\n' in sec else ''

        # Score by keyword overlap with product features
        score = 0
        if feature_kw:
            sec_lower = sec.lower()
            score = sum(1 for kw in feature_kw if kw.lower() in sec_lower)

        # Always boost structural templates and anti-patterns
        if any(tag in heading for tag in ['模板', '结构', '应避免', '可内化', '句式', '钩子']):
            score += 2

        scored.append((score, sec, heading, body))

    # Sort: high score first (most relevant)
    scored.sort(key=lambda x: x[0], reverse=True)

    result_parts = []
    total_chars = 0

    for score, sec, heading, body in scored:
        if score >= 2:
            # High relevance: include full section
            result_parts.append(sec.strip())
            total_chars += len(sec)
        elif score >= 1:
            # Medium relevance: include heading + first 300 chars of body
            snippet = heading + '\n' + body[:300].strip()
            if len(body) > 300:
                snippet += '\n...(省略，详见wiki完整版)'
            result_parts.append(snippet)
            total_chars += len(snippet)
        else:
            # Low relevance: heading only + 1-line summary
            first_line = body.strip().split('\n')[0][:100] if body.strip() else ''
            snippet = heading + '\n' + first_line
            if len(body) > 100:
                snippet += '\n...(省略)'
            result_parts.append(snippet)
            total_chars += len(snippet)

        if total_chars >= max_chars:
            break

    return '\n\n'.join(result_parts)
