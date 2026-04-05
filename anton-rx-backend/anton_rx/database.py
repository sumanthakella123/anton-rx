"""SQLite database helpers — schema creation, inserts, dedup check, ingestion log."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

log = logging.getLogger("anton_rx.database")

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS documents (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    payer               TEXT,
    policy_title        TEXT,
    policy_number       TEXT,
    effective_date      TEXT,
    doc_type            TEXT    DEFAULT 'Medical Benefit Drug Policy',
    file_hash           TEXT    UNIQUE,
    raw_text            TEXT,
    policy_change_log   TEXT,
    policy_review_cycle TEXT    DEFAULT 'N/A',
    source_file         TEXT,
    created_at          TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS drug_policies (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id            INTEGER REFERENCES documents(id),
    brand_name             TEXT    DEFAULT 'N/A',
    generic_name           TEXT    DEFAULT 'N/A',
    drug_category          TEXT    DEFAULT 'N/A',
    is_biosimilar          INTEGER DEFAULT 0,
    hcpcs_codes            TEXT    DEFAULT 'N/A',
    maximum_units          TEXT    DEFAULT 'N/A',
    coverage_status        TEXT    DEFAULT 'N/A',
    coverage_category      TEXT    DEFAULT 'N/A',
    drug_status            TEXT    DEFAULT 'N/A',
    access_status          TEXT    DEFAULT 'N/A',
    prior_auth_required    TEXT    DEFAULT 'N/A',
    prior_auth_criteria    TEXT    DEFAULT 'N/A',
    step_therapy_required  TEXT    DEFAULT 'N/A',
    biosimilar_step_detail TEXT    DEFAULT 'N/A',
    authorization_duration TEXT    DEFAULT 'N/A',
    nccn_supported         TEXT    DEFAULT 'N/A',
    indications            TEXT    DEFAULT 'N/A',
    icd10_codes            TEXT    DEFAULT 'N/A',
    site_of_care           TEXT    DEFAULT 'N/A',
    source_pages           TEXT    DEFAULT 'N/A',
    _confidence            TEXT    DEFAULT 'N/A',
    _flags                 TEXT    DEFAULT '',
    created_at             TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ingestion_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id  INTEGER,
    stage        TEXT,
    status       TEXT,
    detail       TEXT,
    elapsed_sec  REAL,
    created_at   TEXT DEFAULT (datetime('now'))
);

-- Indexes for fast drug-name and payer lookups
CREATE INDEX IF NOT EXISTS idx_dp_brand_name   ON drug_policies(brand_name);
CREATE INDEX IF NOT EXISTS idx_dp_generic_name ON drug_policies(generic_name);
CREATE INDEX IF NOT EXISTS idx_d_payer         ON documents(payer);

-- FTS5 virtual table for full-text search across drug name, category, and criteria
CREATE VIRTUAL TABLE IF NOT EXISTS drug_policies_fts USING fts5(
    brand_name,
    generic_name,
    drug_category,
    indications,
    prior_auth_criteria,
    content='drug_policies',
    content_rowid='id'
);

-- Keep FTS index in sync with drug_policies
CREATE TRIGGER IF NOT EXISTS dp_fts_ai AFTER INSERT ON drug_policies BEGIN
    INSERT INTO drug_policies_fts(rowid, brand_name, generic_name, drug_category, indications, prior_auth_criteria)
    VALUES (new.id, new.brand_name, new.generic_name, new.drug_category, new.indications, new.prior_auth_criteria);
END;

CREATE TRIGGER IF NOT EXISTS dp_fts_au AFTER UPDATE ON drug_policies BEGIN
    INSERT INTO drug_policies_fts(drug_policies_fts, rowid, brand_name, generic_name, drug_category, indications, prior_auth_criteria)
    VALUES ('delete', old.id, old.brand_name, old.generic_name, old.drug_category, old.indications, old.prior_auth_criteria);
    INSERT INTO drug_policies_fts(rowid, brand_name, generic_name, drug_category, indications, prior_auth_criteria)
    VALUES (new.id, new.brand_name, new.generic_name, new.drug_category, new.indications, new.prior_auth_criteria);
END;

CREATE TRIGGER IF NOT EXISTS dp_fts_ad AFTER DELETE ON drug_policies BEGIN
    INSERT INTO drug_policies_fts(drug_policies_fts, rowid, brand_name, generic_name, drug_category, indications, prior_auth_criteria)
    VALUES ('delete', old.id, old.brand_name, old.generic_name, old.drug_category, old.indications, old.prior_auth_criteria);
END;
"""


def init_db(conn: sqlite3.Connection) -> None:
    """Create all tables if they don't exist."""
    conn.executescript(_SCHEMA_SQL)
    conn.commit()
    log.info("Database schema initialised.")


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------

def check_file_hash(conn: sqlite3.Connection, file_hash: str) -> int | None:
    """Return existing document id if hash already ingested, else None."""
    row = conn.execute(
        "SELECT id FROM documents WHERE file_hash = ?", (file_hash,)
    ).fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Inserts
# ---------------------------------------------------------------------------

def insert_document(conn: sqlite3.Connection, data: dict[str, Any]) -> int:
    """Insert a document row and return the new id."""
    cur = conn.execute(
        """INSERT INTO documents
           (payer, policy_title, policy_number, effective_date, doc_type,
            file_hash, raw_text, policy_change_log, policy_review_cycle, source_file)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            data.get("payer", ""),
            data.get("policy_title", ""),
            data.get("policy_number", ""),
            data.get("effective_date", ""),
            data.get("doc_type", "Medical Benefit Drug Policy"),
            data["file_hash"],
            data.get("raw_text", ""),
            data.get("policy_change_log", "N/A"),
            data.get("policy_review_cycle", "N/A"),
            data.get("source_file", ""),
        ),
    )
    return cur.lastrowid  # type: ignore[return-value]


def insert_drug_policy(conn: sqlite3.Connection, doc_id: int, row: dict[str, Any]) -> int:
    """Insert a single drug_policies row. Returns the new id."""
    cur = conn.execute(
        """INSERT INTO drug_policies
           (document_id, brand_name, generic_name, drug_category, is_biosimilar,
            hcpcs_codes, maximum_units, coverage_status, coverage_category,
            drug_status, access_status, prior_auth_required, prior_auth_criteria,
            step_therapy_required, biosimilar_step_detail, authorization_duration,
            nccn_supported, indications, icd10_codes, site_of_care, source_pages,
            _confidence, _flags)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            doc_id,
            row.get("brand_name", "N/A"),
            row.get("generic_name", "N/A"),
            row.get("drug_category", "N/A"),
            1 if row.get("is_biosimilar") else 0,
            row.get("hcpcs_codes", "N/A"),
            row.get("maximum_units", "N/A"),
            row.get("coverage_status", "N/A"),
            row.get("coverage_category", "N/A"),
            row.get("drug_status", "N/A"),
            row.get("access_status", "N/A"),
            row.get("prior_auth_required", "N/A"),
            row.get("prior_auth_criteria", "N/A"),
            row.get("step_therapy_required", "N/A"),
            row.get("biosimilar_step_detail", "N/A"),
            row.get("authorization_duration", "N/A"),
            row.get("nccn_supported", "N/A"),
            row.get("indications", "N/A"),
            row.get("icd10_codes", "N/A"),
            row.get("site_of_care", "N/A"),
            row.get("source_pages", "N/A"),
            row.get("_confidence", "N/A"),
            row.get("_flags", ""),
        ),
    )
    return cur.lastrowid  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Ingestion log
# ---------------------------------------------------------------------------

def log_ingestion(
    conn: sqlite3.Connection,
    doc_id: int | None,
    stage: str,
    status: str,
    detail: str,
    elapsed_sec: float,
) -> None:
    """Write one row to the ingestion_log table."""
    conn.execute(
        """INSERT INTO ingestion_log (document_id, stage, status, detail, elapsed_sec)
           VALUES (?, ?, ?, ?, ?)""",
        (doc_id, stage, status, detail, elapsed_sec),
    )
