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
    """Decisao nao-executavel e' barrada na reconciliacao COM o motivo."""
    db = str(tmp_path / "g8c.db")
    with Storage(db) as store:
        d = _decisao(rollout={})               # rollout barra
        TD.persist_decision(store, d)
        res = TD.reconcile_pending_enqueue(store)
        assert res["reconciliados"] == 0
        assert res["barrados"] == [{"decision_id": d.decision_id,
                                    "motivo": TD.NOT_EXEC_ROLLOUT}]
        assert LaneQueue(store).stats(lane="title_execution")["pending"] == 0

        # decisao DIFERENTE (outro `after`), tambem barrada pelo rollout
        d2 = _decisao(after="Terceiro titulo valido e bem diferente", rollout={})
        TD.persist_decision(store, d2)
        res2 = TD.reconcile_pending_enqueue(store)
        assert res2["reconciliados"] == 0
        assert {b["decision_id"] for b in res2["barrados"]} == {
            d.decision_id, d2.decision_id}


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
    with pytest.raises(ValueError, match="before vazio"):
        _decisao(before="")
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
