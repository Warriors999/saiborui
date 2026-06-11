"""Full-script generator — DeepSeek API wrapper.

Produces 800-1200 char video scripts following D先生's writing style.
"""

from openai import OpenAI

from rag_system.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from rag_system.generation.prompts import (
    PERSONA_PROFILES,
    CATEGORY_CONTEXT,
    SYSTEM_PROMPT,
    USER_PROMPT,
    FRAMEWORK_HKRR,
    FRAMEWORK_HAMD,
)
from rag_system.retrieval.retriever import RetrievedChunk
from rag_system.generation.meme_engine import (
    pick_best_meme, meme_opening_prompt, no_meme_opening_prompt,
)
from rag_system.generation.douyin_filter import filter_prohibited, reduce_filler_phrases
from rag_system.utils import logger


class Generator:
    def __init__(self, api_key: str = "", base_url: str = "", model: str = ""):
        key = api_key or DEEPSEEK_API_KEY
        if not key:
            raise ValueError("DeepSeek API key not configured. Set DEEPSEEK_API_KEY in .env")
        self.client = OpenAI(api_key=key, base_url=base_url or DEEPSEEK_BASE_URL)
        self.model = model or DEEPSEEK_MODEL

    def generate(
        self,
        product_name: str,
        category: str,
        key_points: str,
        persona: str = "",
        price: str = "",
        competitors: str = "",
        duration_minutes: float = 2.0,
        script_format: str = "review",
        retrieved_chunks: list[RetrievedChunk] | None = None,
        temperature: float = 0.8,
        max_tokens: int = 4096,
        brief_context: str = "",
        cover_direction: str = "",
        analytics_context: str = "",
        mode: str = "normal",
        perspective_context: str = "",
    ) -> str:
        profile = PERSONA_PROFILES.get(persona, {})
        context = _format_context(retrieved_chunks or [])
        category_context = CATEGORY_CONTEXT.get(category, "通用数码产品——重点讲性价比和实际体验。")
        # Load compiled wiki knowledge for this category
        wiki_context = ""
        try:
            from rag_system.competitive.wiki_compiler import load_wiki_context
            wiki_context = load_wiki_context(category, product_features=key_points)
        except Exception as e:
            logger.warning("Wiki context load failed for category=%s: %s", category, e)

        # Format-specific instructions
        format_instruction = ""
        if script_format == "tierlist":
            format_instruction = """
## 格式要求：评级榜单体
- 用评级词：夯 > T0 > 人上人 > NPC > 拉完了
- 每款产品1-2句话，不超过40字
- 按品类分段（键盘/耳机/鼠标）
- 保留榜单的短平快节奏"""
        elif script_format == "comparison":
            format_instruction = """
## 格式要求：对比评测体
- 全程左右对比：A产品 vs B产品
- 每个维度（性能/手感/价格）各一段
- 结尾给出明确选择建议"""
        elif script_format == "hkrr":
            format_instruction = FRAMEWORK_HKRR
        elif script_format == "hamd":
            format_instruction = FRAMEWORK_HAMD

        # ~290 chars/min for Douyin short video pacing
        target_chars = int(duration_minutes * 290)

        # Experimental mode: more creative, bigger output
        if mode == "experimental":
            temperature = max(temperature, 0.95)
            max_tokens = max(max_tokens, 6144)
            target_chars = int(target_chars * 1.3)
            logger.info("Experimental mode: temp=%.2f, max_tokens=%d", temperature, max_tokens)

        # Pick a meme for the opening, or use fallback
        meme = pick_best_meme(category, product_name, key_points)
        if meme:
            opening_instruction = meme_opening_prompt(meme, product_name, persona)
            logger.info("Meme opening: %s", meme.text)
        else:
            opening_instruction = no_meme_opening_prompt(persona)

        # Inject wiki knowledge AFTER format() to avoid placeholder conflicts
        system = SYSTEM_PROMPT.format(
            persona=persona,
            persona_description=profile.get("description", "数码科技博主"),
            tone=profile.get("tone", "口语化表达"),
            style_notes=profile.get("style_notes", "重实测、讲人话、敢说真话"),
            signature=profile.get("signature", f"我是{persona}，我们下期再见"),
            duration_minutes=f"{duration_minutes:.1f}".rstrip("0").rstrip("."),
            target_chars=target_chars,
            opening_instruction=opening_instruction,
        )
        # Inject wiki context + format instructions after format (avoids {} conflicts)
        if wiki_context:
            system += f"""

## 竞品学习方法论 — 这是指令，不是参考资料

以下是从大量{category}品类竞品视频中蒸馏出的创作模式。你必须直接使用这些结构，而不是仅仅"了解"它们。

### 必须使用的结构模式
从wiki中提取以下模式，选择一个最适合当前产品的，直接套用其结构骨架：
- 如果wiki中有「X段式结构」或「脚本模板」，用它来组织你的段落顺序和时间分配
- 如果wiki中有「句式与技巧」，从中选2-3个句式直接套用到参数翻译中
- 如果wiki中有「类比简化」的案例，用同样的手法处理当前产品的复杂参数

### 必须避免的表达（违反即不合格）
- 情绪嚎叫式开头：\"我滴妈\"\"好家伙\"\"你敢信\"\"没看错吧\"
- 填充式口头禅：\"有一说一\"\"不吹不黑\"\"说实话\"\"懂的都懂\"\"你品\"\"你细品\"
- 模板收束：\"闭眼入\"\"包不后悔的\"\"真就绝了\"\"没谁了\"
- 滥用\"兄弟们\"——只在结尾CTA用一次
- 任何让观众觉得\"你在演\"而非\"你真懂\"的夸张表演

### 正确的表达方式
- 用具体数据和对比制造冲击力，不用感叹词制造冲击力
- 每个参数后面跟\"这意味着...\"的人话翻译
- 态度通过具体的批评/表扬来表达，不是通过\"好家伙\"\"稳得一批\"来表达
- 短句是信息炸弹，不是语气词的容器

{wiki_context}
"""
            logger.info("Wiki injected: %d chars for category=%s", len(wiki_context), category)
        if cover_direction:
            system += "\n\n## 封面方向（封面前置 — 文案必须围绕封面展开）\n" + cover_direction
            logger.info("Cover direction injected: %d chars", len(cover_direction))
        if perspective_context:
            system += "\n\n" + perspective_context
            logger.info("Perspective injected: %d chars", len(perspective_context))
        if brief_context:
            system += "\n\n## Brief卖点分析（结构化编辑指南）\n" + brief_context
            logger.info("Brief analysis injected: %d chars", len(brief_context))
        if analytics_context:
            system += "\n\n## 历史表现参考（数据反哺 — 保持风格一致）\n" + analytics_context
            logger.info("Analytics context injected: %d chars", len(analytics_context))
        if format_instruction:
            system += format_instruction
            logger.info("Format: %s", script_format)

        user = USER_PROMPT.format(
            product_name=product_name,
            category=category,
            key_points=key_points,
            price=price or "待定",
            competitors=competitors or "无",
            duration_minutes=f"{duration_minutes:.1f}".rstrip("0").rstrip("."),
            target_chars=target_chars,
            category_context=category_context,
            persona=persona,
            context=context,
        )

        logger.info("Generating full script: model=%s, persona=%s, category=%s, tokens=%d",
                     self.model, persona, category, max_tokens)

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        raw = response.choices[0].message.content

        # Auto-learn: log generation event to wiki for continuous improvement
        _auto_learn(product_name, category, persona, raw, wiki_context)

        # Apply Douyin prohibited-phrases filter before returning
        filtered, changes = filter_prohibited(raw)
        if changes:
            logger.info("Douyin filter: %d replacement(s) — %s", len(changes), changes[:5])

        # Apply filler phrase density reduction
        filtered2, filler_removals = reduce_filler_phrases(filtered)
        if filler_removals:
            logger.info("Filler reduction: %d removal(s)", filler_removals)

        return filtered2


def _auto_learn(product: str, category: str, persona: str, script: str, wiki_used: str):
    """Log every generation + auto-compile wiki when 5+ events accumulated per category."""
    from datetime import datetime
    from pathlib import Path
    wiki_had = "有" if wiki_used else "无"
    entry = f"- {datetime.now().strftime('%Y-%m-%d %H:%M')} | generate | {product} | {persona} | {category} | Wiki:{wiki_had} | {len(script)}字\n"
    from rag_system.config import PROJECT_ROOT as _PRJ
    log_file = _PRJ / "wiki" / "log.md"
    if log_file.exists():
        content = log_file.read_text(encoding="utf-8")
    else:
        content = "# 操作日志\n\n"
    log_file.write_text(content + entry, encoding="utf-8")
    # Count events for this category (including the one just written)
    cat_count = sum(1 for line in (content + entry).split("\n") if category in line and '| generate |' in line)
    # Auto-compile wiki insights every 5 events for a category
    if cat_count > 0 and cat_count % 5 == 0:
            logger.info(f'Auto-learning: {category} has {cat_count} events → compiling wiki')
            try:
                from rag_system.competitive.wiki_compiler import _update_log, WIKI_DIR
                _update_log(Path(f'auto/{category}'), category)
                # Create/update a basic wiki page from generation patterns
                wiki_cat_dir = WIKI_DIR / category
                wiki_cat_dir.mkdir(parents=True, exist_ok=True)
                hook_page = wiki_cat_dir / '钩子模式.md'
                if not hook_page.exists():
                    hook_page.write_text(f'# {category} 钩子模式\n\n自动编译中...\n\n最新活动: {datetime.now().strftime("%Y-%m-%d %H:%M")}\n', encoding='utf-8')
            except Exception as e:
                logger.warning(f'Auto-compile skipped: {e}')


def _format_context(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "（暂无 D先生 过去写过的相关参考脚本）"

    parts = []
    for i, c in enumerate(chunks[:8], 1):
        meta = f"[来源: {c.source_file} | 人设: {c.persona or '未知'} | 类别: {c.category or '未知'}]"
        parts.append(f"--- 参考片段 {i} {meta} ---\n{c.document}")
    return "\n\n".join(parts)
