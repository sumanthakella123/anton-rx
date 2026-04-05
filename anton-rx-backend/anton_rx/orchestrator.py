"""Orchestrator — runs all pipeline stages and writes results to SQLite."""

from __future__ import annotations

import asyncio
import logging
import time
import traceback
from pathlib import Path
from typing import Any, Optional

from rich.console import Console
from rich.table import Table

from . import database as db
from .config import timer
from .pdf_parser import parse_pdf
from .stage_changelog import extract_changelog
from .stage_discovery import run_discovery
from .stage_extraction import run_extraction
from .stage_pagemap import group_drugs_by_pages, map_drugs_to_pages
from .stage_validation import retry_flagged, validate_rows

log = logging.getLogger("anton_rx.orchestrator")
console = Console()


def _print_summary_table(rows: list[dict[str, Any]]) -> None:
    """Print a Rich table summarising extracted drugs."""
    table = Table(
        title="Extraction Summary",
        show_lines=True,
        header_style="bold magenta",
    )
    table.add_column("Brand Name", style="cyan", min_width=20)
    table.add_column("Generic Name", min_width=20)
    table.add_column("Coverage Status", min_width=14)
    table.add_column("PA Required", justify="center", min_width=10)
    table.add_column("Confidence", justify="center", min_width=10)

    for r in rows:
        conf = r.get("_confidence", "N/A")
        conf_style = "bold green" if conf == "HIGH" else "bold red"
        table.add_row(
            r.get("brand_name", "N/A"),
            r.get("generic_name", "N/A"),
            r.get("coverage_status", "N/A"),
            r.get("prior_auth_required", "N/A"),
            f"[{conf_style}]{conf}[/{conf_style}]",
        )

    console.print(table)


# ---------------------------------------------------------------------------
# Stage 5 — DB Write
# ---------------------------------------------------------------------------

def _write_to_db(
    conn,
    discovery_data: dict[str, Any],
    rows: list[dict[str, Any]],
    file_hash: str,
    full_text: str,
    changelog: str,
    source_file: str,
) -> int:
    """Insert document + drug_policies rows. Returns doc_id."""
    doc_data = {
        "payer": discovery_data.get("payer", ""),
        "policy_title": discovery_data.get("policy_title", ""),
        "policy_number": discovery_data.get("policy_number", ""),
        "effective_date": discovery_data.get("effective_date", ""),
        "doc_type": discovery_data.get("doc_type", "Medical Benefit Drug Policy"),
        "file_hash": file_hash,
        "raw_text": full_text,
        "policy_change_log": changelog,
        "policy_review_cycle": discovery_data.get("policy_review_cycle", "N/A"),
        "source_file": source_file,
    }
    doc_id = db.insert_document(conn, doc_data)
    log.info(f"Inserted document row: doc_id={doc_id}")

    inserted = 0
    for row in rows:
        try:
            db.insert_drug_policy(conn, doc_id, row)
            inserted += 1
        except Exception as exc:
            log.error(
                f"Failed to insert drug row '{row.get('brand_name')}': {exc}"
            )

    conn.commit()
    log.info(f"Stage 5 — DB Write: doc_id={doc_id}, {inserted}/{len(rows)} rows inserted")
    return doc_id


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

async def ingest_document(
    pdf_path: str | Path,
    conn,
    client,
    auto_retry: bool = True,
    max_concurrent: int = 5,
) -> Optional[int]:
    """
    Run the full ingestion pipeline on a single PDF.

    Returns the document id on success, or None on failure.
    """
    pdf_path = Path(pdf_path)
    pipeline_start = time.perf_counter()

    try:
        log.info(f"{'='*60}")
        log.info(f"Ingesting: {pdf_path.name}")
        log.info(f"{'='*60}")

        # ── PDF parse ──────────────────────────────────────────────
        async with timer("PDF Parsing"):
            pages, full_text, file_hash = parse_pdf(pdf_path)

        # ── Dedup check ────────────────────────────────────────────
        existing = db.check_file_hash(conn, file_hash)
        if existing is not None:
            log.warning(
                f"File already ingested (doc_id={existing}). Skipping."
            )
            return existing

        # ── Stage 1: Discovery ─────────────────────────────────────
        async with timer("Stage 1 — Discovery"):
            discovery = await run_discovery(client, full_text)
            t0 = time.perf_counter()

        drugs_list = discovery.get("drugs", [])
        if not drugs_list:
            log.warning("No drugs discovered — aborting pipeline.")
            return None

        db.log_ingestion(conn, None, "discovery", "ok",
                         f"{len(drugs_list)} drugs", 0)

        # ── Stage 2: Page Mapper ───────────────────────────────────
        async with timer("Stage 2 — Page Mapper"):
            drug_page_map = map_drugs_to_pages(drugs_list, pages)
            groups = group_drugs_by_pages(drug_page_map)

        # Build lookup: brand_name → drug dict
        drugs_lookup: dict[str, dict] = {}
        for d in drugs_list:
            brand = d.get("brand_name", "")
            if brand:
                drugs_lookup[brand] = d

        # ── Stage 3: Extraction ────────────────────────────────────
        semaphore = asyncio.Semaphore(max_concurrent)

        async with timer("Stage 3 — Grouped Batch Extraction"):
            rows = await run_extraction(
                client, groups, drugs_lookup, pages, semaphore
            )

        # ── Stage 4: Validation + Retry ────────────────────────────
        async with timer("Stage 4 — Validation"):
            rows = validate_rows(rows)

        if auto_retry:
            async with timer("Stage 4 — Auto-Retry"):
                rows = await retry_flagged(
                    client, rows, pages, drug_page_map, semaphore
                )

        # ── Change Log ─────────────────────────────────────────────
        async with timer("Change Log Extraction"):
            changelog = await extract_changelog(client, full_text)

        # ── Stage 5: DB Write ──────────────────────────────────────
        async with timer("Stage 5 — DB Write"):
            doc_id = _write_to_db(
                conn, discovery, rows, file_hash, full_text,
                changelog, str(pdf_path),
            )

        # ── Summary ───────────────────────────────────────────────
        elapsed = time.perf_counter() - pipeline_start
        log.info(f"Pipeline complete for {pdf_path.name} in {elapsed:.2f}s")
        _print_summary_table(rows)

        return doc_id

    except Exception:
        log.error(f"Pipeline failed for {pdf_path}:\n{traceback.format_exc()}")
        return None


async def ingest_directory(
    dir_path: str | Path,
    conn,
    client,
    auto_retry: bool = True,
    max_concurrent: int = 5,
) -> None:
    """Glob *.pdf in a directory and ingest each sequentially."""
    dir_path = Path(dir_path)
    pdfs = sorted(dir_path.glob("*.pdf"))
    log.info(f"Found {len(pdfs)} PDF(s) in {dir_path}")

    results: list[tuple[str, Optional[int]]] = []
    for pdf in pdfs:
        doc_id = await ingest_document(
            pdf, conn, client,
            auto_retry=auto_retry,
            max_concurrent=max_concurrent,
        )
        results.append((pdf.name, doc_id))

    # Final batch summary
    console.print()
    table = Table(title="Batch Ingestion Summary", show_lines=True)
    table.add_column("File", style="cyan")
    table.add_column("Doc ID", justify="center")
    table.add_column("Status", justify="center")

    for fname, did in results:
        status = "[bold green]OK[/bold green]" if did else "[bold red]FAILED[/bold red]"
        table.add_row(fname, str(did) if did else "—", status)

    console.print(table)
