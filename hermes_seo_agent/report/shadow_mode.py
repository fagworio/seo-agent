"""FASE 21–24 — Shadow mode, telemetria e rollout progressivo.

Antes de o motor novo alterar qualquer coisa, ele roda EM PARALELO ao motor
atual e as divergências são persistidas (old_decision, new_decision,
reason_for_difference). Em shadow/observação NADA é publicado.

Telemetria do próprio motor e do resultado medido (7/28d) para o painel — sem
tokens, tudo determinístico.
"""

from __future__ import annotations

from typing import Any, Sequence

from .calibration import improved
from .interventions import calibration_sample, classify_intervention

# FASE 23 — rollout progressivo
ROLLOUT_MODES: tuple[str, ...] = ("observe", "approval", "auto")
MODE_OBSERVE, MODE_APPROVAL, MODE_AUTO = ROLLOUT_MODES


def rollout_policy(contract: dict[str, Any], *, mode: str = MODE_OBSERVE,
                   historical_success: dict[str, Any] | None = None) -> dict[str, Any]:
    """Etapa do rollout: observação -> caixa humana -> automação (só casos seguros).

    Etapa A (observe): gera recomendação, nenhuma escrita.
    Etapa B (approval): aprovação humana obrigatória.
    Etapa C (auto): só confidence=high + histórico suficiente + risco baixo.
    """
    mode = (mode or MODE_OBSERVE).lower()
    if mode not in ROLLOUT_MODES:
        mode = MODE_OBSERVE
    decision = str(contract.get("decision") or "")
    confidence = str(contract.get("confidence") or "low")
    context = contract.get("checks_context") or {}
    gain = context.get("coverage_gain")
    try:
        gain_value = float(gain) if gain is not None else 0.0
    except (TypeError, ValueError):
        gain_value = 0.0
    risk = "low" if (confidence == "high" and gain_value >= 0.15) else (
        "medium" if confidence in {"high", "medium"} else "high")
    history_ok = bool((historical_success or {}).get("sufficient"))

    if mode == MODE_OBSERVE:
        return {"mode": mode, "writes_allowed": False, "approval_required": False,
                "risk": risk, "historical_success_sufficient": history_ok,
                "reason": "Etapa A: somente observação (nenhuma escrita de título)"}
    if mode == MODE_APPROVAL:
        return {"mode": mode, "writes_allowed": False, "approval_required": True,
                "risk": risk, "historical_success_sufficient": history_ok,
                "reason": "Etapa B: caixa humana — aprovação obrigatória"}
    if decision != "review_title":
        return {"mode": mode, "writes_allowed": False, "approval_required": False,
                "risk": risk, "historical_success_sufficient": history_ok,
                "reason": f"automação não se aplica a {decision or 'sem decisão'}"}
    if confidence != "high" or risk != "low" or not history_ok:
        return {"mode": mode, "writes_allowed": False, "approval_required": True,
                "risk": risk, "historical_success_sufficient": history_ok,
                "reason": ("automação exige confidence=high + histórico suficiente + "
                           "risco baixo: cai na caixa humana")}
    return {"mode": mode, "writes_allowed": True, "approval_required": False,
            "risk": risk, "historical_success_sufficient": history_ok,
            "reason": "Etapa C: caso seguro (high + histórico + risco baixo)"}


# ---------------------------------------------------------------------------
# FASE 21 — Shadow mode
# ---------------------------------------------------------------------------

def _old_decision_label(old: dict[str, Any] | None) -> str:
    if not old:
        return "sem_proposta"
    return str(old.get("decision") or old.get("action") or "sem_decisao")


def reason_for_difference(old: dict[str, Any] | None,
                          new: dict[str, Any]) -> str:
    """Por que o motor novo divergiu do atual (citável)."""
    old_label = _old_decision_label(old)
    new_label = str(new.get("decision") or "")
    if old_label == new_label:
        return "mesma decisão nos dois motores"
    parts: list[str] = []
    if old is None:
        parts.append("motor atual não tinha proposta (título atual já ótimo ou sem query de valor)")
    else:
        query = old.get("primary_query") or old.get("query") or (old.get("gsc") or {}).get("query")
        if query:
            parts.append(f"motor atual decidiu por UMA query ('{query}')")
        if old.get("reason"):
            first = str(old["reason"][0] if isinstance(old["reason"], list) else old["reason"])
            if first:
                parts.append(f"atual: {first}")
    families = [f for f in (new.get("query_families") or [])
                if f.get("intent") and f["intent"] != "geral"]
    if families:
        top = families[0]
        share = top.get("share")
        share_txt = f"{float(share)*100:.0f}%" if share is not None else "n/d"
        parts.append(f"novo: família '{top['intent']}' com {share_txt} da demanda observada")
    context = new.get("checks_context") or {}
    if context.get("coverage_gain") is not None:
        parts.append(f"ganho de cobertura observada de "
                     f"{float(context['coverage_gain'])*100:.0f} p.p.")
    failed = [k for k, v in (new.get("checks") or {}).items() if v is False]
    if failed:
        parts.append("gates não atendidos: " + ", ".join(failed))
    if new_label == "review_title" and context.get("coverage_gain"):
        parts.append("cadeia completa de evidência (demanda+família+anomalia+gap+posição)")
    return "; ".join(parts) if parts else f"motores divergiram: {old_label} -> {new_label}"


def shadow_compare(*, old: dict[str, Any] | None, new: dict[str, Any],
                   url: str = "") -> dict[str, Any]:
    """Compara motor atual x motor de famílias (nada é publicado)."""
    old_label = _old_decision_label(old)
    new_label = str(new.get("decision") or "")
    return {
        "url": url or new.get("url") or "",
        "old_decision": old_label,
        "new_decision": new_label,
        "same_decision": old_label == new_label,
        "old_confidence": (old or {}).get("confidence"),
        "new_confidence": new.get("confidence"),
        "reason_for_difference": reason_for_difference(old, new),
        "published": False,
    }


def shadow_report(pairs: Sequence[dict[str, Any]], *,
                  mode: str = "shadow") -> dict[str, Any]:
    """Relatório do shadow mode: divergências por tipo + contagem."""
    diffs = [p for p in pairs if not p.get("same_decision")]
    by_transition: dict[str, int] = {}
    for pair in diffs:
        key = f"{pair.get('old_decision')}->{pair.get('new_decision')}"
        by_transition[key] = by_transition.get(key, 0) + 1
    return {
        "mode": mode,
        "published": False,
        "compared": len(pairs),
        "divergent": len(diffs),
        "agreement_rate": round(1 - (len(diffs) / len(pairs)), 4) if pairs else None,
        "transitions": dict(sorted(by_transition.items(), key=lambda kv: -kv[1])),
        "differences": diffs,
        "note": ("shadow mode: as decisões do motor novo são registradas, nunca "
                 "publicadas"),
    }


def persist_report(storage: Any, report: dict[str, Any], *,
                   source: str = "title_engine_shadow") -> None:
    """Persiste o relatório no formato de sinal já lido pelo control plane."""
    storage.save_signal(source, report)


def load_report(storage: Any, *, source: str = "title_engine_shadow") -> dict[str, Any]:
    return (storage.get_signals() or {}).get(source) or {}


# ---------------------------------------------------------------------------
# FASE 24 — Telemetria do motor + resultados medidos
# ---------------------------------------------------------------------------

def engine_telemetry(contracts: Sequence[dict[str, Any]],
                     outcomes: Sequence[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Métricas do PRÓPRIO motor (páginas, famílias, decisões, confiança).

    Inclui `observability`: os agregados que a fase de shadow precisa olhar
    (origem/taxa de rejeição da entidade canônica, motivos de ausência de
    candidato, distribuição de rankability, cobertura semântica medida e razão de
    observação das queries). Nada aqui influencia decisão — é leitura do que o
    motor já decidiu.
    """
    pages = list(contracts or [])
    families_total = 0
    with_data = 0
    candidates_total = 0
    decisions: dict[str, int] = {}
    confidence: dict[str, int] = {}
    entity_source: dict[str, int] = {}
    canonical_rejected = 0
    canonical_total = 0
    failed_reason: dict[str, int] = {}
    observed_ratio: list[float] = []
    rankabilities: list[float] = []
    with_measured_semantics = 0
    ratios: dict[str, int] = {"thin": 0, "partial": 0, "well_observed": 0, "unknown": 0}
    for contract in pages:
        families = contract.get("query_families") or []
        families_total += len(families)
        if families:
            with_data += 1
        candidates_total += len(contract.get("candidates_evaluated") or [])
        decision = str(contract.get("decision") or "unknown")
        decisions[decision] = decisions.get(decision, 0) + 1
        label = str(contract.get("confidence") or "unknown")
        confidence[label] = confidence.get(label, 0) + 1
        entity = contract.get("entity") or {}
        source = str(entity.get("source") or "unknown")
        entity_source[source] = entity_source.get(source, 0) + 1
        if entity.get("canonical_entity"):
            canonical_total += 1
            if not entity.get("canonical_plausible"):
                canonical_rejected += 1
        if contract.get("candidate_failed_reason"):
            reason = str(contract["candidate_failed_reason"])
            failed_reason[reason] = failed_reason.get(reason, 0) + 1
        window = contract.get("signal_window") or {}
        if int(window.get("families_with_measured_semantics") or 0) > 0:
            with_measured_semantics += 1
        observation = contract.get("observation") or {}
        status = str(observation.get("status") or "unknown")
        ratios[status] = ratios.get(status, 0) + 1
        ratio = observation.get("query_observation_ratio")
        if ratio is not None:
            observed_ratio.append(float(ratio))
        for value in (contract.get("rankability") or {}).values():
            rankabilities.append(float(value))
    telemetry = {
        "pages_analyzed": len(pages),
        "pages_with_query_data": with_data,
        "families_generated": families_total,
        "avg_families_per_page": round(families_total / len(pages), 2) if pages else 0.0,
        "combination_candidates": candidates_total,
        "review_title": decisions.get("review_title", 0),
        "no_title_change": decisions.get("no_title_change", 0),
        "investigate_cause": decisions.get("investigate_cause", 0),
        "gather_more_data": decisions.get("gather_more_data", 0),
        "high_confidence": confidence.get("high", 0),
        "medium_confidence": confidence.get("medium", 0),
        "low_confidence": confidence.get("low", 0),
        "by_decision": dict(sorted(decisions.items())),
        "observability": {
            "entity_source": dict(sorted(entity_source.items())),
            "canonical_evaluated": canonical_total,
            "canonical_rejected": canonical_rejected,
            "canonical_rejection_rate": (round(canonical_rejected / canonical_total, 3)
                                         if canonical_total else None),
            "pages_with_measured_semantics": with_measured_semantics,
            "pages_with_measured_semantics_rate": (round(with_measured_semantics / len(pages), 3)
                                                   if pages else None),
            "candidate_failed_reason": dict(sorted(failed_reason.items())),
            "query_observation_ratio": {
                "by_status": ratios,
                "min": min(observed_ratio) if observed_ratio else None,
                "max": max(observed_ratio) if observed_ratio else None,
                "avg": (round(sum(observed_ratio) / len(observed_ratio), 4)
                        if observed_ratio else None),
            },
            "rankability": {
                "count": len(rankabilities),
                "min": round(min(rankabilities), 3) if rankabilities else None,
                "max": round(max(rankabilities), 3) if rankabilities else None,
                "avg": (round(sum(rankabilities) / len(rankabilities), 3)
                        if rankabilities else None),
            },
        },
    }
    if outcomes is not None:
        telemetry["results"] = measurement_summary(outcomes)
    return telemetry


def stratified_sample(contracts: Sequence[dict[str, Any]], *,
                      per_stratum: int = 1) -> dict[str, Any]:
    """Amostra ESTRATIFICADA por (decisão, confiança) para inspeção humana.

    FASE 22: em vez de ler 200 contratos, o operador lê N por estrato e confere
    queries, famílias, percentuais, baseline, cobertura, candidato, score e
    decisão.
    """
    n = max(int(per_stratum or 1), 1)
    buckets: dict[str, list[dict[str, Any]]] = {}
    for contract in contracts or []:
        key = f"{contract.get('decision') or 'unknown'}|{contract.get('confidence') or 'unknown'}"
        buckets.setdefault(key, []).append(contract)
    sample: list[dict[str, Any]] = []
    for key in sorted(buckets):
        sample.extend(buckets[key][:n])
    return {"strata": {key: len(value) for key, value in sorted(buckets.items())},
            "per_stratum": n, "sample": sample}


def measurement_summary(outcomes: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Resultados medidos das alterações SEO (7/28/56/90d)."""
    sample = calibration_sample(outcomes or [])
    windows: dict[str, int] = {}
    for window in ("7d", "28d", "56d", "90d"):
        measured = [o for o in sample if o.get(f"after_{window}")]
        states = [improved(o) for o in measured]
        windows[f"title_changes_measured_{window}"] = len(measured)
        windows[f"improved_{window}"] = sum(1 for s in states if s is True)
        windows[f"neutral_{window}"] = sum(1 for s in states if s is None)
        windows[f"regressed_{window}"] = sum(1 for s in states if s is False)
    return windows


def shadow_outcome_case(contract: dict[str, Any], *, source: str = "title_engine",
                        after: dict[str, Any] | None = None) -> dict[str, Any]:
    """Outcome do shadow/medição — já classificado por TIPO de intervenção."""
    from .interventions import outcome_record

    intervention = classify_intervention(source=source,
                                         intervention_type="seo_title_optimization")
    candidate = contract.get("candidate") or {}
    factors = candidate.get("factors") or {}
    features = {
        "demand_coverage_before": (contract.get("current_title") or {}).get("coverage"),
        # cobertura MEDIDA no título proposto (não a da combinação abstrata)
        "demand_coverage_after": candidate.get("observed_demand_coverage"),
        "primary_intent": (candidate.get("intents") or [None])[0],
        "secondary_intent": (candidate.get("intents") or [None, None])[1]
        if len(candidate.get("intents") or []) > 1 else None,
        "query_rankability": (contract.get("rankability") or {}).get(
            (candidate.get("families") or [None])[0]),
        "baseline_percentile": (contract.get("baseline") or {}).get("verdict"),
        "position_before": (contract.get("page") or {}).get("position"),
        "ctr_before": (contract.get("page") or {}).get("ctr"),
        "family_share": max([f.get("share") or 0 for f in
                             (contract.get("query_families") or [])] or [None]),
        "title_score": candidate.get("score"),
        "confidence": contract.get("confidence"),
        # OBRIGATÓRIO p/ calibração real: os sete fatores que produziram o score
        # (sem proxy, sem rótulo textual) + a confiança numérica.
        "score_factors": factors,
        "confidence_score": (contract.get("confidence_detail") or {}).get("score"),
    }
    return outcome_record(
        url=contract.get("url", ""), intervention=intervention,
        before={"title": (contract.get("current_title") or {}).get("title"),
                "candidate_title": candidate.get("title"),
                "combination_coverage": candidate.get("combination_coverage"),
                "position": features["position_before"],
                "ctr": features["ctr_before"]},
        candidate_features=features, factors=factors,
        confidence_score=features.get("confidence_score"), after=after or {},
        extra={"decision": contract.get("decision"),
               "model_version": contract.get("model_version"),
               "weights_version": contract.get("weights_version"),
               # mesma visão usada por `improved()`/calibração (janelas medidas)
               "results": {w: v for w, v in (after or {}).items() if v}})
