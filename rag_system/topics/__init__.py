"""
自成长选题系统 — Self-Improving Topic Selection Engine

Architecture:
  选题笔记(.docx) → 规则提取 → 规则存储 ← 用户反馈
       ↓                          ↓
  竞品学习(deep analysis) → 跨品类规则迁移 → 每日选题生成
       ↓                          ↓
  热点话题(daily_topics) → 选题生成器 → 选题建议报告

闭环：
  生成选题 → 用户批注 → 规则更新 → 下次生成更精准
"""

from rag_system.topics.rules_store import TopicRulesStore
from rag_system.topics.selector import TopicSelector
from rag_system.topics.learner import RuleLearner

__all__ = ["TopicRulesStore", "TopicSelector", "RuleLearner"]
