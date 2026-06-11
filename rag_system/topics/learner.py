"""Rule learner — extracts and generalizes topic selection rules from various sources.

Input sources:
  1. User's topic notes (.docx) — explicit topic thinking
  2. User feedback on generated topics — corrections and preferences
  3. Competitive deep analysis — what made competitor topics viral
  4. Approved/rejected topic history — pattern recognition
"""

import json
from datetime import datetime
from pathlib import Path

from openai import OpenAI

from rag_system.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from rag_system.utils import logger

EXTRACTION_PROMPT = """你是选题方法论提炼专家。你要从用户的选题笔记中，提炼出【可跨品类复用的选题规则】。

关键要求：
- 每条规则必须是通用的、可跨品类应用的
- 不能只适用于当前这个品类
- 规则要包含：名称、公式、适用条件、反例
- 规则要有可操作性，不能是空洞的原则

## 输入

用户选题笔记：
{notes}

## 输出格式

按以下JSON格式输出，只输出JSON：

```json
{{
  "extracted_rules": [
    {{
      "rule_name": "规则名称（简短，如'场景分化选题法'）",
      "description": "规则描述（一句话讲清楚核心逻辑）",
      "formula": "选题公式（如：品类 + 场景A vs 场景B vs 场景C → 各自的配置方案）",
      "trigger_condition": "什么情况下应该用这个规则？",
      "cross_category_example": "这个规则在另一个完全不同的品类上怎么用？（如：显示器品类怎么用'场景分化选题法'）",
      "applicable_categories": ["ALL"]
    }}
  ],
  "anti_patterns": [
    "发现的选题反例或应该避免的选题方式"
  ],
  "quality_principles": [
    "从这份笔记中提炼的选题质量标准"
  ]
}}
```

现在开始提炼："""


class RuleLearner:
    """Extract, generalize, and adapt topic selection rules."""

    def __init__(self, store=None):
        from rag_system.topics.rules_store import TopicRulesStore
        self.store = store or TopicRulesStore()

    def learn_from_document(self, docx_path: str | Path) -> list[str]:
        """Extract rules from user's topic note document.

        Reads a .docx file containing topic brainstorming/notes,
        sends to DeepSeek to extract generalizable rules,
        stores them persistently.
        """
        docx_path = Path(docx_path)
        if not docx_path.exists():
            logger.error(f"Document not found: {docx_path}")
            return []

        # Read document
        notes = self._read_docx(docx_path)
        if not notes.strip():
            logger.error("Document is empty")
            return []

        logger.info(f"Learning from document: {docx_path.name} ({len(notes)} chars)")

        # Extract rules via LLM
        rules = self._extract_rules_via_llm(notes, source=f"doc:{docx_path.name}")

        # Store each extracted rule
        rule_ids = []
        for rule in rules.get("extracted_rules", []):
            rule_id = self.store.add_rule(rule, source=f"doc:{docx_path.name}")
            rule_ids.append(rule_id)

        # Store anti-patterns
        for ap in rules.get("anti_patterns", []):
            self.store.add_anti_pattern(ap, source=f"doc:{docx_path.name}")

        # Store quality principles as checklist items
        for qp in rules.get("quality_principles", []):
            self.store.add_checklist_item(qp)

        logger.info(f"Learned {len(rule_ids)} rules, {len(rules.get('anti_patterns', []))} anti-patterns")
        return rule_ids

    def learn_from_feedback(self, topic_title: str, category: str,
                            feedback: str, rating: int = 0) -> str | None:
        """Extract generalizable insight from specific topic feedback.

        When user says '这个选题的问题是XXX', extract what principle
        this implies, so it can prevent similar issues in other categories.
        """
        if not feedback.strip():
            return None

        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

        prompt = f"""用户对生成的一个选题给出了反馈。请从中提炼一条【跨品类通用的选题规则或教训】。

选题: {topic_title}
品类: {category}
用户反馈: {feedback}
评价: {'正面' if rating > 0 else '负面' if rating < 0 else '中性'}

请用一句话概括：这个反馈揭示了什么选题规律？这条规律如何应用到其他品类？
只输出一句话，不超过100字。"""

        try:
            resp = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5, max_tokens=200,
            )
            insight = resp.choices[0].message.content.strip()
            self.store.log_feedback(topic_title, category, feedback, rating, insight)
            return insight
        except Exception as e:
            logger.error(f"Feedback learning failed: {e}")
            return None

    def learn_from_competitive(self, deep_analysis_path: str | Path,
                               category: str, video_title: str) -> list[str]:
        """Extract topic selection insights from a competitor deep analysis.

        Reads a deep_analysis.txt (from competitive pipeline),
        pulls out the '选题策略启示' section, and generalizes it.
        """
        path = Path(deep_analysis_path)
        if not path.exists():
            return []

        content = path.read_text(encoding="utf-8")

        # Extract the 选题策略 section
        strategy_section = self._extract_strategy_section(content)
        if not strategy_section:
            return []

        # Generalize to other categories
        generalized = self._generalize_competitive_insight(
            strategy_section, category, video_title)
        return generalized

    def cross_pollinate(self, source_category: str, target_category: str) -> list[dict]:
        """Apply rules from one category to another.

        Uses LLM to adapt rules from source_category context to target_category.
        """
        rules = self.store.get_rules_for_category(source_category)
        if not rules:
            return []

        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

        adapted = []
        for rule in rules[:3]:  # top 3 most relevant
            prompt = f"""将以下选题规则从一个品类适配到另一个品类。

规则: {rule.get('rule_name')}
公式: {rule.get('formula', '')}
源品类: {source_category}
目标品类: {target_category}

请给出这个规则在{target_category}品类上的具体应用示例（包括一个具体选题标题），不超过150字。"""

            try:
                resp = client.chat.completions.create(
                    model=DEEPSEEK_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7, max_tokens=300,
                )
                adaptation = resp.choices[0].message.content.strip()
                adapted.append({"rule": rule.get("rule_name"), "adaptation": adaptation})
                self.store.add_cross_category_mapping(
                    source_category, target_category, adaptation)
            except Exception as e:
                logger.error(f"Cross-pollination failed: {e}")

        return adapted

    # ---- Internal helpers ----

    def _read_docx(self, path: Path) -> str:
        try:
            from docx import Document
            doc = Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception as e:
            logger.error(f"Failed to read docx: {e}")
            return ""

    def _extract_rules_via_llm(self, notes: str, source: str = "") -> dict:
        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
        prompt = EXTRACTION_PROMPT.format(notes=notes[:4000])

        try:
            resp = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5, max_tokens=2000,
            )
            raw = resp.choices[0].message.content.strip()
            # Extract JSON from response
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(raw[start:end])
            return {}
        except Exception as e:
            logger.error(f"Rule extraction failed: {e}")
            return {}

    def _extract_strategy_section(self, content: str) -> str:
        """Extract the strategy analysis section from deep analysis."""
        markers = ["选题策略启示", "爆款原因归因", "核心用户需求"]
        extracted = []
        for marker in markers:
            idx = content.find(marker)
            if idx >= 0:
                # Take ~800 chars after marker
                end = min(idx + 800, len(content))
                extracted.append(content[idx:end])
        return "\n".join(extracted) if extracted else ""

    def _generalize_competitive_insight(self, strategy_text: str,
                                        category: str, video_title: str) -> list[str]:
        """Use LLM to generalize competitive insight to universal rule."""
        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

        prompt = f"""从以下竞品视频的选题策略分析中，提炼一条【跨品类通用的选题规则】。

品类: {category}
视频: {video_title}
策略分析:
{strategy_text[:1500]}

要求：
1. 提炼出的规则不能只适用于{category}品类
2. 给出该规则在至少2个其他品类上的应用示例
3. 输出格式: "规则名称：XXX | 公式：XXX | 示例1（XX品类）：XXX | 示例2（XX品类）：XXX"
4. 总字数不超过200字"""

        try:
            resp = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5, max_tokens=400,
            )
            insight = resp.choices[0].message.content.strip()
            # Store as a rule
            rule = {
                "rule_name": f"[竞品学习] {video_title[:30]}",
                "description": insight,
                "formula": insight,
                "applicable_categories": "ALL",
            }
            self.store.add_rule(rule, source=f"competitive:{category}")
            return [insight]
        except Exception as e:
            logger.error(f"Insight generalization failed: {e}")
            return []
