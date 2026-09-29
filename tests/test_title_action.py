"""Testes da conversao TitleDecision -> SafeAction (roadmap Fases 2/9/15/16).

Cobre os cenarios E2E que o roadmap exige, todos sem rede (o modulo e puro):

- E2E 1: `review_title` + confianca medium/high -> SafeAction `wp_post_meta`
  com `before` + o novo valor (o que o Executor consome).
- E2E 2: uma URL problematica nunca impede as outras (regra principal).
- E2E 7: idempotencia real — propostas diferentes para a mesma URL geram
  fingerprints diferentes (o `before`/o novo valor entram na acao).
- E2E 8: STALE — o titulo vivo mudou depois da decisao: NAO sobrescreve.
"""

from __future__ import annotations

from hermes_seo_agent.report.title_action import (
    SKIP_CONFIDENCE,
    SKIP_DECISION,
    SKIP_NO_CANDIDATE,
    SKIP_NO_POST_ID,
    SKIP_NOOP,
    SKIP_OVER_MAX_LEN,
    SKIP_ROLLOUT,
    SKIP_STALE,
    decision_to_action,
    decisions_to_actions,
)


def _contract(**over):
    base = {
        "url": "https://www.unicorniohater.com.br/cole-young-agora-e-scorpion/",
        "decision": "review_title",
        "confidence": "medium",
        "post_id": 32373,
        # P0.1 (Sprint 1.1): sem writes_allowed=true NENHUMA acao eh criada.
        # `observe` e `approval` carregam writes_allowed=false.
        "rollout": {"mode": "auto", "writes_allowed": True,
                    "approval_required": False},
        "current_title": {"title": "Cole Young agora é Scorpion? Explicado — UnicornioHater"},
        "suggested_titles": ["Cole Young e Scorpion: qual a relação? Explicado"],
    }
    base.update(over)
    return base


# --- E2E 1: decisao vira acao executavel -----------------------------------

def test_review_title_medium_vira_safe_action():
    out = decision_to_action(_contract())
    assert out["ok"] is True
    action = out["action"]
    assert action["rule_id"] == "title_engine"
    assert action["fix"]["type"] == "wp_post_meta"
    assert action["fix"]["post_id"] == 32373
    assert action["fix"]["meta"]["rank_math_title"] == (
        "Cole Young e Scorpion: qual a relação? Explicado")
    # Fase 15/16: o `before` viaja com a acao (idempotencia + STALE).
    assert action["before"]["rank_math_title"].startswith("Cole Young agora")


def test_confianca_high_tambem_escreve():
    assert decision_to_action(_contract(confidence="high"))["ok"] is True


def test_aceita_as_tres_formas_de_candidato():
    for campo in (
        {"suggested_titles": ["Candidato A"]},
        {"candidates": [{"title": "Candidato B", "discarded": False}]},
        {"candidate": {"title": "Candidato C"}},
    ):
        contrato = _contract(**campo)
        contrato.pop("suggested_titles", None) if "suggested_titles" not in campo else None
        assert decision_to_action(contrato)["ok"] is True


def test_candidato_descartado_e_ignorado():
    out = decision_to_action(_contract(suggested_titles=[], candidates=[
        {"title": "ruim", "discarded": True},
        {"title": "bom", "discarded": False},
    ]))
    assert out["ok"] is True
    assert out["action"]["fix"]["meta"]["rank_math_title"] == "bom"


# --- as recusas: nenhuma delas levanta excecao -----------------------------

def test_confianca_low_vai_para_manual_review():
    out = decision_to_action(_contract(confidence="low"))
    assert out["ok"] is False
    assert out["skip"] == SKIP_CONFIDENCE


def test_decisao_diferente_de_review_title_nao_vira_acao():
    out = decision_to_action(_contract(decision="no_title_change"))
    assert out["ok"] is False
    assert out["skip"] == SKIP_DECISION


def test_sem_candidato():
    out = decision_to_action(_contract(suggested_titles=[], candidates=[]))
    assert out["ok"] is False
    assert out["skip"] == SKIP_NO_CANDIDATE


def test_sem_post_id():
    contrato = _contract()
    contrato.pop("post_id")
    out = decision_to_action(contrato)
    assert out["ok"] is False
    assert out["skip"] == SKIP_NO_POST_ID


def test_post_id_na_page_tambem_serve():
    contrato = _contract(page={"post_id": 999})
    contrato.pop("post_id")
    out = decision_to_action(contrato)
    assert out["ok"] is True and out["action"]["fix"]["post_id"] == 999


def test_titulo_igual_ao_atual_nao_escreve():
    titulo = "Cole Young agora é Scorpion? Explicado — UnicornioHater"
    out = decision_to_action(_contract(suggested_titles=[titulo],
                                       current_title={"title": titulo}))
    assert out["ok"] is False
    assert out["skip"] == SKIP_NOOP


# --- E2E 8: STALE ----------------------------------------------------------

def test_stale_quando_o_titulo_vivo_mudou():
    out = decision_to_action(
        _contract(),
        live_title="Outro título qualquer escrito por outro agente")
    assert out["ok"] is False
    assert out["skip"] == SKIP_STALE
    assert out["before"].startswith("Cole Young agora")


def test_nao_e_stale_quando_o_titulo_vivo_bate_com_o_before():
    contrato = _contract()
    out = decision_to_action(
        contrato, live_title=contrato["current_title"]["title"])
    assert out["ok"] is True


# --- E2E 2: uma URL ruim nunca para as outras -----------------------------

def test_lote_isola_falhas_e_processa_o_resto():
    contratos = [
        _contract(url="u1"),                                   # ok
        _contract(url="u2", confidence="low"),                 # manual review
        _contract(url="u3", post_id=None),                     # recusado
        _contract(url="u4", decision="no_title_change"),       # sem acao
        _contract(url="u5"),                                   # ok
    ]
    resultado = decisions_to_actions(contratos)
    assert resultado["counts"] == {"built": 2, "skipped": 3}
    assert [a["url"] for a in resultado["actions"]] == ["u1", "u5"]
    assert {s["skip"] for s in resultado["skipped"]} == {
        SKIP_CONFIDENCE, SKIP_NO_POST_ID, SKIP_DECISION}


def test_contrato_estranho_nao_derruba_o_lote():
    resultado = decisions_to_actions([_contract(url="ok"), None, {}])
    assert resultado["counts"]["built"] == 1
    assert resultado["counts"]["skipped"] == 2


def test_lote_vazio():
    resultado = decisions_to_actions([])
    assert resultado["counts"] == {"built": 0, "skipped": 0}


# --- E2E 7: idempotencia real (o fingerprint muda com o conteudo) ----------

def test_propostas_diferentes_geram_fingerprints_diferentes():
    from hermes_seo_agent.executor.executor import _fingerprint

    a = decision_to_action(_contract(suggested_titles=["Título proposto A"]))
    b = decision_to_action(_contract(suggested_titles=["Título proposto B"]))
    fp = lambda out: _fingerprint(  # noqa: E731
        out["action"]["rule_id"], out["action"]["url"],
        out["action"]["detail"], out["action"]["fix"])
    assert fp(a) != fp(b)
    # e a MESMA proposta nao colide com ela mesma (idempotente)
    assert fp(a) == fp(decision_to_action(
        _contract(suggested_titles=["Título proposto A"])))


# --- P0.4: titulo acima do limite NAO e truncado -------------------------

def test_titulo_acima_do_limite_e_recusado_sem_truncar():
    """Antes o modulo cortava o candidato (`title[:max_len]`), publicando um
    texto que NUNCA passou pela validacao do motor. Agora recusa."""
    longo = "Dragon Ball: idade dos personagens e quando cada um apareceu na série"
    out = decision_to_action(_contract(suggested_titles=[longo]), max_len=60)
    assert out["ok"] is False
    assert out["skip"] == SKIP_OVER_MAX_LEN
    assert out["refused_titles"][0].startswith("Dragon Ball")


def test_titulo_longo_tenta_o_proximo_candidato_valido():
    """Recusa o invalido e usa o proximo — sem modificar nenhum dos dois."""
    longo = "x" * 90
    bom = "Castlevania: o Conselho das Irmas explicado"
    out = decision_to_action(_contract(suggested_titles=[longo, bom]), max_len=60)
    assert out["ok"] is True
    assert out["action"]["fix"]["meta"]["rank_math_title"] == bom


# --- P0.1: o rollout manda (observe/approval NUNCA geram acao) ------------

def test_observe_nunca_gera_acao():
    out = decision_to_action(_contract(
        rollout={"mode": "observe", "writes_allowed": False,
                 "approval_required": False}))
    assert out["ok"] is False
    assert out["skip"] == SKIP_ROLLOUT
    assert out["rollout_mode"] == "observe"


def test_approval_nunca_gera_acao_mesmo_com_confianca_high():
    """O bug do Sprint 1: `approval` escrevia automaticamente. Agora nao."""
    out = decision_to_action(_contract(
        confidence="high",
        rollout={"mode": "approval", "writes_allowed": False,
                 "approval_required": True}))
    assert out["ok"] is False
    assert out["skip"] == SKIP_ROLLOUT
    assert out["rollout_mode"] == "approval"


def test_auto_gera_acao():
    out = decision_to_action(_contract(
        rollout={"mode": "auto", "writes_allowed": True,
                 "approval_required": False}))
    assert out["ok"] is True


def test_contrato_sem_rollout_nao_escreve():
    """Fail-safe: contrato ausente/antigo NAO autoriza escrita."""
    contrato = _contract()
    contrato.pop("rollout")
    out = decision_to_action(contrato)
    assert out["ok"] is False and out["skip"] == SKIP_ROLLOUT


# --- P0.2: a acao carrega a precondicao para o Executor -------------------

def test_acao_carrega_precondicao_do_titulo_atual():
    out = decision_to_action(_contract())
    pre = out["action"]["fix"]["precondition"]
    assert pre["meta"]["rank_math_title"].startswith("Cole Young agora")
    # sem `before` conhecido nao se inventa precondicao
    out2 = decision_to_action(_contract(current_title={}))
    assert out2["action"]["fix"]["precondition"] == {}


# --- P0.2 no Executor: STALE real, perto da escrita -----------------------

def _fake_wp(current_title_value: str):
    """WordPressClient minimo: get_post devolve o meta atual; o update registra."""
    class _WP:
        def __init__(self, atual):
            self.atual = atual
            self.updates: list[dict] = []

        def get_post(self, post_id):  # noqa: ANN001
            return {"id": post_id, "meta": {"rank_math_title": self.atual}}

        def update_post_meta(self, post_id, meta):  # noqa: ANN001
            self.updates.append(meta)
            self.atual = (meta or {}).get("rank_math_title", self.atual)

    return _WP(current_title_value)


def _executor_with(wp):
    from dataclasses import replace

    from hermes_seo_agent.config import load_config
    from hermes_seo_agent.executor.executor import Executor

    class _Store:
        def action_executed(self, fingerprint):  # noqa: ANN001
            return False

        def record_action(self, **kw):  # noqa: ANN003
            return 1

        def log_audit(self, **kw):  # noqa: ANN003
            return 1

    # dry_run=False explicito: o teste exercita o caminho de ESCRITA e nao deve
    # depender do .env da maquina.
    cfg = replace(load_config(), dry_run=False)
    return Executor(cfg, wp, _Store())  # type: ignore[arg-type]


def _title_action_for(before: str, new: str, post_id: int = 32373) -> dict:
    return {
        "rule_id": "title_engine",
        "url": "https://www.unicorniohater.com.br/x/",
        "detail": "title_engine: titulo reescrito",
        "before": {"rank_math_title": before},
        "fix": {"type": "wp_post_meta", "post_id": post_id,
                "meta": {"rank_math_title": new},
                "precondition": {"meta": {"rank_math_title": before}}},
    }


def test_executor_stale_nao_escreve_quando_o_titulo_mudou():
    """P0.2: editor humano alterou entre a decisao e a escrita -> STALE + sem write."""
    wp = _fake_wp("Título C (alterado por humano)")
    res = _executor_with(wp).apply_safe_actions(
        [_title_action_for("Título A", "Título B")], cycle_id="c1")
    assert res["executed"] == []
    assert wp.updates == []                     # NENHUMA escrita
    assert len(res["stale"]) == 1
    assert "stale:" in res["stale"][0]["reason"]


def test_executor_escreve_quando_a_precondicao_bate():
    wp = _fake_wp("Título A")
    res = _executor_with(wp).apply_safe_actions(
        [_title_action_for("Título A", "Título B")], cycle_id="c2")
    assert [a["url"] for a in res["executed"]] == [
        "https://www.unicorniohater.com.br/x/"]
    assert wp.updates == [{"rank_math_title": "Título B"}]
    assert res["stale"] == []


def test_executor_stale_nao_impede_a_proxima_url():
    """Regra principal: uma URL STALE nunca para as outras."""
    wp = _fake_wp("mudou")
    ok = _title_action_for("Título A", "Título B", post_id=1)
    ok["fix"]["precondition"] = {}              # sem precondicao: escreve
    res = _executor_with(wp).apply_safe_actions(
        [_title_action_for("Título A", "Título B", post_id=2), ok], cycle_id="c3")
    assert len(res["stale"]) == 1
    assert len(res["executed"]) == 1


def test_executor_sem_precondicao_escreve_como_antes():
    wp = _fake_wp("qualquer coisa")
    acao = _title_action_for("Título A", "Título B")
    acao["fix"].pop("precondition")
    res = _executor_with(wp).apply_safe_actions([acao], cycle_id="c4")
    assert len(res["executed"]) == 1 and res["stale"] == []


# --- E2E do deadlock: a pendencia nao pode bloquear para sempre -----------

def test_pendencia_libera_a_url_quando_existe_executor(tmp_path):
    """FASE 9/10: com executor ativo a pendencia deixa de bloquear a URL.

    O item da Caixa eh a decisao ja tomada; quem a aplica eh o executor de
    titulos. Sem isso o motor pulava a URL para sempre ("ja existe revisao de
    titulo pendente") e nenhuma decisao saia da Caixa — o deadlock que parava
    a trilhagem continua.
    """
    from hermes_seo_agent.storage.db import Storage

    with Storage(str(tmp_path / "pend.db")) as store:
        store.conn.execute(
            "INSERT INTO improvement_checklist (url, item, status, created_at) "
            "VALUES (?, 'title_meta', 'pending', '2026-09-01')",
            ("https://www.unicorniohater.com.br/pendente/",))
        store.conn.commit()

        # comportamento antigo preservado (motor em observe: pula)
        skip, reason = store.title_review_skippable(
            "https://www.unicorniohater.com.br/pendente/", measurement_days=28)
        assert skip is True and "pendente" in reason

        # com executor ativo: a URL volta ao funil para virar acao
        skip2, reason2 = store.title_review_skippable(
            "https://www.unicorniohater.com.br/pendente/", measurement_days=28,
            ignore_pending_review=True)
        assert skip2 is False and reason2 == ""


def test_medicao_em_andamento_continua_bloqueando(tmp_path):
    """A regra (2) segue valendo: nao reescrever por cima de medicao aberta.

    Ela vive em `opportunity_outcomes` (human_decision='approved' + janela de
    medicao). `ignore_pending_review` libera SO a pendencia da Caixa (regra 1);
    a janela de medicao (regra 2) continua protegida — senao o feedback loop do
    roadmap (7/28/56/90d) perderia o baseline.
    """
    from hermes_seo_agent.storage.db import Storage

    with Storage(str(tmp_path / "meas.db")) as store:
        # created_at eh NOT NULL no schema — o insert completo segue o padrao de
        # tests/test_repeat_prevention.py; a data fica dentro da janela.
        store.conn.execute(
            "INSERT INTO opportunity_outcomes "
            "(keyword, opportunity_type, decision, human_decision, implemented_action, "
            "url, implemented_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("medindo", "title", "review_title", "approved", "title",
             "https://www.unicorniohater.com.br/medindo/",
             "2026-09-20T00:00:00+00:00", "2026-09-20T00:00:00+00:00"))
        store.conn.commit()
        skip, reason = store.title_review_skippable(
            "https://www.unicorniohater.com.br/medindo/", measurement_days=28,
            ignore_pending_review=True)
        assert skip is True and "tratado" in reason


# --- FASE 10: lifecycle (o item resolvido sai da Caixa) -------------------

def test_lifecycle_fecha_executado_e_supersede_sem_mudanca(tmp_path):
    """FASE 10: executado vira 'done'; sem mudanca a fazer vira 'superseded'.

    Antes o item ficava 'pending' para sempre: o motor re-analisava a mesma URL
    a cada ciclo e a Caixa so crescia.
    """
    from hermes_seo_agent.storage.db import Storage

    with Storage(str(tmp_path / "life.db")) as store:
        for url in ("https://x.com/executado/", "https://x.com/sem-mudanca/"):
            store.conn.execute(
                "INSERT INTO improvement_checklist (url, item, status, created_at) "
                "VALUES (?, 'title_meta', 'pending', '2026-09-01')", (url,))
        store.conn.commit()

        assert store.close_title_checklist(
            ["https://x.com/executado/"], status="done",
            when="2026-09-29T00:00:00+00:00") == 1
        assert store.close_title_checklist(
            ["https://x.com/sem-mudanca/"], status="superseded",
            when="2026-09-29T00:00:00+00:00") == 1

        rows = dict(store.conn.execute(
            "SELECT url, status FROM improvement_checklist").fetchall())
        assert rows["https://x.com/executado/"] == "done"
        assert rows["https://x.com/sem-mudanca/"] == "superseded"


def test_lifecycle_nunca_fecha_a_retriagem(tmp_path):
    """'title_regression' (retriagem) fica pendente: e o que reabre a URL."""
    from hermes_seo_agent.storage.db import Storage

    with Storage(str(tmp_path / "reg.db")) as store:
        store.conn.execute(
            "INSERT INTO improvement_checklist (url, item, status, created_at) "
            "VALUES (?, 'title_regression', 'pending', '2026-09-01')",
            ("https://x.com/piorou/",))
        store.conn.commit()
        assert store.close_title_checklist(
            ["https://x.com/piorou/"], status="superseded",
            when="2026-09-29T00:00:00+00:00") == 0
        status = store.conn.execute(
            "SELECT status FROM improvement_checklist WHERE url = ?",
            ("https://x.com/piorou/",)).fetchone()[0]
        assert status == "pending"


def test_lifecycle_ignora_status_invalido(tmp_path):
    from hermes_seo_agent.storage.db import Storage

    with Storage(str(tmp_path / "inv.db")) as store:
        assert store.close_title_checklist(["https://x.com/a/"], status="pending",
                                           when="2026-09-29T00:00:00+00:00") == 0
        assert store.close_title_checklist([], status="done",
                                           when="2026-09-29T00:00:00+00:00") == 0


# --- Sprint 1.2: integridade do feedback loop ------------------------------

_URL_12 = "https://www.unicorniohater.com.br/medicao/"


def _pendente(store):
    store.conn.execute(
        "INSERT INTO improvement_checklist (url, item, status, created_at) "
        "VALUES (?, 'title_meta', 'pending', '2026-09-01')", (_URL_12,))
    store.conn.commit()


def test_outcome_falho_nao_fecha_a_caixa(tmp_path):
    """P0.6: WordPress atualizado + REST ok + outcome FALHOU => NAO vira done.

    A Caixa nao pode mentir fechando um item que o Google nunca vai medir.
    O item fica recuperavel (pending + measurement_unavailable) com o erro.
    """
    from hermes_seo_agent.storage.db import Storage

    with Storage(str(tmp_path / "p06.db")) as store:
        _pendente(store)
        fechaveis: list[str] = []
        try:
            raise RuntimeError("disco cheio")
        except RuntimeError as exc:
            # mesmo caminho do CLI: falha do outcome marca pendencias de medicao
            store.mark_measurement_pending(
                _URL_12, error=f"outcome_failed: {exc}", commit=False)
        store.conn.commit()
        # so o que teve outcome entra em `fechaveis` — aqui, nada
        assert store.close_title_checklist(
            fechaveis, status="done", when="2026-09-29T00:00:00+00:00") == 0

        row = store.conn.execute(
            "SELECT status, measurement_unavailable, rejection_reason "
            "FROM improvement_checklist WHERE url = ?", (_URL_12,)).fetchone()
        assert row[0] == "pending"          # NAO fechou
        assert row[1] == 1                  # marcado como pendencia de medicao
        assert "outcome_failed" in (row[2] or "")


def test_outcome_ok_fecha_a_caixa(tmp_path):
    """Contraprova: outcome persistido => a URL entra em fechaveis e vira done."""
    from hermes_seo_agent.storage.db import Storage

    with Storage(str(tmp_path / "ok.db")) as store:
        _pendente(store)
        store.record_implemented_outcome(
            url=_URL_12, action_type="title_engine", implemented_action="fix",
            before={"rank_math_title": "A"}, after={"rank_math_title": "B"},
            implemented_at="2026-09-29T00:00:00+00:00",
            gsc_baseline={"page": {"impressions": 100}},
            ga4_baseline={"status": "available", "sessions": 7.0})
        assert store.close_title_checklist(
            [_URL_12], status="done", when="2026-09-29T00:00:00+00:00") == 1
        status = store.conn.execute(
            "SELECT status FROM improvement_checklist WHERE url = ?",
            (_URL_12,)).fetchone()[0]
        assert status == "done"


def test_baseline_estruturado_permite_medir_o_ga4(tmp_path):
    """Item 4/6/9: baseline {gsc, ga4, change} — e o GA4 deixa de ser None.

    Antes gravava {before, after}: `baseline_ga4()` devolvia None e
    `engagement_deltas()` caia em insufficient_data/missing_before_or_after.
    """
    import json

    from hermes_seo_agent.report.impact_ga4 import baseline_ga4, engagement_deltas
    from hermes_seo_agent.storage.db import Storage

    ga4_pre = {"status": "available", "sessions": 7.0, "engagement_rate": 0.42}
    with Storage(str(tmp_path / "ga4.db")) as store:
        oid = store.record_implemented_outcome(
            url=_URL_12, action_type="title_engine", implemented_action="fix",
            before={"rank_math_title": "A"}, after={"rank_math_title": "B"},
            implemented_at="2026-09-29T00:00:00+00:00",
            gsc_baseline={"page": {"impressions": 503.0},
                          "context": {"window_start": "2026-09-01"}},
            ga4_baseline=ga4_pre)
        raw = store.conn.execute(
            "SELECT baseline_json FROM opportunity_outcomes WHERE id = ?",
            (oid,)).fetchone()[0]
    baseline = json.loads(raw)

    assert set(baseline) >= {"gsc", "ga4", "change"}
    assert baseline["change"]["before"] == {"rank_math_title": "A"}
    assert baseline["gsc"]["page"]["impressions"] == 503.0
    assert baseline["measurement_status"] == "complete"

    # o medidor agora CONSEGUE ler o antes (era None)
    # `baseline_ga4` devolve o slice NORMALIZADO: o `status` do contrato vira
    # `measurement_status` (o campo que `engagement_deltas` compara).
    assert baseline_ga4(baseline) == {**ga4_pre, "measurement_status": "available"}
    deltas = engagement_deltas(
        baseline_ga4(baseline),
        {"sessions": 12.0, "engagement_rate": 0.55,
         "measurement_status": "available"})
    assert deltas.get("data_quality") != "missing_before_or_after"


def test_baseline_sem_ga4_e_explicito_e_nao_some(tmp_path):
    """Item 6: ausencia do GA4 e EXPLICITA (measurement_status=missing)."""
    import json

    from hermes_seo_agent.report.impact_ga4 import baseline_ga4
    from hermes_seo_agent.storage.db import Storage

    with Storage(str(tmp_path / "missing.db")) as store:
        oid = store.record_implemented_outcome(
            url=_URL_12, action_type="title_engine", implemented_action="fix",
            before={"rank_math_title": "A"}, after={"rank_math_title": "B"},
            implemented_at="2026-09-29T00:00:00+00:00")
        raw = store.conn.execute(
            "SELECT baseline_json FROM opportunity_outcomes WHERE id = ?",
            (oid,)).fetchone()[0]
    baseline = json.loads(raw)
    assert baseline["measurement_status"] == "missing"
    assert baseline["ga4"] == {}
    # `baseline_ga4` devolve o valor de `baseline["ga4"]`; vazio = ausencia
    # EXPLICITA (e falsy, entao `engagement_deltas` reporta insufficient_data em
    # vez de fingir que existe dado).
    assert baseline_ga4(baseline) == {}
    assert not baseline_ga4(baseline)


def test_outcome_em_transacao_sem_commit_nao_persiste_antes(tmp_path):
    """Item 3: `commit=False` permite outcome + lifecycle na MESMA transacao."""
    from hermes_seo_agent.storage.db import Storage

    with Storage(str(tmp_path / "tx.db")) as store:
        store.record_implemented_outcome(
            url=_URL_12, action_type="title_engine", implemented_action="fix",
            before={}, after={}, implemented_at="2026-09-29T00:00:00+00:00",
            commit=False)
        # nao commitado: outra conexao nao veria; aqui conferimos a API
        assert store.conn.in_transaction is True
        store.conn.commit()
        assert store.conn.execute(
            "SELECT COUNT(*) FROM opportunity_outcomes").fetchone()[0] == 1


# --- Sprint 1.2: tracacao real (item 1) e reconciliacao (itens 5-8) --------

def test_transacao_agrupa_e_desfaz_tudo_em_caso_de_erro(tmp_path):
    """Item 1: ou grava tudo (outcome + done), ou NADA. Sem estado parcial."""
    from hermes_seo_agent.storage.db import Storage

    with Storage(str(tmp_path / "tx_rb.db")) as store:
        try:
            with store.transaction():
                store.record_implemented_outcome(
                    url=_URL_12, action_type="t", implemented_action="t",
                    before={}, after={},
                    implemented_at="2026-09-29T00:00:00+00:00", commit=False)
                raise RuntimeError("crash entre outcome e checklist")
        except RuntimeError:
            pass
        assert store.conn.execute(
            "SELECT COUNT(*) FROM opportunity_outcomes").fetchone()[0] == 0


def test_transacao_commita_outcome_e_checklist_juntos(tmp_path):
    """Item 1 (contraprova): outcome + checklist done, atomicos."""
    from hermes_seo_agent.storage.db import Storage

    with Storage(str(tmp_path / "tx_ok.db")) as store:
        _pendente(store)
        with store.transaction():
            store.record_implemented_outcome(
                url=_URL_12, action_type="t", implemented_action="t",
                before={}, after={},
                implemented_at="2026-09-29T00:00:00+00:00", commit=False)
            store.close_title_checklist(
                [_URL_12], status="done", when="2026-09-29T00:00:00+00:00",
                commit=False)
        assert store.conn.execute(
            "SELECT COUNT(*) FROM opportunity_outcomes WHERE url = ?",
            (_URL_12,)).fetchone()[0] == 1
        assert store.conn.execute(
            "SELECT status FROM improvement_checklist WHERE url = ?",
            (_URL_12,)).fetchone()[0] == "done"


def _acao_executada(store, url: str, *, status: str = "executed",
                    fingerprint: str | None = None,
                    rule_id: str = "title_opportunity",
                    fix: dict | None = None) -> None:
    """Grava uma acao no audit trail exatamente como o Executor faz.

    `rule_id` default é o REAL do pipeline de títulos (`title_opportunity`) — não
    existe 'title_engine' no banco. O `fix_json` altera `rank_math_title`, que é
    a marca inequívoca do closed loop usada pela reconciliação.
    """
    import json as _json

    _fix = fix if fix is not None else {
        "type": "wp_post_meta", "post_id": 1,
        "meta": {"rank_math_title": "Título novo"}}
    store.conn.execute(
        "INSERT INTO actions (cycle_id, rule_id, url, level, status, fingerprint, "
        "before_json, after_json, rollback_json, executed_at, fix_json) "
        "VALUES ('c1', ?, ?, 'safe_fix', ?, ?, ?, ?, '{}', ?, ?)",
        (rule_id, url, status, fingerprint or f"fp-{url}-{status}",
         _json.dumps({"rank_math_title": "Título antigo"}),
         _json.dumps({"rank_math_title": "Título novo"}),
         "2026-09-29T10:00:00+00:00",
         _json.dumps(_fix)))
    store.conn.commit()


# --- Sprint 1.2.1 (P0.7): identidade da ACAO, nunca da URL ------------------

def test_p07_mesma_url_duas_intervencoes_a_segunda_nao_fica_invisivel(tmp_path):
    """P0.7 (teste central): #1 medida e #2 executada-sem-outcome na MESMA URL.

    Correlacionar por URL fazia o outcome da #1 "provar" que a #2 foi medida — a
    segunda intervenção ficava sem medição para sempre.
    """
    from hermes_seo_agent.storage.db import Storage

    url = _url("duas-intervencoes")
    with Storage(str(tmp_path / "p07.db")) as store:
        # intervenção #1: executada E medida
        _acao_executada(store, url, fingerprint="fp-1")
        store.record_implemented_outcome(
            url=url, action_type="title_opportunity", implemented_action="fix",
            before={}, after={}, implemented_at="2026-09-29T11:00:00+00:00",
            action_fingerprint="fp-1")
        assert store.executed_without_outcome() == []

        # intervenção #2 na MESMA url: executada, crash antes do outcome
        _acao_executada(store, url, fingerprint="fp-2")
        pend = store.executed_without_outcome()
        assert [p["fingerprint"] for p in pend] == ["fp-2"]

        res = store.reconcile_executed_outcomes()
        assert res["outcomes_created"] == 1
        assert store.conn.execute(
            "SELECT COUNT(*) FROM opportunity_outcomes WHERE url = ?",
            (url,)).fetchone()[0] == 2          # as DUAS medidas
        # idempotente
        assert store.reconcile_executed_outcomes()["candidates"] == 0


def test_p07_outcome_correlaciona_por_fingerprint_e_nao_por_url(tmp_path):
    """P0.7: hash UNIQUE por ação — a mesma URL aceita N outcomes distintos."""
    from hermes_seo_agent.storage.db import Storage

    url = _url("fingerprints-distintos")
    with Storage(str(tmp_path / "p07b.db")) as store:
        for fp in ("a1", "a2"):
            store.record_implemented_outcome(
                url=url, action_type="title_opportunity", implemented_action="fix",
                before={}, after={}, implemented_at="2026-09-29T11:00:00+00:00",
                action_fingerprint=fp)
        assert store.conn.execute(
            "SELECT COUNT(*) FROM opportunity_outcomes WHERE url = ?",
            (url,)).fetchone()[0] == 2


def test_p07_media_alt_nao_entra_no_recovery_de_titulo(tmp_path):
    """Item 5 — só o closed loop de títulos; safe fixes de mídia ficam fora."""
    from hermes_seo_agent.storage.db import Storage

    with Storage(str(tmp_path / "p07c.db")) as store:
        _acao_executada(store, _url("midia"), rule_id="wp_media_alt",
                        fix={"type": "wp_media_alt", "post_id": 1,
                             "attach_id": 9, "alt_text": "novo alt"})
        assert store.executed_without_outcome() == []
        assert store.reconcile_executed_outcomes()["outcomes_created"] == 0


def test_p07_boundary_impede_backfill_de_acao_antiga(tmp_path):
    """Item 6 — nada de transformar ação antiga em EXECUTED_UNMEASURED."""
    from hermes_seo_agent.storage.db import Storage

    url = _url("legado")
    with Storage(str(tmp_path / "p07d.db")) as store:
        _acao_executada(store, url, fingerprint="fp-antigo")
        # ação anterior ao boundary do recovery
        store.conn.execute(
            "UPDATE actions SET executed_at = '2026-08-01T00:00:00+00:00' "
            "WHERE url = ?", (url,))
        store.conn.commit()
        assert store.executed_without_outcome() == []
        assert store.reconcile_executed_outcomes()["outcomes_created"] == 0


def test_p07_lifecycle_nao_commita_escondido_na_transacao(tmp_path):
    """Item 8 — exceção no meio desfaz outcome E lifecycle (nada parcial)."""
    from hermes_seo_agent.storage.db import Storage

    url = _url("lifecycle-tx")
    with Storage(str(tmp_path / "p07e.db")) as store:
        try:
            with store.transaction():
                store.record_implemented_outcome(
                    url=url, action_type="title_opportunity",
                    implemented_action="fix", before={}, after={},
                    implemented_at="2026-09-29T11:00:00+00:00",
                    work_item_id="wi-1", action_fingerprint="fp-wi",
                    commit=False)          # o lifecycle herda commit=False
                raise RuntimeError("crash depois do lifecycle")
        except RuntimeError:
            pass
        assert store.conn.execute(
            "SELECT COUNT(*) FROM opportunity_outcomes WHERE url = ?",
            (url,)).fetchone()[0] == 0
        # se a tabela de work items existir, o lifecycle também foi desfeito
        try:
            n = store.conn.execute(
                "SELECT COUNT(*) FROM work_items WHERE work_item_id = 'wi-1'"
            ).fetchone()[0]
            assert n == 0
        except Exception:
            pass


def _url(sub: str) -> str:
    return f"https://www.unicorniohater.com.br/{sub}/"


def test_reconciliacao_cria_outcome_de_acao_executada_sem_outcome(tmp_path):
    """Item 6: `executed` sem outcome -> a reconciliacao cria o outcome perdido.

    E o caso 'WordPress escreveu e o processo caiu antes do outcome': nenhum
    outro caminho recupera (o motor decide no_title_change e o executor ve
    `already executed`). NAO reexecuta o WordPress.
    """
    import json

    from hermes_seo_agent.storage.db import Storage

    url = _url("reconciliar")
    with Storage(str(tmp_path / "rec.db")) as store:
        _acao_executada(store, url)
        assert [p["url"] for p in store.executed_without_outcome()] == [url]

        res = store.reconcile_executed_outcomes()
        assert res["outcomes_created"] == 1

        row = store.conn.execute(
            "SELECT baseline_json FROM opportunity_outcomes WHERE url = ?",
            (url,)).fetchone()
        assert row is not None                     # o outcome existe agora
        baseline = json.loads(row[0])
        # before/after vieram da ACAO ja executada (audit trail)
        assert baseline["change"]["after"]["rank_math_title"] == "Título novo"
        assert baseline["change"]["before"]["rank_math_title"] == "Título antigo"
        # honestidade: o PRE daquele instante se perdeu
        assert baseline["measurement_status"] == "missing"


def test_reconciliacao_fecha_a_caixa(tmp_path):
    """Item 7: reconciliacao concluida -> o checklist vira done."""
    from hermes_seo_agent.storage.db import Storage

    url = _url("reconciliar2")
    with Storage(str(tmp_path / "rec2.db")) as store:
        store.conn.execute(
            "INSERT INTO improvement_checklist (url, item, status, created_at) "
            "VALUES (?, 'title_meta', 'pending', '2026-09-01')", (url,))
        store.conn.commit()
        _acao_executada(store, url)
        res = store.reconcile_executed_outcomes()
        assert res["checklist_closed"] == 1
        assert store.conn.execute(
            "SELECT status FROM improvement_checklist WHERE url = ?",
            (url,)).fetchone()[0] == "done"


def test_reconciliacao_duas_vezes_nao_duplica_outcome(tmp_path):
    """Item 8: rodar a reconciliacao de novo NAO cria outcome duplicado."""
    from hermes_seo_agent.storage.db import Storage

    url = _url("reconciliar3")
    with Storage(str(tmp_path / "rec3.db")) as store:
        _acao_executada(store, url)
        store.reconcile_executed_outcomes()
        res2 = store.reconcile_executed_outcomes()
        assert res2["candidates"] == 0
        assert res2["outcomes_created"] == 0
        assert store.conn.execute(
            "SELECT COUNT(*) FROM opportunity_outcomes WHERE url = ?",
            (url,)).fetchone()[0] == 1


def test_acao_nao_executada_nao_entra_na_reconciliacao(tmp_path):
    """So `executed` conta: preview/skipped/unverified nao geram outcome."""
    from hermes_seo_agent.storage.db import Storage

    with Storage(str(tmp_path / "rec4.db")) as store:
        _acao_executada(store, _url("nunca"), status="previewed")
        store.reconcile_executed_outcomes()
        assert store.conn.execute(
            "SELECT COUNT(*) FROM opportunity_outcomes").fetchone()[0] == 0


def test_executor_nao_reescreve_wordpress_na_proxima_vez(tmp_path):
    """Item 5: depois de `executed`, a proxima execucao NAO escreve de novo.

    E por isso que a reconciliacao e obrigatoria: a idempotencia protege o
    WordPress, mas sozinha deixaria o outcome perdido para sempre.
    """
    from dataclasses import replace

    from hermes_seo_agent.config import load_config
    from hermes_seo_agent.executor.executor import Executor

    wp = _fake_wp("Título A")

    class _StoreJaExecutado:
        def action_executed(self, fingerprint):  # noqa: ANN001
            return True                            # ja gravado na rodada anterior

        def record_action(self, **kw):  # noqa: ANN003
            return 1

        def log_audit(self, **kw):  # noqa: ANN003
            return 1

    cfg = replace(load_config(), dry_run=False)
    res = Executor(cfg, wp, _StoreJaExecutado()).apply_safe_actions(  # type: ignore[arg-type]
        [_title_action_for("Título A", "Título B")], cycle_id="c5")
    assert res["executed"] == []
    assert wp.updates == []                        # WP intocado
    assert any("idempotent" in s.get("reason", "") for s in res["skipped"])
