"""Weekly scripts batch generator — bridges 选题→脚本 with full context.

Reads _weekly_topics.json (output of weekly-report), converts each topic
into a fully-contextualized generate call including RAG retrieval, structured
brief_context, and cover_direction. Batch produces all 5 scripts with audit.
"""

import json
import re
from pathlib import Path
from datetime import datetime


# Topic type → script format mapping
TOPIC_TYPE_CONFIG = {
    "干货": {"format": "review"},
    "消费向导": {"format": "comparison"},
    "科普": {"format": "hkrr"},
    "热点资讯": {"format": "review"},
}

# Category Chinese → English mapping
CATEGORY_MAP = {
    "键盘": "keyboard", "鼠标": "mouse", "显示器": "monitor",
    "笔记本": "laptop", "手机": "phone", "显卡": "gpu",
    "耳机": "headphone", "音箱": "speaker", "桌椅": "desk_chair",
    "外设": "mouse", "数码": "laptop", "AI": "laptop",
    "音频": "headphone", "其他": "laptop",
}

DURATION_MAP = {"干货": 0.58, "消费向导": 0.70, "科普": 0.63, "热点资讯": 0.67}


def load_weekly_topics(topics_path: str = "") -> dict:
    """Load the winner weekly topics JSON."""
    if not topics_path:
        project_root = Path(__file__).resolve().parent.parent.parent
        topics_path = project_root / "output" / "daily" / "_weekly_topics.json"
    else:
        topics_path = Path(topics_path)

    if not topics_path.exists():
        raise FileNotFoundError(f"Weekly topics not found: {topics_path}\n"
                                "Run 'weekly-report' first.")

    with open(topics_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _extract_product_name(title: str, category: str) -> str:
    """Derive a clean product name from topic title + category.

    Uses category as base rather than blindly truncating the clickbait title.
    """
    # Try to extract a noun phrase from the title
    # Pattern: "XX键盘" or "XX的XX" or first 15 chars as fallback
    clean = re.sub(r'[？?！!，,。.、]', '', title)
    # If title mentions a specific product/brand, extract it
    brand_match = re.search(r'(?:罗技|雷蛇|海盗船|樱桃|ROG|外星人|苹果|华为|小米|OPPO|vivo|三星|索尼|Bose|AirPods|GPW|蝰蛇|毒蝰|夜魔)[^\s，,。.]{0,8}', title)
    if brand_match:
        return brand_match.group(0)[:30]
    # Fallback: category + key feature from title
    keywords = re.findall(r'[一-鿿]{2,6}(?:键盘|鼠标|显示器|耳机|笔记本|手机|显卡|音箱)', title)
    if keywords:
        return keywords[0][:30]
    return f"{category}新品"


def _build_brief_context(topic: dict) -> str:
    """Build structured editorial guide from topic metadata.

    Converts unique_presentation, reverse_structure, user_need, solved_need
    into a markdown-formatted brief_context block (same pattern as brief_to_prompt_context).
    """
    parts = []
    parts.append(f"## 选题创作简报 — {topic.get('type', '')}")

    user_need = topic.get("user_need", "")
    if user_need:
        parts.append(f"\n### 用户痛点\n{user_need}")

    solved = topic.get("solved_need", "")
    if solved:
        parts.append(f"\n### 价值主张\n{solved}")

    up = topic.get("unique_presentation", "")
    if up:
        parts.append(f"\n### 独特展现方式（必须照此执行）\n{up}")

    structure = topic.get("reverse_structure", "")
    if structure:
        parts.append(f"\n### 结构骨架（标注了秒数和钩子类型）\n{structure}")

    ref = topic.get("ref_video", "")
    if ref:
        parts.append(f"\n### 对标参考\n{ref}")

    parts.append(f"\n### 类型要求\n这是一条{topic.get('type', '干货')}类视频。" +
                 {"干货": "只讲HOW，不铺垫WHY。直接给操作步骤和参数建议。",
                  "消费向导": "客观筛选推荐，不偏品牌。给用户明确的购买决策依据。",
                  "科普": "建立认知。讲清楚这是什么、为什么重要。45s内讲完。",
                  "热点资讯": "快速解读热点事件，给出数码博主的独特视角。"}.get(topic.get("type", ""), ""))

    return "\n".join(parts)


def _build_cover_direction(topic: dict) -> str:
    """Extract cover direction from topic title and unique presentation."""
    title = topic.get("title", "")
    up = topic.get("unique_presentation", "")
    direction = f"封面方向：{title[:40]}"
    if up:
        # Extract the most visual/dramatic element
        visual = re.sub(r'[，,。.；;]', ' ', up)[:50]
        direction += f" | 视觉重点：{visual}"
    return direction


def prepare_generate_args(topic: dict, persona: str = "折腾到吐") -> dict:
    """Convert a weekly topic dict into fully-contextualized args for Generator.generate().

    Now includes: structured brief_context, cover_direction, RAG-ready search query,
    auto-selected persona, and properly-derived product_name and key_points.
    """
    topic_type = topic.get("type", "干货")
    title = topic.get("title", "")
    category_cn = topic.get("category", "")
    config = TOPIC_TYPE_CONFIG.get(topic_type, {})

    category = CATEGORY_MAP.get(category_cn, "laptop")
    product = _extract_product_name(title, category_cn)
    duration = DURATION_MAP.get(topic_type, 0.6)
    script_format = config.get("format", "review")

    # Build key_points from structured fields, not from raw title
    kp_parts = [topic.get("user_need", ""), topic.get("unique_presentation", "")]
    key_points = " | ".join(p for p in kp_parts if p) or title

    # Full editorial context
    brief_context = _build_brief_context(topic)
    cover_direction = _build_cover_direction(topic)

    # RAG search query for retrieving relevant past scripts
    rag_query = f"{category_cn} {topic.get('unique_presentation', title)[:60]}"

    return {
        "product": product,
        "category": category,
        "key_points": key_points,
        "persona": persona,
        "duration": duration,
        "script_format": script_format,
        "price": topic.get("price", ""),
        "competitors": topic.get("competitors", ""),
        "topic_type": topic_type,
        "brief_context": brief_context,
        "cover_direction": cover_direction,
        "rag_query": rag_query,
    }


def batch_generate_scripts(topics_path: str = "", out_dir: str = "") -> dict:
    """Main entry: load topics → RAG retrieve → batch generate with full context.

    Returns a dict with paths and status for each generated script.
    """
    data = load_weekly_topics(topics_path)
    topics = data.get("topics", [])
    cover = data.get("cover", {})
    date_str = cover.get("date", datetime.now().strftime("%Y%m%d"))

    if not topics:
        raise ValueError("No topics found in weekly data.")

    project_root = Path(__file__).resolve().parent.parent.parent

    if not out_dir:
        out_dir = project_root / "output" / "reports" / "topic_reports" / f"{date_str}_scripts"
    else:
        out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    from rag_system.generation.generator import Generator
    from rag_system.generation.auditor import audit_script

    # Initialize RAG for context retrieval
    try:
        from rag_system.embedding.embedder import Embedder
        from rag_system.storage.vector_store import VectorStore
        from rag_system.retrieval.retriever import Retriever
        embedder = Embedder()
        store = VectorStore()
        retriever = Retriever(embedder, store)
        rag_available = True
        print("RAG 检索就绪")
    except Exception as e:
        retriever = None
        rag_available = False
        print(f"RAG 不可用（跳过检索）: {e}")

    gen = Generator()
    results = []

    for i, topic in enumerate(topics, 1):
        args = prepare_generate_args(topic, persona="折腾到吐")
        print(f"\n[{i}/{len(topics)}] [{args['topic_type']}] {args['product']}")
        print(f"  品类: {args['category']} | 人设: {args['persona']} | 时长: {args['duration']}min")

        # RAG retrieval
        retrieved_chunks = []
        if rag_available and retriever:
            try:
                retrieved_chunks = retriever.retrieve(
                    args["rag_query"], top_k=8, category=args["category"]
                )
                print(f"  RAG: {len(retrieved_chunks)} 个相关历史脚本")
            except Exception as e:
                print(f"  RAG 检索失败: {e}")

        try:
            script = gen.generate(
                product_name=args["product"],
                category=args["category"],
                key_points=args["key_points"],
                persona=args["persona"],
                price=args["price"],
                competitors=args["competitors"],
                duration_minutes=args["duration"],
                script_format=args["script_format"],
                retrieved_chunks=retrieved_chunks if retrieved_chunks else None,
                brief_context=args.get("brief_context", ""),
                cover_direction=args.get("cover_direction", ""),
            )

            audit = audit_script(
                text=script,
                key_points=args["key_points"],
                duration_minutes=args["duration"],
            )
            passed = "PASS" if audit.passed else f"FAIL ({sum(1 for c in audit.checks if not c.get('passed'))} issues)"

            from docx import Document
            doc = Document()
            doc.add_heading(topic.get("title", "Untitled"), level=1)
            doc.add_paragraph(f"类型: {args['topic_type']} | 品类: {args['category']} | 人设: {args['persona']}")
            doc.add_paragraph(script)
            doc.add_paragraph("─" * 40)
            doc.add_paragraph(audit.summarize())

            safe_title = re.sub(r'[\\/*?:"<>|]', "", topic.get("title", "untitled"))[:40]
            fname = f"{i}_{args['topic_type']}_{safe_title}.docx"
            fpath = out_dir / fname
            doc.save(str(fpath))

            print(f"  -> {fname} [{passed}] {len(script)} chars")
            results.append({
                "index": i, "title": topic.get("title"), "type": args["topic_type"],
                "persona": args["persona"], "path": str(fpath), "passed": audit.passed,
                "chars": len(script), "warnings": len(audit.warnings),
            })

        except Exception as e:
            print(f"  [ERROR] {e}")
            results.append({
                "index": i, "title": topic.get("title"), "type": args.get("topic_type", "?"),
                "path": "", "passed": False, "chars": 0, "error": str(e),
            })

    manifest_path = out_dir / "_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({"date": date_str, "results": results}, f, ensure_ascii=False, indent=2)

    print(f"\n批量生成完成: {out_dir}")
    passed_count = sum(1 for r in results if r.get("passed"))
    print(f"  {passed_count}/{len(results)} 通过审计 | manifest: {manifest_path}")

    return {"date": date_str, "results": results, "out_dir": str(out_dir)}
