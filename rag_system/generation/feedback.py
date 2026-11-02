"""Feedback extraction and injection — bridges 批注→回流 gap.

Two modes:
  1. archive: extract ALL annotations verbatim → JSON reference
  2. inject: apply annotations → rules_store + generate prompt context

The lesson from 2026-06-17: regex can't capture D先生's natural-language
annotations. Store raw verbatim and let the LLM interpret them directly.
"""

import json
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime


def extract_raw_annotations(docx_path: str) -> list[str]:
    """Extract raw annotation lines from a D先生-annotated docx.

    Annotations appear as inline notes in the document body — lines that
    are NOT timestamped script content (e.g. not "[0-3s] ...") and NOT
    metadata (e.g. not "总时长：" or "制作备注").

    Returns every annotation line as-is, preserving D先生's exact wording.
    """
    path = Path(docx_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {docx_path}")

    with zipfile.ZipFile(str(path), "r") as z:
        with z.open("word/document.xml") as f:
            tree = ET.parse(f)

    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = tree.getroot().find(f".//{{{ns}}}body")

    all_lines = []
    for para in body.findall(f".//{{{ns}}}p"):
        line = "".join(t.text or "" for t in para.iter(f"{{{ns}}}t") if t.text).strip()
        if line:
            all_lines.append(line)

    # Classify: script lines vs annotation lines
    script_patterns = [
        r"^\[\d+-\d+s\]",     # timestamp
        r"^总时长",            # duration
        r"^(?:干货|消费向导|科普|热点资讯|商单)$",  # type tag
    ]
    meta_markers = ["制作备注", "注：", "注:", "─"]

    annotations = []
    for line in all_lines:
        is_script = any(re.match(p, line) for p in script_patterns)
        is_meta = any(m in line for m in meta_markers)
        if not is_script and not is_meta and len(line) > 3:
            annotations.append(line)

    return annotations


def archive_annotations(docx_path: str, archive_dir: str = "") -> dict:
    """Extract raw annotations and save to a timestamped JSON file.

    Returns dict with file paths and annotation count.
    """
    annotations = extract_raw_annotations(docx_path)

    if not archive_dir:
        archive_dir = Path(__file__).resolve().parent.parent.parent / "output" / "topics" / "annotations"
    else:
        archive_dir = Path(archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)

    source_name = Path(docx_path).stem
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = archive_dir / f"{source_name[:40]}_{ts}.json"

    record = {
        "source_file": str(Path(docx_path).name),
        "archived_at": datetime.now().isoformat(),
        "annotation_count": len(annotations),
        "annotations": annotations,
    }

    with open(archive_path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)

    # Also update the master annotation index
    index_path = archive_dir / "_master_index.json"
    index = []
    if index_path.exists():
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                index = json.load(f)
        except (json.JSONDecodeError, KeyError):
            pass

    index.append({
        "file": str(archive_path.name),
        "source": str(Path(docx_path).name),
        "date": ts,
        "count": len(annotations),
        "preview": annotations[:3] if annotations else [],
    })

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    return {
        "count": len(annotations),
        "archive_path": str(archive_path),
        "index_path": str(index_path),
    }


def load_annotation_context(max_items: int = 30) -> str:
    """Load recent raw annotations for injection into the generate prompt.

    Returns a formatted string ready for prompt injection, containing
    D先生's verbatim corrections from the most recent feedback sessions.
    """
    archive_dir = Path(__file__).resolve().parent.parent.parent / "output" / "topics" / "annotations"
    index_path = archive_dir / "_master_index.json"

    if not index_path.exists():
        return ""

    try:
        with open(index_path, "r", encoding="utf-8") as f:
            index = json.load(f)
    except (json.JSONDecodeError, KeyError):
        return ""

    # Load the 3 most recent annotation files
    recent = sorted(index, key=lambda x: x.get("date", ""), reverse=True)[:3]
    all_annotations = []

    for entry in recent:
        fp = archive_dir / entry["file"]
        if fp.exists():
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    record = json.load(f)
                source = record.get("source_file", "unknown")
                for ann in record.get("annotations", []):
                    all_annotations.append(f"[{source}] {ann}")
            except (json.JSONDecodeError, KeyError):
                continue

    if not all_annotations:
        return ""

    # Format for prompt injection
    lines = [
        "\n## D先生最新批注——这是硬约束，不是参考资料",
        "",
        "以下是从最新批注中逐条提取的原文。你必须逐条遵守，不得违反：",
        "",
    ]
    for i, ann in enumerate(all_annotations[:max_items], 1):
        lines.append(f"{i}. {ann}")

    lines.append("")
    lines.append("生成脚本后，逐条检查以上每一条是否落实。未落实的视为不合格。")
    lines.append("")

    return "\n".join(lines)


def process_feedback(docx_path: str) -> dict:
    """Full feedback pipeline: extract raw annotations + archive for retrieval.

    2026-06-17 lesson: replaced regex-based rule extraction with raw verbatim
    archiving. The LLM interprets annotations directly rather than relying on
    brittle regex patterns.
    """
    print(f"[1/2] 提取批注原文: {Path(docx_path).name}")
    result = archive_annotations(docx_path)

    print(f"  提取 {result['count']} 条批注原文")
    print(f"  存档: {result['archive_path']}")
    print(f"  索引: {result['index_path']}")

    print(f"\n[2/2] 验证可检索性")
    context = load_annotation_context()
    if context:
        print(f"  注入上下文: {len(context)} chars, 可用于生成 prompt")
    else:
        print(f"  [WARN] 上下文为空，检查存档是否成功")

    # Route topic-relevant feedback to the topic rules store
    print(f"\n[3/3] 选题洞察回流")
    inject_to_topic_rules(result.get("annotations", []))

    return result


def extract_topic_insights(annotations: list[str]) -> list[str]:
    """Extract topic-selection-relevant insights from D先生's raw annotations.

    Filters annotations for patterns related to topic angle, audience targeting,
    type choice, or feasibility — things the topic pipeline should learn from.
    """
    topic_keywords = [
        "选题", "角度", "受众", "方向", "不适合", "没人看", "做不了",
        "伪痛点", "不存在", "讲不通", "太宽", "不精准", "类型",
        "干货", "科普", "消费向导", "抖音", "B站", "选题方向",
        "改成", "不如做", "应该做", "不值得",
    ]
    insights = []
    for ann in annotations:
        if any(kw in ann for kw in topic_keywords):
            insights.append(ann[:120])
    return insights


def inject_to_topic_rules(annotations: list[str]):
    """Route topic-relevant feedback to the self-growing rules store."""
    insights = extract_topic_insights(annotations)
    if not insights:
        return

    try:
        from rag_system.topics.rules_store import TopicRulesStore
        store = TopicRulesStore()
        for insight in insights[:10]:
            store.add_anti_pattern(insight, source="D先生批注")
        store._save()
        from rag_system.utils import logger
        logger.info("Injected %d topic insights from D先生 feedback into rules store", len(insights))
    except Exception as e:
        from rag_system.utils import logger
        logger.warning("Failed to inject topic insights: %s", e)
