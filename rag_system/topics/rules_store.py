"""Persistent topic selection rules store with self-improvement capability."""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from rag_system.utils import logger

STORE_PATH = Path("output/topics/topic_selection_rules.json")
FEEDBACK_PATH = Path("output/topics/topic_feedback_log.json")


class TopicRulesStore:
    """Persistent, self-improving store of topic selection rules.

    Rules are extracted from user's topic notes (.docx), competitive analysis
    deep dives, and explicit feedback. They persist across sessions and grow
    over time.
    """

    def __init__(self, path: Path | None = None):
        self.path = path or STORE_PATH
        self.data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                # Migrate legacy keys
                if "topic_anti_patterns" in data and "anti_patterns" not in data:
                    data["anti_patterns"] = data.pop("topic_anti_patterns")
                # Ensure all required keys exist
                for key, default in self._default_store().items():
                    if key not in data:
                        data[key] = default
                return data
            except Exception:
                pass
        return self._default_store()

    def _default_store(self) -> dict:
        return {
            "version": 1,
            "updated_at": datetime.now().isoformat(),
            "extracted_rules": [],
            "anti_patterns": [],
            "quality_checklist": [],
            "category_specific_rules": {},
            "feedback_log": [],
            "cross_category_mappings": {},
        }

    def save(self):
        self.data["updated_at"] = datetime.now().isoformat()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- Rule CRUD ----

    def add_rule(self, rule: dict, source: str = "manual"):
        """Add a new topic selection rule."""
        rule["id"] = f"rule_{len(self.data['extracted_rules'])+1:03d}"
        rule["source"] = source
        rule["created_at"] = datetime.now().isoformat()
        rule["usage_count"] = 0
        rule["success_rate"] = None
        self.data["extracted_rules"].append(rule)
        self.save()
        logger.info(f"Rule added: {rule['rule_name']} (source: {source})")
        return rule["id"]

    def update_rule(self, rule_id: str, updates: dict):
        """Update an existing rule."""
        for rule in self.data["extracted_rules"]:
            if rule.get("id") == rule_id:
                rule.update(updates)
                self.save()
                return True
        return False

    def get_rules_for_category(self, category: str) -> list[dict]:
        """Get all rules applicable to a category, including universal rules."""
        universal = [r for r in self.data["extracted_rules"]
                     if r.get("applicable_categories") == "ALL"]
        specific = [r for r in self.data["extracted_rules"]
                    if category in (r.get("applicable_categories") or [])]
        # Also check category_specific_rules
        cat_rules = self.data.get("category_specific_rules", {}).get(category, [])
        return universal + specific + cat_rules

    def get_all_rules(self) -> list[dict]:
        return self.data["extracted_rules"]

    # ---- Anti-patterns ----

    def add_anti_pattern(self, pattern: str, source: str = "feedback"):
        self.data["anti_patterns"].append({
            "pattern": pattern,
            "source": source,
            "added_at": datetime.now().isoformat()
        })
        self.save()

    def get_anti_patterns(self) -> list[str]:
        return [p["pattern"] for p in self.data["anti_patterns"]]

    # ---- Quality Checklist ----

    def add_checklist_item(self, item: str):
        self.data["quality_checklist"].append(item)
        self.save()

    def get_checklist(self) -> list[str]:
        return self.data["quality_checklist"]

    # ---- Feedback Loop ----

    def log_feedback(self, topic_title: str, category: str, feedback: str,
                     rating: int = 0, extracted_insight: str | None = None):
        """Log user feedback on a generated topic."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "topic_title": topic_title,
            "category": category,
            "feedback": feedback,
            "rating": rating,  # -1=bad, 0=neutral, 1=good
            "extracted_insight": extracted_insight,
        }
        self.data["feedback_log"].append(entry)
        self.save()

    def get_recent_feedback(self, n: int = 20) -> list[dict]:
        return self.data["feedback_log"][-n:]

    # ---- Cross-category Mappings ----

    def add_cross_category_mapping(self, source_category: str,
                                   target_category: str,
                                   adaptation_note: str):
        """Record how a rule from one category applies to another."""
        key = f"{source_category}→{target_category}"
        if key not in self.data["cross_category_mappings"]:
            self.data["cross_category_mappings"][key] = []
        self.data["cross_category_mappings"][key].append({
            "adaptation_note": adaptation_note,
            "added_at": datetime.now().isoformat(),
        })
        self.save()

    # ---- Stats ----

    def record_rule_usage(self, rule_id: str, approved: bool):
        """Record when a rule was used in topic generation."""
        for rule in self.data["extracted_rules"]:
            if rule.get("id") == rule_id:
                rule["usage_count"] = rule.get("usage_count", 0) + 1
                if approved:
                    old = rule.get("success_rate") or 0
                    count = rule["usage_count"]
                    rule["success_rate"] = (old * (count - 1) + 1) / count
                self.save()
                break

    def get_stats(self) -> dict:
        rules = self.data["extracted_rules"]
        return {
            "total_rules": len(rules),
            "total_anti_patterns": len(self.data["anti_patterns"]),
            "total_feedback_entries": len(self.data["feedback_log"]),
            "most_used_rules": sorted(rules, key=lambda r: r.get("usage_count", 0), reverse=True)[:5],
            "category_mappings": len(self.data["cross_category_mappings"]),
        }
