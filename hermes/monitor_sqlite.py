#!/usr/bin/env python3
"""Cheap local watchdog fingerprint; never contacts external services."""
import hashlib, json, os, sqlite3, sys

path = os.environ.get("SEO_SQLITE_PATH", os.path.join(os.path.dirname(__file__), "..", "state", "seo_agent.db"))
try:
    db = sqlite3.connect(path)
    tables = ("findings", "inspection_queue", "improvement_checklist", "editorial_backlog", "content_briefs")
    state = {}
    for table in tables:
        try:
            cols = {r[1] for r in db.execute("pragma table_info(" + table + ")")}
            ts = next((c for c in ("created_at", "updated_at", "last_collected_at") if c in cols), None)
            state[table] = [db.execute("select count(*) from " + table).fetchone()[0],
                            db.execute("select max(" + ts + ") from " + table).fetchone()[0] if ts else None]
        except sqlite3.Error:
            state[table] = [-1, "missing"]
    state["campaigns"] = db.execute("select status, count(*) from improvement_campaigns group by status").fetchall()
    state["last_cycle"] = db.execute("select max(finished_at) from cycles").fetchone()[0]
    state["last_schedule"] = db.execute("select max(finished_at) from agent_runs where trigger='schedule'").fetchone()[0]
    print(hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()[:24])
except Exception as exc:
    print("ERROR:" + hashlib.sha256(type(exc).__name__.encode()).hexdigest()[:16])
    sys.exit(1)
