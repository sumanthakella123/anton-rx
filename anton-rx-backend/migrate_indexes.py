"""
One-shot migration: adds B-tree indexes and FTS5 virtual table to an existing
anton_rx.db without needing to re-ingest documents.

Usage:
    python migrate_indexes.py                   # uses default ./anton_rx.db
    python migrate_indexes.py path/to/other.db
"""

import sqlite3
import sys

DB_PATH = sys.argv[1] if len(sys.argv) > 1 else "anton_rx.db"

conn = sqlite3.connect(DB_PATH)
conn.execute("PRAGMA journal_mode=WAL")

print(f"Migrating: {DB_PATH}")

# B-tree indexes
conn.executescript("""
CREATE INDEX IF NOT EXISTS idx_dp_brand_name   ON drug_policies(brand_name);
CREATE INDEX IF NOT EXISTS idx_dp_generic_name ON drug_policies(generic_name);
CREATE INDEX IF NOT EXISTS idx_d_payer         ON documents(payer);
""")
print("  ✓ B-tree indexes created")

# FTS5 virtual table
conn.executescript("""
CREATE VIRTUAL TABLE IF NOT EXISTS drug_policies_fts USING fts5(
    brand_name,
    generic_name,
    drug_category,
    indications,
    prior_auth_criteria,
    content='drug_policies',
    content_rowid='id'
);
""")

# Populate FTS from existing rows (only if empty)
fts_count = conn.execute("SELECT COUNT(*) FROM drug_policies_fts").fetchone()[0]
if fts_count == 0:
    conn.execute("""
        INSERT INTO drug_policies_fts(rowid, brand_name, generic_name, drug_category, indications, prior_auth_criteria)
        SELECT id, brand_name, generic_name, drug_category, indications, prior_auth_criteria
        FROM drug_policies
    """)
    conn.commit()
    indexed = conn.execute("SELECT COUNT(*) FROM drug_policies_fts").fetchone()[0]
    print(f"  ✓ FTS5 index populated ({indexed} rows)")
else:
    print(f"  ✓ FTS5 index already populated ({fts_count} rows), skipped")

# Triggers for future inserts/updates/deletes
conn.executescript("""
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
""")
print("  ✓ FTS5 sync triggers created")

conn.commit()
conn.close()
print("Done.")
