"""Sequential scheduler for multi-category competitive analysis.

Runs 8 categories one-by-one with progress tracking and resume support.
Generates a weekly competitive report (.docx) when all categories complete.

Usage:
    python -m rag_system.competitive.scheduler          # run all categories
    python -m rag_system.competitive.scheduler --report  # just generate report
"""

import sys
import time
from datetime import datetime
from pathlib import Path

from rag_system.competitive.pipeline import (
    run_pipeline, _load_progress, _save_progress, SESSIONS_DIR,
)
from rag_system.utils import logger

ALL_CATEGORIES = [
    "keyboard", "mouse", "monitor", "laptop",
    "phone", "gpu", "headphone", "desk_chair",
]

TOP_N = 3  # videos per category


def run_all_categories(resume: bool = True, generate_report: bool = True) -> dict:
    """Run competitive analysis for all 8 product categories sequentially.

    Returns summary dict with per-category results and total stats.
    """
    start_time = time.time()
    progress = _load_progress() if resume else {"completed_videos": [], "completed_categories": []}

    logger.info("=" * 60)
    logger.info("  竞品学习管线 — 全品类顺序调度")
    logger.info(f"  品类: {len(ALL_CATEGORIES)} | 每品类: {TOP_N}视频 | 总计: {len(ALL_CATEGORIES) * TOP_N}视频")
    if resume and progress["completed_videos"]:
        logger.info(f"  续传模式: 已完成 {len(progress['completed_videos'])} 个视频, "
                     f"{len(progress['completed_categories'])} 个品类")
    logger.info("=" * 60)

    all_results = {}
    total_success = 0
    total_attempted = 0
    failed_categories = []

    for ci, category in enumerate(ALL_CATEGORIES):
        # Skip completed categories
        if category in progress.get("completed_categories", []):
            logger.info(f"\n[{ci+1}/{len(ALL_CATEGORIES)}] {category} — 已完成，跳过")
            continue

        logger.info(f"\n{'─' * 50}")
        logger.info(f"[{ci+1}/{len(ALL_CATEGORIES)}] 品类: {category}")
        logger.info(f"{'─' * 50}")

        try:
            results = run_pipeline(category=category, top_n=TOP_N, resume=resume)
            all_results[category] = results
            total_success += len(results)
            total_attempted += TOP_N

            elapsed = time.time() - start_time
            remaining_cats = len(ALL_CATEGORIES) - (ci + 1)
            est_remaining = (elapsed / (ci + 1)) * remaining_cats if ci > 0 else 0

            logger.info(f"  {category}: {len(results)}/{TOP_N} 成功 | "
                         f"耗时: {elapsed/60:.0f}min | "
                         f"预计剩余: {est_remaining/60:.0f}min")

        except Exception as e:
            logger.error(f"  {category} 品类失败: {e}")
            failed_categories.append(category)
            all_results[category] = []

        # Brief pause between categories
        if ci < len(ALL_CATEGORIES) - 1:
            time.sleep(3)

    total_time = time.time() - start_time

    # ── Summary ──
    logger.info("\n" + "=" * 60)
    logger.info(f"  全品类竞品分析完成")
    logger.info(f"  成功: {total_success}/{len(ALL_CATEGORIES) * TOP_N} 视频")
    logger.info(f"  耗时: {total_time/60:.1f} 分钟")
    if failed_categories:
        logger.info(f"  失败品类: {', '.join(failed_categories)}")
    logger.info("=" * 60)

    # Per-category summary
    for cat, results in all_results.items():
        if results:
            hooks = [r.get("hook_type", "?") for r in results]
            creators = [r.get("creator", "?") for r in results]
            logger.info(f"  {cat}: {len(results)}视频 | 创作者: {', '.join(creators[:3])} | 钩子: {', '.join(hooks)}")

    # ── Generate weekly report ──
    report_path = None
    if generate_report and total_success > 0:
        try:
            report_path = _generate_report()
        except Exception as e:
            logger.error(f"Report generation failed: {e}")

    return {
        "categories": ALL_CATEGORIES,
        "total_videos_attempted": len(ALL_CATEGORIES) * TOP_N,
        "total_videos_success": total_success,
        "failed_categories": failed_categories,
        "duration_minutes": round(total_time / 60, 1),
        "report_path": str(report_path) if report_path else None,
        "per_category": {cat: len(results) for cat, results in all_results.items()},
    }


def _generate_report() -> Path | None:
    """Generate a weekly competitive learning report in .docx format."""
    from rag_system.competitive.reporter import generate_docx_report

    logger.info("生成竞品学习周报...")
    path = generate_docx_report(period="weekly")
    logger.info(f"周报已保存: {path}")
    return path


# ── CLI entry ──

if __name__ == "__main__":
    resume = "--no-resume" not in sys.argv
    report_only = "--report" in sys.argv

    if report_only:
        path = _generate_report()
        if path:
            print(f"Report: {path}")
    else:
        summary = run_all_categories(resume=resume, generate_report=True)

        print("\n" + "=" * 60)
        print("  管线完成")
        print(f"  成功: {summary['total_videos_success']}/{summary['total_videos_attempted']}")
        print(f"  耗时: {summary['duration_minutes']} 分钟")
        if summary["report_path"]:
            print(f"  周报: {summary['report_path']}")
        if summary["failed_categories"]:
            print(f"  失败品类: {', '.join(summary['failed_categories'])}")
        print("=" * 60)
