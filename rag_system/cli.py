"""赛博瑞 RAG System CLI — data-driven content factory.

Commands:
  generate              Generate script from product brief (RAG-enhanced LLM)
  generate-storyboard   Finalized .docx script → storyboard .xlsx
  storyboard            Generate storyboard directly from product brief (RAG-enhanced)
  audit                 Audit script text or storyboard JSON for quality
  search                Semantic search the knowledge base
  stats                 Knowledge base statistics
  competitive search    Search Bilibili and run full competitive video analysis
  competitive report    Generate formatted .docx competitive analysis report
"""

import click


@click.group()
def cli():
    """赛博瑞 RAG System — 数据驱动内容工厂.

    AI-powered video script generation, storyboarding, and competitive
    analysis pipeline for Douyin (TikTok) tech review content.
    """
    from rag_system.utils import setup_logging
    setup_logging()


# ============================================================
# generate — Script from product brief
# ============================================================

@cli.command("generate")
@click.option("--product", "-p", required=True, help="产品名称，如：ROG龙鳞ACE MINI")
@click.option("--category", "-c", required=True,
              help="品类：keyboard / mouse / monitor / laptop / phone / gpu / headphone / desk_chair")
@click.option("--key-points", "-k", required=True, help="核心卖点，逗号分隔，如：轻量化54g, 8K回报率, 399元")
@click.option("--persona", default="折腾到吐", help="人设名称 (默认: 折腾到吐)")
@click.option("--price", default="", help="价格信息")
@click.option("--competitors", default="", help="竞品信息")
@click.option("--duration", "-d", default=2.0, type=float, help="目标时长，分钟 (默认: 2.0)")
@click.option("--format", "script_format", default="review",
              help="脚本格式：review / tierlist / comparison (默认: review)")
@click.option("--temperature", default=0.8, type=float, help="LLM 温度 (默认: 0.8)")
@click.option("--output", "-o", default=None, type=click.Path(dir_okay=False), help="输出文件路径 (.txt)")
def generate(product, category, key_points, persona, price, competitors,
             duration, script_format, temperature, output):
    """Generate video script from product brief using RAG-enhanced LLM.

    Retrieves relevant past scripts from the knowledge base as style
    reference, then calls DeepSeek API to produce a ~800-1200 character
    Douyin-style review script.

    Examples:

        python -m rag_system generate -p "ROG龙鳞ACE MINI" -c mouse \\
            -k "54g轻量化,8K回报率,399元" --format tierlist

        python -m rag_system generate -p "迈从K20" -c speaker \\
            -k "双声道,RGB灯效,99元" -d 1.5 -o output/scripts/maicong.txt
    """
    from rag_system.generation.generator import Generator
    from rag_system.retrieval.retriever import Retriever
    from rag_system.embedding.embedder import Embedder
    from rag_system.storage.vector_store import VectorStore

    click.echo(f"Generating script for: {product} [{category}]")

    # RAG retrieval for style context
    embedder = Embedder()
    store = VectorStore()
    retriever = Retriever(embedder, store)
    query = f"{product} {category} {key_points}"
    chunks = retriever.retrieve(query, top_k=8, category=category)

    if chunks:
        click.echo(f"Retrieved {len(chunks)} reference chunks from knowledge base")

    gen = Generator()
    script = gen.generate(
        product_name=product,
        category=category,
        key_points=key_points,
        persona=persona,
        price=price,
        competitors=competitors,
        duration_minutes=duration,
        script_format=script_format,
        retrieved_chunks=chunks,
        temperature=temperature,
    )

    if output:
        from pathlib import Path
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(script, encoding="utf-8")
        click.echo(f"Script saved to: {path}")
    else:
        click.echo("\n" + "=" * 60)
        click.echo(script)
        click.echo("=" * 60)

    click.echo(f"Done: {len(script)} characters")


# ============================================================
# generate-storyboard — Finalized script → storyboard xlsx
# ============================================================

@cli.command("generate-storyboard")
@click.argument("script", type=click.Path(exists=True))
@click.argument("product")
@click.argument("persona", default="折腾到吐")
def generate_storyboard(script: str, product: str, persona: str):
    """Convert finalized .docx script into a shot-by-shot storyboard .xlsx.

    Pipeline: parse .docx → LLM shot breakdown → audit → auto-fix → save.

    SCRIPT: Path to the finalized .docx script file.
    PRODUCT: Product name for the storyboard title.
    PERSONA: Persona name (default: 折腾到吐).

    Example:

        python -m rag_system generate-storyboard output/scripts/ROG.docx "ROG龙鳞ACE MINI"
    """
    from pathlib import Path
    from rag_system.generation.script_to_storyboard import storyboard_pipeline

    click.echo(f"Generating storyboard for: {product}")
    result = storyboard_pipeline(Path(script), product, persona)
    click.echo(f"Done: {result}")


# ============================================================
# storyboard — RAG storyboard from product brief (no script step)
# ============================================================

@cli.command("storyboard")
@click.option("--product", "-p", required=True, help="产品名称")
@click.option("--category", "-c", required=True,
              help="品类：keyboard / mouse / monitor / laptop / phone / gpu / headphone / desk_chair")
@click.option("--key-points", "-k", required=True, help="核心卖点，逗号分隔")
@click.option("--persona", default="折腾到吐", help="人设名称 (默认: 折腾到吐)")
@click.option("--price", default="", help="价格信息")
@click.option("--competitors", default="", help="竞品信息")
@click.option("--extra-notes", default="", help="额外备注（拍摄要求、风格偏好等）")
@click.option("--temperature", default=0.8, type=float, help="LLM 温度 (默认: 0.8)")
@click.option("--output", "-o", default=None, type=click.Path(file_okay=False),
              help="输出目录 (默认: output/storyboards)")
@click.option("--no-audit", is_flag=True, default=False, help="跳过自审步骤")
def storyboard(product, category, key_points, persona, price, competitors,
               extra_notes, temperature, output, no_audit):
    """Generate storyboard directly from product brief (RAG-enhanced).

    Skips the script step — goes straight from brief to camera-ready
    shot list. Retrieves past storyboards from the knowledge base as
    stylistic reference.

    Examples:

        python -m rag_system storyboard -p "ROG龙鳞" -c mouse \\
            -k "54g,PAW3950,399元"

        python -m rag_system storyboard -p "迈从K20" -c speaker \\
            -k "双声道,DSP芯片,99元" --no-audit
    """
    from collections import Counter
    from pathlib import Path

    from rag_system.generation.storyboard_generator import StoryboardGenerator, ProductBrief
    from rag_system.generation.xlsx_formatter import format_storyboard_to_xlsx
    from rag_system.retrieval.retriever import Retriever
    from rag_system.embedding.embedder import Embedder
    from rag_system.storage.vector_store import VectorStore
    from rag_system.utils import sanitize_filename

    click.echo(f"Generating storyboard from brief: {product} [{category}]")

    # RAG retrieval for style context
    embedder = Embedder()
    store = VectorStore()
    retriever = Retriever(embedder, store)
    query = f"{product} {category} {key_points}"
    chunks = retriever.retrieve(query, top_k=8, category=category)

    if chunks:
        click.echo(f"Retrieved {len(chunks)} reference chunks from knowledge base")

    brief = ProductBrief(
        product_name=product,
        category=category,
        persona=persona,
        key_points=key_points,
        price=price,
        competitors=competitors,
        extra_notes=extra_notes,
    )

    gen = StoryboardGenerator()
    result = gen.generate(brief, retrieved_chunks=chunks, temperature=temperature)
    shots = result.get("shots", [])

    # Optional audit
    if not no_audit and shots:
        from rag_system.generation.auditor import audit_storyboard, audit_shootability
        click.echo("Running self-audit...")
        audit_result = audit_storyboard(result, key_points=key_points)
        passed = sum(1 for c in audit_result.checks if c["passed"])
        total = len(audit_result.checks)
        click.echo(f"Content audit: {passed}/{total} checks passed")
        if audit_result.warnings:
            click.echo(f"Warnings: {len(audit_result.warnings)}")
        if audit_result.suggestions:
            click.echo(f"Suggestions: {len(audit_result.suggestions)}")

    # Save to xlsx
    output_dir = Path(output) if output else Path("output/storyboards")
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = sanitize_filename(product)
    import time as _time
    safe_path = output_dir / f"{safe_name}-{persona}-分镜表_{int(_time.time()) % 100000}.xlsx"
    format_storyboard_to_xlsx(
        storyboard=result,
        product_name=product,
        persona=persona,
        output_path=safe_path,
    )

    # Summary
    jingbies = Counter(s.get("jingbie", "") for s in shots)
    yunjings = Counter(s.get("yunjing", "") for s in shots)
    huazi_shots = sum(1 for s in shots if s.get("huazi", "").strip())
    trans_shots = sum(1 for s in shots if s.get("transition", "") not in ("硬切", "开场", ""))
    total_vo = sum(len(s.get("voiceover", "")) for s in shots)

    click.echo(f"\n{'='*50}")
    click.echo(f"  Storyboard: {product} — {persona}")
    click.echo(f"  Shots: {len(shots)} | VO: {total_vo} chars | Transitions: {trans_shots}")
    click.echo(f"  Huazi: {huazi_shots} shots | Jingbie: {dict(jingbies.most_common(4))}")
    click.echo(f"  File: {safe_path}")
    click.echo(f"{'='*50}")


# ============================================================
# audit — Audit script text or storyboard JSON
# ============================================================

@cli.command("audit")
@click.argument("input_file", type=click.Path(exists=True))
@click.option("--key-points", "-k", default="", help="核心卖点(逗号分隔)，用于检查卖点覆盖")
@click.option("--duration", "-d", default=2.0, type=float, help="目标时长，分钟 (默认: 2.0)")
def audit(input_file, key_points, duration):
    """Audit script or storyboard for quality issues.

    Auto-detects format:
      .json  → audits as storyboard (shot count, transitions, etc.)
      .docx  → parses body text and audits as script
      .txt   → audits as plain-text script

    Checks include: forbidden words, e-commerce smell, spoken language
    density, attitude density, sentence rhythm, selling-point coverage,
    and (for storyboards) shot variety, transitions, and shootability.

    Examples:

        python -m rag_system audit output/scripts/ROG.txt -k "54g,8K,399元"

        python -m rag_system audit output/storyboards/ROG-分镜表.json
    """
    import json
    from pathlib import Path

    input_path = Path(input_file)

    if input_path.suffix == ".json":
        # Audit as storyboard
        from rag_system.generation.auditor import audit_storyboard
        try:
            storyboard_data = json.loads(input_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            click.echo(f"Error: Invalid JSON in {input_file}", err=True)
            raise SystemExit(1)
        result = audit_storyboard(storyboard_data, key_points=key_points, duration_minutes=duration)
        click.echo(f"\nAuditing storyboard: {input_path.name}")
    elif input_path.suffix == ".docx":
        # Parse docx body and audit as script
        from rag_system.generation.script_to_storyboard import parse_docx_script
        from rag_system.generation.auditor import audit_script
        script_data = parse_docx_script(input_path)
        result = audit_script(script_data["full_script"], key_points=key_points, duration_minutes=duration)
        click.echo(f"\nAuditing script (docx): {input_path.name}")
    else:
        # Audit as plain text script
        from rag_system.generation.auditor import audit_script
        text = input_path.read_text(encoding="utf-8")
        result = audit_script(text, key_points=key_points, duration_minutes=duration)
        click.echo(f"\nAuditing script: {input_path.name}")

    click.echo(result.summarize())

    if result.passed:
        click.echo("\n✓ Audit passed")
    else:
        click.echo("\n✗ Audit found issues — review warnings and suggestions above")


# ============================================================
# search — Semantic search the knowledge base
# ============================================================

@cli.command("search")
@click.argument("query")
@click.option("--top-k", "-n", default=8, type=int, help="返回结果数量 (默认: 8)")
@click.option("--persona", default=None, help="按人设过滤：折腾到吐 / 等等")
@click.option("--category", "-c", default=None,
              help="按品类过滤：keyboard / mouse / monitor / laptop / phone / gpu / headphone / desk_chair")
@click.option("--final-only/--no-final-only", default=False, help="只返回定稿版本")
@click.option("--exclude-revisions/--no-exclude-revisions", default=False, help="排除修订版本")
def search(query, top_k, persona, category, final_only, exclude_revisions):
    """Semantic search the knowledge base for relevant script chunks.

    Searches across all ingested scripts and competitive analyses.
    Returns chunks ranked by cosine similarity, with metadata about
    source file, persona, category, and product.

    Examples:

        python -m rag_system search "磁轴键盘 手感" -c keyboard -n 5

        python -m rag_system search "ROG 轻量化 鼠标" --persona "折腾到吐" --final-only
    """
    from rag_system.retrieval.retriever import Retriever
    from rag_system.embedding.embedder import Embedder
    from rag_system.storage.vector_store import VectorStore

    embedder = Embedder()
    store = VectorStore()
    retriever = Retriever(embedder, store)

    click.echo(f'Searching: "{query}"')
    results = retriever.retrieve(
        query=query,
        top_k=top_k,
        persona=persona,
        category=category,
        is_final_only=final_only,
        exclude_revisions=exclude_revisions,
    )

    if not results:
        click.echo("No results found.")
        return

    click.echo(f"\nFound {len(results)} results:\n")
    for i, r in enumerate(results, 1):
        click.echo(f"--- Result {i} (score: {r.score:.4f}) ---")
        click.echo(f"  Source:   {r.source_file}")
        click.echo(f"  Persona:  {r.persona}  |  Category: {r.category}  |  Product: {r.product_name}")
        preview = r.document[:200].replace("\n", " ")
        click.echo(f"  Preview:  {preview}...")
        click.echo()


# ============================================================
# stats — Knowledge base statistics
# ============================================================

@cli.command("stats")
def stats():
    """Display knowledge base statistics.

    Shows total chunks, unique sources, distribution by persona
    and category, final version count, and competitive entries.

    Example:

        python -m rag_system stats
    """
    from collections import Counter
    from rag_system.storage.vector_store import VectorStore

    store = VectorStore()
    total = store.count()

    click.echo(f"\n{'='*50}")
    click.echo(f"  Knowledge Base Statistics")
    click.echo(f"{'='*50}")
    click.echo(f"  Total chunks: {total}")

    if total == 0:
        click.echo("  (Empty — ingest scripts first, then try again)")
        click.echo(f"{'='*50}\n")
        return

    metadatas = store.get_all_metadata()
    if not metadatas:
        click.echo("  No metadata available")
        click.echo(f"{'='*50}\n")
        return

    personas = Counter(m.get("persona", "unknown") for m in metadatas)
    categories = Counter(m.get("category", "unknown") for m in metadatas)
    source_files = set(m.get("source_file", "") for m in metadatas)
    finals = sum(1 for m in metadatas if m.get("is_final") == "true")
    competitive = sum(1 for m in metadatas if m.get("is_competitive") == "true")

    click.echo(f"  Unique source files: {len(source_files)}")
    click.echo(f"  Final versions:      {finals}")
    click.echo(f"  Competitive entries: {competitive}")
    click.echo(f"\n  By Persona:")
    for persona_name, count in personas.most_common(10):
        bar = "█" * min(count, 40)
        click.echo(f"    {persona_name:<20} {count:>5}  {bar}")
    click.echo(f"\n  By Category:")
    for cat, count in categories.most_common(12):
        bar = "█" * min(count, 40)
        click.echo(f"    {cat:<20} {count:>5}  {bar}")
    click.echo(f"{'='*50}\n")


# ============================================================
# competitive — Competitive analysis commands
# ============================================================

@cli.group("competitive")
def competitive():
    """Competitive video analysis — learn from top creators.

    Search Bilibili for top-performing videos by category, download,
    transcribe, and analyze their script structure, hooks, and visual
    patterns. Results are stored for use in script generation and
    compiled into professional reports.
    """
    pass


@competitive.command("search")
@click.option("--category", "-c", required=True,
              help="品类：keyboard / mouse / monitor / laptop / phone / gpu / headphone / desk_chair")
@click.option("--top-n", "-n", default=3, type=int, help="分析的视频数量 (默认: 3)")
@click.option("--skip-download/--no-skip-download", default=False, help="跳过视频下载，使用缓存的音频/转录")
def competitive_search(category, top_n, skip_download):
    """Search Bilibili and run full competitive analysis pipeline.

    Downloads top videos by category, transcribes audio (Whisper),
    analyzes script hooks, spoken density, attitude patterns, and
    visual rhythm. Results are indexed into the knowledge base for
    RAG retrieval during script generation.

    Examples:

        python -m rag_system competitive search -c keyboard -n 5

        python -m rag_system competitive search -c mouse --skip-download
    """
    from rag_system.competitive.pipeline import run_pipeline

    click.echo(f"Starting competitive analysis: {category} (top {top_n})")
    if skip_download:
        click.echo("Download skipped — using cached data if available")

    results = run_pipeline(category=category, top_n=top_n, skip_download=skip_download)

    if not results:
        click.echo("No results. Check network connectivity or try a different category.")
        return

    click.echo(f"\nAnalysis complete: {len(results)} videos analyzed\n")
    for r in results:
        click.echo(f"  [{r.get('hook_type', 'N/A')}] {r['title'][:60]}")
        click.echo(f"       {r['creator']}  |  {r['views']:,} views")


@competitive.command("report")
@click.option("--period", default="weekly",
              help="报告周期：weekly / monthly (默认: weekly)")
@click.option("--category", "-c", default=None,
              help="只报告指定品类（默认：全部）")
@click.option("--output", "-o", default=None, type=click.Path(dir_okay=False),
              help="输出路径 (.docx)")
def competitive_report(period, category, output):
    """Generate a professionally formatted .docx competitive analysis report.

    Compiles all analyzed videos into a Swiss-design report with:
    creator rankings, hook-type trends, category insights, deep
    analysis callouts, and actionable recommendations.

    Examples:

        python -m rag_system competitive report

        python -m rag_system competitive report --period monthly -c keyboard
    """
    from rag_system.competitive.reporter import generate_docx_report
    from rag_system.competitive.store import get_analyzed_videos

    videos = get_analyzed_videos(category=category or "")

    if not videos:
        click.echo("No analyzed videos found. Run 'competitive search' first.")
        return

    click.echo(f"Generating {period} competitive report from {len(videos)} videos...")
    if category:
        click.echo(f"Filtered to category: {category}")

    path = generate_docx_report(videos=videos, period=period)
    click.echo(f"Report saved: {path}")


if __name__ == "__main__":
    cli()
