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
)
from rag_system.retrieval.retriever import RetrievedChunk
from rag_system.generation.meme_engine import (
    pick_best_meme, meme_opening_prompt, no_meme_opening_prompt,
)
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
        retrieved_chunks: list[RetrievedChunk] | None = None,
        temperature: float = 0.8,
        max_tokens: int = 4096,
    ) -> str:
        profile = PERSONA_PROFILES.get(persona, {})
        context = _format_context(retrieved_chunks or [])
        category_context = CATEGORY_CONTEXT.get(category, "通用数码产品——重点讲性价比和实际体验。")
        # Load compiled wiki knowledge for this category
        wiki_context = ""
        try:
            from rag_system.competitive.wiki_compiler import load_wiki_context
            wiki_context = load_wiki_context(category)
        except Exception:
            pass
        # ~290 chars/min for Douyin short video pacing
        target_chars = int(duration_minutes * 290)

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
        # Inject wiki context after format (avoids {} conflicts)
        if wiki_context:
            system += "\n\n## 竞品学习知识库（Wiki编译结果，可直接参考）\n" + wiki_context
            logger.info("Wiki injected: %d chars for category=%s", len(wiki_context), category)

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
        return response.choices[0].message.content


def _format_context(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "（暂无 D先生 过去写过的相关参考脚本）"

    parts = []
    for i, c in enumerate(chunks[:8], 1):
        meta = f"[来源: {c.source_file} | 人设: {c.persona or '未知'} | 类别: {c.category or '未知'}]"
        parts.append(f"--- 参考片段 {i} {meta} ---\n{c.document}")
    return "\n\n".join(parts)
