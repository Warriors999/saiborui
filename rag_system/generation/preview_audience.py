"""AI Preview Audience — 影视飓风"AI点映团" methodology.

Simulates 3 audience personas (casual viewer, expert user, client) reviewing a script
before publication. Identifies engagement drop-off points and produces actionable feedback.
"""

import json
import re

from openai import OpenAI

from rag_system.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from rag_system.utils import logger

# ---------------------------------------------------------------------------
# System prompt for the AI audience review
# ---------------------------------------------------------------------------

AUDIENCE_REVIEW_PROMPT = """你是一个专业的视频脚本审阅AI，模拟"AI点映团"的3类观众对脚本进行审阅。
你需要站在每类观众的视角，真实模拟他们的观看体验，找出脚本的薄弱环节。

## 审阅规则

1. 逐段分析脚本，标记每个时间段的观众投入度（高/中/低）
2. 模拟3类观众的真实反应，不要敷衍，要指出具体问题
3. 给出可执行的改进建议，而不是泛泛而谈
4. 时间估算：按大约每秒5-6个汉字的语速推算时间节点

## 三类观众画像

### 1. 路人观众（普通刷视频用户）
- 对产品不了解，没有预先信任
- 注意力极易分散，随时可能划走
- 最关心：这和我有什么关系？为什么我要继续看？
- 容易被节奏拖沓、术语过多、开头不吸引人劝退

### 2. 专业用户（资深产品用户）
- 懂产品参数和行业常识
- 会挑刺，注重细节真实性和专业性
- 最关心：数据准不准？有没有夸大？对比是否公平？
- 反感过度营销话术、参数错误、避重就轻

### 3. 甲方视角（品牌方审稿人）
- 关注品牌形象和核心卖点传达
- 在意合规风险和市场影响
- 最关心：品牌露出够不够？核心卖点是否突出？有没有风险？
- 警惕竞品对比不当、虚假宣传、品牌调性不符

## 输出格式

严格按以下JSON格式输出，不要输出任何其他内容：

```json
{
  "reviews": [
    {
      "persona": "路人观众",
      "overall": "整体评价，1-2句话概括",
      "hook_score": 8,
      "retention_risk": [
        {"position": "具体时间段或位置", "risk": "流失风险描述", "suggestion": "具体改进建议"}
      ],
      "confusing_terms": ["观众可能看不懂的术语"],
      "verdict": "会看完 / 中间划走 / 开头就划走"
    },
    {
      "persona": "专业用户",
      "overall": "整体评价，1-2句话概括",
      "credibility_score": 8,
      "accuracy_issues": [
        {"position": "具体位置", "issue": "参数或表述问题", "correction": "修正建议"}
      ],
      "fairness_note": "对比是否公平的评价",
      "verdict": "可信 / 有疑虑 / 不可信"
    },
    {
      "persona": "甲方视角",
      "overall": "整体评价，1-2句话概括",
      "brand_score": 8,
      "brand_issues": [
        {"aspect": "品牌露出/卖点传达/合规风险", "problem": "具体问题", "suggestion": "改进建议"}
      ],
      "risk_level": "低风险 / 中风险 / 高风险",
      "verdict": "可发布 / 修改后发布 / 不建议发布"
    }
  ],
  "boring_timeline": [
    {"time_range": "0-15s", "engagement": "高", "note": "简短说明当前段的观众状态"},
    {"time_range": "15-30s", "engagement": "中", "note": "简短说明当前段的观众状态"}
  ],
  "top_action_items": [
    "最重要的改进项1",
    "最重要的改进项2",
    "最重要的改进项3"
  ]
}
```

## 注意事项
- hook_score、credibility_score、brand_score 为 1-10 的整数
- boring_timeline 按时间顺序排列，覆盖整个脚本
- top_action_items 只列最关键的3项，按优先级排序
- 所有评价必须具体、可执行，拒绝空洞的套话
- 时间估算以正常语速（约每秒5-6个汉字）为基准
"""


def run_audience_review(
    script: str,
    product_name: str,
    category: str,
    persona: str,
) -> dict:
    """Run the AI Preview Audience review on a script.

    Calls DeepSeek API to simulate 3 audience personas reviewing the script.

    Args:
        script: The full video script text to review.
        product_name: Name of the product being reviewed.
        category: Product category (keyboard, mouse, monitor, etc.).
        persona: The script's content persona (e.g. "D先生").

    Returns:
        A dict with keys: reviews, boring_timeline, top_action_items.
    """
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    system_prompt = AUDIENCE_REVIEW_PROMPT

    user_prompt = f"""请审阅以下视频脚本，模拟3类观众的真实观看体验。

## 脚本信息
- 产品：{product_name}
- 品类：{category}
- 人设：{persona}

## 脚本正文
{script}

请严格按照JSON格式输出审阅结果。"""

    logger.info(
        "Audience review: model=%s, product=%s, category=%s, persona=%s, script_len=%d",
        DEEPSEEK_MODEL, product_name, category, persona, len(script),
    )

    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.4,
        max_tokens=4096,
    )

    raw = response.choices[0].message.content
    logger.info("Audience review raw response length: %d", len(raw))

    # Extract JSON from the response (handle possible markdown code fences)
    review = _parse_review_json(raw)

    return review


def _parse_review_json(raw: str) -> dict:
    """Extract and parse JSON from the LLM response.

    Handles responses wrapped in ```json code fences or containing extra text.
    """
    # Try to extract JSON from markdown code blocks first
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if json_match:
        json_str = json_match.group(1).strip()
    else:
        # Try to find JSON object boundaries
        brace_start = raw.find("{")
        brace_end = raw.rfind("}")
        if brace_start != -1 and brace_end != -1:
            json_str = raw[brace_start:brace_end + 1]
        else:
            json_str = raw

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning("JSON parse failed: %s. Raw: %s", e, raw[:500])
        return {
            "reviews": [],
            "boring_timeline": [],
            "top_action_items": [],
            "_parse_error": str(e),
            "_raw": raw,
        }


def format_audience_review(review: dict) -> str:
    """Pretty-print the audience review results as a readable text report.

    Args:
        review: The dict returned by run_audience_review().

    Returns:
        A formatted multi-line string suitable for CLI display.
    """
    lines = []
    lines.append("=" * 60)
    lines.append("  AI点映团 · 脚本审阅报告")
    lines.append("=" * 60)

    # --- Persona Reviews ---
    reviews = review.get("reviews", [])
    if not reviews:
        lines.append("\n(无法解析审阅结果，请检查API返回)\n")
        if review.get("_raw"):
            lines.append(f"原始返回:\n{review['_raw'][:500]}")
        return "\n".join(lines)

    persona_icons = {
        "路人观众": "路人",
        "专业用户": "专业",
        "甲方视角": "甲方",
    }

    for i, r in enumerate(reviews):
        persona_name = r.get("persona", f"审阅者{i + 1}")
        tag = persona_icons.get(persona_name, "——")
        lines.append(f"\n{'─' * 60}")
        lines.append(f"  [{tag}] {persona_name}")
        lines.append(f"{'─' * 60}")

        # Overall
        overall = r.get("overall", "")
        if overall:
            lines.append(f"\n  整体评价：{overall}")

        # Scores
        if "hook_score" in r:
            lines.append(f"  钩子评分：{r['hook_score']}/10")
        if "credibility_score" in r:
            lines.append(f"  可信度评分：{r['credibility_score']}/10")
        if "brand_score" in r:
            lines.append(f"  品牌评分：{r['brand_score']}/10")

        # Retention risks (路人)
        if r.get("retention_risk"):
            lines.append(f"\n  【流失风险点】")
            for risk in r["retention_risk"]:
                pos = risk.get("position", "?")
                risk_desc = risk.get("risk", "")
                suggestion = risk.get("suggestion", "")
                lines.append(f"    ◆ {pos}")
                lines.append(f"      风险：{risk_desc}")
                lines.append(f"      建议：{suggestion}")

        # Confusing terms (路人)
        if r.get("confusing_terms"):
            terms = "、".join(r["confusing_terms"])
            lines.append(f"\n  【可能看不懂的术语】{terms}")

        # Accuracy issues (专业用户)
        if r.get("accuracy_issues"):
            lines.append(f"\n  【准确性问题】")
            for issue in r["accuracy_issues"]:
                pos = issue.get("position", "?")
                problem = issue.get("issue", "")
                correction = issue.get("correction", "")
                lines.append(f"    ◆ {pos}")
                lines.append(f"      问题：{problem}")
                lines.append(f"      修正：{correction}")

        # Fairness note (专业用户)
        if r.get("fairness_note"):
            lines.append(f"\n  【对比公平性】{r['fairness_note']}")

        # Brand issues (甲方)
        if r.get("brand_issues"):
            lines.append(f"\n  【品牌关注点】")
            for bi in r["brand_issues"]:
                aspect = bi.get("aspect", "")
                problem = bi.get("problem", "")
                suggestion = bi.get("suggestion", "")
                lines.append(f"    ◆ [{aspect}]")
                lines.append(f"      问题：{problem}")
                lines.append(f"      建议：{suggestion}")

        # Risk level (甲方)
        if r.get("risk_level"):
            lines.append(f"\n  【风险等级】{r['risk_level']}")

        # Verdict
        verdict = r.get("verdict", "")
        if verdict:
            lines.append(f"\n  【结论】{verdict}")

    # --- Boring Timeline ---
    timeline = review.get("boring_timeline", [])
    if timeline:
        lines.append(f"\n{'─' * 60}")
        lines.append(f"  [时间线] 观众投入度变化")
        lines.append(f"{'─' * 60}")

        eng_icons = {"高": "高", "中": "中", "低": "低"}
        for t in timeline:
            tr = t.get("time_range", "?")
            eng = t.get("engagement", "?")
            note = t.get("note", "")
            icon = eng_icons.get(eng, eng)
            lines.append(f"  {tr}  [{icon}]  {note}")

    # --- Top Action Items ---
    action_items = review.get("top_action_items", [])
    if action_items:
        lines.append(f"\n{'─' * 60}")
        lines.append(f"  [行动项] 优先改进清单")
        lines.append(f"{'─' * 60}")
        for idx, item in enumerate(action_items, 1):
            lines.append(f"  {idx}. {item}")

    lines.append(f"\n{'=' * 60}")
    lines.append("  审阅完成 — AI点映团")
    lines.append(f"{'=' * 60}")

    return "\n".join(lines)
