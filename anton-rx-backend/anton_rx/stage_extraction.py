"""Stage 3 — Grouped Batch Extraction: parallel async LLM calls per page group."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import google.genai as genai

from .config import STAGE_MODELS, strip_fences

log = logging.getLogger("anton_rx.stage_extraction")

EXTRACTION_PROMPT = """\
You are extracting structured insurance coverage data for MULTIPLE drugs from a health insurance policy document.

Drugs to extract (return one JSON object per drug, in this exact order):
{drug_list}

For each drug, extract ONLY information explicitly stated about THAT drug.
Use "N/A" for anything not found. Never borrow criteria from one drug and apply to another.

Return ONLY a valid JSON array. No markdown, no explanation. One object per drug, same order as the list above.

Each object must follow this exact schema:
{{
  "brand_name": "",
  "generic_name": "",
  "drug_category": "",
  "is_biosimilar": false,
  "hcpcs_codes": "",
  "maximum_units": "",
  "coverage_status": "Covered|Not Covered|Excluded|N/A",
  "coverage_category": "Proven|Unproven|Medically Necessary|Excluded|N/A",
  "drug_status": "Restricted|Unrestricted|N/A",
  "access_status": "Preferred|Non-Preferred|N/A",
  "prior_auth_required": "Yes|No|N/A",
  "prior_auth_criteria": "",
  "step_therapy_required": "Yes|No|N/A",
  "biosimilar_step_detail": "",
  "authorization_duration": "",
  "nccn_supported": "Yes|No|N/A",
  "indications": "",
  "icd10_codes": "",
  "site_of_care": "",
  "source_pages": []
}}

Field notes:
- coverage_category: Look for "proven", "unproven", "medically necessary", "not medically necessary", "excluded".
- drug_status: "Restricted" = PA required. "Unrestricted" = no PA needed. (BCBS NC concept)
- biosimilar_step_detail: Name the SPECIFIC biosimilars that must be tried. Do not just say "Yes".
- icd10_codes: Comma-separated ICD-10 codes if a diagnosis code table is present (e.g. "G43.701, G43.709").
- maximum_units: Look for "Maximum Units" columns in tables.
- nccn_supported: "Yes" if NCCN Category 1 or 2A is an alternative coverage basis.
- authorization_duration: Extract explicitly ("365 days", "12 months"). Use initial auth period.
- indications: Semicolon-separated list of covered diagnoses/conditions.
- source_pages: Page numbers where you found data for this specific drug.

Relevant document pages:
{relevant_page_text}
"""


def _build_page_text(pages: dict[int, str], page_numbers: list[int]) -> str:
    """Concatenate selected pages with headers and separators."""
    parts: list[str] = []
    for pnum in sorted(page_numbers):
        if pnum in pages:
            parts.append(f"[Page {pnum}]")
            parts.append(pages[pnum])
            parts.append("--- PAGE BREAK ---")
    return "\n".join(parts)


def _build_drug_list_text(
    drug_names: list[str], drugs_lookup: dict[str, dict]
) -> str:
    """Build the enumerated drug list for the prompt."""
    lines: list[str] = []
    for i, name in enumerate(drug_names, 1):
        info = drugs_lookup.get(name, {})
        generic = info.get("generic_name", "")
        label = f"{i}. {name}"
        if generic:
            label += f" ({generic})"
        lines.append(label)
    return "\n".join(lines)


def _empty_row(drug_name: str, generic: str) -> dict[str, Any]:
    """Return a stub row with LOW confidence for failed extractions."""
    return {
        "brand_name": drug_name,
        "generic_name": generic,
        "drug_category": "N/A",
        "is_biosimilar": False,
        "hcpcs_codes": "N/A",
        "maximum_units": "N/A",
        "coverage_status": "N/A",
        "coverage_category": "N/A",
        "drug_status": "N/A",
        "access_status": "N/A",
        "prior_auth_required": "N/A",
        "prior_auth_criteria": "N/A",
        "step_therapy_required": "N/A",
        "biosimilar_step_detail": "N/A",
        "authorization_duration": "N/A",
        "nccn_supported": "N/A",
        "indications": "N/A",
        "icd10_codes": "N/A",
        "site_of_care": "N/A",
        "source_pages": "N/A",
        "_confidence": "LOW",
        "_flags": "extraction_failed",
    }


async def _extract_group(
    client: genai.Client,
    drug_names: list[str],
    drugs_lookup: dict[str, dict],
    pages: dict[int, str],
    page_numbers: list[int],
    semaphore: asyncio.Semaphore,
) -> list[dict[str, Any]]:
    """Extract all drugs in a single page-fingerprint group with one LLM call."""
    model = STAGE_MODELS["extraction"]

    async with semaphore:
        drug_list_text = _build_drug_list_text(drug_names, drugs_lookup)
        page_text = _build_page_text(pages, page_numbers)

        prompt = EXTRACTION_PROMPT.format(
            drug_list=drug_list_text,
            relevant_page_text=page_text,
        )

        log.debug(
            f"Extraction group: {len(drug_names)} drugs, "
            f"pages={page_numbers}, model={model}"
        )

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
            log.debug(f"Extraction group done in {elapsed:.2f}s  model={model}")
        except Exception as exc:
            log.error(f"Extraction API error for group {drug_names}: {exc}")
            return [
                _empty_row(name, drugs_lookup.get(name, {}).get("generic_name", ""))
                for name in drug_names
            ]

        raw = strip_fences(response.text)
        try:
            rows = json.loads(raw)
            if not isinstance(rows, list):
                raise ValueError("Expected JSON array")
        except (json.JSONDecodeError, ValueError) as exc:
            log.error(f"Extraction JSON parse failed: {exc}")
            log.error(f"Raw response (first 500 chars): {raw[:500]}")
            return [
                _empty_row(name, drugs_lookup.get(name, {}).get("generic_name", ""))
                for name in drug_names
            ]

        # Pad or trim to match the drug list length
        while len(rows) < len(drug_names):
            idx = len(rows)
            name = drug_names[idx]
            rows.append(
                _empty_row(name, drugs_lookup.get(name, {}).get("generic_name", ""))
            )

        return rows[: len(drug_names)]


async def run_extraction(
    client: genai.Client,
    groups: dict[str, list[str]],
    drugs_lookup: dict[str, dict],
    pages: dict[int, str],
    semaphore: asyncio.Semaphore,
) -> list[dict[str, Any]]:
    """
    Run Stage 3 — Grouped Batch Extraction.

    Parameters
    ----------
    groups : {fingerprint: [drug_brand_names]}
    drugs_lookup : {brand_name: drug discovery dict}
    pages : {page_number: text}
    semaphore : controls max concurrent LLM calls

    Returns a flat list of extraction rows (one per drug).
    """
    total_drugs = sum(len(v) for v in groups.values())
    log.info(
        f"Stage 3: {total_drugs} drugs → {len(groups)} page groups → "
        f"{len(groups)} LLM calls (vs {total_drugs} naive)"
    )

    tasks: list[asyncio.Task] = []
    for fingerprint, drug_names in groups.items():
        page_numbers = [int(p) for p in fingerprint.split("-")]
        task = asyncio.create_task(
            _extract_group(
                client, drug_names, drugs_lookup, pages, page_numbers, semaphore
            )
        )
        tasks.append(task)

    results = await asyncio.gather(*tasks)

    # Flatten
    flat: list[dict[str, Any]] = []
    for group_rows in results:
        flat.extend(group_rows)

    # Log per-drug summary
    for row in flat:
        log.info(
            f"  {row.get('brand_name', '?'):30s} | "
            f"coverage={row.get('coverage_status', '?'):12s} | "
            f"PA={row.get('prior_auth_required', '?')}"
        )

    return flat
