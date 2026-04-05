"""Stage 4 — Validation + Auto-Retry: enum enforcement, confidence scoring, retry."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import google.genai as genai

from .config import ALLOWED_VALUES, STAGE_MODELS, strip_fences

log = logging.getLogger("anton_rx.stage_validation")

RETRY_PROMPT = """\
The previous extraction for {brand_name} ({generic_name}) produced invalid or empty values.

Problems detected: {flags}

Please re-examine the document and fix only the flagged fields.
Return a complete JSON object using the same schema as before.

Previous extraction attempt:
{previous_json}

Document context:
{relevant_page_text}
"""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_row(row: dict[str, Any]) -> dict[str, Any]:
    """
    Validate a single drug row.

    - Enforce enum fields (reset to N/A + flag if invalid).
    - Flag if all of prior_auth_criteria, indications, coverage_status are N/A/empty.
    - Flag if step_therapy_required=Yes but biosimilar_step_detail is N/A/empty.
    - Convert source_pages list → comma-separated string.
    - Set _confidence HIGH or LOW.
    """
    flags: list[str] = list(filter(None, row.get("_flags", "").split(",")))

    # Enum enforcement
    for field, allowed in ALLOWED_VALUES.items():
        val = row.get(field, "N/A")
        if isinstance(val, str) and val not in allowed:
            log.warning(f"Enum violation: {field}='{val}' for {row.get('brand_name')}")
            flags.append(f"invalid_{field}={val}")
            row[field] = "N/A"

    # Sparse-row check
    pa_crit = row.get("prior_auth_criteria", "N/A") or "N/A"
    indications = row.get("indications", "N/A") or "N/A"
    cov_status = row.get("coverage_status", "N/A") or "N/A"
    if all(v.strip() in ("N/A", "") for v in [pa_crit, indications, cov_status]):
        flags.append("sparse_row")

    # Step therapy consistency
    if row.get("step_therapy_required") == "Yes":
        bsd = row.get("biosimilar_step_detail", "N/A") or "N/A"
        if bsd.strip() in ("N/A", ""):
            flags.append("step_therapy_missing_detail")

    # source_pages → string
    sp = row.get("source_pages", "N/A")
    if isinstance(sp, list):
        row["source_pages"] = ", ".join(str(p) for p in sp) if sp else "N/A"

    # Confidence
    row["_flags"] = ",".join(flags) if flags else ""
    row["_confidence"] = "LOW" if flags else "HIGH"
    return row


def validate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate all drug rows. Returns the same list, mutated in place."""
    for row in rows:
        _validate_row(row)

    high = sum(1 for r in rows if r.get("_confidence") == "HIGH")
    low = len(rows) - high
    log.info(f"Validation: {high} HIGH, {low} LOW out of {len(rows)} rows")
    return rows


# ---------------------------------------------------------------------------
# Auto-retry
# ---------------------------------------------------------------------------

def _build_page_text(pages: dict[int, str], page_numbers: list[int]) -> str:
    parts: list[str] = []
    for pnum in sorted(page_numbers):
        if pnum in pages:
            parts.append(f"[Page {pnum}]")
            parts.append(pages[pnum])
            parts.append("--- PAGE BREAK ---")
    return "\n".join(parts)


async def _retry_single(
    client: genai.Client,
    row: dict[str, Any],
    pages: dict[int, str],
    drug_page_map: dict[str, list[int]],
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    """Retry extraction for a single LOW-confidence drug."""
    model = STAGE_MODELS["retry"]
    brand = row.get("brand_name", "?")
    generic = row.get("generic_name", "?")
    flags = row.get("_flags", "")

    log.warning(f"Retrying: {brand} ({generic}) | flags={flags} | model={model}")

    page_numbers = drug_page_map.get(brand, list(pages.keys()))
    page_text = _build_page_text(pages, page_numbers)

    prompt = RETRY_PROMPT.format(
        brand_name=brand,
        generic_name=generic,
        flags=flags,
        previous_json=json.dumps(row, indent=2),
        relevant_page_text=page_text,
    )

    async with semaphore:
        try:
            t0 = time.perf_counter()
            from .config import call_with_retry
            response = await call_with_retry(
                client.aio.models.generate_content,
                model=model,
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    temperature=0.0,
                    max_output_tokens=8192,
                ),
            )
            elapsed = time.perf_counter() - t0
            log.debug(f"Retry done for {brand} in {elapsed:.2f}s")
        except Exception as exc:
            log.error(f"Retry API error for {brand}: {exc}")
            return row  # keep original

        raw = strip_fences(response.text)
        try:
            new_row = json.loads(raw)
            if isinstance(new_row, list):
                new_row = new_row[0] if new_row else row
        except (json.JSONDecodeError, ValueError) as exc:
            log.error(f"Retry JSON parse failed for {brand}: {exc}")
            return row

    # Re-validate
    new_row["_flags"] = ""  # reset before re-validation
    _validate_row(new_row)
    return new_row


async def retry_flagged(
    client: genai.Client,
    rows: list[dict[str, Any]],
    pages: dict[int, str],
    drug_page_map: dict[str, list[int]],
    semaphore: asyncio.Semaphore,
) -> list[dict[str, Any]]:
    """
    For every LOW confidence row, fire one retry using gemini-2.5-pro.
    Re-validate after retry. If still LOW, keep it — do not loop.
    """
    low_indices = [
        i for i, r in enumerate(rows) if r.get("_confidence") == "LOW"
    ]

    if not low_indices:
        log.info("No LOW confidence rows — skipping retry stage.")
        return rows

    log.info(f"Retrying {len(low_indices)} LOW confidence rows…")

    tasks = [
        _retry_single(client, rows[i], pages, drug_page_map, semaphore)
        for i in low_indices
    ]
    results = await asyncio.gather(*tasks)

    for idx, new_row in zip(low_indices, results):
        rows[idx] = new_row

    high = sum(1 for r in rows if r.get("_confidence") == "HIGH")
    low = len(rows) - high
    log.info(f"After retry: {high} HIGH, {low} LOW out of {len(rows)} rows")
    return rows
