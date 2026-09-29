"""Sprint 2, item 7A — gates obrigatorios da decisao persistida.

Cada teste corresponde a um dos 8 gates acordados. O gate 3 e' o mais estrutural:
ele PROVA que a execucao nao depende de GSC, GA4 nem do motor de titulo, bloqueando
o import desses modulos durante a montagem do payload — se algum voltar a ser
consultado no caminho de escrita, este teste quebra.
"""
from __future__ import annotations

import builtins
import sys

import pytest

from hermes_seo_agent.lanes import title_decision as TD
from hermes_seo_agent.lanes.queue import LaneQueue
from hermes_seo_agent.storage.db import Storage

URL = "https://www.unicorniohater.com.br/por-que-snape-matou-dumbledore/"
AFTER = "Por que Snape matou Dumbledore? A explicação real"
BEFORE = "Por que Snape matou Dumbledore em Harry Potter"


def _decisao(**kw):
    base = dict(url=URL, post_id=1234, before=BEFORE, after=AFTER,
                evidence={"family": "snape", "impressions": 1200},
                rollout={"write_allowed": True}, confidence=0.62)
    base.update(kw)
    return TD.make_decision(**base)


# ---------------------------------------------------------------------------
# Gate 1 — mesma evidencia + mesma decisao => mesma identidade, enqueue idempotente
# ---------------------------------------------------------------------------

def test_gate1_mesma_decisao_mesmo_fingerprint_e_enqueue_idempotente(tmp_path):
    db = str(tmp_path / "g1.db")
    with Storage(db) as store:
        d1 = _decisao()
        d2 = _decisao()                      # mesmos dados, outra instancia
        assert d1.decision_id == d2.decision_id
        assert d1.action_fingerprint == d2.action_fingerprint

        r1 = TD.persist_decision(store, d1)
        r2 = TD.persist_decision(store, d2)
        assert r1["acao"] == "criado"
        assert r2["acao"] == "existente", "decisao repetida nao cria linha nova"

        e1 = TD.enqueue_execution(store, d1)
        e2 = TD.enqueue_execution(store, d2)
        assert e1["enfileirado"] is True
        assert e2["enfileirado"] is False and e2["ja_existia"] is True, (
            "2o enqueue da mesma decisao tem de ser no-op")
        assert LaneQueue(store).stats(lane="title_execution")["pending"] == 1


def test_gate1_mesma_url_outro_titulo_e_outra_acao(tmp_path):
    """A identidade e' a ACAO: trocar o `after` cria outro item."""
    a = _decisao()
    b = _decisao(after="Outro título completamente diferente aqui")
    assert a.action_fingerprint != b.action_fingerprint
    assert a.decision_id != b.decision_id
    # e o `before` diferente tambem muda a acao (precondicao distinta)
    c = _decisao(before="Titulo diferente")
    assert c.action_fingerprint != a.action_fingerprint


def test_gate1_fingerprint_cobre_post_id_campo_e_versao():
    base = TD.title_action_fingerprint(post_id=1, before="a", after="b")
    assert TD.title_action_fingerprint(post_id=1, before="a", after="b") == base
    assert TD.title_action_fingerprint(post_id=2, before="a", after="b") != base
    assert TD.title_action_fingerprint(post_id=1, before="a", after="b",
                                       field="seo_title") != base
    assert TD.title_action_fingerprint(post_id=1, before="a", after="b",
                                       action_version=2) != base, (
        "mudanca de semantica da acao tem de invalidar fingerprint antigo")


# ---------------------------------------------------------------------------
# Gate 2 — URL ja decidida: o consumer nao recalcula
# ---------------------------------------------------------------------------

def test_gate2_decisao_persistida_e_carregavel_sem_recalculo(tmp_path):
    """O consumer carrega a decisao e usa o `after` gravado, nao um novo."""
    db = str(tmp_path / "g2.db")
    with Storage(db) as store:
        d = _decisao()
        TD.persist_decision(store, d)
        TD.enqueue_execution(store, d)

        carregada = store.title_decision_by_url(URL)
        assert carregada is not None
        assert carregada["after"] == AFTER, "o `after` vem do banco, nao de análise"
        assert carregada["before"] == BEFORE
        assert carregada["action_fingerprint"] == d.action_fingerprint
        assert carregada["decision_version"] == TD.DECISION_VERSION

        # o item de fila carrega a decisao inteira
        itens = LaneQueue(store).stats(lane="title_execution")
        assert itens["pending"] == 1
        item = store.conn.execute(
            "SELECT payload_json FROM lane_queue WHERE lane='title_execution'"
        ).fetchone()
        import json
        payload = json.loads(item[0])
        assert payload["after"] == AFTER
        assert payload["decision_id"] == d.decision_id


# ---------------------------------------------------------------------------
# Gate 3 — o payload basta: sem GSC, sem GA4, sem title engine
# ---------------------------------------------------------------------------

class _ImportBloqueado:
    """Bloqueia modulos de analise: se a execucao depender deles, o teste quebra."""

    PROIBIDOS = ("google", "googleapiclient", "google.oauth2",
                 "hermes_seo_agent.report.title_engine",
                 "hermes_seo_agent.report.query_families",
                 "hermes_seo_agent.report.rankability_signals",
                 "hermes_seo_agent.report.rankability_v2",
                 "hermes_seo_agent.report.baseline",
                 "hermes_seo_agent.tools.title_opportunities",
                 "hermes_seo_agent.report.title_generator")

    def __init__(self):
        self.real = builtins.__import__
        self.tentativas: list[str] = []

    def __call__(self, name, *a, **kw):
        if name in self.PROIBIDOS or name.startswith("google"):
            self.tentativas.append(name)
            raise AssertionError(f"execucao tentou consultar '{name}': payload incompleto")
        return self.real(name, *a, **kw)


def test_gate3_payload_completo_sem_dependencia_externa(tmp_path):
    """Montar o item de execucao NAO pode importar nada de análise."""
    db = str(tmp_path / "g3.db")
    with Storage(db) as store:
        d = _decisao()
        TD.persist_decision(store, d)

        guarda = _ImportBloqueado()
        builtins.__import__ = guarda
        try:
            itens = TD.execution_item(d)
            store.mark_title_decision_enqueued(d.decision_id)
        finally:
            builtins.__import__ = guarda.real

        assert guarda.tentativas == [], (
            f"o caminho de escrita consultou análise: {guarda.tentativas}")
        # o payload tem TUDO o que a execucao precisa (7B)
        for campo in ("decision_id", "url", "post_id", "field", "before", "after",
                      "action_fingerprint", "decision_version", "decided_at",
                      "evidence", "rollout"):
            assert campo in itens, f"payload sem '{campo}'"
        assert itens["after"] == AFTER and itens["before"] == BEFORE
        assert itens["post_id"] == 1234


def test_gate3_linha_persistida_tem_tudo(tmp_path):
    """O que sai do banco tambem tem de bastar (sem `evidence` vazia)."""
    db = str(tmp_path / "g3b.db")
    with Storage(db) as store:
        d = _decisao()
        TD.persist_decision(store, d)
        salva = store.title_decision(d.decision_id)
        assert salva["evidence"]["family"] == "snape"
        assert salva["rollout"]["write_allowed"] is True
        assert salva["confidence"] == 0.62
        assert salva["not_executable_reason"] is None


# ---------------------------------------------------------------------------
# Gate 4 — o `before` persistido e' o titulo OBSERVADO
# ---------------------------------------------------------------------------

def test_gate4_before_gravado_sem_normalizar(tmp_path):
    """Espacos e caixa sao preservados: a precondicao compara com o WordPress."""
    db = str(tmp_path / "g4.db")
    bruto = "  Titulo  Com   Espacos Estranhos  "
    with Storage(db) as store:
        d = _decisao(before=bruto)
        TD.persist_decision(store, d)
        salva = store.title_decision(d.decision_id)
        assert salva["before"] == bruto, (
            "normalizar o `before` faria a conferencia comparar valor inexistente")

        # e o fingerprint usa o valor sem strip apenas no `after`/`before` decididos
        assert d.action_fingerprint == TD.title_action_fingerprint(
            post_id=1234, before=bruto, after=AFTER)


# ---------------------------------------------------------------------------
# Gate 5 — decisao sem `after` valido nao cria execucao
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("after,motivo", [
    ("", TD.NOT_EXEC_EMPTY_AFTER),
    ("   ", TD.NOT_EXEC_EMPTY_AFTER),
    (BEFORE, TD.NOT_EXEC_SAME_AS_BEFORE),
    ("x" * 61, TD.NOT_EXEC_TOO_LONG),
])
def test_gate5_after_invalido_nao_gera_execucao(tmp_path, after, motivo):
    db = str(tmp_path / "g5.db")
    with Storage(db) as store:
        d = _decisao(after=after)
        TD.persist_decision(store, d)
        res = TD.enqueue_execution(store, d)
        assert res["enfileirado"] is False and res["motivo"] == motivo
        assert LaneQueue(store).stats(lane="title_execution")["pending"] == 0
        # a decisao continua registrada (auditavel) com o motivo
        salva = store.title_decision(d.decision_id)
        assert salva is not None and salva["not_executable_reason"] == motivo


def test_gate5_limite_exato_e_permitido(tmp_path):
    """60 caracteres e' valido; 61 nao (limite claro, nao aproximado)."""
    db = str(tmp_path / "g5b.db")
    ok = "a" * 60
    with Storage(db) as store:
        d = _decisao(after=ok)
        TD.persist_decision(store, d)
        assert TD.enqueue_execution(store, d)["enfileirado"] is True


# ---------------------------------------------------------------------------
# Gate 6 — low-confidence / manual nao entra na execucao automatica
# ---------------------------------------------------------------------------

def test_gate6_baixa_confianca_registra_mas_nao_executa(tmp_path):
    db = str(tmp_path / "g6.db")
    with Storage(db) as store:
        d = _decisao(confidence=0.10)
        TD.persist_decision(store, d)
        res = TD.enqueue_execution(store, d)
        assert res["enfileirado"] is False
        assert res["motivo"] == TD.NOT_EXEC_LOW_CONFIDENCE
        assert store.title_decision(d.decision_id)["not_executable_reason"] == (
            TD.NOT_EXEC_LOW_CONFIDENCE)


def test_gate6_requires_review_nao_executa(tmp_path):
    db = str(tmp_path / "g6b.db")
    with Storage(db) as store:
        d = _decisao(requires_review=True)
        TD.persist_decision(store, d)
        res = TD.enqueue_execution(store, d)
        assert res["enfileirado"] is False
        assert res["motivo"] == TD.NOT_EXEC_REVIEW


def test_gate6_confianca_limite_e_permitida(tmp_path):
    """No limiar exato, executa: o corte e' `< MIN_CONFIDENCE`."""
    db = str(tmp_path / "g6c.db")
    with Storage(db) as store:
        d = _decisao(confidence=TD.MIN_CONFIDENCE)
        TD.persist_decision(store, d)
        assert TD.enqueue_execution(store, d)["enfileirado"] is True


# ---------------------------------------------------------------------------
# Gate 7 — rollout nao permitido: registra a decisao, nao executa
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rollout", [
    {},                                   # ausente = NAO autoriza (default negado)
    {"write_allowed": False},
    {"stage": "observe"},
    {"phase": "shadow"},
])
def test_gate7_rollout_barra_execucao_mas_registra(tmp_path, rollout):
    db = str(tmp_path / "g7.db")
    with Storage(db) as store:
        d = _decisao(rollout=rollout)
        r = TD.persist_decision(store, d)
        assert r["executavel"] is False and r["motivo"] == TD.NOT_EXEC_ROLLOUT
        res = TD.enqueue_execution(store, d)
        assert res["enfileirado"] is False
        salva = store.title_decision(d.decision_id)
        assert salva is not None, "a decisao TEM de ser registrada"
        assert salva["status"] == "decided"
        assert LaneQueue(store).stats(lane="title_execution")["pending"] == 0


@pytest.mark.parametrize("rollout", [
    {"write_allowed": True}, {"stage": "auto"}, {"phase": "write"},
])
def test_gate7_rollout_permitido_executa(tmp_path, rollout):
    db = str(tmp_path / "g7b.db")
    with Storage(db) as store:
        d = _decisao(rollout=rollout)
        TD.persist_decision(store, d)
        assert TD.enqueue_execution(store, d)["enfileirado"] is True


# ---------------------------------------------------------------------------
# Gate 8 — crash entre persistir e enfileirar: reconciliacao sem duplicar
# ---------------------------------------------------------------------------

def test_gate8_crash_apos_persistir_e_antes_do_enqueue(tmp_path):
    """Simula o processo morrendo: decisao gravada, nenhum item de execucao."""
    db = str(tmp_path / "g8.db")
    with Storage(db) as store:
        d = _decisao()
        TD.persist_decision(store, d)          # <- grava
        # ... processo morre aqui: `enqueue_execution` NUNCA roda ...
        assert LaneQueue(store).stats(lane="title_execution")["pending"] == 0
        assert store.title_decision(d.decision_id)["enqueued_at"] is None
        assert store.title_decision_stats()["sem_execucao"] == 1

        # reconciliacao (o que o cron roda depois)
        res = TD.reconcile_pending_enqueue(store)
        assert res["pendentes"] == 1
        assert res["reconciliados"] == 1
        assert res["criados"] == [d.decision_id]
        assert LaneQueue(store).stats(lane="title_execution")["pending"] == 1
        assert store.title_decision(d.decision_id)["enqueued_at"] is not None
        assert store.title_decision_stats()["sem_execucao"] == 0


def test_gate8_reconciliacao_repetida_nao_duplica(tmp_path):
    """Rodar a reconciliacao 3x nao pode criar item extra."""
    db = str(tmp_path / "g8b.db")
    with Storage(db) as store:
        d = _decisao()
        TD.persist_decision(store, d)
        for _ in range(3):
            TD.reconcile_pending_enqueue(store)
        assert LaneQueue(store).stats(lane="title_execution")["pending"] == 1, (
            "a reconciliacao e' idempotente pelo `work_item_id`")
        assert store.conn.execute(
            "SELECT COUNT(*) FROM title_decision").fetchone()[0] == 1


def test_gate8_reconciliacao_respeita_os_gates(tmp_path):
    """Decisao barrada por gate NAO entra no conjunto reconciliável.

    Depois do fix de starvation (P1.2), o filtro `not_executable_reason IS NULL`
    impede que a bloqueada ocupe vaga no lote da reconciliacao. Ela continua
    registrada, com o motivo — o que muda e' nao ser mais candidata.
    """
    db = str(tmp_path / "g8c.db")
    with Storage(db) as store:
        d = _decisao(rollout={})               # rollout barra
        TD.persist_decision(store, d)
        res = TD.reconcile_pending_enqueue(store)
        assert res["pendentes"] == 0, "bloqueada nao pode ocupar o lote da reconciliacao"
        assert res["reconciliados"] == 0
        assert res["barrados"] == []
        assert LaneQueue(store).stats(lane="title_execution")["pending"] == 0
        assert store.title_decision(d.decision_id)["not_executable_reason"] == (
            TD.NOT_EXEC_ROLLOUT), "a decisao segue registrada com o motivo"
        assert TD.stats(store)["bloqueadas"] == 1


def test_gate8_rollout_muda_sem_mudar_a_decisao(tmp_path):
    """O rollout e' gate de EXECUCAO, nao parte da acao: liberar reusa a decisao.

    Como `rollout` nao entra no fingerprint, liberar a escrita nao cria decisao
    nova — a mesma decisao persistida passa a ser executavel e a reconciliacao
    fecha o item. Se o rollout entrasse no fingerprint, cada mudanca de fase do
    rollout geraria uma decisao nova para o mesmo titulo.
    """
    db = str(tmp_path / "g8d.db")
    with Storage(db) as store:
        d_barrada = _decisao(rollout={})
        TD.persist_decision(store, d_barrada)

        d_liberada = _decisao(rollout={"write_allowed": True})
        assert d_liberada.action_fingerprint == d_barrada.action_fingerprint, (
            "rollout nao pode mudar a identidade da acao")
        assert d_liberada.decision_id == d_barrada.decision_id

        TD.persist_decision(store, d_liberada)     # atualiza o MESMO registro
        assert store.conn.execute(
            "SELECT COUNT(*) FROM title_decision").fetchone()[0] == 1

        res = TD.reconcile_pending_enqueue(store)
        assert res["reconciliados"] == 1
        assert LaneQueue(store).stats(lane="title_execution")["pending"] == 1


def test_gate8_decisao_invalida_nao_entra_na_reconciliacao(tmp_path):
    """O `make_decision` recusa antes de sujar o banco."""
    # `before=""` DESCONHECIDO continua erro (sem leitura confiavel nao ha
    # precondicao). `before=""` OBSERVADO — `before_known=True`, o default — e'
    # ESTADO REAL e passou a ser aceito: e' a distincao do 7A.2.2.
    with pytest.raises(ValueError, match="before desconhecido"):
        _decisao(before="", before_known=False)
    with pytest.raises(ValueError, match="post_id"):
        _decisao(post_id=None)


# ---------------------------------------------------------------------------
# Regras de desenho que sustentam o 7B
# ---------------------------------------------------------------------------

def test_decision_version_e_persistida(tmp_path):
    """Versao da semantica gravada desde ja': decisao antiga continua legivel."""
    db = str(tmp_path / "v.db")
    with Storage(db) as store:
        d = _decisao(decision_version=2)
        TD.persist_decision(store, d)
        assert store.title_decision(d.decision_id)["decision_version"] == 2
        assert TD.DECISION_VERSION == 1 and TD.ACTION_VERSION == 1


def test_persistir_vem_antes_de_enfileirar(tmp_path):
    """A ordem e' o que torna o gate 8 possivel (nao inverter)."""
    db = str(tmp_path / "ordem.db")
    with Storage(db) as store:
        d = _decisao()
        TD.persist_decision(store, d)          # 1o: decisao durável
        assert store.title_decision(d.decision_id) is not None
        TD.enqueue_execution(store, d)         # 2o: item de fila
        assert store.title_decision(d.decision_id)["enqueued_at"] is not None
        assert store.title_decision(d.decision_id)["status"] == "enqueued"


def test_stats_do_7a(tmp_path):
    db = str(tmp_path / "st.db")
    with Storage(db) as store:
        TD.persist_decision(store, _decisao())
        TD.persist_decision(store, _decisao(after="Titulo alternativo valido aqui"))
        st = TD.stats(store)
        assert st["total"] == 2 and st["sem_execucao"] == 2
        TD.reconcile_pending_enqueue(store)
        assert TD.stats(store)["sem_execucao"] == 0


def test_modulo_nao_importa_analise(tmp_path):
    """Guard de arquitetura: o modulo do 7A nao pode arrastar GSC/GA4/engine."""
    import ast
    from pathlib import Path

    arq = Path(TD.__file__)
    arvore = ast.parse(arq.read_text(encoding="utf-8"))
    importados: list[str] = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            importados += [a.name for a in no.names]
        elif isinstance(no, ast.ImportFrom) and no.module:
            importados.append(no.module)
    proibidos = [m for m in importados
                 if "google" in m or "report." in m or "title_engine" in m
                 or "title_generator" in m or "title_opportunities" in m]
    assert proibidos == [], f"7A nao pode importar analise: {proibidos}"
    assert sys.modules is not None


# ---------------------------------------------------------------------------
# 7A.1 — os 3 P1 e o hardening da revisao (antes de ligar o motor)
# ---------------------------------------------------------------------------

def test_p1_1_fingerprint_usa_os_titulos_exatos():
    """`"Titulo"` e `" Titulo "` sao ESTADOS DIFERENTES para a precondition.

    Com `strip()` no fingerprint as duas decisoes colidiam no mesmo `decision_id`:
    o UPSERT sobrescrevia o `before` da tabela enquanto o item ja' enfileirado
    continuava com o payload antigo — fila e decisao divergindo em silencio.
    """
    a = TD.title_action_fingerprint(post_id=7, before="Titulo", after="Novo titulo")
    b = TD.title_action_fingerprint(post_id=7, before=" Titulo ", after="Novo titulo")
    assert a != b, "before com espacos nao pode colidir com before sem espacos"
    c = TD.title_action_fingerprint(post_id=7, before="Titulo", after="Novo titulo ")
    assert a != c, "espaco no after tambem muda a acao"

    d1 = _decisao(before="Titulo")
    d2 = _decisao(before=" Titulo ")
    assert d1.decision_id != d2.decision_id


def test_p1_1_upsert_nao_sobrescreve_a_decisao_enfileirada(tmp_path):
    """O cenario do report: 1o enfileira, depois chega o `before` com espacos."""
    import json

    db = str(tmp_path / "colisao.db")
    with Storage(db) as store:
        d1 = _decisao(before="Titulo")
        TD.persist_decision(store, d1)
        TD.enqueue_execution(store, d1)
        payload1 = json.loads(store.conn.execute(
            "SELECT payload_json FROM lane_queue WHERE lane='title_execution'"
        ).fetchone()[0])

        d2 = _decisao(before=" Titulo ")
        assert d2.decision_id != d1.decision_id
        TD.persist_decision(store, d2)

        salva1 = store.title_decision(d1.decision_id)
        assert salva1["before"] == "Titulo", "o UPSERT nao pode tocar a decisao 1"
        assert payload1["before"] == "Titulo"
        assert salva1["before"] == payload1["before"], (
            "fila e decisao nao podem divergir")
        assert store.conn.execute(
            "SELECT COUNT(*) FROM title_decision").fetchone()[0] == 2


def test_p1_2_reconciliacao_nao_sofre_starvation(tmp_path):
    """50 bloqueadas antigas + 1 executavel nova com `limit=50`.

    Antes, `ORDER BY decided_at ASC LIMIT 50` fazia as 50 bloqueadas ocuparem o
    lote em TODA passada e a executavel nunca ser alcancada — o title_execution
    travaria no dia em que o cron fosse ligado.
    """
    base = "https://www.unicorniohater.com.br"
    db = str(tmp_path / "starve.db")
    with Storage(db) as store:
        for i in range(50):
            d = TD.make_decision(
                url=f"{base}/antiga-{i}/", post_id=1000 + i,
                before=f"Titulo antigo {i}", after=f"Titulo novo {i}",
                rollout={}, confidence=0.9,               # rollout barra
                decided_at=f"2026-01-{i + 1:02d}T00:00:00+00:00")
            TD.persist_decision(store, d)
        nova = TD.make_decision(url=f"{base}/nova/", post_id=9999,
                                before="Titulo velho", after="Titulo novo valido",
                                rollout={"write_allowed": True}, confidence=0.9,
                                decided_at="2026-09-29T00:00:00+00:00")
        TD.persist_decision(store, nova)

        res = TD.reconcile_pending_enqueue(store, limit=50)
        assert res["reconciliados"] == 1, "a executavel TEM de ser alcancada"
        assert res["criados"] == [nova.decision_id]
        assert LaneQueue(store).stats(lane="title_execution")["pending"] == 1


def test_p1_2_observabilidade_separada(tmp_path):
    """`sem_execucao` nao pode somar recuperavel com deliberadamente bloqueada."""
    db = str(tmp_path / "obs.db")
    with Storage(db) as store:
        TD.persist_decision(store, _decisao())                        # recuperavel
        TD.persist_decision(store, _decisao(after="Outro titulo valido aqui",
                                            rollout={}))               # bloqueada
        TD.persist_decision(store, _decisao(after="Terceiro titulo valido aqui",
                                            confidence=0.05))          # bloqueada
        st = TD.stats(store)
        assert st["total"] == 3
        assert st["sem_execucao"] == 3, "todas estao sem item de execucao"
        assert st["sem_execucao_recuperavel"] == 1, "so' 1 e' trabalho parado"
        assert st["bloqueadas"] == 2
        assert st["bloqueadas_por_motivo"] == {
            TD.NOT_EXEC_ROLLOUT: 1, TD.NOT_EXEC_LOW_CONFIDENCE: 1}

        TD.reconcile_pending_enqueue(store)
        st2 = TD.stats(store)
        assert st2["sem_execucao_recuperavel"] == 0
        assert st2["bloqueadas"] == 2, "bloqueada nao vira item de execucao"


def test_p1_3_decisao_finalizada_nao_regride(tmp_path):
    """Item `done` + decision `executed`: o motor reencontra a decisao e ela fica."""
    db = str(tmp_path / "regress.db")
    with Storage(db) as store:
        d = _decisao()
        TD.persist_decision(store, d)
        TD.enqueue_execution(store, d)
        store.mark_title_decision_enqueued(d.decision_id, status="executed")
        store.conn.execute(
            "UPDATE lane_queue SET status='done' WHERE work_item_id = ?",
            (d.decision_id,))
        store.conn.commit()

        res = TD.enqueue_execution(store, d)
        assert res["enfileirado"] is False
        assert res["nao_regrediu"] is True
        assert res["item_status"] == "done"
        assert LaneQueue(store).stats(lane="title_execution")["pending"] == 0
        assert LaneQueue(store).stats(lane="title_execution")["done"] == 1
        assert store.title_decision(d.decision_id)["status"] == "executed", (
            "estado terminal nao pode regredir para `enqueued`")


def test_p1_3_item_vivo_confirma_enqueued(tmp_path):
    """Item ainda `pending`: confirmar `enqueued` e' correto, sem duplicar item."""
    db = str(tmp_path / "vivo.db")
    with Storage(db) as store:
        d = _decisao()
        TD.persist_decision(store, d)
        TD.enqueue_execution(store, d)
        store.mark_title_decision_enqueued(d.decision_id, status="decided")
        res = TD.enqueue_execution(store, d)
        assert res["enfileirado"] is False
        assert res["item_status"] == "pending"
        assert res["status_confirmado"] is True
        assert LaneQueue(store).stats(lane="title_execution")["pending"] == 1
        assert store.title_decision(d.decision_id)["status"] == "enqueued"


def test_p1_3_guard_do_storage_impede_regressao_direta(tmp_path):
    """Defesa em profundidade: `mark_..._enqueued` nao regride estado terminal."""
    db = str(tmp_path / "guard.db")
    with Storage(db) as store:
        d = _decisao()
        TD.persist_decision(store, d)
        store.mark_title_decision_enqueued(d.decision_id, status="executed")
        store.mark_title_decision_enqueued(d.decision_id, status="enqueued")
        assert store.title_decision(d.decision_id)["status"] == "executed"


def test_hardening_confidence_ausente_e_fail_closed(tmp_path):
    """Confianca ausente NAO pode liberar escrita automatica (fail-closed)."""
    db = str(tmp_path / "conf.db")
    with Storage(db) as store:
        d = _decisao(confidence=None)
        assert TD.production_ready(d) == (False, TD.NOT_EXEC_MISSING_CONFIDENCE)
        assert TD.persist_decision(store, d)["executavel"] is False
        res = TD.enqueue_execution(store, d)
        assert res["enfileirado"] is False
        assert res["motivo"] == TD.NOT_EXEC_MISSING_CONFIDENCE
        salva = store.title_decision(d.decision_id)
        assert salva is not None, "a decisao continua persistida"
        assert salva["not_executable_reason"] == TD.NOT_EXEC_MISSING_CONFIDENCE
        assert LaneQueue(store).stats(lane="title_execution")["pending"] == 0


def test_hardening_limpar_o_motivo_devolve_ao_reconciliavel(tmp_path):
    """Decisao que passa a satisfazer os gates volta sozinha ao fluxo."""
    db = str(tmp_path / "limpa.db")
    with Storage(db) as store:
        sem_conf = _decisao(confidence=None)
        TD.persist_decision(store, sem_conf)
        assert TD.stats(store)["bloqueadas"] == 1
        assert TD.reconcile_pending_enqueue(store)["reconciliados"] == 0

        com_conf = _decisao(confidence=0.8)          # MESMA acao, agora confiavel
        assert com_conf.decision_id == sem_conf.decision_id, (
            "confidence nao faz parte da acao")
        TD.persist_decision(store, com_conf)
        assert store.title_decision(com_conf.decision_id)[
            "not_executable_reason"] is None, "o motivo tem de ser limpo"
        assert TD.stats(store)["bloqueadas"] == 0
        assert TD.reconcile_pending_enqueue(store)["reconciliados"] == 1
        assert LaneQueue(store).stats(lane="title_execution")["pending"] == 1


# ---------------------------------------------------------------------------
# 7A.2 — integracao com o motor de titulos
# ---------------------------------------------------------------------------

def _contrato(**kw):
    """Contrato do motor no formato REAL (`report/shadow_mode.py`)."""
    c = {"url": URL, "post_id": 4242, "decision": "review_title",
         "confidence": 0.71,
         "rollout": {"mode": "auto", "writes_allowed": True,
                     "approval_required": False},
         "page": {"impressions": 1200.0, "clicks": 8.0, "ctr": 0.0067},
         "baseline": {"window_end": "2026-09-20"},
         "signal_window": {"window_start": "2026-08-23"}}
    c.update(kw)
    return c


# O meta BRUTO lido do WP (a fonte do `before`) — nao o `<title>` renderizado.
LIVE = "Titulo atual bruto"


def _acao(title="Titulo reescrito pelo motor", before=LIVE,
          post_id=4242, conf=0.71):
    """SafeAction no formato REAL que `decision_to_action` monta."""
    return {"rule_id": "title_engine", "url": URL,
            "detail": "title_engine: titulo reescrito",
            "before": {"rank_math_title": before},
            "fix": {"type": "wp_post_meta", "post_id": post_id,
                    "meta": {"rank_math_title": title},
                    "precondition": {"meta": {"rank_math_title": before}}},
            "confidence": conf, "source": "title_engine"}


def test_7a2_writes_allowed_e_a_chave_do_contrato_real():
    """O contrato real usa `writes_allowed`.

    Sem essa chave na lista, TODA decisao vinda do motor cairia em
    `rollout_blocks_write` — o gate funcionaria ao contrario e nada executaria,
    em silencio. Por isso a chave canonica vem primeiro.
    """
    assert TD._rollout_allows_write({"writes_allowed": True}) is True
    assert TD._rollout_allows_write({"writes_allowed": False}) is False
    # retrocompatibilidade com as variantes antigas
    assert TD._rollout_allows_write({"write_allowed": True}) is True
    # modo sem chave booleana continua valendo
    assert TD._rollout_allows_write({"mode": "auto"}) is True
    assert TD._rollout_allows_write({"mode": "observe"}) is False
    # e nao inventa permissao: ausencia/desconhecido = negado
    assert TD._rollout_allows_write({"mode": "sei_la"}) is False
    assert TD._rollout_allows_write({}) is False
    assert TD._rollout_allows_write(None) is False


def test_7a2_acao_vira_decisao_com_o_before_observado():
    """`before` = titulo observado: e' ele que o gate 4 confere no WordPress."""
    d = TD.decision_from_action(_acao(), contract=_contrato(),
                                live_title=LIVE)
    assert d.post_id == 4242
    assert d.before == "Titulo atual bruto", "before exato, sem normalizar"
    assert d.after == "Titulo reescrito pelo motor"
    assert d.confidence == 0.71
    assert d.url == URL
    assert d.rollout.get("writes_allowed") is True
    assert d.requires_review is False
    assert d.action_fingerprint == TD.title_action_fingerprint(
        post_id=4242, before="Titulo atual bruto",
        after="Titulo reescrito pelo motor", field=TD.DEFAULT_FIELD)
    ok, motivo = TD.production_ready(d)
    assert ok is True and motivo is None


def test_7a2_titulo_vivo_manda_no_before():
    """Quando o titulo vivo foi lido, ELE e' o `before` (Fase 16 / STALE)."""
    d = TD.decision_from_action(_acao(before="Titulo da acao"),
                                contract=_contrato(),
                                live_title="Titulo vivo no WP")
    assert d.before == "Titulo vivo no WP"


def test_7a2_o_contrato_real_gera_decisao_executavel(tmp_path):
    """O caso exato que o bug do `writes_allowed` quebraria em producao."""
    db = str(tmp_path / "7a2.db")
    with Storage(db) as store:
        r = TD.persist_actions(store, [_acao()],
                               contracts_by_url={URL: _contrato()},
                               live_titles={URL: LIVE})
        assert r["counts"] == {"criadas": 1, "executaveis": 1,
                               "sem_execucao": 0, "erros": 0}
        assert TD.stats(store)["sem_execucao_recuperavel"] == 0
        assert LaneQueue(store).stats(lane="title_execution")["pending"] == 1
        salva = store.title_decision(r["criadas"][0])
        assert salva["before"] == "Titulo atual bruto"
        assert salva["after"] == "Titulo reescrito pelo motor"


def test_7a2_rollout_negado_registra_sem_enfileirar(tmp_path):
    """Contrato em `observe`: a decisao existe, a execucao nao."""
    db = str(tmp_path / "7a2b.db")
    with Storage(db) as store:
        c = _contrato(rollout={"mode": "observe", "writes_allowed": False,
                               "approval_required": True})
        r = TD.persist_actions(store, [_acao()], contracts_by_url={URL: c},
                               live_titles={URL: LIVE})
        assert r["counts"]["criadas"] == 1
        assert r["counts"]["executaveis"] == 0
        assert r["sem_execucao"][0]["motivo"] == TD.NOT_EXEC_ROLLOUT
        assert LaneQueue(store).stats(lane="title_execution")["pending"] == 0


def test_7a2_uma_url_estranha_nao_derruba_o_lote(tmp_path):
    """Regra principal do roadmap: um item ruim nunca segura os outros."""
    db = str(tmp_path / "7a2c.db")
    with Storage(db) as store:
        r = TD.persist_actions(store, [_acao(), "nao-e-dict", _acao()],
                               contracts_by_url={URL: _contrato()},
                               live_titles={URL: LIVE})
        assert r["counts"]["criadas"] == 2, "as validas entram"
        assert r["counts"]["erros"] == 1
        assert "AttributeError" in r["erros"][0]["erro"] or r["erros"]


# ---------------------------------------------------------------------------
# 7A.2.1 — os dois P1 latentes no caminho positivo
# ---------------------------------------------------------------------------

def test_7a21_rotulo_de_confidence_nao_vira_score():
    """`float("high")` estourava em `production_ready` no 1o review_title real.

    `decision_to_action` grava `confidence` como ROTULO na acao; o numero vive em
    `contract["confidence_detail"]["score"]`. Como `review_title` era 0, o bug
    estava latente — apareceria exatamente na primeira decisao real.
    """
    c = _contrato(confidence_detail={"score": 0.62, "label": "medium"})
    a = _acao()
    a["confidence"] = "high"  # ROTULO, como o motor grava
    d = TD.decision_from_action(a, contract=c, live_title=LIVE)
    assert d.confidence == 0.62, "tem de usar o score NUMERICO"
    assert d.evidence.get("confidence_label") == "high", "o rotulo vai p/ evidence"
    ok, motivo = TD.production_ready(d)
    assert ok is True and motivo is None


def test_7a21_rotulo_sem_score_vira_missing_confidence():
    """Sem numero, fail-closed — nunca `float("high")`."""
    a = _acao()
    a["confidence"] = "high"
    d = TD.decision_from_action(a, contract=_contrato(confidence="high"),
                                live_title=LIVE)
    assert d.confidence is None
    ok, motivo = TD.production_ready(d)
    assert ok is False and motivo == TD.NOT_EXEC_MISSING_CONFIDENCE


def test_7a21_confidence_numerica_em_string_ainda_vale():
    a = _acao()
    a["confidence"] = "0.44"
    d = TD.decision_from_action(a, contract=_contrato(confidence="0.44"))
    assert d.confidence == 0.44


def test_7a21_score_real_medido_em_producao():
    """O contrato medido em producao traz `confidence_detail.score` = 0.388."""
    c = _contrato(confidence="low",
                  confidence_detail={"score": 0.388, "label": "low"})
    d = TD.decision_from_action(_acao(), contract=c, live_title=LIVE)
    assert isinstance(d.confidence, float)
    assert d.confidence == 0.388
    # 0.388 > MIN_CONFIDENCE (0.35): a confianca NAO seria a barreira aqui
    assert d.confidence > TD.MIN_CONFIDENCE


def test_7a21_bool_nao_e_confianca():
    """`True` e' 1.0 em Python — aceitar seria dar confianca maxima de graca."""
    a = _acao()
    a["confidence"] = True
    d = TD.decision_from_action(a, contract=_contrato(confidence=True))
    assert d.confidence is None


# ---------------------------------------------------------------------------
# 7A.2.2 — `before_known`: meta vazio observado vs leitura que falhou
# ---------------------------------------------------------------------------

def test_7a22_meta_vazio_observado_e_aceito_e_executavel(tmp_path):
    """`rank_math_title=""` observado e' ESTADO REAL: a decisao executa.

    O codigo antigo descartava o vazio (`if _t:`) e caia no `<title>` renderizado
    em silencio — a precondition passava a ser um valor que nunca esteve no banco.
    """
    db = str(tmp_path / "vazio.db")
    with Storage(db) as store:
        r = TD.persist_actions(store, [_acao(before="")],
                               contracts_by_url={URL: _contrato()},
                               live_titles={URL: ""})
        assert r["counts"]["criadas"] == 1
        assert r["counts"]["executaveis"] == 1, "meta vazio nao bloqueia"
        assert r["counts"]["sem_execucao"] == 0
        salva = store.title_decision(r["criadas"][0])
        assert salva["before"] == "", "gravado EXATAMENTE como observado"
        assert salva["before_known"] is True
        assert LaneQueue(store).stats(lane="title_execution")["pending"] == 1


def test_7a22_leitura_que_falhou_e_fail_closed(tmp_path):
    """URL ausente de `live_titles` = leitura falhou: registra, mas NUNCA executa."""
    db = str(tmp_path / "unknown.db")
    with Storage(db) as store:
        r = TD.persist_actions(store, [_acao()],
                               contracts_by_url={URL: _contrato()})
        assert r["counts"]["criadas"] == 1, "a decisao existe (observavel)"
        assert r["counts"]["executaveis"] == 0, "mas nao executa"
        assert r["sem_execucao"][0]["motivo"] == TD.NOT_EXEC_BEFORE_UNKNOWN
        salva = store.title_decision(r["criadas"][0])
        assert salva["before_known"] is False
        assert LaneQueue(store).stats(lane="title_execution")["pending"] == 0


def test_7a22_before_known_sobrevive_ao_banco(tmp_path):
    """O `reconcile` le do banco: o flag tem de voltar pelo dict."""
    db = str(tmp_path / "flag.db")
    with Storage(db) as store:
        ok_d = TD.make_decision(url=URL, post_id=4242, before="",
                                after="Novo titulo valido aqui",
                                rollout={"writes_allowed": True}, confidence=0.6,
                                before_known=True)
        TD.persist_decision(store, ok_d)
        dd = store.title_decision(ok_d.decision_id)
        assert dd["before_known"] is True
        assert TD.production_ready(dd) == (True, None), "vazio observado executa"

        # Fail-closed ja' na CRIACAO: `make_decision` recusa `before=""` quando a
        # leitura nao aconteceu (o valor nao existe em lugar nenhum).
        with pytest.raises(ValueError, match="before desconhecido"):
            TD.make_decision(url=URL, post_id=4243, before="",
                             after="Outro titulo valido aqui",
                             rollout={"writes_allowed": True}, confidence=0.6,
                             before_known=False)

        # O round-trip do flag e' testado pelo caminho que o produtor usa: o dict
        # vindo do BANCO tem de devolver `before_known=False` e barrar a execucao.
        fid = "x" * 32
        store.record_title_decision(
            decision_id=TD.decision_id_for(fid), url=URL, post_id=4243,
            field=TD.DEFAULT_FIELD, before="", after="Outro titulo valido aqui",
            action_fingerprint=fid, rollout={"writes_allowed": True},
            confidence=0.6, before_known=False)
        dd2 = store.title_decision(TD.decision_id_for(fid))
        assert dd2["before_known"] is False
        assert TD.production_ready(dd2)[1] == TD.NOT_EXEC_BEFORE_UNKNOWN
