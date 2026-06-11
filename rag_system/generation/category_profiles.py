"""Category profiles — data-driven rules extracted from real video performance.

These rules are injected into the generator's system prompt to provide
evidence-based guidance per category.
"""

from pathlib import Path
from rag_system.config import PROJECT_ROOT

PROFILES_FILE = PROJECT_ROOT / "output" / "performance" / "category_profiles.json"

# ── Default profiles (pre-seeded from 31-video analysis) ──
DEFAULT_PROFILES = {
    "gpu": {
        "avg_5s_rate": 0.406,
        "avg_duration": 14.2,
        "effective_hooks": ["价格锚定", "代际对比", "性价比判断"],
        "ineffective_hooks": ["功能罗列", "参数堆砌", "纯展示"],
        "hook_rule": "优先使用价格对比或代际对比开场。禁止参数罗列式开头。开场前2秒必须有画面信息+口播信息同时出现。",
        "pacing_rule": "信息密度要高——观众期待深度参数解析。长句(≤25字)讲技术原理，短句(≤10字)给结论。比例2:1。",
        "best_publish_day": "周二",
    },
    "laptop": {
        "avg_5s_rate": 0.304,
        "avg_duration": 12.7,
        "effective_hooks": ["避坑指南", "性价比排行", "场景化推荐"],
        "ineffective_hooks": ["品牌吹捧", "单纯参数"],
        "hook_rule": "用'避坑'或'价位段怎么选'开场。笔记本观众要的是购买决策辅助，不是产品说明书。",
        "pacing_rule": "多机型对比时控制每台1-2句话，最后给明确选择建议。花字标注价格区间和适用人群。",
        "best_publish_day": "周五",
    },
    "monitor": {
        "avg_5s_rate": 0.259,
        "avg_duration": 8.1,
        "effective_hooks": ["刷新率冲击", "画面对比", "性价比排行"],
        "ineffective_hooks": ["品牌历史", "技术科普"],
        "hook_rule": "显示器最大的问题是视觉信息无法通过口播传递。开场前三镜必须是画面冲击——对比画面/慢动作/色彩震撼。",
        "pacing_rule": "屏幕画面:口播 = 6:4。多用B-roll覆盖口播，减少纯口播镜头。运镜占比放宽至固定50%。",
        "best_publish_day": "周四",
    },
    "keyboard": {
        "avg_5s_rate": 0.119,
        "avg_duration": 3.4,
        "effective_hooks": ["价格极端对比", "声音ASMR", "手感体验"],
        "ineffective_hooks": ["参数列表", "开箱"],
        "hook_rule": "键盘视频的钩子不是'说什么'而是'看什么+听什么'。开场必须: 敲击声+价格对比+一句话观点，三要素缺一不可。",
        "pacing_rule": "打字声音是核心卖点——每30秒至少1段纯打字声(无口播覆盖)。轴体特写占比>40%。",
        "best_publish_day": "周四",
    },
    "mouse": {
        "avg_5s_rate": 0.20,
        "avg_duration": 5.0,
        "effective_hooks": ["克重冲击", "握感对比", "性价比排行"],
        "ineffective_hooks": ["传感器参数", "品牌故事"],
        "hook_rule": "鼠标的核心钩子是克重数字——'54克'比'轻量化'有效10倍。开场就报重量+对比参照物。",
        "pacing_rule": "握持展示+手部跟拍占比>30%。传感器参数移到花字，口播只说结论。",
        "best_publish_day": "周二",
    },
    "desk_chair": {
        "avg_5s_rate": 0.107,
        "avg_duration": 4.1,
        "effective_hooks": ["痛点共鸣", "坐感对比", "长期使用体验"],
        "ineffective_hooks": ["外观展示", "材质罗列"],
        "hook_rule": "电竞椅/桌椅品类的钩子是'身体感受'而非'产品外观'。开场必须痛点共鸣: '打一下午游戏腰酸背痛'。禁止产品亮相式开场。",
        "pacing_rule": "坐感体验描述:产品展示=6:4。需要有真人坐着说话的越肩镜头或使用场景，不能全是静态产品。",
        "best_publish_day": "周五",
    },
    "headphone": {
        "avg_5s_rate": 0.25,
        "avg_duration": 8.0,
        "effective_hooks": ["价格对比", "佩戴舒适度", "音质盲测"],
        "ineffective_hooks": ["参数堆砌", "开箱"],
        "hook_rule": "耳机核心是'听'。开场用价格对比+一个音质结论。佩戴舒适度是第二卖点。",
        "pacing_rule": "佩戴展示(假人/模特)>30%。频谱/参数移到花字。",
        "best_publish_day": "周二",
    },
    "phone": {
        "avg_5s_rate": 0.30,
        "avg_duration": 10.0,
        "effective_hooks": ["性价比对比", "拍照样张", "续航测试"],
        "ineffective_hooks": ["外观展示", "系统功能介绍"],
        "hook_rule": "用价格锚定+一句话结论开场。拍照样张和续航数据是核心卖点。",
        "pacing_rule": "样张/屏幕特写占50%以上。竞品对比用分屏画面。",
        "best_publish_day": "周五",
    },
    "speaker": {
        "avg_5s_rate": 0.22,
        "avg_duration": 6.0,
        "effective_hooks": ["价格冲击", "音质对比", "体积小声音大的反差"],
        "ineffective_hooks": ["外观展示", "品牌介绍"],
        "hook_rule": "开场用价格+体积反差制造认知冲突。音质片段是核心说服力。",
        "pacing_rule": "播放音乐/游戏音效的B-roll>40%。",
        "best_publish_day": "周三",
    },
}


def load_profiles() -> dict:
    """Load category profiles, with defaults as fallback."""
    if PROFILES_FILE.exists():
        import json
        saved = json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
        # Merge with defaults so new categories always have data
        merged = dict(DEFAULT_PROFILES)
        merged.update(saved)
        return merged
    return dict(DEFAULT_PROFILES)


def save_profiles(profiles: dict):
    import json
    PROFILES_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILES_FILE.write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")


def get_profile(category: str) -> dict:
    profiles = load_profiles()
    return profiles.get(category, profiles.get("monitor", {}))


def build_rule_context(category: str) -> str:
    """Build a rule injection string for the given category.

    Injects data-driven rules into the generator's system prompt.
    """
    p = get_profile(category)
    if not p:
        return ""

    parts = [f"\n## 数据反推——{category}品类的真实表现规律\n"]
    parts.append("以下规则来自D先生账号31条视频的真实播放数据，非主观判断：\n")

    # Hook rule
    parts.append(f"### 钩子策略（5s完播率: {p.get('avg_5s_rate', 0):.0%}）")
    parts.append(f"有效钩子: {', '.join(p.get('effective_hooks', []))}")
    parts.append(f"无效钩子: {', '.join(p.get('ineffective_hooks', []))}")
    parts.append(p.get("hook_rule", ""))
    parts.append("")

    # Pacing
    parts.append(f"### 节奏要求（平均观看时长: {p.get('avg_duration', 0):.0f}s）")
    parts.append(p.get("pacing_rule", ""))
    parts.append("")

    # Publish
    parts.append(f"### 发布策略")
    parts.append(f"该品类最佳发布日: {p.get('best_publish_day', '待定')}")

    return "\n".join(parts)


def update_profiles_from_data():
    """Recompute category profiles from the latest video performance data."""
    try:
        from rag_system.generation.performance_tracker import load_performances, compute_effectiveness_scores
    except ImportError:
        return

    perfs = load_performances()
    if not perfs:
        return

    scored = compute_effectiveness_scores(perfs)

    # Group by category
    from collections import defaultdict
    cat_data = defaultdict(list)
    for s in scored:
        cat_data[s["category"]].append(s)

    profiles = dict(DEFAULT_PROFILES)

    for cat, items in cat_data.items():
        if len(items) < 2:
            continue
        from statistics import mean
        avg_s5 = mean(it["s5_rate"] for it in items)
        avg_dur = mean(it["avg_duration"] for it in items)

        if cat in profiles:
            profiles[cat]["avg_5s_rate"] = round(avg_s5, 3)
            profiles[cat]["avg_duration"] = round(avg_dur, 1)
        else:
            profiles[cat] = {
                "avg_5s_rate": round(avg_s5, 3),
                "avg_duration": round(avg_dur, 1),
                "effective_hooks": [],
                "ineffective_hooks": [],
                "hook_rule": "",
                "pacing_rule": "",
                "best_publish_day": "待定",
            }

    save_profiles(profiles)


def format_profiles_report() -> str:
    """Pretty-print all category profiles."""
    profiles = load_profiles()
    lines = ["=" * 60, "  品类画像 — 数据驱动的创作规则", "=" * 60]
    for cat in sorted(profiles.keys()):
        p = profiles[cat]
        lines.append(f"\n  [{cat}]")
        lines.append(f"    5s完播率: {p.get('avg_5s_rate', 0):.1%} | 均观看时长: {p.get('avg_duration', 0):.0f}s")
        lines.append(f"    有效钩子: {', '.join(p.get('effective_hooks', []))}")
        lines.append(f"    无效钩子: {', '.join(p.get('ineffective_hooks', []))}")
        lines.append(f"    最佳发布日: {p.get('best_publish_day', '待定')}")
    lines.append("\n" + "=" * 60)
    return "\n".join(lines)
