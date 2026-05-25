"""CLI entry point for the RAG system.

Commands:
  ingest   Parse and index all documents
  upload   Add a new document to the knowledge base
  search   Semantic search against the knowledge base
  generate    Full RAG pipeline: retrieve + generate short script (.docx)
  storyboard  Full RAG pipeline: retrieve + generate table storyboard (.xlsx)
  stats       Show index statistics
  reset       Wipe and rebuild the index
"""

import shutil
import subprocess
from collections import Counter
from datetime import datetime
from pathlib import Path

import click

from rag_system.config import (
    CACHE_DIR,
    DATA_DIR,
    DEFAULT_TOP_K,
    DOCS_DIR,
    SUPPORTED_EXTENSIONS,
)
from rag_system.embedding.embedder import Embedder
from rag_system.storage.vector_store import VectorStore, make_chunk_id
from rag_system.utils import logger, setup_logging, sanitize_filename


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def cli(verbose: bool = False):
    """Personal RAG Knowledge Retrieval System."""
    setup_logging(verbose)


def _ingest_single_file(filepath: Path, embedder: Embedder, store: VectorStore) -> int:
    """Ingest a single file into the vector store. Returns number of chunks added."""
    from rag_system.chunking.splitter import split_text
    from rag_system.ingest.metadata import extract_metadata
    from rag_system.ingest.parser import parse_file

    text = parse_file(filepath)
    if not text:
        return 0

    meta = extract_metadata(filepath, text)
    chunks = split_text(text)
    if not chunks:
        return 0

    chunk_dicts = []
    for ci, chunk_text in enumerate(chunks):
        chunk_dicts.append({
            "id": make_chunk_id(meta["source_file"], ci),
            "document": chunk_text,
            "metadata": {**meta, "chunk_index": str(ci), "chunk_count": str(len(chunks))},
        })

    embeddings = embedder.embed_documents([c["document"] for c in chunk_dicts])
    for j, emb in enumerate(embeddings):
        chunk_dicts[j]["embedding"] = emb

    store.upsert_chunks(chunk_dicts)
    return len(chunks)


@cli.command()
@click.option("--force", is_flag=True, help="Re-parse all files, ignoring cache")
@click.option("--docs-dir", default=None, help="Custom source documents directory")
def ingest(force: bool = False, docs_dir: str | None = None):
    """Parse and index all documents from the source directory."""
    src_dir = Path(docs_dir) if docs_dir else DOCS_DIR
    if not src_dir.exists():
        click.echo(f"ERROR: Source directory not found: {src_dir}")
        raise SystemExit(1)

    if force and CACHE_DIR.exists():
        shutil.rmtree(CACHE_DIR)
        click.echo("Cache cleared.")

    files = []
    for ext in SUPPORTED_EXTENSIONS:
        files.extend(src_dir.glob(f"*{ext}"))
    files = sorted(files, key=lambda f: f.name)

    click.echo(f"Found {len(files)} files to process.\n")

    embedder = Embedder()
    store = VectorStore()
    total_chunks = 0
    new_count = 0
    cached_count = 0
    failed_count = 0

    from rag_system.utils import is_cached as _is_cached

    for i, filepath in enumerate(files, 1):
        click.echo(f"[{i}/{len(files)}] {filepath.name} ... ", nl=False)

        was_cached = _is_cached(filepath, CACHE_DIR) and not force
        n = _ingest_single_file(filepath, embedder, store)

        if n == 0:
            click.echo("FAILED")
            failed_count += 1
        elif was_cached:
            click.echo("cached")
            cached_count += 1
        else:
            click.echo(f"{n} chunks")
            new_count += 1
        total_chunks += n

    click.echo(f"\nDone. {total_chunks} chunks indexed. "
               f"({new_count} new, {cached_count} cached, {failed_count} failed)")


@cli.command()
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True))
@click.option("--category", "-c", default=None, help="Product category (auto-detected if omitted)")
@click.option("--persona", "-p", default=None, help="Creator persona (auto-detected if omitted)")
def upload(files: tuple[str, ...], category: str | None = None, persona: str | None = None):
    """Upload one or more documents to the knowledge base.

    Supports .docx, .doc, .pdf, .xlsx, .xls files.
    Files are copied to the docs directory and immediately indexed.
    """
    from rag_system.ingest.metadata import extract_metadata
    from rag_system.ingest.parser import parse_file

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    embedder = Embedder()
    store = VectorStore()
    added = 0

    for filepath_str in files:
        src = Path(filepath_str).resolve()
        if src.suffix.lower() not in SUPPORTED_EXTENSIONS:
            click.echo(f"SKIP: unsupported format: {src.name}")
            continue

        # Copy to docs directory
        dest = DOCS_DIR / src.name
        if dest.exists():
            # Add timestamp to avoid overwriting
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest = DOCS_DIR / f"{src.stem}_{ts}{src.suffix}"
        shutil.copy2(src, dest)

        # Immediately index
        click.echo(f"Indexing: {dest.name} ... ", nl=False)
        n = _ingest_single_file(dest, embedder, store)
        if n > 0:
            click.echo(f"{n} chunks")
            added += 1
        else:
            click.echo("FAILED")

    click.echo(f"\nUploaded and indexed {added} file(s).")
    click.echo(f"Total chunks in store: {store.count()}")


@cli.command()
@click.argument("query")
@click.option("--persona", "-p", default=None, help="Filter by creator persona")
@click.option("--category", "-c", default=None, help="Filter by product category")
@click.option("--top-k", "-k", default=DEFAULT_TOP_K, help="Number of results")
@click.option("--final-only", is_flag=True, help="Only show final versions (定稿)")
@click.option("--exclude-revisions", is_flag=True, help="Exclude revision versions")
def search(
    query: str,
    persona: str | None = None,
    category: str | None = None,
    top_k: int = DEFAULT_TOP_K,
    final_only: bool = False,
    exclude_revisions: bool = False,
):
    """Semantic search against the knowledge base."""
    from rag_system.retrieval.retriever import Retriever

    embedder = Embedder()
    store = VectorStore()

    if store.count() == 0:
        click.echo("Index is empty. Run 'python -m rag_system ingest' first.")
        return

    retriever = Retriever(embedder, store)
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

    click.echo(f"\nTop {len(results)} results for: {query}\n")
    for i, r in enumerate(results, 1):
        flags = []
        if r.is_final:
            flags.append("定稿")
        if r.is_revision():
            flags.append("修改版")
        flag_str = f" [{'|'.join(flags)}]" if flags else ""

        click.echo(f"[{i}] score={r.score:.3f} | {r.source_file}{flag_str}")
        click.echo(f"    category={r.category} | persona={r.persona} | chunk={r.chunk_index}")
        preview = r.document[:200].replace("\n", " ")
        click.echo(f"    {preview}...")
        click.echo()


@cli.command()
@click.option("--product", "-n", required=True, help="New product name")
@click.option("--category", "-c", required=True, help="Product category")
@click.option("--persona", "-p", required=True, help="Writing persona to emulate")
@click.option("--key-points", "-k", required=True, help="Key selling points (comma-separated)")
@click.option("--price", default="", help="Product price (e.g., '299元起')")
@click.option("--competitors", default="", help="Competitor products for comparison")
@click.option("--duration", "-d", default=2.0, help="Target video duration in minutes (e.g., 1.5 for 90s)")
@click.option("--format", "-f", default="review", help="Script format: review(评测) / tierlist(榜单) / comparison(对比)")
@click.option("--top-k", default=DEFAULT_TOP_K, help="Number of reference chunks to retrieve")
@click.option("--output", "-o", default=None, help="Output file path (optional, auto-generated if omitted)")
@click.option("--temperature", default=0.8, help="Generation temperature")
@click.option("--no-filter", is_flag=True, help="Skip Douyin prohibited words filtering")
@click.option("--no-index", is_flag=True, help="Skip auto-adding to knowledge base")
def generate(
    product: str,
    category: str,
    persona: str,
    key_points: str,
    price: str = "",
    competitors: str = "",
    duration: float = 2.0,
    format: str = "review",
    top_k: int = DEFAULT_TOP_K,
    output: str | None = None,
    temperature: float = 0.8,
    no_filter: bool = False,
    no_index: bool = False,
):
    """Full RAG pipeline: retrieve relevant past scripts, then generate new copy (800-1200 chars).

    Outputs a formatted .docx file in output/scripts/.
    Generated content is filtered for Douyin prohibited words and
    automatically added back to the knowledge base for future retrieval.
    """
    from rag_system.generation.generator import Generator
    from rag_system.generation.docx_formatter import format_script_to_docx
    from rag_system.generation.douyin_filter import filter_prohibited, validate_no_prohibited
    from rag_system.retrieval.retriever import Retriever

    embedder = Embedder()
    store = VectorStore()

    if store.count() == 0:
        click.echo("Index is empty. Run 'python -m rag_system ingest' first.")
        return

    # Step 1: Retrieve
    click.echo(f"Retrieving references for: {product}")
    retriever = Retriever(embedder, store)
    results = retriever.retrieve(
        query=f"{product} {key_points}",
        top_k=top_k,
        persona=persona,
        category=category,
        exclude_revisions=True,
    )

    click.echo(f"Found {len(results)} reference chunks:\n")
    for i, r in enumerate(results, 1):
        click.echo(f"  [{i}] {r.source_file} (score={r.score:.3f})")

    # Step 2: Generate
    click.echo(f"\nGenerating with persona '{persona}'...")
    try:
        gen = Generator()
        raw_text = gen.generate(
            product_name=product,
            category=category,
            key_points=key_points,
            persona=persona,
            price=price,
            competitors=competitors,
            duration_minutes=duration,
            script_format=format,
            retrieved_chunks=results,
            temperature=temperature,
        )
    except Exception as e:
        click.echo(f"ERROR: Generation failed: {e}")
        return

    # Step 3: Douyin prohibited words filter
    if not no_filter:
        filtered_text, changes = filter_prohibited(raw_text)
        if changes:
            click.echo(f"\n违禁词已替换 ({len(changes)}处):")
            for c in changes:
                click.echo(f"  {c}")
        else:
            click.echo("\n违禁词检查通过，未发现需要替换的内容。")
    else:
        filtered_text = raw_text
        click.echo("\n(违禁词过滤已跳过)")

    # Step 4: Determine output path
    output_dir = Path("output/scripts")
    output_dir.mkdir(parents=True, exist_ok=True)
    if output:
        docx_path = Path(output).with_suffix(".docx")
    else:
        safe_name = sanitize_filename(product)
        docx_path = output_dir / f"{safe_name}-{persona}.docx"

    # Step 5: Format and save as .docx
    format_script_to_docx(
        text=filtered_text,
        product_name=product,
        persona=persona,
        key_points=key_points,
        output_path=docx_path,
    )
    click.echo(f"\nWord文档已保存: {docx_path}")

    # Step 6: Show generated text
    click.echo("\n" + "=" * 60)
    click.echo(filtered_text)
    click.echo("=" * 60)

    # Step 7: Auto-add to knowledge base
    if not no_index:
        click.echo(f"\n自动入库: {docx_path.name}")
        dest = DOCS_DIR / docx_path.name
        if dest.exists():
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest = DOCS_DIR / f"{docx_path.stem}_{ts}.docx"
        shutil.copy2(docx_path, dest)

        n = _ingest_single_file(dest, embedder, store)
        click.echo(f"已索引 {n} chunks，知识库已更新。(总计: {store.count()} chunks)")


@cli.command()
@click.option("--product", "-n", required=True, help="Product name (e.g., '狼蛛G7 Pro')")
@click.option("--category", "-c", required=True,
              type=click.Choice(["keyboard", "mouse", "monitor", "laptop", "phone",
                                 "gpu", "headphone", "desk_chair"]),
              help="Product category")
@click.option("--persona", "-p", required=True,
              type=click.Choice(["折腾到吐", "好设牛啊", "朋克", "超机懂"]),
              help="Writing persona / channel")
@click.option("--features", "-f", required=True, help="Key selling points (comma-separated)")
@click.option("--price", required=True, help="Product price (e.g., '299元起')")
@click.option("--competitors", default="", help="Competitor products for comparison")
@click.option("--extra-notes", default="", help="Additional notes or requirements")
@click.option("--top-k", "-k", default=DEFAULT_TOP_K, help="Number of reference chunks")
@click.option("--output", "-o", default=None, help="Output .xlsx path (auto-generated if omitted)")
@click.option("--temperature", default=0.8, help="Generation temperature")
@click.option("--no-index", is_flag=True, help="Skip indexing generated storyboard")
def storyboard(
    product: str,
    category: str,
    persona: str,
    features: str,
    price: str,
    competitors: str = "",
    extra_notes: str = "",
    top_k: int = DEFAULT_TOP_K,
    output: str | None = None,
    temperature: float = 0.8,
    no_index: bool = False,
):
    """Generate a complete 35-shot table storyboard (.xlsx) following D先生's style.

    Retrieves relevant past scripts via RAG, then generates a full storyboard
    with shot-by-shot breakdown including camera direction, voiceover text,
    on-screen graphics (花字), and production notes.
    """
    from rag_system.generation.storyboard_generator import ProductBrief, StoryboardGenerator
    from rag_system.generation.xlsx_formatter import format_storyboard_to_xlsx
    from rag_system.retrieval.retriever import Retriever

    embedder = Embedder()
    store = VectorStore()

    if store.count() == 0:
        click.echo("Index is empty. Run 'python -m rag_system ingest' first.")
        return

    # Step 1: Retrieve relevant past scripts
    click.echo(f"检索参考脚本: {product}")
    retriever = Retriever(embedder, store)
    results = retriever.retrieve(
        query=f"{product} {features}",
        top_k=top_k,
        persona=persona,
        category=category,
        exclude_revisions=True,
    )
    click.echo(f"找到 {len(results)} 个参考片段:\n")
    for i, r in enumerate(results, 1):
        click.echo(f"  [{i}] {r.source_file} (score={r.score:.3f})")

    # Step 2: Generate storyboard
    click.echo(f"\n生成 '{persona}' 频道的完整分镜表 (35镜)...")
    brief = ProductBrief(
        product_name=product,
        category=category,
        persona=persona,
        key_points=features,
        price=price,
        competitors=competitors,
        extra_notes=extra_notes,
    )

    try:
        gen = StoryboardGenerator()
        storyboard = gen.generate(
            brief=brief,
            retrieved_chunks=results,
            temperature=temperature,
        )
    except Exception as e:
        click.echo(f"ERROR: 生成失败: {e}")
        return

    shot_count = len(storyboard.get("shots", []))
    click.echo(f"生成完成: {shot_count} 镜")

    # Step 3: Determine output path
    output_dir = Path("output/storyboards")
    output_dir.mkdir(parents=True, exist_ok=True)
    if output:
        xlsx_path = Path(output).with_suffix(".xlsx")
    else:
        safe_name = sanitize_filename(product)
        xlsx_path = output_dir / f"{safe_name}-{persona}-分镜表.xlsx"

    # Step 4: Format and save as .xlsx
    format_storyboard_to_xlsx(
        storyboard=storyboard,
        product_name=product,
        persona=persona,
        output_path=xlsx_path,
    )
    click.echo(f"\n分镜表已保存: {xlsx_path}")

    # Step 5: Quick quality summary
    _print_storyboard_summary(storyboard)

    # Step 6: Auto-index
    if not no_index:
        click.echo(f"\n自动入库: {xlsx_path.name}")
        dest = DOCS_DIR / xlsx_path.name
        if dest.exists():
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest = DOCS_DIR / f"{xlsx_path.stem}_{ts}.xlsx"
        shutil.copy2(xlsx_path, dest)

        n = _ingest_single_file(dest, embedder, store)
        click.echo(f"已索引 {n} chunks，知识库已更新。(总计: {store.count()} chunks)")


def _print_storyboard_summary(storyboard: dict):
    """Print a quick quality summary of the generated storyboard."""
    shots = storyboard.get("shots", [])
    if not shots:
        return

    md = storyboard.get("metadata", {})
    click.echo(f"\n--- 分镜摘要 ---")
    click.echo(f"  标题: {md.get('title', 'N/A')}")
    click.echo(f"  话题: {md.get('hashtags', 'N/A')}")

    # Count shot types
    acts = Counter(s.get("act", "unknown") for s in shots)
    jingbies = Counter(s.get("jingbie", "") for s in shots)
    total_chars = sum(len(s.get("voiceover", "")) for s in shots)
    huazi_count = sum(1 for s in shots if s.get("huazi", "").strip())

    click.echo(f"  口播总字数: {total_chars}")
    click.echo(f"  花字镜数: {huazi_count}")
    click.echo(f"  幕分布: {dict(acts)}")
    click.echo(f"  景别分布: {dict(jingbies.most_common(5))}")


@cli.command()
@click.option("--file", "-f", required=True, type=click.Path(exists=True), help="Script .docx or storyboard .xlsx to audit")
@click.option("--key-points", "-k", default="", help="Client required selling points (comma-separated, for coverage check)")
@click.option("--output", "-o", default=None, help="Save audit report to file (optional)")
@click.option("--duration", "-d", default=2.0, help="Target video duration in minutes (default 2.0)")
def audit(file: str, key_points: str = "", output: str | None = None, duration: float = 2.0):
    """Audit a generated script or storyboard against D先生's quality standards.

    Checks: spoken language, forbidden words, attitude density,
    sentence rhythm, selling-point coverage, and duration.
    """
    from pathlib import Path

    filepath = Path(file)
    ext = filepath.suffix.lower()

    if ext == ".docx":
        from rag_system.ingest.parser import parse_file
        text = parse_file(filepath)
        from rag_system.generation.auditor import audit_script
        result = audit_script(text, key_points, duration_minutes=duration)
    elif ext in (".xlsx", ".xls"):
        from openpyxl import load_workbook
        wb = load_workbook(filepath, data_only=True)
        ws = wb.active
        sb = {"shots": []}
        for row in ws.iter_rows(min_row=10, values_only=True):
            if row[0] and str(row[0]).strip().isdigit():
                # 9-column layout: A镜号 B景别·运镜 C画面描述 D口播 E时长 F花字 G音效 H灯光/机位 I备注
                def _s(idx):
                    return str(row[idx]) if len(row) > idx and row[idx] else ""
                import re as _re
                # Parse B column: "[转场:xx] 特写 | 推" format
                framing = _s(1)
                transition = ""
                trans_match = _re.match(r'^\[转场:([^\]]+)\]\s*', framing)
                if trans_match:
                    transition = trans_match.group(1)
                    framing = framing[trans_match.end():].strip()
                jingbie = yunjing = ""
                if "|" in framing:
                    parts = framing.split("|")
                    jingbie = parts[0].strip() if len(parts) > 0 else ""
                    yunjing = parts[1].strip() if len(parts) > 1 else ""
                # Parse H column for lighting vs camera_setup
                light_cam = _s(7)
                lighting = light_cam
                camera_setup = ""
                if "\n" in light_cam:
                    lines = light_cam.split("\n")
                    lt_lines = []
                    cam_lines = []
                    for l in lines:
                        l = l.strip()
                        if "焦段" in l or "光圈" in l or "机位" in l:
                            cam_lines.append(l)
                        else:
                            lt_lines.append(l)
                    lighting = "\n".join(lt_lines) if lt_lines else ""
                    camera_setup = "\n".join(cam_lines) if cam_lines else ""
                sb["shots"].append({
                    "shot_number": int(row[0]),
                    "jingbie": jingbie,
                    "yunjing": yunjing,
                    "jiandu": "",
                    "visual": _s(2),
                    "voiceover": _s(3),
                    "duration": _s(4),
                    "huazi": _s(5),
                    "audio": _s(6),
                    "lighting": lighting,
                    "camera_setup": camera_setup,
                    "notes": _s(8),
                    "transition": transition,
                    "act": "",
                })
        from rag_system.generation.auditor import audit_storyboard
        result = audit_storyboard(sb, key_points, duration_minutes=duration)
    else:
        click.echo(f"Unsupported format: {ext} (use .docx or .xlsx)")
        return

    report = result.summarize()
    click.echo(report)

    if output:
        out_path = Path(output)
        out_path.write_text(report, encoding="utf-8")
        click.echo(f"\n审核报告已保存: {out_path}")
    else:
        audit_dir = Path("output/audits")
        audit_dir.mkdir(parents=True, exist_ok=True)
        audit_path = audit_dir / f"{filepath.stem}_审核.txt"
        audit_path.write_text(report, encoding="utf-8")
        click.echo(f"\n审核报告已保存: {audit_path}")


@cli.command()
def stats():
    """Show index statistics."""
    store = VectorStore()
    total = store.count()

    if total == 0:
        click.echo("Index is empty.")
        return

    metadatas = store.get_all_metadata()

    personas = Counter(m["persona"] for m in metadatas if m.get("persona"))
    categories = Counter(m["category"] for m in metadatas if m.get("category"))
    file_types = Counter(m["file_type"] for m in metadatas if m.get("file_type"))
    is_final_count = sum(1 for m in metadatas if m.get("is_final") == "true")
    with_revision = sum(1 for m in metadatas if m.get("revision"))
    source_files = len(set(m["source_file"] for m in metadatas if m.get("source_file")))

    click.echo(f"\nCollection: tech_reviews")
    click.echo(f"  Total chunks:      {total}")
    click.echo(f"  Unique documents:  {source_files}")
    click.echo(f"  Is final (定稿):    {is_final_count}")
    click.echo(f"  Has revision info: {with_revision}")

    click.echo(f"\n  By persona:")
    for name, count in personas.most_common():
        click.echo(f"    {name}: {count}")

    click.echo(f"\n  By category:")
    for name, count in categories.most_common():
        click.echo(f"    {name}: {count}")

    click.echo(f"\n  By file type:")
    for name, count in file_types.most_common():
        click.echo(f"    {name}: {count}")


@cli.command()
@click.option("--keep-cache", is_flag=True, help="Keep parsed text cache, only reset vector store")
def reset(keep_cache: bool = False):
    """Wipe the index (and optionally cache) to rebuild from scratch."""
    store = VectorStore()
    store.reset()
    click.echo("Vector store reset.")

    if not keep_cache and CACHE_DIR.exists():
        shutil.rmtree(CACHE_DIR)
        click.echo("Cache cleared.")

    click.echo("Ready for fresh ingest.")


# ═══════════════════════════════════════════
# COMPETITIVE ANALYSIS COMMANDS
# ═══════════════════════════════════════════

@cli.group()
def competitive():
    """Learn from top-performing competitor videos."""
    pass


@competitive.command("search")
@click.option("--category", "-c", required=True, help="Product category (keyboard/mouse/monitor/...)")
@click.option("--top", "-n", default=3, help="Number of top videos to analyze")
@click.option("--source", "-s", default="bilibili", help="Platform: bilibili")
@click.option("--skip-download", is_flag=True, help="Skip video download (use cached audio)")
def competitive_search(category: str, top: int = 3, source: str = "bilibili", skip_download: bool = False):
    """Search and analyze top videos for a product category."""
    from rag_system.competitive.pipeline import run_pipeline

    click.echo(f"Searching {source} for {category} (top {top})...")
    results = run_pipeline(category, top_n=top, skip_download=skip_download)

    if not results:
        click.echo("No results found or analysis failed.")
        return

    click.echo(f"\n{'='*60}")
    click.echo(f"竞品分析结果 — {category} (Top {len(results)})")
    click.echo(f"{'='*60}")
    for i, r in enumerate(results, 1):
        click.echo(f"\n[{i}] {r['title'][:60]}")
        click.echo(f"    创作者: {r['creator']}  |  播放: {r['views']:,}")
        click.echo(f"    钩子类型: {r['hook_type']}  |  口语密度: {r['spoken_density']:.1f}")
        if r['patterns']:
            click.echo(f"    亮点: {', '.join(r['patterns'][:3])}")


@competitive.command("analyze")
@click.option("--url", "-u", required=True, help="Bilibili video URL to analyze")
def competitive_analyze(url: str):
    """Analyze a single competitor video by URL."""
    from rag_system.competitive.downloader import download_video
    from rag_system.competitive.transcriber import transcribe
    from rag_system.competitive.script_analyzer import analyze_transcript
    from rag_system.competitive.store import save_analysis
    from rag_system.competitive.models import VideoProfile
    import re

    # Parse video ID from URL
    match = re.search(r'(?:bilibili\.com/video/|BV)([A-Za-z0-9]+)', url)
    if not match:
        click.echo(f"Invalid Bilibili URL: {url}")
        return
    video_id = f"BV{match.group(1)}" if not match.group(0).startswith("BV") else match.group(0)

    video = VideoProfile(
        video_id=video_id, title="", url=url,
        source="bilibili", creator_name="",
    )

    click.echo(f"Downloading {url}...")
    audio = download_video(video)
    if not audio:
        click.echo("Download failed.")
        return

    click.echo("Transcribing...")
    text = transcribe(audio)
    if not text:
        click.echo("Transcription failed.")
        return

    click.echo(f"Transcribed: {len(text)} chars. Analyzing...")
    result = analyze_transcript(video, text)
    save_analysis(result)

    click.echo(f"\n钩子: {result.hook_type}")
    click.echo(f"口语密度: {result.spoken_density:.1f}/百字")
    click.echo(f"态度密度: {result.attitude_density:.1f}/200字")
    click.echo(f"短句: {result.short_sentence_pct:.0f}%  长句: {result.long_sentence_pct:.0f}%")
    if result.standout_patterns:
        click.echo(f"亮点: {', '.join(result.standout_patterns)}")


@competitive.command("report")
@click.option("--period", "-p", default="weekly", help="Report period: weekly, monthly")
def competitive_report(period: str = "weekly"):
    """Generate a competitive analysis report."""
    from rag_system.competitive.reporter import generate_weekly_report

    click.echo(f"Generating {period} report...")
    report = generate_weekly_report()

    click.echo(f"\n{'='*60}")
    click.echo(f"竞品分析报告 — {report.period_start} ~ {report.period_end}")
    click.echo(f"{'='*60}")
    click.echo(f"分析视频数: {report.videos_analyzed}")
    if report.top_creators:
        click.echo(f"热门创作者: {', '.join(report.top_creators)}")
    if report.trending_hook_types:
        click.echo(f"热门钩子: {report.trending_hook_types}")
    if report.new_patterns_discovered:
        click.echo(f"新发现模式: {', '.join(report.new_patterns_discovered)}")
    click.echo(f"\n建议:")
    for r in report.recommendations:
        click.echo(f"  • {r}")


@competitive.command("stats")
def competitive_stats():
    """Show competitive analysis statistics."""
    from rag_system.competitive.store import get_analyzed_videos
    from collections import Counter

    videos = get_analyzed_videos()
    if not videos:
        click.echo("No analyzed videos yet. Run 'competitive search' first.")
        return

    cats = Counter(v.get("category", "other") for v in videos)
    hooks = Counter(v.get("hook_type", "unknown") for v in videos)
    creators = Counter(v.get("creator", "unknown") for v in videos)

    click.echo(f"\n竞品知识库: {len(videos)} 个视频")
    click.echo(f"\n品类分布: {dict(cats)}")
    click.echo(f"\n钩子分布: {dict(hooks)}")
    click.echo(f"\nTop创作者: {dict(creators.most_common(5))}")
