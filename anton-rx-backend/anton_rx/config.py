"""Configuration, constants, logging setup, and shared utilities."""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime

from rich.logging import RichHandler

# ---------------------------------------------------------------------------
# Model tiering
# ---------------------------------------------------------------------------
STAGE_MODELS: dict[str, str | None] = {
    "discovery":  "gemini-2.5-flash",
    "extraction": "gemini-2.5-flash", 
    "retry":      "gemini-2.5-flash", 
    "changelog":  "gemini-2.5-flash",
    "validation": None,  # pure Python, no LLM
}

# ---------------------------------------------------------------------------
# Enum enforcement sets
# ---------------------------------------------------------------------------
ALLOWED_VALUES: dict[str, set[str]] = {
    "coverage_status":       {"Covered", "Not Covered", "Excluded", "N/A"},
    "coverage_category":     {"Proven", "Unproven", "Medically Necessary", "Excluded", "N/A"},
    "drug_status":           {"Restricted", "Unrestricted", "N/A"},
    "access_status":         {"Preferred", "Non-Preferred", "N/A"},
    "prior_auth_required":   {"Yes", "No", "N/A"},
    "step_therapy_required": {"Yes", "No", "N/A"},
    "nccn_supported":        {"Yes", "No", "N/A"},
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging() -> logging.Logger:
    """Configure root logger with Rich console handler + timestamped file handler."""
    logger = logging.getLogger("anton_rx")
    if logger.handlers:
        return logger  # already configured

    logger.setLevel(logging.DEBUG)

    # Console — Rich
    console_handler = RichHandler(
        rich_tracebacks=True,
        show_time=True,
        show_path=False,
        markup=True,
    )
    console_handler.setLevel(logging.INFO)
    logger.addHandler(console_handler)

    # File
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs("logs", exist_ok=True)
    file_handler = logging.FileHandler(f"logs/ingest_{ts}.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    )
    logger.addHandler(file_handler)

    return logger


# ---------------------------------------------------------------------------
# Timer context manager
# ---------------------------------------------------------------------------

@asynccontextmanager
async def timer(label: str, logger: logging.Logger | None = None):
    """Async context manager that logs START / END with elapsed seconds."""
    log = logger or logging.getLogger("anton_rx")
    log.info(f"[bold cyan]START[/bold cyan] {label}")
    t0 = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - t0
        log.info(f"[bold green]END[/bold green]   {label}  ({elapsed:.2f}s)")


# ---------------------------------------------------------------------------
# Helper: strip markdown fences from LLM responses
# ---------------------------------------------------------------------------

def strip_fences(text: str) -> str:
    """Remove ```json ... ``` or ``` ... ``` wrappers that Gemini adds."""
    t = text.strip()
    if t.startswith("```"):
        # remove first line (```json or ```)
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
    if t.endswith("```"):
        t = t[:-3]
    return t.strip()


# ---------------------------------------------------------------------------
# Helper: Exponential backoff for API calls
# ---------------------------------------------------------------------------

FALLBACK_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.5-pro",
]

async def call_with_retry(fn, *args, max_retries=10, **kwargs):
    """Wrap async LLM calls with exponential backoff and model swapping on rate limits."""
    import asyncio
    log = logging.getLogger("anton_rx")
    for attempt in range(max_retries):
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            err_str = str(e).upper()
            is_404 = "404" in err_str or "NOT_FOUND" in err_str
            is_quota = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "QUOTA" in err_str

            if is_quota or is_404:
                if attempt == max_retries - 1:
                    log.error(f"Max retries exceeded for Error: {e}")
                    raise
                
                # Swap to a fresh model to bypass free-tier rate limits or missing models
                if "model" in kwargs:
                    next_model = FALLBACK_MODELS[(attempt + 1) % len(FALLBACK_MODELS)]
                    old_model = kwargs["model"]
                    kwargs["model"] = next_model
                    log.warning(f"Error on {old_model}. Swapping to {next_model} for next attempt...")

                wait = 1 if is_404 else min(15 * (2 ** attempt), 120) 
                log.warning(f"Waiting {wait}s before retry {attempt+1}/{max_retries}...")
                await asyncio.sleep(wait)
            else:
                raise
