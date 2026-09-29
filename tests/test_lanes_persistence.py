"""Sprint 2.0.1 — persistência entre conexões reais, lease vivo e limite efetivo.

Os testes anteriores usavam UMA conexão e verificavam pela mesma conexão — por
isso não detectaram que as mutações da `LaneQueue` não commitavam
(`if not conn.in_transaction` nunca é verdadeiro depois de um INSERT/UPDATE) e nem
que um lease VENCIDO continuava valendo como posse. Aqui os dois casos são
exercitados de forma independente.
"""
from __future__ import annotations

from hermes_seo_agent.lanes import LaneQueue, policy as P
from hermes_seo_agent.storage.db import Storage

LANE = P.LANE_TITLE_EXECUTION
T0 = "2026-09-29T12:00:00+00:00"
T_INSIDE = "2026-09-29T12:04:00+00:00"     # dentro do lease (vence 12:05)
T_EXPIRED = "2026-09-29T12:06:00+00:00"    # depois do vencimento
T_LATE = "2026-09-29T12:10:00+00:00"


# --- P0.9: persistência de verdade (duas conexões) --------------------------

def test_enqueue_e_visivel_em_outra_conexao(tmp_path):
    """Sem commit, o INSERT fica pendente e a conexão B não enxerga."""
    db = str(tmp_path / "p09_enq.db")
    a, b = Storage(db), Storage(db)
    try:
        assert LaneQueue(a).enqueue(LANE, "wi-1", url="https://x/1",
                                    now=T0) is True
        row = b.conn.execute(
            "SELECT status FROM lane_queue WHERE work_item_id = 'wi-1'"
        ).fetchone()
        assert row is not None, "enqueue não persistiu: B não vê o item"
        assert row[0] == P.ST_PENDING
    finally:
        a.close()
        b.close()


def test_claim_de_a_invisibiliza_o_item_para_b(tmp_path):
    """O claim precisa estar commitado — senão B pega o mesmo item."""
    db = str(tmp_path / "p09_claim.db")
    a, b = Storage(db), Storage(db)
    try:
        LaneQueue(a).enqueue(LANE, "wi-1", url="https://x/1", now=T0)
        item = LaneQueue(a).claim(LANE, "worker-A", now=T0)[0]

        assert LaneQueue(b).claim(LANE, "worker-B", now=T0) == [], \
            "B pegou um item já claimado por A"
        status = b.conn.execute(
            "SELECT status, worker_id FROM lane_queue WHERE work_item_id = 'wi-1'"
        ).fetchone()
        assert (status[0], status[1]) == (P.ST_CLAIMED, "worker-A")

        # complete de A fica persistido para B
        assert LaneQueue(a).complete("wi-1", "worker-A",
                                     item["lease_version"], now=T0) is True
        assert b.conn.execute(
            "SELECT status FROM lane_queue WHERE work_item_id = 'wi-1'"
        ).fetchone()[0] == P.ST_DONE
    finally:
        a.close()
        b.close()


def test_falha_e_recover_ficam_persistidos_para_outra_conexao(tmp_path):
    """fail() e recover_expired() também precisam commitar."""
    db = str(tmp_path / "p09_fail.db")
    a, b = Storage(db), Storage(db)
    try:
        qa, qb = LaneQueue(a), LaneQueue(b)
        qa.enqueue(LANE, "wi-1", url="https://x/1", now=T0)
        item = qa.claim(LANE, "worker-A", now=T0, lease_seconds=60)[0]
        qa.fail("wi-1", "worker-A", item["lease_version"], "HTTPError: 503", now=T0)
        assert b.conn.execute(
            "SELECT status, error_class FROM lane_queue WHERE work_item_id = 'wi-1'"
        ).fetchone() == (P.ST_RETRY, P.ERR_RETRYABLE)

        # claim de novo com lease curto, deixa expirar, recupera: B vê a recuperação
        item2 = qa.claim(LANE, "worker-B", now=T_LATE, lease_seconds=60)[0]
        assert item2 is not None
        assert qa.recover_expired(now=P.plus_seconds(T_LATE, 120), limit=10)
        row = b.conn.execute(
            "SELECT worker_id, recoveries FROM lane_queue WHERE work_item_id = 'wi-1'"
        ).fetchone()
        assert row[0] is None and row[1] == 1, "a recuperação não persistiu"
        assert qb.pending_count(LANE, now=P.plus_seconds(T_LATE, 130)) == 1
    finally:
        a.close()
        b.close()


def test_composicao_atomica_com_commit_false(tmp_path):
    """`commit=False` participa da transação externa; nada persiste no rollback."""
    db = str(tmp_path / "p09_tx.db")
    a, b = Storage(db), Storage(db)
    try:
        qa = LaneQueue(a)
        try:
            with a.transaction():
                qa.enqueue(LANE, "wi-1", url="https://x/1", now=T0, commit=False)
                raise RuntimeError("crash antes do fim")
        except RuntimeError:
            pass
        assert b.conn.execute(
            "SELECT COUNT(*) FROM lane_queue").fetchone()[0] == 0, \
            "o rollback tinha de desfazer o enqueue"

        # e com sucesso, o commit único persiste
        with a.transaction():
            qa.enqueue(LANE, "wi-2", url="https://x/2", now=T0, commit=False)
        assert b.conn.execute(
            "SELECT COUNT(*) FROM lane_queue").fetchone()[0] == 1
    finally:
        a.close()
        b.close()


# --- P0.10: lease vencido não é posse ---------------------------------------

def test_lease_vencido_recusa_todas_as_operacoes_sem_recovery(tmp_path):
    """Expiração revoga a posse ANTES de qualquer recover_expired()."""
    with Storage(str(tmp_path / "p10.db")) as store:
        q = LaneQueue(store)
        q.enqueue(LANE, "wi-1", url="https://x/1", now=T0)
        item = q.claim(LANE, "worker-A", now=T0, lease_seconds=300)[0]
        v = item["lease_version"]

        # dentro do prazo: contraprova, tudo funciona (lease curto para não
        # estender até depois do vencimento que queremos testar)
        assert q.owns_lease("wi-1", "worker-A", v, now=T_INSIDE) is True
        assert q.heartbeat("wi-1", "worker-A", v, lease_seconds=30,
                           now=T_INSIDE) is True

        # NENHUM recovery rodou ainda — e mesmo assim o vencido não manda mais
        assert q.owns_lease("wi-1", "worker-A", v, now=T_EXPIRED) is False
        assert q.mark_executing("wi-1", "worker-A", v, now=T_EXPIRED) is False
        assert q.heartbeat("wi-1", "worker-A", v, now=T_EXPIRED) is False
        assert q.complete("wi-1", "worker-A", v, now=T_EXPIRED) is False
        assert q.fail("wi-1", "worker-A", v, "boom", now=T_EXPIRED)["ok"] is False

        # o item segue 'claimed' (ninguém recuperou) com o lease no PASSADO
        row = store.conn.execute(
            "SELECT status, lease_until FROM lane_queue WHERE work_item_id = 'wi-1'"
        ).fetchone()
        assert row[0] == P.ST_CLAIMED
        assert row[1] <= T_EXPIRED, "o heartbeat não pode ter ressuscitado o lease"


def test_heartbeat_vencido_nao_ressuscita_o_lease(tmp_path):
    with Storage(str(tmp_path / "p10_hb.db")) as store:
        q = LaneQueue(store)
        q.enqueue(LANE, "wi-1", url="https://x/1", now=T0)
        item = q.claim(LANE, "worker-A", now=T0, lease_seconds=60)[0]
        before = store.conn.execute(
            "SELECT lease_until FROM lane_queue WHERE work_item_id = 'wi-1'"
        ).fetchone()[0]

        assert q.heartbeat("wi-1", "worker-A", item["lease_version"],
                           lease_seconds=9999, now=T_LATE) is False
        after = store.conn.execute(
            "SELECT lease_until FROM lane_queue WHERE work_item_id = 'wi-1'"
        ).fetchone()[0]
        assert after == before, "heartbeat tardio não pode estender lease vencido"


def test_apos_recovery_o_antigo_nao_volta_e_o_novo_assume(tmp_path):
    """Aceitação completa: vence -> recupera -> B assume -> A é barrado."""
    with Storage(str(tmp_path / "p10_rec.db")) as store:
        q = LaneQueue(store)
        q.enqueue(LANE, "wi-1", url="https://x/1", now=T0)
        a = q.claim(LANE, "worker-A", now=T0, lease_seconds=300)[0]

        q.recover_expired(now=T_LATE, limit=10)
        b = q.claim(LANE, "worker-B", now=T_LATE)[0]
        assert b["lease_version"] > a["lease_version"]

        assert q.complete("wi-1", "worker-A", a["lease_version"], now=T_LATE) is False
        assert q.complete("wi-1", "worker-B", b["lease_version"], now=T_LATE) is True


# --- P1: limite efetivo e semântica do zero ---------------------------------

def test_recover_expired_altera_no_maximo_o_limite(tmp_path):
    """500 leases vencidos com limit=50 -> 50 mudam, 450 esperam o próximo ciclo."""
    with Storage(str(tmp_path / "p1_lim.db")) as store:
        q = LaneQueue(store)
        for i in range(500):
            q.enqueue(LANE, f"wi-{i}", url=f"https://x/{i}", now=T0)
        claimados = q.claim(LANE, "w1", limit=0, now=T0, lease_seconds=60)
        assert len(claimados) == 500, "limit=0 tem de significar ILIMITADO"

        rec = q.recover_expired(now=T_LATE, limit=50)
        assert len(rec) == 50
        contagem = dict(store.conn.execute(
            "SELECT status, COUNT(*) FROM lane_queue GROUP BY status").fetchall())
        assert contagem.get(P.ST_RETRY) == 50, "mais que o limite foi mutado"
        assert contagem.get(P.ST_CLAIMED) == 450, "o resto tem de ficar para depois"

        # o próximo ciclo pega o lote seguinte, e não os mesmos 50
        rec2 = q.recover_expired(now=T_LATE, limit=50)
        assert len(rec2) == 50
        assert not ({r["work_item_id"] for r in rec} &
                    {r["work_item_id"] for r in rec2}), "recuperou o mesmo item 2x"


def test_limit_zero_significa_ilimitado_e_nao_zero_itens():
    assert P.normalize_limit(0) is None
    assert P.normalize_limit(None) is None
    assert P.normalize_limit(-3) is None
    assert P.normalize_limit(7) == 7
    # `lane_limit` com 0 = desligado (ilimitado), nunca "LIMIT 0"

    class _Cfg:
        lane_limits = {LANE: 0}

    assert P.lane_limit(LANE, _Cfg()) == 0
    assert P.normalize_limit(P.lane_limit(LANE, _Cfg())) is None


def test_claim_com_limit_zero_pega_tudo_e_com_limite_respeita(tmp_path):
    with Storage(str(tmp_path / "p1_claim.db")) as store:
        q = LaneQueue(store)
        for i in range(5):
            q.enqueue(LANE, f"wi-{i}", url=f"https://x/{i}", now=T0)

        assert len(q.claim(LANE, "w1", limit=2, now=T0)) == 2
        assert len(q.claim(LANE, "w1", limit=0, now=T0)) == 3   # o resto, ilimitado
