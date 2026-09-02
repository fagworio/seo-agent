"""SQLite state layer: cycles, findings, urls, audit_log, inspection queue,
daily inspection budget (DESIGN.md section 5). Idempotent init."""

from __future__ import annotations

import datetime
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cycles (
    id TEXT PRIMARY KEY,
    started_at TEXT,
    finished_at TEXT,
    summary_json TEXT
);
CREATE TABLE IF NOT EXISTS urls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    source TEXT,
    static_url TEXT,
    last_status_code INTEGER,
    in_sitemap INTEGER,
    is_orphan INTEGER,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id TEXT,
    rule_id TEXT,
    url TEXT,
    severity TEXT,
    detail_json TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT,
    actor TEXT,
    action_type TEXT,
    entity TEXT,
    before_json TEXT,
    after_json TEXT
);
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id TEXT,
    rule_id TEXT,
    url TEXT,
    level TEXT,
    status TEXT,
    fingerprint TEXT UNIQUE,
    before_json TEXT,
    after_json TEXT,
    rollback_json TEXT,
    executed_at TEXT
);
CREATE TABLE IF NOT EXISTS inspection_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    priority INTEGER NOT NULL,          -- 1 = highest (DESIGN/README tiers)
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | in_progress | done | failed
    source TEXT,
    last_inspected_at TEXT,
    result_json TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT,
    UNIQUE(url, status)
);
CREATE TABLE IF NOT EXISTS inspection_budget (
    date TEXT PRIMARY KEY,              -- YYYY-MM-DD
    used INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS page_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    cycle_id TEXT,
    source TEXT,                        -- audit | executor | manual
    linked_action TEXT,                 -- action fingerprint that caused this state
    status_code INTEGER,
    title TEXT,
    meta_description TEXT,
    canonical TEXT,
    meta_robots TEXT,
    h1 TEXT,
    word_count INTEGER,
    content_hash TEXT,                  -- sha256 of page HTML (change detection)
    cwv_json TEXT,                      -- {"lcp":..,"cls":..,"inp":..}
    gsc_json TEXT                       -- {"impressions":..,"clicks":..,"ctr":..}
);
CREATE INDEX IF NOT EXISTS idx_snapshots_url ON page_snapshots(url, captured_at);
CREATE TABLE IF NOT EXISTS seo_expectations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    source TEXT,                        -- apply | set-title | expectations | reindex-status
    changed_at TEXT,
    position REAL,
    impressions REAL,
    clicks REAL,
    ctr REAL,
    expected_ctr REAL,
    expected_clicks REAL,
    gap_clicks REAL,
    conservative_clicks REAL,
    realistic_clicks REAL,
    optimistic_clicks REAL
);
CREATE INDEX IF NOT EXISTS idx_expectations_url ON seo_expectations(url, computed_at);
CREATE TABLE IF NOT EXISTS improvement_checklist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    item TEXT NOT NULL,
    reason TEXT,
    action TEXT,
    gain_clicks REAL,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending | done | rejected | snoozed | superseded | expired
    created_at TEXT,
    done_at TEXT,
    responsible TEXT,
    deadline TEXT,
    rejection_reason TEXT,
    intervention_type TEXT,
    implemented_at TEXT,
    baseline_json TEXT,
    hypothesis_key TEXT,
    evidence_fingerprint TEXT,
    measurement_unavailable INTEGER DEFAULT 0,
    explainable_score REAL,
    score_breakdown_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_checklist_status ON improvement_checklist(status);
CREATE TABLE IF NOT EXISTS internal_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url TEXT NOT NULL,
    target_url TEXT NOT NULL,
    crawled_at TEXT NOT NULL,
    UNIQUE(source_url, target_url)
);
CREATE INDEX IF NOT EXISTS idx_il_target ON internal_links(target_url);
CREATE TABLE IF NOT EXISTS editorial_inventory (
    url TEXT PRIMARY KEY,
    title TEXT,
    h1 TEXT,
    h2s_json TEXT,
    body_text TEXT,
    content_hash TEXT,
    canonical TEXT,
    is_noindex INTEGER NOT NULL DEFAULT 0,
    status_code INTEGER,
    crawled_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_editorial_inventory_crawled ON editorial_inventory(crawled_at);
CREATE TABLE IF NOT EXISTS query_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    url TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    clicks REAL,
    impressions REAL,
    ctr REAL,
    position REAL,
    intent TEXT,
    UNIQUE(query, url, window_start)
);
CREATE INDEX IF NOT EXISTS idx_qp_query ON query_pages(query, window_start);
CREATE TABLE IF NOT EXISTS content_briefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    title TEXT,
    intent TEXT,
    queries_json TEXT,
    gaps_json TEXT,
    action TEXT,
    priority REAL,
    status TEXT NOT NULL DEFAULT 'proposed',   -- proposed | approved | rejected | done
    created_at TEXT,
    UNIQUE(url)
);
CREATE TABLE IF NOT EXISTS editorial_backlog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pauta_type TEXT NOT NULL,
    title TEXT NOT NULL,
    intent TEXT,
    evidence TEXT,
    related_urls_json TEXT,
    scope TEXT,
    duplication_risk TEXT,
    score REAL,
    status TEXT NOT NULL DEFAULT 'proposed',   -- proposed|approved|rejected|published|measured|snoozed|superseded|expired
    created_at TEXT,
    published_url TEXT,
    baseline_json TEXT,
    responsible TEXT,
    deadline TEXT,
    rejection_reason TEXT
);
CREATE TABLE IF NOT EXISTS interlink_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url TEXT NOT NULL,
    target_url TEXT NOT NULL,
    reason TEXT,
    anchor TEXT,
    status TEXT NOT NULL DEFAULT 'proposed',
    created_at TEXT,
    UNIQUE(source_url, target_url)
);
CREATE TABLE IF NOT EXISTS editorial_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    backlog_id INTEGER NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    details_json TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ga4_collection_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_scope TEXT NOT NULL,             -- organic_landing | page_engagement
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    status TEXT NOT NULL,                   -- ok | partial | empty | failed
    rows_received INTEGER NOT NULL DEFAULT 0,
    rows_matched INTEGER NOT NULL DEFAULT 0,
    rows_unmatched INTEGER NOT NULL DEFAULT 0,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_ga4_runs_scope ON ga4_collection_runs(source_scope, window_start);
CREATE TABLE IF NOT EXISTS ga4_page_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    source_scope TEXT NOT NULL,             -- organic_landing | page_engagement
    channel TEXT NOT NULL DEFAULT 'Organic Search',
    sessions REAL,
    engaged_sessions REAL,
    engagement_rate REAL,
    engagement_time REAL,
    key_events REAL,
    measurement_status TEXT NOT NULL,       -- available | missing | invalid | partial
    collected_at TEXT NOT NULL,
    UNIQUE(url, window_start, window_end, source_scope, channel)
);
CREATE INDEX IF NOT EXISTS idx_ga4_url ON ga4_page_metrics(url, window_start);
CREATE TABLE IF NOT EXISTS corpus_documents (
    url TEXT PRIMARY KEY,
    title TEXT,
    seo_title TEXT,
    h1 TEXT,
    body_text TEXT,
    category TEXT,
    tags_json TEXT,
    published_at TEXT,
    modified_at TEXT,
    canonical TEXT,
    is_noindex INTEGER NOT NULL DEFAULT 0,
    status_code INTEGER,
    content_hash TEXT,
    built_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS corpus_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    heading TEXT,
    heading_level INTEGER NOT NULL DEFAULT 0,
    position INTEGER NOT NULL DEFAULT 0,
    text TEXT,
    hash TEXT,
    UNIQUE(url, position)
);
CREATE INDEX IF NOT EXISTS idx_corpus_sections_url ON corpus_sections(url);
CREATE TABLE IF NOT EXISTS corpus_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    entity TEXT NOT NULL,
    entity_type TEXT NOT NULL,       -- person | work | franchise | game | platform | term
    count INTEGER NOT NULL DEFAULT 1,
    UNIQUE(url, entity, entity_type)
);
CREATE INDEX IF NOT EXISTS idx_corpus_entities_entity ON corpus_entities(entity);
CREATE VIRTUAL TABLE IF NOT EXISTS corpus_fts USING fts5(
    url UNINDEXED,
    title,
    h1,
    body,
    tokenize='porter unicode61'
);
CREATE INDEX IF NOT EXISTS idx_editorial_events_backlog ON editorial_events(backlog_id, created_at);
CREATE TABLE IF NOT EXISTS opportunity_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT NOT NULL,
    opportunity_type TEXT NOT NULL,
    decision TEXT NOT NULL,
    evidence_json TEXT,                -- evidência e scores no momento da sugestão
    candidate_score REAL,
    action_score REAL,
    human_decision TEXT,               -- approved | rejected | snoozed | skipped
    rejection_reason TEXT,
    implemented_action TEXT,           -- o que foi feito (title/expand/refresh…)
    url TEXT,
    baseline_json TEXT,                -- GSC+GA4 no momento da aprovação/implementação
    implemented_at TEXT,
    measured_28d INTEGER NOT NULL DEFAULT 0,
    measured_56d INTEGER NOT NULL DEFAULT 0,
    measured_90d INTEGER NOT NULL DEFAULT 0,
    result_28d_json TEXT,
    result_56d_json TEXT,
    result_90d_json TEXT,
    verdict TEXT,                      -- improved | neutral | worsened | insufficient_data
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outcomes_keyword ON opportunity_outcomes(keyword);
CREATE INDEX IF NOT EXISTS idx_outcomes_verdict ON opportunity_outcomes(verdict);
CREATE TABLE IF NOT EXISTS corpus_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL,               -- running | ok | partial | failed
    total_urls INTEGER NOT NULL DEFAULT 0,
    processed INTEGER NOT NULL DEFAULT 0,
    changed INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    sitemap_total INTEGER NOT NULL DEFAULT 0,   -- tamanho COMPLETO do sitemap
    sitemap_signature TEXT,                     -- hash da lista de URLs (detecta mudança)
    started_at TEXT NOT NULL,
    finished_at TEXT,
    error TEXT
);
CREATE TABLE IF NOT EXISTS corpus_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',     -- pending | in_progress | done | failed
    worker_id TEXT,                             -- dono do lease (processo)
    leased_at TEXT,                             -- quando o lease foi tomado
    lease_version INTEGER NOT NULL DEFAULT 0,   -- fencing token (incrementa a cada claim/recuperação)
    error TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, url)
);
CREATE INDEX IF NOT EXISTS idx_corpus_queue_run ON corpus_queue(run_id, status);
CREATE TABLE IF NOT EXISTS corpus_run_failures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_corpus_failures_run ON corpus_run_failures(run_id);
CREATE INDEX IF NOT EXISTS idx_findings_cycle ON findings(cycle_id);
CREATE INDEX IF NOT EXISTS idx_urls_url ON urls(url);
CREATE INDEX IF NOT EXISTS idx_queue_status ON inspection_queue(status, priority);

-- ===== Control plane: auth, RBAC, sessions =====
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    password_hash TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    is_mfa_enabled INTEGER NOT NULL DEFAULT 0,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_login_at TEXT
);
CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS role_permissions (
    role_id INTEGER NOT NULL REFERENCES roles(id),
    permission_id INTEGER NOT NULL REFERENCES permissions(id),
    PRIMARY KEY (role_id, permission_id)
);
CREATE TABLE IF NOT EXISTS user_roles (
    user_id INTEGER NOT NULL REFERENCES users(id),
    role_id INTEGER NOT NULL REFERENCES roles(id),
    PRIMARY KEY (user_id, role_id)
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,        -- absolute timeout
    idle_expires_at TEXT NOT NULL,   -- idle timeout
    ip_hash TEXT,
    user_agent TEXT,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS mfa_factors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL DEFAULT 'totp',
    secret TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_used_at TEXT
);
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT,
    ip_hash TEXT,
    outcome TEXT NOT NULL,           -- success | failure
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_login_attempts ON login_attempts(email, at);
CREATE TABLE IF NOT EXISTS auth_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT,
    user_id INTEGER,
    event TEXT NOT NULL,             -- LOGIN_SUCCESS, LOGIN_FAILURE, ...
    detail_json TEXT
);

-- ===== Control plane: agent run observability (ADR-0007) =====
CREATE TABLE IF NOT EXISTS agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id INTEGER NOT NULL REFERENCES agents(id),
    status TEXT NOT NULL,            -- queued|running|success|partial|failed|cancelled
    trigger TEXT NOT NULL,           -- schedule|manual|system
    intent TEXT,                     -- comando lógico: technical|sitemap|opportunities|content|url
    mode TEXT,                       -- analyze|safe_fix
    started_by TEXT,                 -- email / 'system' / 'schedule'
    started_at TEXT,
    finished_at TEXT,
    duration_ms INTEGER,
    summary_json TEXT,
    comparison_json TEXT,            -- delta vs run comparável
    urls_analyzed INTEGER NOT NULL DEFAULT 0,
    findings_count INTEGER NOT NULL DEFAULT 0,
    opportunities_count INTEGER NOT NULL DEFAULT 0,
    safe_fixes_count INTEGER NOT NULL DEFAULT 0,
    executed_changes_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT,
    target_url TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_agent_status ON agent_runs(agent_id, status, id);
CREATE TABLE IF NOT EXISTS agent_run_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES agent_runs(id),
    stage TEXT NOT NULL,
    status TEXT NOT NULL,            -- pending|running|success|failed|skipped
    started_at TEXT,
    finished_at TEXT,
    duration_ms INTEGER,
    detail_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_steps_run ON agent_run_steps(run_id);
CREATE TABLE IF NOT EXISTS agent_run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES agent_runs(id),
    ts TEXT NOT NULL,
    event TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'info',  -- info|warning|error
    message TEXT,
    detail_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_run ON agent_run_events(run_id);
"""


class Storage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.executescript(_SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """Add columns to pre-existing databases (CREATE TABLE is a no-op there)."""
        # FTS5 contentless (content='') não devolve os valores no SELECT —
        # recria como FTS5 padrão para o corpus buscar por título/corpo.
        try:
            row = self.conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='corpus_fts'"
            ).fetchone()
            if row and "content='" in (row[0] or ""):
                self.conn.execute("DROP TABLE corpus_fts")
                self.conn.execute(
                    "CREATE VIRTUAL TABLE corpus_fts USING fts5("
                    "url UNINDEXED, title, h1, body, tokenize='porter unicode61')"
                )
        except Exception:
            pass
        additions = {
            "editorial_backlog": [
                ("responsible", "TEXT"), ("deadline", "TEXT"),
                ("rejection_reason", "TEXT"),
            ],
            "improvement_checklist": [
                ("responsible", "TEXT"), ("deadline", "TEXT"),
                ("rejection_reason", "TEXT"), ("intervention_type", "TEXT"),
                ("implemented_at", "TEXT"), ("baseline_json", "TEXT"),
                ("hypothesis_key", "TEXT"), ("evidence_fingerprint", "TEXT"),
                ("measurement_unavailable", "INTEGER DEFAULT 0"),
                ("explainable_score", "REAL"), ("score_breakdown_json", "TEXT"),
            ],
            "interlink_suggestions": [
                ("responsible", "TEXT"), ("deadline", "TEXT"),
                ("rejection_reason", "TEXT"),
                ("hypothesis_key", "TEXT"), ("evidence_fingerprint", "TEXT"),
            ],
            "opportunity_outcomes": [
                ("baseline_json", "TEXT"),
                ("measured_28d", "INTEGER NOT NULL DEFAULT 0"),
                ("measured_56d", "INTEGER NOT NULL DEFAULT 0"),
                ("measured_90d", "INTEGER NOT NULL DEFAULT 0"),
            ],
            "corpus_runs": [
                ("sitemap_total", "INTEGER NOT NULL DEFAULT 0"),
                ("sitemap_signature", "TEXT"),
            ],
            "corpus_queue": [
                ("worker_id", "TEXT"),
                ("leased_at", "TEXT"),
                ("lease_version", "INTEGER NOT NULL DEFAULT 0"),
            ],
            "sessions": [
                ("csrf_token_hash", "TEXT"),
                ("strong_auth_at", "TEXT"),
            ],
            "agent_runs": [
                ("target_url", "TEXT"),
            ],
        }
        editorial_extra = [
            ("responsible", "TEXT"), ("deadline", "TEXT"),
            ("rejection_reason", "TEXT"),
            ("hypothesis_key", "TEXT"), ("evidence_fingerprint", "TEXT"),
        ]
        for column, ddl in editorial_extra:
            existing = {r[1] for r in self.conn.execute(
                "PRAGMA table_info(editorial_backlog)")}
            if column not in existing:
                self.conn.execute(f"ALTER TABLE editorial_backlog ADD COLUMN {column} {ddl}")
        for table, columns in additions.items():
            existing = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            for column, ddl in columns:
                if column not in existing:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    # -- cycles / findings ---------------------------------------------------

    def save_cycle(self, cycle_id: str, started_at: str, finished_at: str, summary: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO cycles (id, started_at, finished_at, summary_json) VALUES (?, ?, ?, ?)",
            (cycle_id, started_at, finished_at, json.dumps(summary, ensure_ascii=False)),
        )
        self.conn.commit()

    def save_findings(self, cycle_id: str, findings: list[dict[str, Any]], created_at: str) -> None:
        self.conn.executemany(
            "INSERT INTO findings (cycle_id, rule_id, url, severity, detail_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    cycle_id,
                    f.get("rule_id"),
                    f.get("url", ""),
                    f.get("severity", "info"),
                    json.dumps(f, ensure_ascii=False),
                    created_at,
                )
                for f in findings
            ],
        )
        self.conn.commit()

    # -- audit ---------------------------------------------------------------

    def log_audit(self, actor: str, action_type: str, entity: str, before: Any, after: Any) -> None:
        self.conn.execute(
            "INSERT INTO audit_log (ts, actor, action_type, entity, before_json, after_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                _now(),
                actor,
                action_type,
                entity,
                json.dumps(before, ensure_ascii=False, default=str),
                json.dumps(after, ensure_ascii=False, default=str),
            ),
        )
        self.conn.commit()

    # -- actions (Phase 4) ---------------------------------------------------

    def action_executed(self, fingerprint: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM actions WHERE fingerprint = ? AND status = 'executed'", (fingerprint,)
        ).fetchone()
        return row is not None

    def record_action(
        self,
        *,
        cycle_id: str,
        rule_id: str,
        url: str,
        level: str,
        fingerprint: str,
        before: Any,
        after: Any,
        rollback: Any,
        status: str = "executed",
    ) -> None:
        """Register an executed (or UNVERIFIED) action.

        status='unverified' means the write was attempted but post-write REST
        confirmation failed (e.g. rank_math_title not persisted). action_executed()
        only honors 'executed', so an unverified action does NOT block a retry.
        A retry with the SAME fingerprint overwrites the previous unverified row
        (UPSERT) — it must not crash on the UNIQUE fingerprint.
        """
        self.conn.execute(
            "INSERT INTO actions (cycle_id, rule_id, url, level, status, fingerprint, "
            "before_json, after_json, rollback_json, executed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(fingerprint) DO UPDATE SET "
            "cycle_id = excluded.cycle_id, status = excluded.status, "
            "before_json = excluded.before_json, after_json = excluded.after_json, "
            "rollback_json = excluded.rollback_json, executed_at = excluded.executed_at",
            (
                cycle_id, rule_id, url, level, status, fingerprint,
                json.dumps(before, ensure_ascii=False, default=str),
                json.dumps(after, ensure_ascii=False, default=str),
                json.dumps(rollback, ensure_ascii=False, default=str),
                _now(),
            ),
        )
        self.conn.commit()

    # -- inspection queue ----------------------------------------------------

    def enqueue_urls(self, entries: list[dict[str, Any]]) -> int:
        """Queue URLs reusing one row per URL (state-machine on a single row).

        pending -> in_progress -> done|failed -> pending (re-queue reuses the
        row, so (url, status) can never collide on a second failure).
        Returns the number of URLs newly queued (previously not pending).
        """
        queued = 0
        now = _now()
        for entry in entries:
            url = (entry.get("url") or "").strip()
            if not url:
                continue
            priority = int(entry.get("priority", 6))
            source = entry.get("source", "")
            pending = self.conn.execute(
                "SELECT 1 FROM inspection_queue WHERE url = ? AND status = 'pending'", (url,)
            ).fetchone()
            if pending:
                continue
            existing = self.conn.execute(
                "SELECT id FROM inspection_queue WHERE url = ?", (url,)
            ).fetchone()
            if existing:
                # Reuse the row (failed/done -> pending again).
                self.conn.execute(
                    "UPDATE inspection_queue SET status = 'pending', priority = ?, source = ?, "
                    "result_json = NULL, last_inspected_at = NULL WHERE id = ?",
                    (priority, source, existing[0]),
                )
            else:
                self.conn.execute(
                    "INSERT INTO inspection_queue (url, priority, status, source, created_at) "
                    "VALUES (?, ?, 'pending', ?, ?)",
                    (url, priority, source, now),
                )
            queued += 1
        self.conn.commit()
        return queued

    def reset_stuck_in_progress(self) -> int:
        """Crash recovery: in_progress rows from interrupted runs -> pending."""
        cur = self.conn.execute(
            "UPDATE inspection_queue SET status = 'pending' WHERE status = 'in_progress'"
        )
        self.conn.commit()
        return cur.rowcount

    def dequeue_next(self, limit: int = 50) -> list[dict[str, Any]]:
        """Claim the highest-priority pending URLs (priority ASC, FIFO)."""
        rows = self.conn.execute(
            "SELECT id, url, priority, source FROM inspection_queue "
            "WHERE status = 'pending' ORDER BY priority ASC, id ASC LIMIT ?",
            (limit,),
        ).fetchall()
        items = [
            {"id": row[0], "url": row[1], "priority": row[2], "source": row[3]}
            for row in rows
        ]
        if items:
            ids = tuple(item["id"] for item in items)
            placeholders = ",".join("?" * len(ids))
            self.conn.execute(
                f"UPDATE inspection_queue SET status = 'in_progress' WHERE id IN ({placeholders})",
                ids,
            )
            self.conn.commit()
        return items

    def mark_done(self, queue_id: int, result: dict[str, Any]) -> None:
        self.conn.execute(
            "UPDATE inspection_queue SET status = 'done', last_inspected_at = ?, result_json = ? "
            "WHERE id = ?",
            (_now(), json.dumps(result, ensure_ascii=False, default=str), queue_id),
        )
        self.conn.commit()

    def mark_failed(self, queue_id: int, error: str) -> None:
        self.conn.execute(
            "UPDATE inspection_queue SET status = 'failed', attempts = attempts + 1, "
            "last_inspected_at = ?, result_json = ? WHERE id = ?",
            (_now(), json.dumps({"error": error}, ensure_ascii=False), queue_id),
        )
        self.conn.commit()

    def queue_stats(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) FROM inspection_queue GROUP BY status"
        ).fetchall()
        return {row[0]: row[1] for row in rows}

    def pending_snapshot(self, limit: int = 50) -> list[dict[str, Any]]:
        """Top pending entries by priority (for dry-run previews)."""
        rows = self.conn.execute(
            "SELECT id, url, priority, source, created_at FROM inspection_queue "
            "WHERE status = 'pending' ORDER BY priority ASC, id ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {"id": r[0], "url": r[1], "priority": r[2], "source": r[3], "created_at": r[4]}
            for r in rows
        ]

    def last_inspected_at(self, url: str) -> str | None:
        row = self.conn.execute(
            "SELECT last_inspected_at FROM inspection_queue "
            "WHERE url = ? AND status = 'done' ORDER BY last_inspected_at DESC LIMIT 1",
            (url,),
        ).fetchone()
        return row[0] if row else None

    # -- daily budget --------------------------------------------------------

    def budget_used(self, date: str | None = None) -> int:
        date = date or _today()
        row = self.conn.execute(
            "SELECT used FROM inspection_budget WHERE date = ?", (date,)
        ).fetchone()
        return row[0] if row else 0

    def budget_consume(self, amount: int = 1, date: str | None = None) -> int:
        date = date or _today()
        self.conn.execute(
            "INSERT INTO inspection_budget (date, used) VALUES (?, ?) "
            "ON CONFLICT(date) DO UPDATE SET used = used + excluded.used",
            (date, amount),
        )
        self.conn.commit()
        return self.budget_used(date)

    # -- page snapshots (per-page history / before-after) --------------------

    def save_snapshot(
        self,
        *,
        url: str,
        captured_at: str,
        cycle_id: str = "",
        source: str = "manual",
        linked_action: str = "",
        status_code: int | None = None,
        title: str = "",
        meta_description: str = "",
        canonical: str = "",
        meta_robots: str = "",
        h1: str = "",
        word_count: int | None = None,
        content_hash: str = "",
        cwv: dict[str, Any] | None = None,
        gsc: dict[str, Any] | None = None,
    ) -> None:
        self.conn.execute(
            "INSERT INTO page_snapshots (url, captured_at, cycle_id, source, linked_action, "
            "status_code, title, meta_description, canonical, meta_robots, h1, word_count, "
            "content_hash, cwv_json, gsc_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                url, captured_at, cycle_id, source, linked_action,
                status_code, title, meta_description, canonical, meta_robots,
                h1, word_count, content_hash,
                json.dumps(cwv, ensure_ascii=False) if cwv else None,
                json.dumps(gsc, ensure_ascii=False) if gsc else None,
            ),
        )
        self.conn.commit()

    def page_snapshots(self, url: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """Chronological snapshots for one URL (oldest first)."""
        rows = self.conn.execute(
            "SELECT url, captured_at, cycle_id, source, linked_action, status_code, title, "
            "meta_description, canonical, meta_robots, h1, word_count, content_hash, "
            "cwv_json, gsc_json FROM page_snapshots "
            "WHERE url = ? ORDER BY captured_at ASC LIMIT ?",
            (url, limit),
        ).fetchall()
        return [_snapshot_row(row) for row in rows]

    def latest_snapshot(self, url: str) -> dict[str, Any] | None:
        rows = self.page_snapshots(url, limit=1)
        return rows[-1] if rows else None

    def snapshot_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM page_snapshots").fetchone()[0]

    def distinct_snapshot_urls(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(DISTINCT url) FROM page_snapshots"
        ).fetchone()[0]

    # -- SEO expectations (deterministic impact projection) ------------------

    def save_expectation(self, *, url: str, computed_at: str, source: str = "",
                         changed_at: str = "", expectation: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO seo_expectations (url, computed_at, source, changed_at, position, "
            "impressions, clicks, ctr, expected_ctr, expected_clicks, gap_clicks, "
            "conservative_clicks, realistic_clicks, optimistic_clicks) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                url, computed_at, source, changed_at,
                expectation.get("position"),
                expectation.get("impressions"),
                expectation.get("clicks"),
                expectation.get("ctr"),
                expectation.get("expected_ctr"),
                expectation.get("expected_clicks"),
                expectation.get("gap_clicks"),
                expectation.get("conservative_clicks"),
                expectation.get("realistic_clicks"),
                expectation.get("optimistic_clicks"),
            ),
        )
        self.conn.commit()

    def expectations_for(self, url: str, *, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT url, computed_at, source, changed_at, position, impressions, clicks, "
            "ctr, expected_ctr, expected_clicks, gap_clicks, conservative_clicks, "
            "realistic_clicks, optimistic_clicks FROM seo_expectations "
            "WHERE url = ? ORDER BY computed_at DESC LIMIT ?",
            (url, limit),
        ).fetchall()
        return [
            {
                "url": r[0], "computed_at": r[1], "source": r[2], "changed_at": r[3],
                "position": r[4], "impressions": r[5], "clicks": r[6], "ctr": r[7],
                "expected_ctr": r[8], "expected_clicks": r[9], "gap_clicks": r[10],
                "conservative_clicks": r[11], "realistic_clicks": r[12],
                "optimistic_clicks": r[13],
            }
            for r in rows
        ]

    # -- improvement checklist (manual improvement flow) ---------------------

    def save_checklist_item(self, *, url: str, item: str, reason: str, action: str,
                            gain_clicks: float | None,
                            explainable_score: float | None = None,
                            score_breakdown: dict[str, Any] | None = None) -> bool:
        """Insert a checklist item with its explainable score.

        Rejection semantics: a rejected hypothesis (same url+item) reopens ONLY
        when the material evidence (reason) changes — same fingerprint blocks.
        A PENDING duplicate is REFRESHED (score/evidence updated) instead of
        keeping the old calculation.
        """
        import json as _json
        hypothesis_key = f"{url}|{item}"
        fp = _evidence_fingerprint(reason)
        rejected = self.conn.execute(
            "SELECT evidence_fingerprint FROM improvement_checklist "
            "WHERE hypothesis_key = ? AND status = 'rejected' ORDER BY id DESC LIMIT 1",
            (hypothesis_key,),
        ).fetchone()
        if rejected and rejected[0] == fp:
            return False  # mesma evidência rejeitada: não volta
        pending = self.conn.execute(
            "SELECT id FROM improvement_checklist WHERE hypothesis_key = ? AND status = 'pending' "
            "ORDER BY id LIMIT 1",
            (hypothesis_key,),
        ).fetchone()
        if pending:
            # Pendente já existe: atualiza score/evidência (cálculo mais recente).
            self.conn.execute(
                "UPDATE improvement_checklist SET reason = ?, action = ?, gain_clicks = ?, "
                "evidence_fingerprint = ?, explainable_score = ?, score_breakdown_json = ? "
                "WHERE id = ?",
                (reason, action, gain_clicks, fp, explainable_score,
                 _json.dumps(score_breakdown, ensure_ascii=False) if score_breakdown else None,
                 pending[0]),
            )
            self.conn.commit()
            return True
        self.conn.execute(
            "INSERT INTO improvement_checklist (url, item, reason, action, gain_clicks, "
            "status, created_at, hypothesis_key, evidence_fingerprint, explainable_score, "
            "score_breakdown_json) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)",
            (url, item, reason, action, gain_clicks, _now(), hypothesis_key, fp,
             explainable_score,
             _json.dumps(score_breakdown, ensure_ascii=False) if score_breakdown else None),
        )
        self.conn.commit()
        return True

    def checklist_stats(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) FROM improvement_checklist GROUP BY status"
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def get_checklist_item(self, checklist_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT id, url, item, reason, action, gain_clicks, status, created_at, done_at, "
            "responsible, deadline, rejection_reason, intervention_type, implemented_at, "
            "baseline_json, measurement_unavailable, explainable_score, score_breakdown_json "
            "FROM improvement_checklist WHERE id = ?",
            (checklist_id,),
        ).fetchone()
        if not row:
            return None
        import json as _json
        return {
            "id": row[0], "url": row[1], "item": row[2], "reason": row[3],
            "action": row[4], "gain_clicks": row[5], "status": row[6],
            "created_at": row[7], "done_at": row[8], "responsible": row[9],
            "deadline": row[10], "rejection_reason": row[11],
            "intervention_type": row[12], "implemented_at": row[13],
            "baseline": _json.loads(row[14]) if row[14] else None,
            "measurement_unavailable": bool(row[15]),
            "explainable_score": row[16],
            "score_breakdown": _json.loads(row[17]) if row[17] else None,
        }

    # -- internal link graph (E0) --------------------------------------------

    def save_internal_links(self, edges: dict[str, list[str]], crawled_at: str) -> int:
        saved = 0
        for source, targets in edges.items():
            for target in targets:
                try:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO internal_links (source_url, target_url, crawled_at) "
                        "VALUES (?, ?, ?)",
                        (source, target, crawled_at),
                    )
                    saved += 1
                except Exception:
                    continue
        self.conn.commit()
        return saved

    def link_graph_stats(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT COUNT(DISTINCT source_url), COUNT(*) FROM internal_links"
        ).fetchone()
        return {"sources": rows[0] or 0, "edges": rows[1] or 0}

    def replace_internal_links(self, edges: dict[str, list[str]], crawled_at: str) -> int:
        """Replace the graph snapshot so removed links do not remain as signals."""
        self.conn.execute("DELETE FROM internal_links")
        saved = self.save_internal_links(edges, crawled_at)
        return saved

    def save_editorial_inventory(self, pages: list[Any], *, crawled_at: str) -> int:
        """Persist the editorial fields needed by briefs and contextual linking."""
        saved = 0
        for page in pages:
            body = getattr(page, "body_text", "") or ""
            content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
            self.conn.execute(
                "INSERT INTO editorial_inventory (url, title, h1, h2s_json, body_text, "
                "content_hash, canonical, is_noindex, status_code, crawled_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(url) DO UPDATE SET title=excluded.title, h1=excluded.h1, "
                "h2s_json=excluded.h2s_json, body_text=excluded.body_text, "
                "content_hash=excluded.content_hash, canonical=excluded.canonical, "
                "is_noindex=excluded.is_noindex, status_code=excluded.status_code, "
                "crawled_at=excluded.crawled_at",
                (page.url, getattr(page, "title", ""), " ".join(getattr(page, "h1", []) or []),
                 json.dumps(getattr(page, "h2s", []) or [], ensure_ascii=False), body, content_hash,
                 getattr(page, "canonical", ""),
                 int("noindex" in (getattr(page, "meta_robots", "") or "").lower()),
                 getattr(page, "status_code", 0), crawled_at),
            )
            saved += 1
        self.conn.commit()
        return saved

    def editorial_contexts(self, urls: list[str] | None = None) -> dict[str, dict[str, Any]]:
        sql = "SELECT url, title, h1, h2s_json, body_text, canonical, is_noindex, status_code FROM editorial_inventory"
        params: list[Any] = []
        if urls:
            sql += " WHERE url IN (" + ", ".join("?" for _ in urls) + ")"
            params.extend(urls)
        contexts: dict[str, dict[str, Any]] = {}
        for row in self.conn.execute(sql, params).fetchall():
            try:
                h2s = json.loads(row[3] or "[]")
            except json.JSONDecodeError:
                h2s = []
            contexts[row[0]] = {"title": row[1] or "", "h1": row[2] or "", "h2s": h2s,
                                "body_text": row[4] or "", "canonical": row[5] or "",
                                "is_noindex": bool(row[6]), "status_code": row[7] or 0}
        return contexts

    # -- demand base: query × page (E1) --------------------------------------

    def save_query_pages(self, rows: list[dict[str, Any]], *, window_start: str,
                         window_end: str) -> int:
        saved = 0
        for row in rows:
            try:
                self.conn.execute(
                    "INSERT OR IGNORE INTO query_pages (query, url, window_start, window_end, "
                    "clicks, impressions, ctr, position, intent) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (row["query"], row["url"], window_start, window_end,
                     row.get("clicks"), row.get("impressions"), row.get("ctr"),
                     row.get("position"), row.get("intent", "")),
                )
                saved += 1
            except Exception:
                continue
        self.conn.commit()
        return saved

    def cannibalization_candidates(self, *, min_impressions: float = 20,
                                   window_start: str | None = None) -> list[dict[str, Any]]:
        """Queries shared by 2+ URLs in ONE window (latest by default)."""
        ws = window_start or self.latest_window_start()
        if not ws:
            return []
        rows = self.conn.execute(
            "SELECT query, COUNT(DISTINCT url) AS urls, SUM(impressions) AS impressions "
            "FROM query_pages WHERE impressions >= ? AND window_start = ? "
            "GROUP BY query HAVING urls >= 2 ORDER BY impressions DESC LIMIT 50",
            (min_impressions, ws),
        ).fetchall()
        return [
            {"query": r[0], "urls": r[1], "total_impressions": r[2]} for r in rows
        ]

    def top_pages_for_brief(self, *, limit: int = 50) -> list[tuple[str, float]]:
        """URLs with the most accumulated impressions in the LATEST window only."""
        latest = self.latest_window_start()
        if not latest:
            return []
        rows = self.conn.execute(
            "SELECT url, SUM(impressions) AS impressions FROM query_pages "
            "WHERE window_start = ? GROUP BY url ORDER BY impressions DESC LIMIT ?",
            (latest, limit),
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def latest_window_start(self) -> str | None:
        row = self.conn.execute("SELECT MAX(window_start) FROM query_pages").fetchone()
        return row[0] if row and row[0] else None

    def url_demand(self, url: str, *, window_start: str | None = None) -> dict[str, Any]:
        """Aggregate demand of ONE URL in ONE window (latest by default):
        SUM impressions/clicks + impressions-weighted position. Same base as
        content-brief/rescore, so backfill matches the original scoring.

        NOTE (filtro de persistência): query_pages só contém queries que a
        coleta `demand --store` salvou — queries com impressões abaixo de
        `demand --min-impressions` (default 10) ficam de fora. Ou seja, este
        agregado é fiel ao GSC até o limite do filtro de persistência, não a
        soma incondicional do GSC page_metrics."""
        ws = window_start or self.latest_window_start()
        if not ws:
            return {"impressions": 0.0, "clicks": 0.0, "position": None, "has_queries": False}
        row = self.conn.execute(
            "SELECT SUM(impressions), SUM(clicks), "
            "SUM(position * impressions) / SUM(impressions) "
            "FROM query_pages WHERE url = ? AND window_start = ?",
            (url, ws),
        ).fetchone()
        if not row or not row[0]:
            return {"impressions": 0.0, "clicks": 0.0, "position": None, "has_queries": False}
        return {
            "impressions": float(row[0]),
            "clicks": float(row[1] or 0),
            "position": round(row[2], 1) if row[2] else None,
            "has_queries": True,
        }

    def top_demand(self, *, min_impressions: float = 50, limit: int = 50,
                   window_start: str | None = None) -> list[dict[str, Any]]:
        """Top queries in ONE window (latest by default), impressions-weighted
        position — avoids inflating by summing across windows."""
        ws = window_start or self.latest_window_start()
        if not ws:
            return []
        rows = self.conn.execute(
            "SELECT query, intent, SUM(impressions) AS impressions, SUM(clicks) AS clicks, "
            "SUM(position * impressions) / SUM(impressions) AS wposition "
            "FROM query_pages WHERE window_start = ? AND impressions >= ? "
            "GROUP BY query, intent ORDER BY impressions DESC LIMIT ?",
            (ws, min_impressions, limit),
        ).fetchall()
        return [
            {"query": r[0], "intent": r[1], "impressions": r[2], "clicks": r[3],
             "position": round(r[4], 1) if r[4] else None}
            for r in rows
        ]

    def demand_trend(self, query: str, *, window_a: str, window_b: str) -> dict[str, Any]:
        """Compare the same query across two windows (trend/stability)."""
        def _agg(window: str) -> dict[str, Any]:
            row = self.conn.execute(
                "SELECT SUM(impressions), SUM(clicks), "
                "SUM(position * impressions) / SUM(impressions) "
                "FROM query_pages WHERE query = ? AND window_start = ?",
                (query, window),
            ).fetchone()
            if not row or not row[0]:
                return {"impressions": 0.0, "clicks": 0.0, "position": None}
            return {"impressions": float(row[0]), "clicks": float(row[1] or 0),
                    "position": round(row[2], 1) if row[2] else None}

        a = _agg(window_a)
        b = _agg(window_b)
        delta_pct = None
        if a["impressions"]:
            delta_pct = round((b["impressions"] - a["impressions"]) / a["impressions"] * 100, 1)
        trend = "stable"
        if delta_pct is not None:
            if delta_pct <= -30:
                trend = "declining"
            elif delta_pct >= 30:
                trend = "growing"
        return {
            "query": query,
            "window_a": window_a, "window_b": window_b,
            "impressions_a": a["impressions"], "impressions_b": b["impressions"],
            "clicks_a": a["clicks"], "clicks_b": b["clicks"],
            "position_a": a["position"], "position_b": b["position"],
            "delta_pct": delta_pct, "trend": trend,
        }

    def demand_windows(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT window_start FROM query_pages ORDER BY window_start"
        ).fetchall()
        return [r[0] for r in rows]

    # -- GA4 (A1: histórico persistido) --------------------------------------

    def save_ga4_collection_run(self, *, source_scope: str, window_start: str,
                                window_end: str, status: str, rows_received: int,
                                rows_matched: int, rows_unmatched: int,
                                error: str = "") -> None:
        self.conn.execute(
            "INSERT INTO ga4_collection_runs (source_scope, window_start, window_end, "
            "collected_at, status, rows_received, rows_matched, rows_unmatched, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (source_scope, window_start, window_end, _now(), status,
             rows_received, rows_matched, rows_unmatched, error),
        )
        self.conn.commit()

    def save_ga4_page_metrics(self, rows: list[dict[str, Any]], *,
                              window_start: str, window_end: str,
                              source_scope: str,
                              channel: str = "Organic Search") -> int:
        """Upsert: mesma URL+janela+scope+channel sobrescreve (janela fechada)."""
        saved = 0
        for row in rows:
            try:
                self.conn.execute(
                    "INSERT INTO ga4_page_metrics (url, window_start, window_end, "
                    "source_scope, channel, sessions, engaged_sessions, "
                    "engagement_rate, engagement_time, key_events, "
                    "measurement_status, collected_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(url, window_start, window_end, source_scope, channel) "
                    "DO UPDATE SET sessions = excluded.sessions, "
                    "engaged_sessions = excluded.engaged_sessions, "
                    "engagement_rate = excluded.engagement_rate, "
                    "engagement_time = excluded.engagement_time, "
                    "key_events = excluded.key_events, "
                    "measurement_status = excluded.measurement_status, "
                    "collected_at = excluded.collected_at",
                    (row["url"], window_start, window_end, source_scope, channel,
                     row.get("sessions"), row.get("engaged_sessions"),
                     row.get("engagement_rate"), row.get("engagement_time"),
                     row.get("key_events"), row.get("measurement_status", "missing"),
                     _now()),
                )
                saved += 1
            except Exception:
                continue
        self.conn.commit()
        return saved

    def latest_ga4_window(self, *, source_scope: str = "organic_landing") -> str | None:
        row = self.conn.execute(
            "SELECT MAX(window_start) FROM ga4_page_metrics WHERE source_scope = ?",
            (source_scope,),
        ).fetchone()
        return row[0] if row and row[0] else None

    def ga4_windows(self, *, source_scope: str = "organic_landing") -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT window_start FROM ga4_page_metrics "
            "WHERE source_scope = ? ORDER BY window_start",
            (source_scope,),
        ).fetchall()
        return [r[0] for r in rows]

    def ga4_metrics_for_url(self, url: str, *,
                            source_scope: str = "organic_landing",
                            window_start: str | None = None) -> dict[str, Any] | None:
        """Métricas GA4 de UMA URL em UMA janela (mais recente por padrão).
        NUNCA soma janelas nem mistura canais — retorna None quando não há
        dado (ausência ≠ zero)."""
        ws = window_start or self.latest_ga4_window(source_scope=source_scope)
        if not ws:
            return None
        row = self.conn.execute(
            "SELECT url, window_start, window_end, source_scope, channel, sessions, "
            "engaged_sessions, engagement_rate, engagement_time, key_events, "
            "measurement_status, collected_at FROM ga4_page_metrics "
            "WHERE url = ? AND source_scope = ? AND window_start = ?",
            (url, source_scope, ws),
        ).fetchone()
        if not row:
            return None
        return {
            "url": row[0], "window_start": row[1], "window_end": row[2],
            "source_scope": row[3], "channel": row[4],
            "sessions": row[5], "engaged_sessions": row[6],
            "engagement_rate": row[7], "engagement_time": row[8],
            "key_events": row[9], "measurement_status": row[10],
            "collected_at": row[11],
        }

    def ga4_trend_for_url(self, url: str, *, window_a: str, window_b: str,
                          source_scope: str = "organic_landing") -> dict[str, Any]:
        """Compara a MESMA URL entre duas janelas equivalentes (mesmo scope)."""
        def _agg(window: str) -> dict[str, Any]:
            row = self.conn.execute(
                "SELECT sessions, engaged_sessions, engagement_rate "
                "FROM ga4_page_metrics WHERE url = ? AND source_scope = ? "
                "AND window_start = ?",
                (url, source_scope, window),
            ).fetchone()
            if not row:
                return {"sessions": None, "engaged_sessions": None,
                        "engagement_rate": None}
            return {"sessions": row[0], "engaged_sessions": row[1],
                    "engagement_rate": row[2]}

        a = _agg(window_a)
        b = _agg(window_b)
        delta_pct = None
        if a["sessions"] not in (None, 0):
            delta_pct = round(
                ((b["sessions"] or 0) - a["sessions"]) / a["sessions"] * 100, 1
            )
        trend = "stable"
        if delta_pct is not None:
            if delta_pct <= -30:
                trend = "declining"
            elif delta_pct >= 30:
                trend = "growing"
        return {
            "url": url, "window_a": window_a, "window_b": window_b,
            "source_scope": source_scope,
            "sessions_a": a["sessions"], "sessions_b": b["sessions"],
            "engaged_sessions_a": a["engaged_sessions"],
            "engaged_sessions_b": b["engaged_sessions"],
            "engagement_rate_a": a["engagement_rate"],
            "engagement_rate_b": b["engagement_rate"],
            "delta_pct": delta_pct, "trend": trend,
        }

    def ga4_collection_health(self) -> dict[str, Any]:
        """Cobertura e saúde das coletas por scope (últimas 5 execuções)."""
        health: dict[str, Any] = {}
        for scope in ("organic_landing", "page_engagement"):
            runs = self.conn.execute(
                "SELECT source_scope, window_start, window_end, status, "
                "rows_received, rows_matched, rows_unmatched, error "
                "FROM ga4_collection_runs WHERE source_scope = ? "
                "ORDER BY window_start DESC LIMIT 5",
                (scope,),
            ).fetchall()
            health[scope] = [
                {"window_start": r[1], "window_end": r[2], "status": r[3],
                 "rows_received": r[4], "rows_matched": r[5],
                 "rows_unmatched": r[6], "error": r[7]}
                for r in runs
            ]
        return health

    # -- corpus (M2: memória editorial) --------------------------------------

    def save_corpus_document(self, *, url: str, title: str, h1: str, body_text: str,
                             canonical: str = "", is_noindex: int = 0,
                             status_code: int = 0, content_hash: str = "",
                             built_at: str = "", commit: bool = True) -> None:
        self.conn.execute(
            "INSERT INTO corpus_documents (url, title, h1, body_text, canonical, "
            "is_noindex, status_code, content_hash, built_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(url) DO UPDATE SET title=excluded.title, h1=excluded.h1, "
            "body_text=excluded.body_text, canonical=excluded.canonical, "
            "is_noindex=excluded.is_noindex, status_code=excluded.status_code, "
            "content_hash=excluded.content_hash, built_at=excluded.built_at",
            (url, title, h1, body_text, canonical, is_noindex, status_code,
             content_hash, built_at),
        )
        if commit:
            self.conn.commit()

    def replace_corpus_sections(self, url: str, sections: list[dict[str, Any]],
                                commit: bool = True) -> None:
        self.conn.execute("DELETE FROM corpus_sections WHERE url = ?", (url,))
        for sec in sections:
            self.conn.execute(
                "INSERT INTO corpus_sections (url, heading, heading_level, position, "
                "text, hash) VALUES (?, ?, ?, ?, ?, ?)",
                (url, sec.get("heading", ""), sec.get("heading_level", 2),
                 sec.get("position", 0), sec.get("text", ""), sec.get("hash", "")),
            )
        if commit:
            self.conn.commit()

    def replace_corpus_entities(self, url: str, entities: list[dict[str, Any]],
                                commit: bool = True) -> None:
        self.conn.execute("DELETE FROM corpus_entities WHERE url = ?", (url,))
        for ent in entities:
            self.conn.execute(
                "INSERT INTO corpus_entities (url, entity, entity_type, count) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(url, entity, entity_type) DO UPDATE SET count=excluded.count",
                (url, ent.get("entity", ""), ent.get("entity_type", "term"),
                 ent.get("count", 1)),
            )
        if commit:
            self.conn.commit()

    def index_corpus_document(self, url: str, title: str, h1: str, body: str,
                              commit: bool = True) -> None:
        # FTS5 contentless: DELETE + INSERT reindexa a doc.
        self.conn.execute("DELETE FROM corpus_fts WHERE url = ?", (url,))
        self.conn.execute(
            "INSERT INTO corpus_fts (url, title, h1, body) VALUES (?, ?, ?, ?)",
            (url, title, h1, body),
        )
        if commit:
            self.conn.commit()

    def corpus_search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """BM25 search sobre documentos (title+h1+body) — retorna doc + snippet."""
        q = query.strip()
        if not q:
            return []
        try:
            rows = self.conn.execute(
                "SELECT url, title, snippet(corpus_fts, 3, '[', ']', '…', 24) AS snip, "
                "bm25(corpus_fts) AS score FROM corpus_fts WHERE corpus_fts MATCH ? "
                "ORDER BY score LIMIT ?",
                (q, limit),
            ).fetchall()
        except Exception:
            return []
        return [{"url": r[0], "title": r[1], "snippet": r[2] or "", "bm25": r[3]}
                for r in rows]

    def corpus_sections_for_url(self, url: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT heading, heading_level, position, text FROM corpus_sections "
            "WHERE url = ? ORDER BY position",
            (url,),
        ).fetchall()
        return [{"heading": r[0], "heading_level": r[1], "position": r[2],
                 "text": r[3]} for r in rows]

    def corpus_entities_for_url(self, url: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT entity, entity_type, count FROM corpus_entities "
            "WHERE url = ? ORDER BY count DESC",
            (url,),
        ).fetchall()
        return [{"entity": r[0], "entity_type": r[1], "count": r[2]} for r in rows]

    def corpus_coverage(self, term: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """Cobertura de um termo: documentos + seções + entidades que o contêm."""
        term = term.strip()
        if not term:
            return []
        docs = []
        # busca textual (FTS) + entidade + heading
        try:
            for r in self.conn.execute(
                "SELECT url, title FROM corpus_fts WHERE corpus_fts MATCH ? LIMIT ?",
                (term, limit),
            ).fetchall():
                docs.append({"url": r[0], "title": r[1] or "",
                             "via": "fts", "sections": []})
        except Exception:
            pass
        seen = {d["url"] for d in docs}
        for r in self.conn.execute(
            "SELECT DISTINCT url FROM corpus_entities WHERE entity LIKE ? LIMIT ?",
            (f"%{term}%", limit),
        ).fetchall():
            if r[0] not in seen:
                docs.append({"url": r[0], "title": "", "via": "entity", "sections": []})
                seen.add(r[0])
        # seções específicas que cobrem o termo (matching por heading/texto) —
        # uma seção que casa CRIA a entrada mesmo sem match FTS/entidade.
        for r in self.conn.execute(
            "SELECT s.url, s.heading, s.position FROM corpus_sections s "
            "WHERE s.heading LIKE ? OR s.text LIKE ? LIMIT ?",
            (f"%{term}%", f"%{term}%", limit),
        ).fetchall():
            entry = next((d for d in docs if d["url"] == r[0]), None)
            if entry is None:
                entry = {"url": r[0], "title": "", "via": "section",
                         "sections": []}
                docs.append(entry)
            entry["sections"].append({"heading": r[1] or "", "position": r[2]})
        return docs

    def corpus_stats(self) -> dict[str, Any]:
        docs = self.conn.execute("SELECT COUNT(*) FROM corpus_documents").fetchone()[0]
        secs = self.conn.execute("SELECT COUNT(*) FROM corpus_sections").fetchone()[0]
        ents = self.conn.execute("SELECT COUNT(*) FROM corpus_entities").fetchone()[0]
        fts = 0
        try:
            fts = self.conn.execute("SELECT COUNT(*) FROM corpus_fts").fetchone()[0]
        except Exception:
            pass
        return {"documents": docs, "sections": secs, "entities": ents, "fts_docs": fts}

    # -- corpus runs: checkpoint, failures e cobertura (endurecimento M2) -----

    def start_corpus_run(self, *, total_urls: int, sitemap_total: int = 0,
                         sitemap_signature: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO corpus_runs (status, total_urls, sitemap_total, "
            "sitemap_signature, started_at) "
            "VALUES ('running', ?, ?, ?, ?)",
            (total_urls, sitemap_total, sitemap_signature, _now()),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_corpus_run(self, run_id: int, *, processed: int, changed: int,
                          failed: int) -> None:
        self.conn.execute(
            "UPDATE corpus_runs SET processed = ?, changed = ?, failed = ? WHERE id = ?",
            (processed, changed, failed, run_id),
        )
        self.conn.commit()

    def finish_corpus_run(self, run_id: int, *, status: str, error: str = "") -> None:
        self.conn.execute(
            "UPDATE corpus_runs SET status = ?, finished_at = ?, error = ? WHERE id = ?",
            (status, _now(), error, run_id),
        )
        self.conn.commit()

    def record_corpus_failure(self, run_id: int, url: str, error: str) -> None:
        self.conn.execute(
            "INSERT INTO corpus_run_failures (run_id, url, error, created_at) "
            "VALUES (?, ?, ?, ?)",
            (run_id, url, error, _now()),
        )
        self.conn.commit()

    # -- fila de URLs por run (retomada real, não prefixo do sitemap) --------

    def corpus_enqueue_urls(self, run_id: int, urls: list[str]) -> int:
        """Adiciona URLs à fila do run como pending (idempotente por run+url)."""
        added = 0
        for url in urls:
            try:
                self.conn.execute(
                    "INSERT OR IGNORE INTO corpus_queue (run_id, url, status, "
                    "created_at) VALUES (?, ?, 'pending', ?)",
                    (run_id, url, _now()),
                )
                added += 1
            except Exception:
                continue
        self.conn.commit()
        return added

    def corpus_claim_pending(self, run_id: int, *, limit: int = 50,
                             worker_id: str = "") -> list[str]:
        """Claim ATOMÁTICO: marca o lote como in_progress no mesmo UPDATE
        (RETURNING), registrando o worker (dono), o timestamp e o FENCING
        TOKEN (lease_version) do lease.

        O TTL é aplicado APENAS na recuperação (corpus_recover_expired_leases).
        Cada claim/recuperação incrementa lease_version — a versão é a prova de
        posse: um worker antigo com versão defasada não pode gravar nem
        concluir a URL.
        """
        import datetime as _dt
        now = _dt.datetime.now(_dt.timezone.utc).isoformat()
        rows = self.conn.execute(
            "UPDATE corpus_queue SET status = 'in_progress', worker_id = ?, "
            "leased_at = ?, lease_version = lease_version + 1 "
            "WHERE id IN (SELECT id FROM corpus_queue WHERE run_id = ? "
            "AND status = 'pending' ORDER BY id LIMIT ?) "
            "RETURNING url",
            (worker_id, now, run_id, limit),
        ).fetchall()
        self.conn.commit()
        return [r[0] for r in rows]

    def corpus_claim_pending_with_token(self, run_id: int, *, limit: int = 50,
                                        worker_id: str = ""
                                        ) -> list[dict[str, Any]]:
        """Como corpus_claim_pending, mas retorna {url, lease_version} — o
        fencing token que o worker deve guardar e apresentar em owns_lease /
        mark_done / mark_failed."""
        import datetime as _dt
        now = _dt.datetime.now(_dt.timezone.utc).isoformat()
        rows = self.conn.execute(
            "UPDATE corpus_queue SET status = 'in_progress', worker_id = ?, "
            "leased_at = ?, lease_version = lease_version + 1 "
            "WHERE id IN (SELECT id FROM corpus_queue WHERE run_id = ? "
            "AND status = 'pending' ORDER BY id LIMIT ?) "
            "RETURNING url, lease_version",
            (worker_id, now, run_id, limit),
        ).fetchall()
        self.conn.commit()
        return [{"url": r[0], "lease_version": r[1]} for r in rows]

    def corpus_owns_lease(self, run_id: int, url: str, worker_id: str,
                          lease_version: int) -> bool:
        """Fencing check: o worker AINDA é o dono desta URL com a versão de
        lease que lhe foi concedida? False = o lease foi recuperado por outro
        (versão incrementada) e este worker não deve gravar nem concluir."""
        row = self.conn.execute(
            "SELECT 1 FROM corpus_queue WHERE run_id = ? AND url = ? "
            "AND worker_id = ? AND lease_version = ? AND status = 'in_progress'",
            (run_id, url, worker_id, lease_version),
        ).fetchone()
        return row is not None

    def corpus_renew_lease(self, run_id: int, urls: list[str],
                           worker_id: str) -> int:
        """HEARTBEAT: renova o leased_at dos leases que AINDA pertencem ao
        worker. Só atualiza linhas cujo worker_id == dono — nunca estende o
        lease de um lote que outro worker já recuperou (expirado)."""
        if not urls:
            return 0
        import datetime as _dt
        now = _dt.datetime.now(_dt.timezone.utc).isoformat()
        placeholders = ", ".join("?" for _ in urls)
        cur = self.conn.execute(
            f"UPDATE corpus_queue SET leased_at = ? "
            f"WHERE run_id = ? AND worker_id = ? "
            f"AND status = 'in_progress' AND url IN ({placeholders})",
            (now, run_id, worker_id, *urls),
        )
        self.conn.commit()
        return cur.rowcount

    def corpus_recover_expired_leases(self, run_id: int, *,
                                      ttl_seconds: int = 3600,
                                      exclude_worker: str = "") -> int:
        """Recupera APENAS leases expirados (TTL) para pending.

        NÃO toca leases vivos de outro processo — a exclusão mútua entre
        workers concorrentes é preservada. Um lease expirado (processo morto)
        volta a pending para ser retomado; lease_version é incrementado, o que
        INVALIDA o fencing token do worker antigo (ele não poderá mais gravar).
        """
        import datetime as _dt
        cutoff = (_dt.datetime.now(_dt.timezone.utc)
                  - _dt.timedelta(seconds=ttl_seconds)).isoformat()
        sql = ("UPDATE corpus_queue SET status = 'pending', worker_id = NULL, "
               "leased_at = NULL, lease_version = lease_version + 1 "
               "WHERE run_id = ? AND status = 'in_progress' AND leased_at < ?")
        params: list[Any] = [run_id, cutoff]
        if exclude_worker:
            sql += " AND COALESCE(worker_id, '') != ?"
            params.append(exclude_worker)
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur.rowcount

    def corpus_mark_done(self, run_id: int, url: str, worker_id: str,
                         lease_version: int,
                         lease_seconds: int | None = None) -> bool:
        """Marca done SOMENTE se o worker ainda é o dono com o FENCING TOKEN
        correto e (se lease_seconds dado) o lease não expirou por relógio.
        worker_id e lease_version são OBRIGATÓRIOS — chamada sem dono/token
        ou com token/lease defasado retorna False e não registra."""
        if not worker_id or lease_version is None:
            return False
        import datetime as _dt
        sql = ("UPDATE corpus_queue SET status = 'done', worker_id = NULL, "
               "leased_at = NULL WHERE run_id = ? AND url = ? AND worker_id = ? "
               "AND lease_version = ? AND status = 'in_progress'")
        params: list[Any] = [run_id, url, worker_id, lease_version]
        if lease_seconds:
            cutoff = (_dt.datetime.now(_dt.timezone.utc)
                      - _dt.timedelta(seconds=lease_seconds)).isoformat()
            sql += " AND leased_at >= ?"
            params.append(cutoff)
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur.rowcount > 0

    def corpus_mark_failed(self, run_id: int, url: str, error: str,
                           worker_id: str, lease_version: int,
                           lease_seconds: int | None = None) -> bool:
        """Marca failed SOMENTE se o worker ainda é o dono com o token correto
        e (se lease_seconds dado) o lease não expirou por relógio — o caminho
        de FALHA respeita o TTL por relógio igual ao caminho de escrita."""
        if not worker_id or lease_version is None:
            return False
        import datetime as _dt
        sql = ("UPDATE corpus_queue SET status = 'failed', worker_id = NULL, "
               "leased_at = NULL, error = ? WHERE run_id = ? AND url = ? "
               "AND worker_id = ? AND lease_version = ? AND status = 'in_progress'")
        params: list[Any] = [error, run_id, url, worker_id, lease_version]
        if lease_seconds:
            cutoff = (_dt.datetime.now(_dt.timezone.utc)
                      - _dt.timedelta(seconds=lease_seconds)).isoformat()
            sql += " AND leased_at >= ?"
            params.append(cutoff)
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur.rowcount > 0

    def corpus_commit_page(self, *, run_id: int, url: str, worker_id: str,
                           lease_version: int, built_at: str,
                           page: Any, lease_seconds: int | None = None,
                           before_commit: Any = None) -> str:
        """Operação TRANSACIONAL ÚNICA: escreve documento+seções+entidades+FTS
        e marca done em UM commit, sob BEGIN IMMEDIATE (escrita exclusiva).

        A janela entre 'validar posse' e 'gravar' é ELIMINADA: a revalidação
        (worker_id + lease_version + status='in_progress') acontece DENTRO da
        transação exclusiva, imediatamente antes das escritas. Se B recuperou
        o lease (token incrementado), a revalidação falha, tudo é revertido
        (ROLLBACK) e NADA é gravado.

        SEMÂNTICA DO TTL: quando ``lease_seconds`` é fornecido, a revalidação
        também exige ``leased_at >= agora - lease_seconds`` — o TTL vira
        revogação POR RELÓGIO (uma escrita não é aceita sequer após o horário
        de expiração, mesmo que nenhum outro worker tenha executado a
        recuperação). Sem o parâmetro, a revogação só ocorre quando outro
        worker executa corpus_recover_expired_leases (serializável: quem ganha
        a transação exclusiva decide). O caminho CLI passa sempre o TTL
        configurado.

        GATE FINAL DE TTL: o TTL é revalidado DUAS vezes. (1) no início da
        transação (revalidação acima) e (2) IMEDIATAMENTE antes do
        UPDATE...done, com o cutoff RECALCULADO nesse instante e embutido no
        próprio UPDATE (predicado atômico). Se a transação cruzar o instante
        de expiração durante extração/escritas/hook — o relógio anda mesmo com
        o lock de escrita exclusivo — o UPDATE final afeta 0 linhas e o
        método executa ROLLBACK: as escritas já feitas (documento, seções,
        entidades, FTS) seguem NÃO persistidas por estarem na mesma
        transação.

        Retorna: 'written' | 'unchanged' (hash igual, só marca done) |
        'not_owned' (posse perdida ou expirada — zero alterações).

        ``before_commit`` é um hook opcional chamado DENTRO da transação
        (após as escritas e ANTES do gate final de TTL/UPDATE...done) — usado
        por testes de concorrência para pausar ou envelhecer o lease no ponto
        crítico.
        """
        import datetime as _dt
        import hashlib
        # Nota: extract_sections/extract_entities vivem em corpus.builder;
        # são importados abaixo no ponto de uso (evita ciclo de import).
        body = getattr(page, "body_text", "") or ""
        content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        h1 = " ".join(getattr(page, "h1", []) or [])
        title = getattr(page, "title", "") or ""
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            # revalidação DENTRO da escrita exclusiva (fecha a janela):
            # dono + token + status + (opcional) não expirado por relógio.
            sql = ("SELECT 1 FROM corpus_queue WHERE run_id = ? AND url = ? "
                   "AND worker_id = ? AND lease_version = ? "
                   "AND status = 'in_progress'")
            params: list[Any] = [run_id, url, worker_id, lease_version]
            if lease_seconds:
                cutoff = (_dt.datetime.now(_dt.timezone.utc)
                          - _dt.timedelta(seconds=lease_seconds)).isoformat()
                sql += " AND leased_at >= ?"
                params.append(cutoff)
            owned = self.conn.execute(sql, params).fetchone()
            if not owned:
                self.conn.rollback()
                return "not_owned"

            def _finalize_done() -> bool:
                """Gate FINAL de TTL: o relógio andou desde a revalidação
                inicial (extração, escritas, hook). Revalida AGORA, com cutoff
                recalculado, no MESMO UPDATE que marca done. Se o lease
                expirou nesse intervalo, o UPDATE afeta 0 linhas -> o chamador
                executa ROLLBACK e nada persiste."""
                u_params: list[Any] = [run_id, url, worker_id, lease_version]
                ttl_clause = ""
                if lease_seconds:
                    cutoff = (_dt.datetime.now(_dt.timezone.utc)
                              - _dt.timedelta(seconds=lease_seconds)).isoformat()
                    ttl_clause = " AND leased_at >= ?"
                    u_params.append(cutoff)
                cur = self.conn.execute(
                    "UPDATE corpus_queue SET status = 'done', worker_id = NULL, "
                    "leased_at = NULL WHERE run_id = ? AND url = ? "
                    "AND worker_id = ? AND lease_version = ?" + ttl_clause,
                    u_params,
                )
                return cur.rowcount == 1

            row = self.conn.execute(
                "SELECT content_hash FROM corpus_documents WHERE url = ?", (url,)
            ).fetchone()
            if row and row[0] == content_hash:
                # inalterado: só marca done, sem reindexar
                if before_commit is not None:
                    before_commit()  # hook de teste antes do gate final
                if not _finalize_done():
                    self.conn.rollback()
                    return "not_owned"
                self.conn.commit()
                return "unchanged"
            # escritas SEM commit interno (a transação faz o commit único)
            self.save_corpus_document(
                url=url, title=title, h1=h1, body_text=body,
                canonical=getattr(page, "canonical", "") or "",
                is_noindex=int("noindex" in (getattr(page, "meta_robots", "") or "").lower()),
                status_code=getattr(page, "status_code", 0),
                content_hash=content_hash, built_at=built_at, commit=False)
            from ..corpus.builder import extract_entities, extract_sections
            secs = extract_sections(getattr(page, "html", "") or "", url)
            self.replace_corpus_sections(url, secs, commit=False)
            ents = extract_entities(title, h1, body)
            self.replace_corpus_entities(url, ents, commit=False)
            self.index_corpus_document(url, title, h1, body, commit=False)
            if before_commit is not None:
                before_commit()  # hook de teste antes do gate final
            if not _finalize_done():
                self.conn.rollback()
                return "not_owned"
            self.conn.commit()
            return "written"
        except Exception:
            try:
                self.conn.rollback()
            except Exception:
                pass
            raise

    def corpus_queue_counts(self, run_id: int) -> dict[str, int]:
        counts = {"pending": 0, "done": 0, "failed": 0, "in_progress": 0}
        for r in self.conn.execute(
            "SELECT status, COUNT(*) FROM corpus_queue WHERE run_id = ? "
            "GROUP BY status", (run_id,),
        ).fetchall():
            counts[r[0]] = r[1]
        return counts

    def latest_corpus_run(self, *, status: str | None = None) -> dict[str, Any] | None:
        """Último run (running se status='running') com sitemap metadata."""
        sql = ("SELECT id, status, total_urls, processed, changed, failed, "
               "sitemap_total, sitemap_signature, started_at, finished_at, error "
               "FROM corpus_runs")
        params: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY id DESC LIMIT 1"
        row = self.conn.execute(sql, params).fetchone()
        if not row:
            return None
        return {
            "id": row[0], "status": row[1], "total_urls": row[2],
            "processed": row[3], "changed": row[4], "failed": row[5],
            "sitemap_total": row[6] or 0, "sitemap_signature": row[7] or "",
            "started_at": row[8], "finished_at": row[9], "error": row[10] or "",
        }

    def corpus_run_summary(self) -> dict[str, Any]:
        """Últimos runs + falhas (para operar o crawl incremental)."""
        runs = self.conn.execute(
            "SELECT id, status, total_urls, processed, changed, failed, "
            "sitemap_total, sitemap_signature, started_at, finished_at, error "
            "FROM corpus_runs ORDER BY id DESC LIMIT 10"
        ).fetchall()
        last_run_id = runs[0][0] if runs else None
        failures = []
        if last_run_id:
            failures = [
                {"url": r[0], "error": r[1]} for r in self.conn.execute(
                    "SELECT url, error FROM corpus_run_failures "
                    "WHERE run_id = ? ORDER BY id DESC LIMIT 50",
                    (last_run_id,),
                ).fetchall()
            ]
        return {
            "runs": [
                {"id": r[0], "status": r[1], "total_urls": r[2], "processed": r[3],
                 "changed": r[4], "failed": r[5], "sitemap_total": r[6] or 0,
                 "sitemap_signature": r[7] or "", "started_at": r[8],
                 "finished_at": r[9], "error": r[10] or ""}
                for r in runs
            ],
            "last_run_failures": failures,
            "last_run_failure_count": len(failures),
        }

    def corpus_coverage_report(self, sitemap_urls: list[str] | None = None
                               ) -> dict[str, Any]:
        """Cobertura do corpus vs sitemap publicado (endurecimento M2).

        docs_indexados: URLs no corpus_documents;
        no_sitemap: URLs no corpus mas fora do sitemap atual (removidas?);
        sitemap_sem_corpus: URLs do sitemap ainda não indexadas;
        staleness: docs cujo content_hash local DIVERGE do inventory (conteúdo
            mudou e o corpus está desatualizado) — só quando o inventory tem a URL;
        unverifiable: docs no corpus SEM registro no inventory (não dá para
            julgar staleness; indica inventory desatualizado, não conteúdo velho).
        """
        indexed = self.conn.execute(
            "SELECT COUNT(*) FROM corpus_documents").fetchone()[0]
        staleness = self.conn.execute(
            "SELECT COUNT(*) FROM corpus_documents d WHERE EXISTS ("
            "SELECT 1 FROM editorial_inventory i WHERE i.url = d.url "
            "AND i.content_hash != d.content_hash)"
        ).fetchone()[0]
        unverifiable = self.conn.execute(
            "SELECT COUNT(*) FROM corpus_documents d WHERE NOT EXISTS ("
            "SELECT 1 FROM editorial_inventory i WHERE i.url = d.url)"
        ).fetchone()[0]
        report: dict[str, Any] = {
            "indexed_docs": indexed,
            "staleness": staleness,
            "unverifiable_docs": unverifiable,
            "sitemap_total": len(sitemap_urls or []),
        }
        if sitemap_urls:
            corpus_urls = {r[0] for r in self.conn.execute(
                "SELECT url FROM corpus_documents").fetchall()}
            sitemap_set = set(sitemap_urls)
            report["sitemap_without_corpus"] = len(sitemap_set - corpus_urls)
            report["corpus_outside_sitemap"] = len(corpus_urls - sitemap_set)
            report["coverage_pct"] = round(
                (len(sitemap_set & corpus_urls) / len(sitemap_set)) * 100, 1
            ) if sitemap_set else 0.0
        return report

    def corpus_global_coverage(self) -> dict[str, Any]:
        """Cobertura GLOBAL por INTERSEÇÃO EXATA entre as URLs do sitemap
        daquele run (a fila é o snapshot) e corpus_documents.

        Escolhe o snapshot mais recente ADEQUADO: o último run concluído
        (ok/partial) com fila; se nenhum existe, o run running mais recente.
        `coverage_basis_run_id` deixa EXPLÍCITO qual run serviu de base —
        durante uma execução em andamento, a métrica pode refletir um snapshot
        anterior (histórico), não o crawl em curso.
        """
        last = None
        for status in ("ok", "partial"):
            candidate = self.latest_corpus_run(status=status)
            if candidate and candidate["sitemap_total"]:
                last = candidate
                break
        basis_run = last
        if not basis_run:
            running = self.latest_corpus_run(status="running")
            if running and running["sitemap_total"]:
                basis_run = running
        if not basis_run or not basis_run["sitemap_total"]:
            return {"global_sitemap_total": 0, "global_coverage_pct": None,
                    "coverage_basis_run_id": None,
                    "basis": "nenhum run concluído com sitemap completo registrado"}
        # interseção exata: docs no corpus QUE estão no snapshot do sitemap
        row = self.conn.execute(
            "SELECT COUNT(*) FROM corpus_queue q "
            "JOIN corpus_documents d ON d.url = q.url "
            "WHERE q.run_id = ?",
            (basis_run["id"],),
        ).fetchone()
        in_sitemap = row[0] if row else 0
        total_snapshot = self.conn.execute(
            "SELECT COUNT(*) FROM corpus_queue WHERE run_id = ?",
            (basis_run["id"],),
        ).fetchone()[0]
        pct = round((in_sitemap / total_snapshot) * 100, 1) if total_snapshot else 0.0
        return {
            "global_sitemap_total": total_snapshot,
            "global_docs_in_sitemap": in_sitemap,
            "global_coverage_pct": pct,
            "coverage_basis_run_id": basis_run["id"],
            "coverage_basis_status": basis_run["status"],
            "basis": (f"run {basis_run['id']} ({basis_run['status']}) — "
                      "interseção exata fila×corpus"),
        }


    # -- M8: opportunity outcomes e aprendizado ------------------------------

    def save_opportunity_outcome(self, *, keyword: str, opportunity_type: str,
                                 decision: str, evidence: dict[str, Any] | None = None,
                                 candidate_score: float | None = None,
                                 action_score: float | None = None,
                                 human_decision: str = "",
                                 rejection_reason: str = "",
                                 implemented_action: str = "",
                                 url: str = "",
                                 baseline: dict[str, Any] | None = None,
                                 implemented_at: str = "") -> int:
        import json as _json
        cur = self.conn.execute(
            "INSERT INTO opportunity_outcomes (keyword, opportunity_type, decision, "
            "evidence_json, candidate_score, action_score, human_decision, "
            "rejection_reason, implemented_action, url, baseline_json, "
            "implemented_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (keyword, opportunity_type, decision,
             _json.dumps(evidence, ensure_ascii=False, default=str) if evidence else None,
             candidate_score, action_score, human_decision, rejection_reason,
             implemented_action, url,
             _json.dumps(baseline, ensure_ascii=False, default=str) if baseline else None,
             implemented_at, _now()),
        )
        self.conn.commit()
        return cur.lastrowid

    def set_outcome_baseline(self, outcome_id: int, baseline: dict[str, Any]) -> None:
        import json as _json
        self.conn.execute(
            "UPDATE opportunity_outcomes SET baseline_json = ? WHERE id = ?",
            (_json.dumps(baseline, ensure_ascii=False, default=str), outcome_id),
        )
        self.conn.commit()

    def set_outcome_verdict(self, outcome_id: int, *, verdict: str,
                            days: int | None = None,
                            result: dict[str, Any] | None = None) -> None:
        """Registra o resultado de uma janela (28/56/90) e o verdict.

        ``days`` marca qual janela foi medida (flag measured_{days}d) e grava
        o resultado no campo correspondente. Um outcome já medido em uma janela
        NÃO é re-medido (enforcement de agendamento).
        """
        import json as _json
        if days not in (28, 56, 90):
            raise ValueError("days deve ser 28, 56 ou 90")
        col = f"result_{days}d_json"
        flag = f"measured_{days}d"
        row = self.conn.execute(
            f"SELECT {flag} FROM opportunity_outcomes WHERE id = ?", (outcome_id,)
        ).fetchone()
        if row and row[0]:
            raise ValueError(f"outcome {outcome_id} já medido na janela {days}d")
        self.conn.execute(
            f"UPDATE opportunity_outcomes SET verdict = ?, {col} = ?, {flag} = 1 "
            "WHERE id = ?",
            (verdict,
             _json.dumps(result, ensure_ascii=False, default=str) if result else None,
             outcome_id),
        )
        self.conn.commit()

    def list_opportunity_outcomes(self, *, verdict: str | None = None,
                                  limit: int = 200) -> list[dict[str, Any]]:
        sql = ("SELECT id, keyword, opportunity_type, decision, evidence_json, "
               "candidate_score, action_score, human_decision, rejection_reason, "
               "implemented_action, url, baseline_json, implemented_at, verdict, "
               "measured_28d, measured_56d, measured_90d, "
               "result_28d_json, result_56d_json, result_90d_json, created_at "
               "FROM opportunity_outcomes")
        params: list[Any] = []
        if verdict:
            sql += " WHERE verdict = ?"
            params.append(verdict)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        import json as _json
        rows = self.conn.execute(sql, params).fetchall()
        return [
            {
                "id": r[0], "keyword": r[1], "opportunity_type": r[2],
                "decision": r[3],
                "evidence": _json.loads(r[4]) if r[4] else None,
                "candidate_score": r[5], "action_score": r[6],
                "human_decision": r[7] or "", "rejection_reason": r[8] or "",
                "implemented_action": r[9] or "", "url": r[10] or "",
                "baseline": _json.loads(r[11]) if r[11] else None,
                "implemented_at": r[12] or "", "verdict": r[13] or "",
                "measured": {"28d": bool(r[14]), "56d": bool(r[15]),
                             "90d": bool(r[16])},
                "results": {
                    "28d": _json.loads(r[17]) if r[17] else None,
                    "56d": _json.loads(r[18]) if r[18] else None,
                    "90d": _json.loads(r[19]) if r[19] else None,
                },
                "created_at": r[20] or "",
            }
            for r in rows
        ]

    def recalibration_stats(self) -> dict[str, Any]:
        """Regras simples de recalibração a partir de outcomes medidos (M8).

        Para cada opportunity_type com >= 3 outcomes com verdict, calcula a
        taxa de 'improved' — a ideia: tipos que nunca melhoram podem ter o
        peso/prioridade reduzidos de forma EXPLICÁVEL. Sem modelo estatístico
        ainda (só após volume suficiente).
        """
        rows = self.conn.execute(
            "SELECT opportunity_type, verdict, COUNT(*) FROM opportunity_outcomes "
            "WHERE verdict IS NOT NULL AND verdict != '' "
            "GROUP BY opportunity_type, verdict"
        ).fetchall()
        by_type: dict[str, dict[str, int]] = {}
        for otype, verdict, count in rows:
            by_type.setdefault(otype, {})[verdict] = count
        per_type: list[dict[str, Any]] = []
        for otype, counts in sorted(by_type.items()):
            total = sum(counts.values())
            improved = counts.get("improved", 0)
            worsened = counts.get("worsened", 0)
            rate = improved / total if total else 0.0
            per_type.append({
                "opportunity_type": otype,
                "measured": total,
                "improved": improved,
                "worsened": worsened,
                "improved_rate": round(rate, 2),
                "suggested_weight_adjustment": (
                    -0.1 if (total >= 3 and rate < 0.3)
                    else (0.0 if total < 3 else 0.05)
                ),
                "note": ("poucos casos (>= 3 p/ recalibrar)" if total < 3
                         else "sem modelo estatístico ainda — regras simples"),
            })
        return {"by_type": per_type,
                "total_measured": sum(sum(c.values()) for c in by_type.values()),
                "rule": "tipos com >=3 outcomes e <30% improved perdem 0.1 de peso; "
                        ">=3 e >=50% ganham 0.05"}

    def queries_for_url(self, url: str, *, limit: int = 15,
                        window_start: str | None = None) -> list[dict[str, Any]]:
        """Queries of ONE page in ONE window (latest by default), with clicks."""
        ws = window_start or self.latest_window_start()
        if not ws:
            return []
        rows = self.conn.execute(
            "SELECT query, intent, impressions, clicks, position, ctr FROM query_pages "
            "WHERE url = ? AND window_start = ? ORDER BY impressions DESC LIMIT ?",
            (url, ws, limit),
        ).fetchall()
        return [
            {"query": r[0], "intent": r[1], "impressions": r[2], "clicks": r[3],
             "position": round(r[4], 1) if r[4] else None, "ctr": r[5]}
            for r in rows
        ]

    def save_content_brief(self, *, url: str, title: str, intent: str,
                           queries: list[str], gaps: list[dict[str, Any]],
                           action: str, priority: float) -> bool:
        import json as _json
        try:
            self.conn.execute(
                "INSERT OR REPLACE INTO content_briefs (url, title, intent, queries_json, "
                "gaps_json, action, priority, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, "
                "'proposed', ?)",
                (url, title, intent, _json.dumps(queries, ensure_ascii=False),
                 _json.dumps(gaps, ensure_ascii=False), action, priority, _now()),
            )
            self.conn.commit()
            return True
        except Exception:
            return False

    # -- editorial backlog + workflow (E3/E5) --------------------------------

    def list_backlog(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql = ("SELECT id, pauta_type, title, intent, evidence, related_urls_json, scope, "
               "duplication_risk, score, status, created_at, published_url, baseline_json "
               "FROM editorial_backlog")
        params: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY score DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [
            {"id": r[0], "pauta_type": r[1], "title": r[2], "intent": r[3],
             "evidence": r[4], "related_urls": r[5], "scope": r[6],
             "duplication_risk": r[7], "score": r[8], "status": r[9],
             "created_at": r[10], "published_url": r[11], "baseline_json": r[12]}
            for r in rows
        ]

    def save_pauta(self, pauta: dict[str, Any]) -> bool:
        import json as _json
        hypothesis_key = f"{pauta['pauta_type']}|{pauta['title']}"
        fp = _evidence_fingerprint((pauta.get("evidence") or "") + (pauta.get("scope") or ""))
        exists = self.conn.execute(
            "SELECT 1 FROM editorial_backlog WHERE title = ? AND pauta_type = ? "
            "AND evidence = ? AND scope = ?",
            (pauta["title"], pauta["pauta_type"], pauta["evidence"], pauta.get("scope", "")),
        ).fetchone()
        if exists:
            return False
        # Rejeitada reabre apenas com evidência material nova.
        rejected = self.conn.execute(
            "SELECT evidence_fingerprint FROM editorial_backlog "
            "WHERE hypothesis_key = ? AND status = 'rejected' ORDER BY id DESC LIMIT 1",
            (hypothesis_key,),
        ).fetchone()
        if rejected and rejected[0] == fp:
            return False
        self.conn.execute(
            "INSERT INTO editorial_backlog (pauta_type, title, intent, evidence, "
            "related_urls_json, scope, duplication_risk, score, status, created_at, "
            "hypothesis_key, evidence_fingerprint) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'proposed', ?, ?, ?)",
            (pauta["pauta_type"], pauta["title"], pauta["intent"], pauta["evidence"],
             _json.dumps(pauta.get("related_urls", []), ensure_ascii=False),
             pauta.get("scope", ""), pauta.get("duplication_risk", ""),
             pauta.get("score", 0), _now(), hypothesis_key, fp),
        )
        self.conn.commit()
        return True

    def transition_backlog(self, backlog_id: int, status: str,
                           *, published_url: str = "", baseline: dict[str, Any] | None = None,
                           reason: str = "", responsible: str = "",
                           deadline: str = "") -> bool:
        """Apply only valid editorial transitions and record the human decision."""
        import json as _json
        row = self.conn.execute(
            "SELECT status, published_url FROM editorial_backlog WHERE id = ?", (backlog_id,)
        ).fetchone()
        if not row:
            return False
        current = row[0]
        allowed = {
            "proposed": {"approved", "rejected", "snoozed", "superseded"},
            "approved": {"published", "rejected", "snoozed", "superseded"},
            "published": {"measured"},
            "snoozed": {"approved", "rejected", "superseded"},
            "superseded": set(),
        }
        if status not in allowed.get(current, set()):
            return False
        if status == "published" and not published_url:
            return False
        params: list[Any] = [status]
        set_parts = ["status = ?"]
        if published_url:
            set_parts.append("published_url = ?")
            params.append(published_url)
        if baseline is not None:
            set_parts.append("baseline_json = ?")
            params.append(_json.dumps(baseline, ensure_ascii=False))
        if reason:
            set_parts.append("rejection_reason = ?")
            params.append(reason)
        if responsible:
            set_parts.append("responsible = ?")
            params.append(responsible)
        if deadline:
            set_parts.append("deadline = ?")
            params.append(deadline)
        params.append(backlog_id)
        cur = self.conn.execute(
            f"UPDATE editorial_backlog SET {', '.join(set_parts)} WHERE id = ? AND status = ?",
            [*params, current],
        )
        if cur.rowcount:
            self.conn.execute(
                "INSERT INTO editorial_events (backlog_id, from_status, to_status, details_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (backlog_id, current, status,
                 _json.dumps({"published_url": published_url, "baseline": baseline or {},
                              "reason": reason, "responsible": responsible,
                              "deadline": deadline}, ensure_ascii=False),
                 _now()),
            )
        self.conn.commit()
        return cur.rowcount > 0

    def expire_overdue(self) -> int:
        """proposed/approved items past their deadline become 'expired'."""
        import datetime as _dt
        now = _dt.datetime.now(_dt.timezone.utc).isoformat()
        cur = self.conn.execute(
            "UPDATE editorial_backlog SET status = 'expired' "
            "WHERE status IN ('proposed', 'approved') AND deadline IS NOT NULL AND deadline < ?",
            (now,),
        )
        self.conn.commit()
        return cur.rowcount

    def published_at(self, backlog_id: int) -> str | None:
        row = self.conn.execute(
            "SELECT created_at FROM editorial_events WHERE backlog_id = ? AND to_status = 'published' "
            "ORDER BY id DESC LIMIT 1", (backlog_id,)
        ).fetchone()
        return row[0] if row else None

    # -- interlink suggestions (E4) ------------------------------------------

    def save_interlink(self, *, source_url: str, target_url: str, reason: str,
                       anchor: str = "") -> bool:
        try:
            hypothesis_key = f"{source_url}|{target_url}"
            fp = _evidence_fingerprint(reason)
            rejected = self.conn.execute(
                "SELECT evidence_fingerprint FROM interlink_suggestions "
                "WHERE hypothesis_key = ? AND status = 'rejected' ORDER BY id DESC LIMIT 1",
                (hypothesis_key,),
            ).fetchone()
            if rejected and rejected[0] == fp:
                return False  # mesma evidência rejeitada: não volta
            self.conn.execute(
                "INSERT OR IGNORE INTO interlink_suggestions (source_url, target_url, reason, "
                "anchor, status, created_at, hypothesis_key, evidence_fingerprint) "
                "VALUES (?, ?, ?, ?, 'proposed', ?, ?, ?)",
                (source_url, target_url, reason, anchor, _now(), hypothesis_key, fp),
            )
            self.conn.commit()
            return True
        except Exception:
            return False

    def transition_interlink(self, interlink_id: int, status: str,
                             *, reason: str = "") -> bool:
        valid = {"rejected", "snoozed", "superseded", "approved", "done"}
        if status not in valid:
            return False
        set_parts = ["status = ?"]
        params: list[Any] = [status]
        if reason:
            set_parts.append("rejection_reason = ?")
            params.append(reason)
        params.append(interlink_id)
        cur = self.conn.execute(
            f"UPDATE interlink_suggestions SET {', '.join(set_parts)} WHERE id = ?", params
        )
        self.conn.commit()
        return cur.rowcount > 0

    def transition_checklist(self, checklist_id: int, status: str,
                             *, reason: str = "", responsible: str = "",
                             deadline: str = "", intervention_type: str = "",
                             baseline: dict[str, Any] | None = None,
                             measurement_unavailable: bool | None = None) -> bool:
        import json as _json
        valid = {"done", "rejected", "snoozed", "superseded", "expired", "pending"}
        if status not in valid:
            return False
        set_parts = ["status = ?"]
        params: list[Any] = [status]
        if reason:
            set_parts.append("rejection_reason = ?")
            params.append(reason)
        if responsible:
            set_parts.append("responsible = ?")
            params.append(responsible)
        if deadline:
            set_parts.append("deadline = ?")
            params.append(deadline)
        if intervention_type:
            set_parts.append("intervention_type = ?")
            params.append(intervention_type)
        if baseline is not None:
            set_parts.append("baseline_json = ?")
            params.append(_json.dumps(baseline, ensure_ascii=False))
        if measurement_unavailable is not None:
            set_parts.append("measurement_unavailable = ?")
            params.append(1 if measurement_unavailable else 0)
        if status == "done":
            # implemented_at = momento da implementação (base da janela de medição).
            set_parts.append("implemented_at = ?")
            params.append(_now())
            set_parts.append("done_at = ?")
            params.append(_now())
        params.append(checklist_id)
        cur = self.conn.execute(
            f"UPDATE improvement_checklist SET {', '.join(set_parts)} WHERE id = ?", params
        )
        self.conn.commit()
        return cur.rowcount > 0

    def list_interlinks(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql = "SELECT id, source_url, target_url, reason, anchor, status, created_at " \
              "FROM interlink_suggestions"
        params: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [
            {"id": r[0], "source_url": r[1], "target_url": r[2], "reason": r[3],
             "anchor": r[4], "status": r[5], "created_at": r[6]}
            for r in rows
        ]

    def out_links_for(self, source_url: str) -> set[str]:
        rows = self.conn.execute(
            "SELECT target_url FROM internal_links WHERE source_url = ?", (source_url,)
        ).fetchall()
        return {r[0] for r in rows}

    def list_checklist(self, *, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        import json as _json
        sql = ("SELECT id, url, item, reason, action, gain_clicks, status, created_at, done_at, "
               "explainable_score, score_breakdown_json FROM improvement_checklist")
        params: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        # Fila priorizada: pendentes primeiro por explainable_score DESC, depois por data.
        sql += (" ORDER BY CASE WHEN status = 'pending' THEN 0 ELSE 1 END, "
                "COALESCE(explainable_score, -1) DESC, created_at DESC, id DESC LIMIT ?")
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [
            {"id": r[0], "url": r[1], "item": r[2], "reason": r[3], "action": r[4],
             "gain_clicks": r[5], "status": r[6], "created_at": r[7], "done_at": r[8],
             "explainable_score": r[9],
             "score_breakdown": _json.loads(r[10]) if r[10] else None}
            for r in rows
        ]

    def set_checklist_score(self, checklist_id: int, explainable_score: float | None,
                            score_breakdown: dict[str, Any] | None) -> bool:
        import json as _json
        cur = self.conn.execute(
            "UPDATE improvement_checklist SET explainable_score = ?, score_breakdown_json = ? "
            "WHERE id = ?",
            (explainable_score,
             _json.dumps(score_breakdown, ensure_ascii=False) if score_breakdown else None,
             checklist_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def mark_checklist_done(self, checklist_id: int) -> bool:
        cur = self.conn.execute(
            "UPDATE improvement_checklist SET status = 'done', done_at = ? WHERE id = ? AND status = 'pending'",
            (_now(), checklist_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Storage":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _evidence_fingerprint(text: str) -> str:
    """MATERIAL evidence fingerprint: normalize ONLY metric numbers.

    Digits are stripped only inside known metric patterns (impressions,
    clicks, CTR %, position) so that metric-value fluctuations do not reopen a
    rejected suggestion. Years, versions, seasons and quantities that are part
    of the intent ("guia 2025", "temporada 3", "top 10") are PRESERVED — a
    qualitative change there reopens.
    """
    import hashlib
    import re

    t = (text or "").lower()
    # "N impressões/N impr/N cliques/N clicks"
    t = re.sub(r"\d[\d.,]*\s*(impress|impr|clique|click)", "METRIC \\1", t)
    # "CTR N%" / "N%"
    t = re.sub(r"(?:ctr\s*)?\d[\d.,]*\s*%", "CTR METRIC%", t)
    # "posição N / pos N / position N"
    t = re.sub(r"(posi(?:cao)?|position|pos)\s*\d[\d.,]*", r"\1 METRIC", t)
    # "para N" (impressões em frases "para 500 impressões") — coberto acima por impress
    t = re.sub(r"\s+", " ", t).strip()
    return hashlib.sha256(t.encode("utf-8")).hexdigest()[:32]


def _today() -> str:
    return datetime.date.today().isoformat()


def _snapshot_row(row: tuple) -> dict[str, Any]:
    def _load(raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    return {
        "url": row[0],
        "captured_at": row[1],
        "cycle_id": row[2] or "",
        "source": row[3] or "",
        "linked_action": row[4] or "",
        "status_code": row[5],
        "title": row[6] or "",
        "meta_description": row[7] or "",
        "canonical": row[8] or "",
        "meta_robots": row[9] or "",
        "h1": row[10] or "",
        "word_count": row[11],
        "content_hash": row[12] or "",
        "cwv": _load(row[13]),
        "gsc": _load(row[14]),
    }
