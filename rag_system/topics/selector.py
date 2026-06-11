"""Topic selector — generates topic suggestions using stored rules + context.

Pulls from multiple sources:
  1. Stored topic selection rules (from user docs + feedback)
  2. Competitive analysis insights (wiki + deep analysis)
  3. Current hot topics (daily_topics pipeline)
  4. Category performance data
  5. Seasonal/timeliness context
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

from openai import OpenAI

from rag_system.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from rag_system.utils import logger

TOPIC_PROMPT = """你是顶级数码科技选题策划师，D先生的选题参谋。

## 你必须遵守的选题规则

{active_rules}

## 你必须避免的选题陷阱

{anti_patterns}

## 选题质量自检清单

{checklist}

## 当前上下文

日期: {today}
品类: {category}
近期热点: {hot_topics}
竞品洞察: {competitive_insights}
用户近期反馈: {recent_feedback}

## 任务

为【{category}】品类生成 3 个选题建议。

每个选题必须：
1. 包含完整的选题标题（吸引人、有信息量）
2. 说明选题角度和切入点
3. 标注应用了哪条/哪些选题规则
4. 列出目标用户场景（谁看了会想点）
5. 给出核心冲突/信息差是什么
6. 说明时效性挂载点（如果有）

输出JSON数组格式：
[
  {{
    "title": "选题标题",
    "angle": "切入角度说明",
    "applied_rules": ["规则1", "规则2"],
    "target_scenes": ["场景1", "场景2"],
    "core_conflict": "核心冲突/信息差",
    "timeliness_hook": "时效性挂载（无则null）",
    "why_it_works": "为什么这个选题会火"
  }}
]

直接输出JSON，不要其他文字。"""


class TopicSelector:
    """Generates topic suggestions informed by rules, data, and feedback."""

    CATEGORIES = ["keyboard", "mouse", "monitor", "laptop", "phone",
                  "gpu", "headphone", "desk_chair"]

    def __init__(self, store=None):
        from rag_system.topics.rules_store import TopicRulesStore
        self.store = store or TopicRulesStore()

    def generate_for_category(self, category: str, n: int = 3) -> list[dict]:
        """Generate topic suggestions for a single category."""
        # Gather context
        rules = self.store.get_rules_for_category(category)
        anti_patterns = self.store.get_anti_patterns()
        checklist = self.store.get_checklist()
        hot_topics = self._get_hot_topics()
        competitive_insights = self._get_competitive_insights(category)
        recent_feedback = self.store.get_recent_feedback(10)

        # Format rules for prompt
        rules_text = "\n".join(
            f"- {r.get('rule_name', '')}: {r.get('description', '')}"
            for r in rules
        ) if rules else "暂无选题规则，请先通过选题笔记学习。"

        anti_text = "\n".join(f"- {p}" for p in anti_patterns)
        checklist_text = "\n".join(f"- {c}" for c in checklist)

        feedback_text = "\n".join(
            f"[{f.get('rating', 0)}] {f.get('topic_title', '')}: {f.get('feedback', '')[:100]}"
            for f in recent_feedback
        ) if recent_feedback else "暂无反馈"

        prompt = TOPIC_PROMPT.format(
            active_rules=rules_text,
            anti_patterns=anti_text,
            checklist=checklist_text,
            today=datetime.now().strftime("%Y-%m-%d"),
            category=category,
            hot_topics=hot_topics or "暂无近期热点",
            competitive_insights=competitive_insights or "暂无竞品洞察",
            recent_feedback=feedback_text,
        )

        # Generate via LLM
        topics = self._generate_via_llm(prompt, category)
        return topics[:n]

    def generate_all_categories(self, n: int = 2) -> dict[str, list[dict]]:
        """Generate topic suggestions for all 8 categories."""
        results = {}
        for cat in self.CATEGORIES:
            logger.info(f"Generating topics for: {cat}")
            topics = self.generate_for_category(cat, n=n)
            results[cat] = topics
        return results

    def generate_daily_report(self) -> dict:
        """Generate daily topic suggestions across all categories."""
        topics = self.generate_all_categories(n=2)
        report = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "generated_at": datetime.now().isoformat(),
            "total_topics": sum(len(v) for v in topics.values()),
            "topics_by_category": topics,
            "active_rules_count": len(self.store.get_all_rules()),
            "quality_checklist": self.store.get_checklist(),
        }
        self._save_report(report, "daily")
        return report

    def generate_weekly_report(self) -> dict:
        """Generate weekly topic suggestions with competitive integration."""
        # Learn from recent competitive analysis before generating
        self._integrate_competitive_learnings()

        topics = self.generate_all_categories(n=3)
        report = {
            "date_range": f"{datetime.now().strftime('%Y-%m-%d')} (weekly)",
            "generated_at": datetime.now().isoformat(),
            "total_topics": sum(len(v) for v in topics.values()),
            "topics_by_category": topics,
            "store_stats": self.store.get_stats(),
            "trending_integration": self._get_hot_topics(),
        }
        self._save_report(report, "weekly")
        return report

    # ---- Context gathering ----

    def _get_hot_topics(self) -> str:
        """Read latest hot topics from daily pipeline output."""
        seed_file = Path("output/daily/topics_seed.txt")
        if not seed_file.exists():
            return ""
        try:
            content = seed_file.read_text(encoding="utf-8")
            # Take first 500 chars
            return content[:500]
        except Exception:
            return ""

    def _get_competitive_insights(self, category: str) -> str:
        """Pull recent competitive analysis insights for a category."""
        # Check wiki entries
        wiki_dir = Path(f"output/competitive/wiki/{category}")
        insights = []
        if wiki_dir.exists():
            for f in sorted(wiki_dir.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)[:3]:
                content = f.read_text(encoding="utf-8")[:300]
                insights.append(content)

        # Check deep analysis files
        sessions_dir = Path("output/competitive/sessions")
        if sessions_dir.exists():
            for d in sorted(sessions_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
                if category in d.name:
                    deep_file = d / "deep_analysis.txt"
                    if deep_file.exists():
                        content = deep_file.read_text(encoding="utf-8")
                        # Extract strategy section
                        idx = content.find("选题策略启示")
                        if idx >= 0:
                            insights.append(content[idx:idx+500])
                        if len(insights) >= 2:
                            break

        return "\n---\n".join(insights) if insights else ""

    def _generate_via_llm(self, prompt: str, category: str) -> list[dict]:
        """Call LLM to generate topic suggestions."""
        if not DEEPSEEK_API_KEY:
            logger.warning("No DeepSeek API key, using rule-based fallback")
            return self._rule_based_fallback(category)

        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
        try:
            resp = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.8, max_tokens=2500,
            )
            raw = resp.choices[0].message.content.strip()
            # Extract JSON
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start >= 0 and end > start:
                topics = json.loads(raw[start:end])
                logger.info(f"Generated {len(topics)} topics for {category}")
                return topics
            return []
        except Exception as e:
            logger.error(f"Topic generation failed: {e}")
            return self._rule_based_fallback(category)

    def _rule_based_fallback(self, category: str) -> list[dict]:
        """Generate topics from rules alone (no LLM)."""
        rules = self.store.get_rules_for_category(category)
        if not rules:
            return [{
                "title": f"[{category}] 请先学习选题笔记以生成选题",
                "angle": "需要至少一份选题笔记来提取规则",
                "applied_rules": [],
                "target_scenes": [],
                "core_conflict": "",
                "timeliness_hook": None,
                "why_it_works": "",
            }]
        # Simple template-based generation
        templates = [
            "{scene_a}、{scene_b}、{scene_c}——你的{product}该选哪一款",
            "{scene_a}玩家和{scene_b}玩家需要的{product}根本不同",
            "别再只看{common_mistake}选{product}了，关键是{correct_way}",
        ]
        return [{"title": t.format(scene_a="场景A", scene_b="场景B", scene_c="场景C",
                                    product=category, common_mistake="价格",
                                    correct_way="你的使用场景"),
                 "angle": "场景分化", "applied_rules": [r["rule_name"] for r in rules[:2]],
                 "target_scenes": [], "core_conflict": "", "timeliness_hook": None,
                 "why_it_works": ""} for t in templates]

    def _integrate_competitive_learnings(self):
        """Before generating weekly report, learn from recent competitive analysis."""
        sessions_dir = Path("output/competitive/sessions")
        if not sessions_dir.exists():
            return

        from rag_system.topics.learner import RuleLearner
        learner = RuleLearner(self.store)

        # Process recent sessions
        recent = sorted(sessions_dir.iterdir(),
                        key=lambda x: x.stat().st_mtime, reverse=True)[:10]
        for d in recent:
            deep_file = d / "deep_analysis.txt"
            if not deep_file.exists():
                continue
            category = d.name.split("_")[1] if "_" in d.name else "unknown"
            learner.learn_from_competitive(
                str(deep_file), category, d.name)

    def _save_report(self, report: dict, report_type: str):
        """Save generated topic report."""
        out_dir = Path("output/topic_reports")
        out_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y%m%d")
        path = out_dir / f"topic_report_{report_type}_{date_str}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"Topic report saved: {path}")
