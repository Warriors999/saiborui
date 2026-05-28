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

WIKI_DIR = Path("wiki")

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

        prompt = f"""你是赛博瑞知识库的维护者。你需要根据最新竞品分析结果，更新知识库Wiki页面。

## 当前Wiki页面内容
{existing[:2000]}

## 新竞品分析结果
{deep[:3000]}

## 视觉数据
{visual[:500]}

## 音频数据
{audio[:500]}

## 任务
请更新上面的Wiki页面 "{page_name}"。要求：
1. 保留原有内容中仍然有效的部分
2. 添加新发现的知识点
3. 如果新发现与旧知识冲突，标注出来（不要删除旧内容，用 [⚠️ 待验证: ...] 标记）
4. 每个知识点注明来源（创作者名+视频标题+日期）
5. 用Markdown格式，保持简洁
6. 如果是"新页面，暂无内容"，则从头创建

直接输出更新后的完整Wiki页面内容，不要加解释。"""

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


def load_wiki_context(category: str) -> str:
    """Load relevant wiki pages as context for script/storyboard generation.

    Returns concatenated wiki knowledge for the given category.
    """
    pages = _get_pages_for_category(category)
    context_parts = ["## Wiki知识库（编译后的竞品学习成果）\n"]

    for page_name, page_path in pages.items():
        page_file = WIKI_DIR / page_path
        if page_file.exists():
            content = page_file.read_text(encoding="utf-8")
            # Truncate to most relevant parts
            if len(content) > 1500:
                content = content[:1500] + "\n\n...(truncated, see full page)"
            context_parts.append(f"### {page_name}\n{content}\n")

    # Add competitor patterns
    comp_file = WIKI_DIR / WIKI_PAGES["竞品创作者模式"]
    if comp_file.exists():
        context_parts.append(f"### 竞品创作者模式\n{comp_file.read_text(encoding='utf-8')[:1000]}\n")

    return "\n---\n".join(context_parts)
