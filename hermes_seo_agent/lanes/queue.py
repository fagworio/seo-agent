"""Sprint 2 — `LaneQueue`: claim atômico, lease com expiração e fencing token.

Opera sobre o MESMO `Storage` (mesmo arquivo SQLite e mesma transação) — não é um
sistema paralelo à Caixa: `work_item_lifecycle` continua sendo o estado canônico
do item e `lane_queue` é a fila de trabalho com claim/lease. O `work_item_id`
usado aqui é exatamente o id do lifecycle, então o mesmo item é rastreável nos
dois lugares.

Garantias e o que cada uma custa:

* **Nenhum worker pega o mesmo item** — o `claim` é um único `UPDATE ... RETURNING`
  que marca e devolve as linhas; o segundo worker (mesmo em OUTRA conexão) não vê
  o que o primeiro marcou, desde que o claim esteja commitado.
* **Nenhum worker possui a tarefa para sempre** — `lease_until` expira e
  `recover_expired()` devolve o item para a fila (worker morto nunca deixa
  `claimed`/`executing` eterno).
* **LEASE VENCIDO NÃO É POSSE** — `owns_lease`/`complete`/`fail`/`heartbeat`/
  `mark_executing` exigem `lease_until > agora` além do fencing token. Sem isso o
  dono que volta depois do vencimento ainda seria aceito — inclusive para escrever
  no WordPress. A expiração revoga a posse por si só: não dependemos de
  `recover_expired()` ter rodado.
* **Nenhuma escrita repetida** — o fencing token (`lease_version`, incrementado no
  claim E na recuperação) barra o worker antigo.
* **Retry com backoff, não loop** — a falha é classificada e agenda
  `next_attempt_at`; depois de `max_attempts` o item sai da fila para
  `manual_review`.

Padrão de commit (o mesmo do `Storage`): TODA mutação aceita `commit: bool = True`
e faz `if commit: self.conn.commit()`. `commit=False` existe para composição
atômica dentro de `Storage.transaction()`. NUNCA se decide persistência por
`conn.in_transaction`: depois de um INSERT/UPDATE o SQLite JÁ está em transação
(`in_transaction == True`), então um guard `if not in_transaction` não commita
nada — o trabalho desaparece no fechamento da conexão e a outra conexão nem vê o
claim (ou recebe `database is locked`).
"""
from __future__ import annotations

from typing import Any

from hermes_seo_agent.lanes import policy as P

__all__ = ["LaneQueue", "MAX_RECOVERIES"]

# Quantas vezes o MESMO item pode ser recuperado de lease expirado antes de virar
# `manual_review`. Protege contra o item que derruba todo worker que o pega: sem
# isto, a recuperação o devolveria à fila para sempre (o mesmo deadlock, de outra
# forma). A falha de infraestrutura não consome `attempt_count` do item; este
# contador existe só para isso.
MAX_RECOVERIES = 3

# Predicado de POSSE VÁLIDA: dono + fencing token atual + estado sob lease + LEASE
# VIVO. Reutilizado por todos os métodos que exigem posse, para não haver um
# caminho que "esqueça" de checar a expiração.
_LIVE_LEASE = "lease_until IS NOT NULL AND lease_until > ?"


class LaneQueue:
    def __init__(self, store: Any) -> None:
        self.store = store

    @property
    def conn(self) -> Any:
        return self.store.conn

    def _maybe_commit(self, commit: bool) -> None:
        if commit:
            self.conn.commit()

    # -- enfileirar ----------------------------------------------------------

    def enqueue(self, lane: str, work_item_id: str | None = None, *,
                url: str | None = None, payload: Any = None,
                priority: int = 100, max_attempts: int = 3,
                now: str | None = None, commit: bool = True) -> bool:
        """Enfileira (idempotente por `(lane, work_item_id)`).

        Devolve `True` se o item foi criado, `False` se já existia (em qualquer
        estado). Idempotência é o que permite o produtor rodar quantas vezes for
        sem duplicar trabalho — o oposto do `producers-cycle` atual, que recria a
        mesma hipótese todo dia.
        """
        ts = now or P.utc_now()
        wid = work_item_id or P.work_item_key(lane, url)
        cur = self.conn.execute(
            "INSERT INTO lane_queue (lane, work_item_id, url, payload_json, "
            "status, priority, max_attempts, next_attempt_at, created_at, "
            "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(lane, work_item_id) DO NOTHING",
            (lane, wid, url, P.dumps_payload(payload), P.ST_PENDING,
             int(priority), int(max_attempts), ts, ts, ts))
        created = (cur.rowcount or 0) > 0
        self._maybe_commit(commit)
        return created

    # -- claim ---------------------------------------------------------------

    def claim(self, lane: str, worker_id: str, *, limit: int = 10,
              lease_seconds: int = 300, now: str | None = None,
              commit: bool = True) -> list[dict[str, Any]]:
        """Claim ATÔMICO de até `limit` itens elegíveis da lane.

        Elegível = `pending`/`retry` com `next_attempt_at` vencido. O mesmo
        `UPDATE` marca como `claimed`, grava o worker, o lease e INCREMENTA o
        fencing token — o valor devolvido é a única versão com a qual este worker
        pode concluir. Um item ruim não interrompe o lote: o lote é uma consulta
        ordenada por prioridade, não uma iteração sobre dados coletados antes.

        `limit=0` significa ILIMITADO (`policy.normalize_limit`), não "zero itens".
        """
        ts = now or P.utc_now()
        until = P.plus_seconds(ts, lease_seconds)
        top = P.normalize_limit(limit)
        sql = (
            "UPDATE lane_queue SET status = ?, worker_id = ?, leased_at = ?, "
            "lease_until = ?, lease_version = lease_version + 1, updated_at = ? "
            "WHERE id IN ("
            "  SELECT id FROM lane_queue WHERE lane = ? AND status IN (?, ?) "
            "    AND (next_attempt_at IS NULL OR next_attempt_at <= ?) "
            "    AND recoveries < ? "
            "  ORDER BY priority ASC, next_attempt_at ASC, id ASC"
            + (" LIMIT ?" if top else "") +
            ") RETURNING id, lane, work_item_id, url, payload_json, "
            "attempt_count, max_attempts, lease_version, priority")
        params: list[Any] = [P.ST_CLAIMED, worker_id, ts, until, ts, lane,
                             P.ST_PENDING, P.ST_RETRY, ts, MAX_RECOVERIES]
        if top:
            params.append(top)
        rows = self.conn.execute(sql, tuple(params)).fetchall()
        self._maybe_commit(commit)
        return [{
            "id": r[0], "lane": r[1], "work_item_id": r[2], "url": r[3],
            "payload": P.loads_payload(r[4]), "attempt_count": r[5],
            "max_attempts": r[6], "lease_version": r[7], "priority": r[8],
        } for r in rows]

    def mark_executing(self, work_item_id: str, worker_id: str,
                       lease_version: int, *, lane: str | None = None,
                       lease_seconds: int | None = None,
                       now: str | None = None, commit: bool = True) -> bool:
        """Marcação explícita de "comecei a agir" (com fencing e lease vivo).

        Separa *peguei* de *estou no meio disto*: o recovery precisa saber que um
        `executing` órfão pode ter escrito no WordPress pela metade.
        """
        ts = now or P.utc_now()
        sql = "UPDATE lane_queue SET status = ?, updated_at = ?"
        params: list[Any] = [P.ST_EXECUTING, ts]
        if lease_seconds is not None:
            sql += ", lease_until = ?"
            params.append(P.plus_seconds(ts, lease_seconds))
        sql += (" WHERE work_item_id = ? AND worker_id = ? AND lease_version = ? "
                "AND status IN (?, ?) AND " + _LIVE_LEASE)
        params += [work_item_id, worker_id, int(lease_version),
                   P.ST_CLAIMED, P.ST_EXECUTING, ts]
        if lane:
            sql += " AND lane = ?"
            params.append(lane)
        cur = self.conn.execute(sql, params)
        ok = (cur.rowcount or 0) > 0
        self._maybe_commit(commit)
        return ok

    def owns_lease(self, work_item_id: str, worker_id: str, lease_version: int,
                   *, lane: str | None = None,
                   now: str | None = None) -> bool:
        """FENCING + validade: só o dono, com a versão ATUAL e o LEASE VIVO.

        Um worker que voltou de um crash tem uma versão antiga e recebe `False`.
        Um worker cujo lease VENCEU também recebe `False`, mesmo que
        `recover_expired()` ainda não tenha rodado: a expiração revoga a posse.
        """
        ts = now or P.utc_now()
        sql = ("SELECT 1 FROM lane_queue WHERE work_item_id = ? AND worker_id = ? "
               "AND lease_version = ? AND status IN (?, ?) AND " + _LIVE_LEASE)
        params: list[Any] = [work_item_id, worker_id, int(lease_version),
                             P.ST_CLAIMED, P.ST_EXECUTING, ts]
        if lane:
            sql += " AND lane = ?"
            params.append(lane)
        return self.conn.execute(sql, params).fetchone() is not None

    def heartbeat(self, work_item_id: str, worker_id: str, lease_version: int,
                  *, lease_seconds: int = 300, lane: str | None = None,
                  now: str | None = None, commit: bool = True) -> bool:
        """Renova o lease de um item que este worker ainda possui VIVO.

        Heartbeat depois do vencimento é RECUSADO: não pode ressuscitar um lease
        expirado (senão o worker que volta tarde retomaria a posse por cima de
        quem já a tomou).
        """
        ts = now or P.utc_now()
        sql = ("UPDATE lane_queue SET lease_until = ?, updated_at = ? "
               "WHERE work_item_id = ? AND worker_id = ? AND lease_version = ? "
               "AND status IN (?, ?) AND " + _LIVE_LEASE)
        params: list[Any] = [P.plus_seconds(ts, lease_seconds), ts, work_item_id,
                             worker_id, int(lease_version),
                             P.ST_CLAIMED, P.ST_EXECUTING, ts]
        if lane:
            sql += " AND lane = ?"
            params.append(lane)
        cur = self.conn.execute(sql, params)
        ok = (cur.rowcount or 0) > 0
        self._maybe_commit(commit)
        return ok

    # -- conclusão / falha ---------------------------------------------------

    def complete(self, work_item_id: str, worker_id: str, lease_version: int, *,
                 lane: str | None = None, now: str | None = None,
                 commit: bool = True) -> bool:
        """Conclui o item — só com o fencing token atual e o lease VIVO.

        `False` significa que a posse foi perdida (recuperado, roubado ou lease
        vencido): o worker NÃO deve considerar o trabalho concluído nem registrar
        sucesso.
        """
        ts = now or P.utc_now()
        sql = ("UPDATE lane_queue SET status = ?, worker_id = NULL, leased_at = NULL, "
               "lease_until = NULL, last_error = NULL, error_class = NULL, "
               "next_attempt_at = NULL, updated_at = ? "
               "WHERE work_item_id = ? AND worker_id = ? AND lease_version = ? "
               "AND status IN (?, ?) AND " + _LIVE_LEASE)
        params: list[Any] = [P.ST_DONE, ts, work_item_id, worker_id,
                             int(lease_version), P.ST_CLAIMED, P.ST_EXECUTING, ts]
        if lane:
            sql += " AND lane = ?"
            params.append(lane)
        cur = self.conn.execute(sql, params)
        ok = (cur.rowcount or 0) > 0
        self._maybe_commit(commit)
        return ok

    def fail(self, work_item_id: str, worker_id: str, lease_version: int,
             error: BaseException | str, *, error_class: str | None = None,
             retry_in: int | None = None, lane: str | None = None,
             now: str | None = None, commit: bool = True) -> dict[str, Any]:
        """Registra a falha com CLASSIFICAÇÃO e agenda o retry (ou encerra).

        Devolve `{ok, error_class, status, attempt_count, next_attempt_at}`.
        `ok=False` quando a posse não é mais válida (fencing vencido ou lease
        expirado): nesse caso NADA é gravado, porque o item já pertence a outro
        worker ou aguarda recuperação.

        Regra de destino:
          * `stale`         -> `stale` (já aplicado; nunca reexecutar)
          * `terminal`      -> `terminal`
          * `manual_review` -> `manual_review`
          * `retryable`     -> `retry` com backoff; ao esgotar `max_attempts`
                               vira `manual_review` (não fica em loop)
        """
        ts = now or P.utc_now()
        klass = P.classify_error(error, kind=error_class)
        msg = (f"{type(error).__name__}: {error}"
               if isinstance(error, BaseException) else str(error))[:2000]

        row = self.conn.execute(
            "SELECT attempt_count, max_attempts FROM lane_queue "
            "WHERE work_item_id = ? AND worker_id = ? AND lease_version = ? "
            "AND status IN (?, ?) AND " + _LIVE_LEASE +
            (" AND lane = ?" if lane else ""),
            tuple([work_item_id, worker_id, int(lease_version),
                   P.ST_CLAIMED, P.ST_EXECUTING, ts] + ([lane] if lane else []))
        ).fetchone()
        if row is None:
            return {"ok": False, "error_class": klass, "status": None,
                    "attempt_count": None, "next_attempt_at": None}

        attempt = int(row[0]) + 1
        max_attempts = int(row[1])

        if klass == P.ERR_STALE:
            status, next_at = P.ST_STALE, None
        elif klass == P.ERR_TERMINAL:
            status, next_at = P.ST_TERMINAL, None
        elif klass == P.ERR_MANUAL_REVIEW:
            status, next_at = P.ST_MANUAL_REVIEW, None
        elif attempt >= max_attempts:
            status, next_at = P.ST_MANUAL_REVIEW, None
        else:
            delay = (int(retry_in) if retry_in is not None
                     else P.backoff_seconds(attempt, seed=work_item_id))
            status, next_at = P.ST_RETRY, P.plus_seconds(ts, delay)

        sql = ("UPDATE lane_queue SET status = ?, worker_id = NULL, "
               "leased_at = NULL, lease_until = NULL, attempt_count = ?, "
               "last_error = ?, error_class = ?, next_attempt_at = ?, "
               "updated_at = ? WHERE work_item_id = ? AND worker_id = ? "
               "AND lease_version = ? AND status IN (?, ?) AND " + _LIVE_LEASE)
        params: list[Any] = [status, attempt, msg, klass, next_at, ts,
                             work_item_id, worker_id, int(lease_version),
                             P.ST_CLAIMED, P.ST_EXECUTING, ts]
        if lane:
            sql += " AND lane = ?"
            params.append(lane)
        cur = self.conn.execute(sql, params)
        ok = (cur.rowcount or 0) > 0
        self._maybe_commit(commit)
        return {"ok": ok, "error_class": klass, "status": status,
                "attempt_count": attempt, "next_attempt_at": next_at}

    def mark_stale(self, work_item_id: str, worker_id: str, lease_version: int,
                   reason: str = "already_executed", *, now: str | None = None,
                   commit: bool = True) -> dict[str, Any]:
        """Atalho para o caso 'o fingerprint já está executed': NÃO reexecutar."""
        return self.fail(work_item_id, worker_id, lease_version, reason,
                         error_class=P.ERR_STALE, now=now, commit=commit)

    # -- recuperação de crash ------------------------------------------------

    def recover_expired(self, *, lane: str | None = None, now: str | None = None,
                        limit: int = 200, commit: bool = True) -> list[dict[str, Any]]:
        """Devolve à fila os itens com lease expirado (worker morto).

        Um worker que morreu não deixa `executing` eterno. O item volta como
        `retry` elegível imediatamente, com o fencing token INCREMENTADO (o worker
        antigo perde o direito de concluir, mesmo que volte). A falha aqui é do
        worker, não do item, então `attempt_count` não é consumido — mas
        `recoveries` é, e ao atingir `MAX_RECOVERIES` o item vai para
        `manual_review` em vez de derrubar workers para sempre.

        `limit` é aplicado ANTES da mutação (`WHERE id IN (SELECT ... LIMIT ?)`):
        com 10.000 leases vencidos e `limit=200`, apenas 200 mudam de estado nesta
        chamada — o resto fica para o próximo ciclo. Limitar só o retorno
        executaria a mutação inteira e devolveria 200, que é o oposto de trabalho
        limitado. `limit=0` = ILIMITADO.
        """
        ts = now or P.utc_now()
        top = P.normalize_limit(limit)
        cond = " AND lane = ?" if lane else ""
        inner_params: list[Any] = [P.ST_CLAIMED, P.ST_EXECUTING, ts]
        if lane:
            inner_params.append(lane)
        sql = (
            "UPDATE lane_queue SET status = CASE WHEN recoveries + 1 >= ? "
            "       THEN ? ELSE ? END, "
            "worker_id = NULL, leased_at = NULL, lease_until = NULL, "
            "lease_version = lease_version + 1, recoveries = recoveries + 1, "
            "next_attempt_at = ?, last_error = 'lease_expired', "
            "error_class = ?, updated_at = ? "
            "WHERE id IN ("
            "  SELECT id FROM lane_queue WHERE status IN (?, ?) "
            "    AND lease_until IS NOT NULL AND lease_until <= ?" + cond +
            "  ORDER BY lease_until ASC, id ASC"
            + (" LIMIT ?" if top else "") +
            ") RETURNING id, lane, work_item_id, url, lease_version, recoveries, "
            "status")
        params: list[Any] = [MAX_RECOVERIES, P.ST_MANUAL_REVIEW, P.ST_RETRY, ts,
                             P.ERR_RETRYABLE, ts] + inner_params
        if top:
            params.append(top)
        rows = self.conn.execute(sql, tuple(params)).fetchall()
        self._maybe_commit(commit)
        return [{"id": r[0], "lane": r[1], "work_item_id": r[2], "url": r[3],
                 "lease_version": r[4], "recoveries": r[5], "status": r[6]}
                for r in rows]

    # -- observabilidade -----------------------------------------------------

    def stats(self, *, lane: str | None = None, now: str | None = None) -> dict[str, Any]:
        """Snapshot por lane — a métrica que denuncia deadlock.

        `oldest_pending_age_seconds` é a principal: fila que só cresce aparece
        aqui antes de aparecer em qualquer outro lugar. `expired_leases` mostra
        itens presos AGORA (workers mortos que ninguém recuperou ainda).
        """
        ts = now or P.utc_now()
        where, params = "", []
        if lane:
            where, params = " WHERE lane = ?", [lane]

        counts = {st: 0 for st in (P.ST_PENDING, P.ST_CLAIMED, P.ST_EXECUTING,
                                   P.ST_RETRY, P.ST_DONE, P.ST_STALE,
                                   P.ST_TERMINAL, P.ST_MANUAL_REVIEW)}
        for row in self.conn.execute(
                "SELECT status, COUNT(*) FROM lane_queue" + where +
                " GROUP BY status", tuple(params)):
            counts[str(row[0])] = int(row[1])

        oldest_pending = self.conn.execute(
            "SELECT MIN(created_at) FROM lane_queue" + where +
            (" AND " if where else " WHERE ") +
            "status IN (?, ?)", tuple(params + [P.ST_PENDING, P.ST_RETRY])
        ).fetchone()[0]

        oldest_claimed = self.conn.execute(
            "SELECT MIN(leased_at) FROM lane_queue" + where +
            (" AND " if where else " WHERE ") +
            "status IN (?, ?)", tuple(params + [P.ST_CLAIMED, P.ST_EXECUTING])
        ).fetchone()[0]

        expired = self.conn.execute(
            "SELECT COUNT(*) FROM lane_queue" + where +
            (" AND " if where else " WHERE ") +
            "status IN (?, ?) AND lease_until IS NOT NULL AND lease_until <= ?",
            tuple(params + [P.ST_CLAIMED, P.ST_EXECUTING, ts])).fetchone()[0]

        tail = (" AND " if where else " WHERE ") + "status = ?"
        attempts, last_done = self.conn.execute(
            "SELECT COALESCE(SUM(attempt_count), 0), MAX(updated_at) "
            "FROM lane_queue" + where + tail,
            tuple(params + [P.ST_DONE])).fetchone()

        total = sum(counts.values())
        return {
            "lane": lane or "all",
            **counts,
            "total": total,
            "oldest_pending_age_seconds": P.age_seconds(oldest_pending, ts),
            "oldest_claimed_age_seconds": P.age_seconds(oldest_claimed, ts),
            "expired_leases": int(expired or 0),
            "total_attempts": int(attempts or 0),
            "last_completed_at": last_done,
            "generated_at": ts,
        }

    def stats_all(self, *, now: str | None = None) -> dict[str, dict[str, Any]]:
        """Observabilidade de TODAS as lanes, cada uma isolada."""
        ts = now or P.utc_now()
        lanes = [str(r[0]) for r in self.conn.execute(
            "SELECT DISTINCT lane FROM lane_queue ORDER BY lane")]
        return {ln: self.stats(lane=ln, now=ts) for ln in lanes}

    # -- consulta ------------------------------------------------------------

    def get(self, work_item_id: str, *, lane: str | None = None) -> dict[str, Any] | None:
        sql = ("SELECT id, lane, work_item_id, url, payload_json, status, "
               "priority, attempt_count, max_attempts, last_error, error_class, "
               "next_attempt_at, worker_id, leased_at, lease_until, lease_version, "
               "recoveries, created_at, updated_at FROM lane_queue "
               "WHERE work_item_id = ?")
        params: list[Any] = [work_item_id]
        if lane:
            sql += " AND lane = ?"
            params.append(lane)
        row = self.conn.execute(sql, params).fetchone()
        if row is None:
            return None
        keys: tuple[str, ...] = (
            "id", "lane", "work_item_id", "url", "payload", "status", "priority",
            "attempt_count", "max_attempts", "last_error", "error_class",
            "next_attempt_at", "worker_id", "leased_at", "lease_until",
            "lease_version", "recoveries", "created_at", "updated_at")
        out: dict[str, Any] = dict(zip(keys, row))
        out["payload"] = P.loads_payload(out.get("payload"))
        return out

    def pending_count(self, lane: str, *, now: str | None = None) -> int:
        """Quantos itens estão elegíveis AGORA nesta lane."""
        ts = now or P.utc_now()
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM lane_queue WHERE lane = ? AND status IN (?, ?) "
            "AND (next_attempt_at IS NULL OR next_attempt_at <= ?) "
            "AND recoveries < ?",
            (lane, P.ST_PENDING, P.ST_RETRY, ts, MAX_RECOVERIES)).fetchone()[0])
