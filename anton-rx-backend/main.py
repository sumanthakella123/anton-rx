"""Anton Rx Ingestion Pipeline — CLI Entry Point."""

from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import sys
import urllib.parse

from dotenv import load_dotenv
load_dotenv()

import google.genai as genai

from anton_rx.config import setup_logging
from anton_rx.database import init_db
from anton_rx.orchestrator import ingest_directory, ingest_document


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Anton Rx Medical Benefit Drug Policy Tracker — Ingestion Pipeline",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pdf", type=str, help="Path to a single PDF to ingest")
    group.add_argument("--dir", type=str, help="Path to a directory of PDFs to ingest")

    parser.add_argument(
        "--db",
        type=str,
        default="anton_rx.db",
        help="SQLite database file (default: anton_rx.db)",
    )
    parser.add_argument(
        "--no-retry",
        action="store_true",
        help="Disable auto-retry of LOW confidence rows",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=2,
        help="Max concurrent LLM calls in Stage 3 (default: 2)",
    )

    return parser.parse_args()


def normalize_path(path_str: str) -> str:
    """Normalize file:/// URIs and URL-escaped paths."""
    if not path_str:
        return path_str
    
    if path_str.startswith("file:///"):
        path_str = path_str[8:]
    elif path_str.startswith("file://"):
        path_str = path_str[7:]
    elif path_str.startswith("file:"):
        path_str = path_str[5:]
        
    if "%" in path_str:
        path_str = urllib.parse.unquote(path_str)
        
    return path_str


async def main() -> None:
    args = parse_args()
    logger = setup_logging()

    # ── API key ────────────────────────────────────────────────
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        logger.error(
            "GOOGLE_API_KEY environment variable is not set. "
            "Set it with: set GOOGLE_API_KEY=your-key"
        )
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    # ── Database ───────────────────────────────────────────────
    conn = sqlite3.connect(args.db)
    init_db(conn)

    # ── Run ────────────────────────────────────────────────────
    auto_retry = not args.no_retry

    try:
        if args.pdf:
            pdf_path = normalize_path(args.pdf)
            await ingest_document(
                pdf_path,
                conn,
                client,
                auto_retry=auto_retry,
                max_concurrent=args.max_concurrent,
            )
        else:
            dir_path = normalize_path(args.dir)
            await ingest_directory(
                dir_path,
                conn,
                client,
                auto_retry=auto_retry,
                max_concurrent=args.max_concurrent,
            )
    finally:
        conn.close()


if __name__ == "__main__":
    asyncio.run(main())
