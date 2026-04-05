"""Stage 2 — Page Mapper: map drugs to pages + group by page fingerprint."""

from __future__ import annotations

import logging

log = logging.getLogger("anton_rx.stage_pagemap")


def map_drugs_to_pages(
    drugs: list[dict], pages: dict[int, str]
) -> dict[str, list[int]]:
    """
    For each discovered drug, find which pages mention it by case-insensitive
    string search on brand_name and generic_name.

    Rules
    -----
    - Always include page 1 (often has shared PA criteria header).
    - If a drug has zero page hits, fall back to ALL pages and log WARNING.

    Returns {brand_name: sorted list of page numbers}.
    """
    result: dict[str, list[int]] = {}

    for drug in drugs:
        brand = drug.get("brand_name", "") or ""
        generic = drug.get("generic_name", "") or ""
        search_terms = [t.lower() for t in (brand, generic) if t]

        hits: set[int] = set()
        for pnum, ptext in pages.items():
            lower_text = ptext.lower()
            for term in search_terms:
                if term and term in lower_text:
                    hits.add(pnum)
                    break

        # Always include page 1
        hits.add(1)

        if len(hits) == 1 and 1 in hits:
            # Only page 1 was found (no real hits) → fall back to ALL pages
            log.warning(
                f"Zero page hits for '{brand}' ('{generic}') — falling back to all pages"
            )
            hits = set(pages.keys())

        sorted_pages = sorted(hits)
        result[brand] = sorted_pages
        log.debug(f"  Page map: {brand} → pages {sorted_pages}")

    return result


def group_drugs_by_pages(
    drug_page_map: dict[str, list[int]]
) -> dict[str, list[str]]:
    """
    Group drugs that share the exact same set of pages.

    Returns {page_fingerprint: [list of drug brand names]}.

    Example::

        Avastin  → [4,5,6,7] → fingerprint "4-5-6-7"
        Mvasi    → [4,5,6,7] → fingerprint "4-5-6-7"  ← same group
        Botox    → [8,9,10]  → fingerprint "8-9-10"   ← separate
    """
    groups: dict[str, list[str]] = {}
    for drug_name, page_list in drug_page_map.items():
        fingerprint = "-".join(str(p) for p in sorted(page_list))
        groups.setdefault(fingerprint, []).append(drug_name)
    return groups
