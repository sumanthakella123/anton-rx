"""Change Log Extraction — extract policy change history via LLM."""

from __future__ import annotations

import logging
import time

import google.genai as genai

from .config import STAGE_MODELS, strip_fences

log = logging.getLogger("anton_rx.stage_changelog")

CHANGELOG_PROMPT = """\
Extract the policy change history / revision log from the end of this document.
Return the change log verbatim as plain text.
If no change log or revision history is found, return exactly: N/A

Document (last section):
{tail_text}
"""

TAIL_CHARS = 10_000


async def extract_changelog(client: genai.Client, full_text: str) -> str:
    """
    Extract the policy change log from the tail of the document.

    Uses gemini-2.5-flash-lite on the last 10,000 characters.
    Returns the changelog text or "N/A".
    """
    model = STAGE_MODELS["changelog"]
    log.info(f"Change log extraction | model={model}")

    tail = full_text[-TAIL_CHARS:] if len(full_text) > TAIL_CHARS else full_text
    prompt = CHANGELOG_PROMPT.format(tail_text=tail)

    try:
        t0 = time.perf_counter()
        from .config import call_with_retry
        response = await call_with_retry(
            client.aio.models.generate_content,
            model=model,
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=2000,
            ),
        )
        elapsed = time.perf_counter() - t0
        log.debug(f"Changelog LLM response time: {elapsed:.2f}s")

        text = strip_fences(response.text).strip()
        if not text:
            text = "N/A"
        log.info(f"Changelog length: {len(text)} chars")
        return text

    except Exception as exc:
        log.error(f"Changelog extraction failed: {exc}")
        return "N/A"
