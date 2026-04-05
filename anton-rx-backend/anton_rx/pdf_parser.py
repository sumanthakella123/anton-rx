"""PDF Parsing — page-by-page text extraction via pdfplumber + SHA-256 hashing."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import pdfplumber

log = logging.getLogger("anton_rx.pdf_parser")


def parse_pdf(pdf_path: str | Path) -> tuple[dict[int, str], str, str]:
    """
    Extract text from a PDF file.

    Returns
    -------
    pages : dict[int, str]
        {1-indexed page_number: page_text}
    full_text : str
        All pages concatenated with page headers.
    file_hash : str
        SHA-256 hex digest of the raw PDF bytes.
    """
    pdf_path = Path(pdf_path)
    raw_bytes = pdf_path.read_bytes()
    file_hash = hashlib.sha256(raw_bytes).hexdigest()

    pages: dict[int, str] = {}
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            pages[i] = text

    # Build full text with page headers
    parts: list[str] = []
    for pnum in sorted(pages):
        parts.append(f"[Page {pnum}]")
        parts.append(pages[pnum])
        parts.append("--- PAGE BREAK ---")
    full_text = "\n".join(parts)

    total_chars = sum(len(t) for t in pages.values())
    log.info(
        f"PDF parsed: {len(pages)} pages, {total_chars:,} chars, "
        f"hash={file_hash[:12]}…"
    )
    return pages, full_text, file_hash
