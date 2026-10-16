"""Regressão #15: migrations rodam UMA vez por banco (PRAGMA user_version).

Antes cada Storage() executava executescript(_SCHEMA)+_migrate()+commit a cada
open. Com user_version, o schema/migração rodam 1x por banco e o gating não
quebra a abertura subsequente do mesmo arquivo.
"""
from hermes_seo_agent.storage.db import Storage, _SCHEMA_VERSION
import sqlite3


def test_schema_applies_once_and_versions(tmp_path):
    db = str(tmp_path / "s.db")
    with Storage(db) as s1:
        assert s1.conn.execute("PRAGMA user_version").fetchone()[0] == _SCHEMA_VERSION
        assert s1.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='http_cache'"
        ).fetchone() is not None

    # segundo open no MESMO arquivo: gating não quebra (schema já aplicado)
    with Storage(db) as s2:
        assert s2.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
        ).fetchone() is not None
        assert s2.conn.execute("PRAGMA user_version").fetchone()[0] == _SCHEMA_VERSION


def test_schema_v11_to_v12_preserves_title_decision_data(tmp_path):
    db = tmp_path / "v11.db"
    conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE title_decision (
            decision_id TEXT PRIMARY KEY, url TEXT NOT NULL, post_id INTEGER,
            field TEXT NOT NULL, before TEXT NOT NULL, after TEXT NOT NULL,
            action_fingerprint TEXT NOT NULL, decision_version INTEGER NOT NULL,
            evidence_json TEXT NOT NULL, rollout_json TEXT NOT NULL, confidence REAL,
            requires_review INTEGER NOT NULL, before_known INTEGER NOT NULL,
            status TEXT NOT NULL, not_executable_reason TEXT, decided_at TEXT NOT NULL,
            enqueued_at TEXT, executed_at TEXT, outcome_id TEXT,
            publication_status TEXT NOT NULL, publication_checked_at TEXT,
            publication_error TEXT, updated_at TEXT NOT NULL
        )
    """)
    conn.execute(
        "INSERT INTO title_decision VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("d1", "https://x.test/post", 7, "rank_math_title", "Old", "New",
         "fp", 1, "{}", "{}", 0.9, 0, 1, "decided", None, "2026-01-01",
         None, None, None, "not_checked", None, None, "2026-01-01"),
    )
    conn.execute("PRAGMA user_version = 11")
    conn.commit()
    conn.close()

    with Storage(str(db)) as storage:
        saved = storage.title_decision("d1")
        columns = {row[1] for row in storage.conn.execute(
            "PRAGMA table_info(title_decision)")}
        assert saved["before"] == "Old"
        assert saved["after"] == "New"
        assert saved["publication_operation_id"] is None
        assert {"publication_operation_id", "publication_rebuild_kind",
                "publication_requested_at"}.issubset(columns)
        assert storage.conn.execute("PRAGMA user_version").fetchone()[0] == _SCHEMA_VERSION
