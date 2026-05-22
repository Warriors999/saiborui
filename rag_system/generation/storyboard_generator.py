"""Storyboard generator — LLM orchestration with post-processing enforcement.

Pipeline:
  1. Build prompt from product brief + RAG context
  2. Single LLM call → JSON storyboard
  3. Parse JSON (3 retries with format correction)
  4. Post-process: shot count, visual variety, voiceover rhythm, 花字 extraction
"""

import json
import re
from dataclasses import dataclass, field
from collections import Counter

from openai import OpenAI

from rag_system.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from rag_system.generation.storyboard_prompts import (
    STORYBOARD_SYSTEM_PROMPT,
    STORYBOARD_USER_PROMPT,
    CATEGORY_CONVENTIONS,
    PERSONA_STORYBOARD_PROFILES,
    FORBIDDEN_WORDS,
    JINGBIE,
    JINGBIE_SPECIAL,
    YUNJING,
    JIANDU,
    NARRATIVE_ARC,
)
from rag_system.retrieval.retriever import RetrievedChunk
from rag_system.utils import logger


@dataclass
class ProductBrief:
    product_name: str
    category: str
    persona: str
    key_points: str
    price: str = ""
    competitors: str = ""
    extra_notes: str = ""


class StoryboardGenerator:
    def __init__(self, api_key: str = "", base_url: str = "", model: str = ""):
        key = api_key or DEEPSEEK_API_KEY
        if not key:
            raise ValueError("DeepSeek API key not configured. Set DEEPSEEK_API_KEY in .env")
        self.client = OpenAI(api_key=key, base_url=base_url or DEEPSEEK_BASE_URL)
        self.model = model or DEEPSEEK_MODEL

    def generate(
        self,
        brief: ProductBrief,
        retrieved_chunks: list[RetrievedChunk] | None = None,
        temperature: float = 0.8,
        max_tokens: int = 8192,
    ) -> dict:
        system = STORYBOARD_SYSTEM_PROMPT
        user = self._build_user_prompt(brief, retrieved_chunks or [])

        logger.info("Calling DeepSeek API for storyboard: model=%s, persona=%s, category=%s",
                     self.model, brief.persona, brief.category)

        raw_json = self._call_llm_with_retry(system, user, temperature, max_tokens)
        storyboard = self._parse_json(raw_json)
        storyboard = self._post_process(storyboard, brief)

        return storyboard

    def _build_user_prompt(self, brief: ProductBrief, chunks: list[RetrievedChunk]) -> str:
        conventions = CATEGORY_CONVENTIONS.get(brief.category, {})
        conv_text = json.dumps(conventions, ensure_ascii=False, indent=2) if conventions else "（通用数码产品）"

        context = _format_context(chunks)

        return STORYBOARD_USER_PROMPT.format(
            product_name=brief.product_name,
            category=brief.category,
            persona=brief.persona,
            key_points=brief.key_points,
            price=brief.price,
            competitors=brief.competitors or "无",
            extra_notes=brief.extra_notes or "无",
            category_conventions=conv_text,
            context=context,
        )

    def _call_llm_with_retry(self, system: str, user: str, temperature: float, max_tokens: int) -> str:
        last_error = None
        for attempt in range(3):
            try:
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
            except Exception as e:
                last_error = e
                logger.warning("LLM call attempt %d failed: %s", attempt + 1, e)
        raise RuntimeError(f"LLM call failed after 3 attempts: {last_error}")

    def _parse_json(self, raw: str) -> dict:
        raw = raw.strip()
        # Remove markdown code fences if present
        raw = re.sub(r'^```(?:json)?\s*\n?', '', raw)
        raw = re.sub(r'\n?```\s*$', '', raw)

        # Try direct parse
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Try extracting JSON block between { and }
        match = re.search(r'\{[\s\S]*\}', raw)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        raise ValueError(f"Failed to parse JSON from LLM response. Raw length: {len(raw)}")

    def _post_process(self, storyboard: dict, brief: ProductBrief) -> dict:
        shots = storyboard.get("shots", [])
        if not shots:
            raise ValueError("Storyboard contains no shots")

        shots = _enforce_shot_count(shots)
        shots = _enforce_visual_variety(shots)
        shots = _enforce_voiceover_quality(shots)
        shots = _enforce_huazi_separation(shots)
        shots = _fill_missing_durations(shots)
        shots = _enforce_new_field_defaults(shots)

        # Ensure metadata
        if "metadata" not in storyboard:
            storyboard["metadata"] = {}
        md = storyboard["metadata"]
        if "title" not in md or not md["title"]:
            md["title"] = f"{brief.product_name}到底值不值得买？"
        if "hashtags" not in md or not md["hashtags"]:
            md["hashtags"] = _generate_hashtags(brief)
        if "persona" not in md:
            md["persona"] = brief.persona
        if "category" not in md:
            md["category"] = brief.category

        storyboard["shots"] = shots
        return storyboard


# ---- Post-processing functions ----

def _enforce_shot_count(shots: list[dict], min_shots: int = 30, max_shots: int = 45) -> list[dict]:
    """Ensure shot count is within 30-45 range; pad if below, trim if above."""
    n = len(shots)
    if min_shots <= n <= max_shots:
        for i, shot in enumerate(shots, 1):
            shot["shot_number"] = i
        return shots

    if n < min_shots:
        logger.warning("Shot count %d below minimum %d, padding with pure-visual shots", n, min_shots)
        for extra in range(min_shots - n):
            shots.append({
                "shot_number": len(shots) + 1,
                "act": "deep_dive",
                "jingbie": "特写",
                "yunjing": "推镜头",
                "jiandu": "前侧45°",
                "duration": "6s",
                "transition": "硬切",
                "visual": "产品细节B-roll (PADDED)",
                "voiceover": "",
                "huazi": "",
                "audio": "",
                "lighting": "",
                "camera_setup": "",
                "notes": "(PADDED — needs manual review)",
            })
    else:
        logger.warning("Shot count %d above maximum %d, trimming", n, max_shots)
        shots = shots[:max_shots]

    for i, shot in enumerate(shots, 1):
        shot["shot_number"] = i
    return shots


def _enforce_visual_variety(shots: list[dict]) -> list[dict]:
    """No more than 2 consecutive shots with same (jingbie + yunjing) combo."""
    for i in range(2, len(shots)):
        prev2 = (shots[i-2].get("jingbie", ""), shots[i-2].get("yunjing", ""))
        prev1 = (shots[i-1].get("jingbie", ""), shots[i-1].get("yunjing", ""))
        curr = (shots[i].get("jingbie", ""), shots[i].get("yunjing", ""))

        if prev2 == prev1 == curr and curr[0] not in JINGBIE_SPECIAL:
            # Mutate the 3rd shot
            alt_jingbie = "近景" if curr[0] != "近景" else "特写"
            alt_yunjing = "摇镜头" if curr[1] == "固定镜头" else "固定镜头"
            shots[i]["jingbie"] = alt_jingbie
            shots[i]["yunjing"] = alt_yunjing
            logger.debug("Shot %d: visual variety enforced (%s/%s → %s/%s)",
                         i+1, curr[0], curr[1], alt_jingbie, alt_yunjing)

    return shots


def _enforce_voiceover_quality(shots: list[dict]) -> list[dict]:
    """Check voiceover text for forbidden words and minimum substance."""
    forbidden = FORBIDDEN_WORDS

    voiceover_shots = 0
    total_voiceover_chars = 0

    for shot in shots:
        vo = shot.get("voiceover", "")
        if not vo:
            continue
        voiceover_shots += 1
        total_voiceover_chars += len(vo)

        for word in forbidden:
            if word in vo:
                logger.warning("Shot %d: forbidden word '%s' found in voiceover",
                             shot.get("shot_number", "?"), word)

    if voiceover_shots > 0:
        avg_len = total_voiceover_chars / voiceover_shots
        if total_voiceover_chars < 400:
            logger.warning("Total voiceover text too short: %d chars (target 800-1200)", total_voiceover_chars)
        elif total_voiceover_chars < 600:
            logger.info("Total voiceover text: %d chars (minimum acceptable)", total_voiceover_chars)

    return shots


def _enforce_huazi_separation(shots: list[dict]) -> list[dict]:
    """Ensure huazi content is separate from voiceover (no parenthetical spec callouts in VO)."""
    for shot in shots:
        vo = shot.get("voiceover", "")
        # Remove （花字：...） patterns from voiceover
        cleaned = re.sub(r'[（(]花字[：:][^）)]*[）)]', '', vo)
        # Remove trailing whitespace from cleaned text
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        if cleaned != vo:
            shot["voiceover"] = cleaned
            logger.debug("Shot %d: removed inline 花字 from voiceover",
                        shot.get("shot_number", "?"))
    return shots


def _fill_missing_durations(shots: list[dict]) -> list[dict]:
    """Fill missing duration fields with context-aware discrete values."""
    for shot in shots:
        if shot.get("duration") and shot["duration"].strip():
            continue
        act = shot.get("act", "")
        jingbie = shot.get("jingbie", "")
        voiceover = shot.get("voiceover", "")

        if not voiceover.strip():
            shot["duration"] = "6s"  # pure visual shots get breathing room
        elif act == "hook":
            shot["duration"] = "2s"  # fast-paced
        elif act == "reveal":
            shot["duration"] = "5s"  # product showcase
        elif jingbie in ("大特写", "特写"):
            shot["duration"] = "3s"
        elif jingbie == "图文形式动画":
            shot["duration"] = "2s"
        else:
            shot["duration"] = "3s"  # default medium
    return shots


def _enforce_new_field_defaults(shots: list[dict]) -> list[dict]:
    """Ensure all 14 fields exist on every shot with valid defaults."""
    for i, shot in enumerate(shots):
        shot.setdefault("jiandu", "")
        shot.setdefault("transition", "开场" if i == 0 else "硬切")
        shot.setdefault("audio", "")
        shot.setdefault("lighting", "")
        shot.setdefault("camera_setup", "")
        shot.setdefault("act", shot.get("act", ""))
        shot.setdefault("huazi", shot.get("huazi", ""))
    return shots


def _generate_hashtags(brief: ProductBrief) -> str:
    tags = [f"#{brief.product_name}", f"#{brief.category}"]
    if brief.persona:
        tags.append(f"#{brief.persona}")
    tags.extend(["#数码评测", "#新品首发"])
    return "  ".join(tags[:6])


# ---- Format RAG context for prompt injection ----

def _format_context(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "（暂无 D先生 过去写过的相关参考脚本）"

    parts = []
    for i, c in enumerate(chunks[:8], 1):
        meta = f"[来源: {c.source_file} | 人设: {c.persona or '未知'} | 类别: {c.category or '未知'}]"
        parts.append(f"--- 参考片段 {i} {meta} ---\n{c.document}")
    return "\n\n".join(parts)
