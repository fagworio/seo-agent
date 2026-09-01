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
CREATE INDEX IF NOT EXISTS idx_editorial_events_backlog ON editorial_events(backlog_id, created_at);
CREATE INDEX IF NOT EXISTS idx_findings_cycle ON findings(cycle_id);
CREATE INDEX IF NOT EXISTS idx_urls_url ON urls(url);
CREATE INDEX IF NOT EXISTS idx_queue_status ON inspection_queue(status, priority);
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
