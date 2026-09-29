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
