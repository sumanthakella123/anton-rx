"""Stage 1 — Discovery: Extract document metadata and drug list via LLM."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import google.genai as genai

from .config import STAGE_MODELS, strip_fences, timer

log = logging.getLogger("anton_rx.stage_discovery")

DISCOVERY_PROMPT = """\
You are reading a health insurance medical benefit drug policy document.

Your ONLY job is to extract document metadata and produce a list of the PRIMARY SUBJECT drugs (the medications this policy is providing coverage criteria for).
DO NOT extract secondary drugs that are merely mentioned in passing, such as prerequisites, prior therapies the patient must fail, or contraindications.

Return ONLY a valid JSON object. No markdown, no explanation, no preamble.

{{
  "payer": "",
  "policy_title": "",
  "policy_number": "",
  "effective_date": "",
  "doc_type": "",
  "drug_category": "",
  "policy_review_cycle": "",
  "drugs": [
    {{
      "brand_name": "",
      "generic_name": "",
      "is_biosimilar": false
    }}
  ]
}}

Rules:
- Include EVERY drug: brand names, generics, biosimilars, reference biologics.
- If a drug appears under multiple brand names, create one entry per brand.
- is_biosimilar = true if the drug name contains a biosimilar suffix (-awwb, -bvzr, -adus, etc.) or is explicitly labeled as a biosimilar.
- If a field is not present in the document, use an empty string.
- Do NOT extract criteria yet. Only metadata and drug list.

Document:
{full_text}
"""

MAX_INPUT_CHARS = 100_000


async def run_discovery(
    client: genai.Client, full_text: str
) -> dict[str, Any]:
    """
    Run Stage 1 — Discovery.

    Returns a dict with keys: payer, policy_title, policy_number,
    effective_date, doc_type, drug_category, policy_review_cycle, drugs.
    """
    model = STAGE_MODELS["discovery"]
    log.info(f"Stage 1 — Discovery  | model={model}")

    # Truncate if needed
    if len(full_text) > MAX_INPUT_CHARS:
        log.warning(
            f"Full text truncated from {len(full_text):,} to {MAX_INPUT_CHARS:,} chars"
        )
        full_text = full_text[:MAX_INPUT_CHARS]

    prompt = DISCOVERY_PROMPT.format(full_text=full_text)

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

    raw = strip_fences(response.text)
    log.debug(f"Discovery LLM response time: {elapsed:.2f}s  model={model}")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error(f"Discovery JSON parse failed: {exc}")
        log.error(f"Raw response (first 500 chars): {raw[:500]}")
        return {
            "payer": "",
            "policy_title": "",
            "policy_number": "",
            "effective_date": "",
            "doc_type": "",
            "drug_category": "",
            "policy_review_cycle": "",
            "drugs": [],
        }

    raw_drugs = data.get("drugs", [])
    valid_drugs = []
    text_lower = full_text.lower()
    
    for d in raw_drugs:
        brand = d.get("brand_name", "").lower()
        generic = d.get("generic_name", "").lower()
        
        count = 0
        if brand and brand != "n/a":
            count += text_lower.count(brand)
        if generic and generic != "n/a":
            count += text_lower.count(generic)
            
        if count >= 2:
            valid_drugs.append(d)
        else:
            log.debug(
                f"  → [FILTERED OUT] {d.get('brand_name', '?')} "
                f"({d.get('generic_name', '?')}) - occurrences: {count}"
            )

    data["drugs"] = valid_drugs

    log.info(
        f"Discovered {len(valid_drugs)} primary drugs (filtered from {len(raw_drugs)}) "
        f"| payer={data.get('payer', '?')} | policy={data.get('policy_title', '?')}"
    )
    for d in valid_drugs:
        log.debug(f"  → {d.get('brand_name', '?')} ({d.get('generic_name', '?')})")

    return data
