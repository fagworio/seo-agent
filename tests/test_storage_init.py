"""Regressão #15: migrations rodam UMA vez por banco (PRAGMA user_version).

Antes cada Storage() executava executescript(_SCHEMA)+_migrate()+commit a cada
open. Com user_version, o schema/migração rodam 1x por banco e o gating não
quebra a abertura subsequente do mesmo arquivo.
"""
from hermes_seo_agent.storage.db import Storage, _SCHEMA_VERSION


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
