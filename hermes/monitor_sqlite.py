#!/usr/bin/env python3
"""Cheap local watchdog fingerprint; never contacts external services.

O hash representa ESTADO ÚTIL (contagens/status), não "quando um job rodou".
Timestamp de execução (last_schedule / last_cycle / max(ts) de job) muda a cada
execução e acordaria o agente sem trabalho novo — contradiz o objetivo. A env é
SQLITE_PATH (a mesma da aplicação), não SEO_SQLITE_PATH.
"""
import hashlib, json, os, sqlite3, sys

path = os.environ.get("SQLITE_PATH",
                      os.path.join(os.path.dirname(__file__), "..", "state", "seo_agent.db"))
try:
    db = sqlite3.connect(path)
    state: dict[str, object] = {}

    def status_groups(table: str):
        try:
            return db.execute(
                f"select status, count(*) from {table} group by status").fetchall()
        except sqlite3.Error:
            return [("missing", -1)]

    def count_where(table: str, where: str):
        try:
            return db.execute(f"select count(*) from {table} where {where}").fetchone()[0]
        except sqlite3.Error:
            return -1

    # Estado ACIONÁVEL (fila/decisão/campanhas), não histórico cumulativo.
    state["inspection_queue"] = status_groups("inspection_queue")
    state["improvement_checklist"] = status_groups("improvement_checklist")
    state["editorial_backlog"] = status_groups("editorial_backlog")
    state["content_briefs"] = status_groups("content_briefs")
    state["campaigns"] = status_groups("improvement_campaigns")
    # Só runs que FALHARAM/PARCIALIZARAM merecem atenção (não toda execução OK).
    state["failed_runs"] = count_where("agent_runs", "status in ('failed','partial')")
    # Findings do ÚLTIMO ciclo por IDENTIDADE (rule_id+url+severity), não só
    # contagem: dois ciclos com os mesmos totais mas problemas DIFERENTES devem
    # mudar o hash. Ordenado para ser determinístico.
    try:
        latest = db.execute("select id from cycles order by started_at desc limit 1").fetchone()
        if latest:
            rows = db.execute(
                "select rule_id, url, severity from findings where cycle_id = ? "
                "order by rule_id, url, severity", (latest[0],)).fetchall()
            state["findings_latest_digest"] = hashlib.sha256(
                "\n".join(f"{r[0]}|{r[1]}|{r[2]}" for r in rows).encode()).hexdigest()[:24]
    except sqlite3.Error:
        pass

    print(hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()[:24])
except Exception as exc:
    print("ERROR:" + hashlib.sha256(type(exc).__name__.encode()).hexdigest()[:16])
    sys.exit(1)
