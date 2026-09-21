# ADR-0011 — Motor de título por famílias de query (decisão combinatória determinística)

## Status
Implementado (P0–P6). Modo de operação padrão: **observação** (`TITLE_ENGINE_MODE=observe`).

## Contexto
A decisão de título vinha de **uma query individual**: o gerador estratégico
(`tools/title_opportunities.py`) escolhia a query de maior valor estatístico e
cruzava com o baseline do próprio site (`empirical_title_case`, SEO-INC-017/018/019).
Isso tem três limites estruturais:

1. **Variações da mesma pergunta competem entre si.** `gojo idade`,
   `idade do gojo` e `quantos anos tem gojo` eram três oportunidades, não uma
   intenção com 1.070 impressões.
2. **Nenhuma visão de demanda da página.** Não havia percentual de demanda por
   intenção, nem quanto o título atual já cobre dessa demanda.
3. **Sem combinatória.** O título só podia "adicionar uma keyword", nunca avaliar
   `idade + poderes` (78% da demanda observada) versus cada intenção sozinha.

## Decisão
A decisão passa a ser **determinística sobre famílias de intenção**, sem LLM:

```
GSC -> famílias -> demanda percentual -> baseline -> intenção -> rankability
    -> combinações -> score -> gates -> decisão -> título
```

Regras fixadas:

- **GSC é a evidência de demanda**; GA4 e Trends são auxiliares. Trends não cria
  oportunidade; GA4 não escolhe keyword (só confiança e pós-clique).
- **Ausência de dado nunca é zero** (`share=None`, `interest=None`, gate `False`
  com motivo declarado).
- Falamos de **`observed_query_share`** — share do universo OBSERVADO no GSC,
  nunca "cobertura total das buscas".
- O score é **índice de decisão 0–100** ("Title Opportunity Score: 78/100"),
  nunca "probabilidade de melhorar/rankear".
- **Alterar título exige a cadeia completa** de gates; score alto sozinho não
  autoriza nada.
- **Integridade editorial ≠ otimização SEO** (`title_integrity_repair` não
  calibra o motor de título).
- Nenhuma etapa analítica consome tokens. LLM é opcional e **só redige**
  (`TITLE_GENERATION_MODE=hybrid`), sempre sob validação determinística.

## Fluxo de decisão (gates)
Para `review_title` exigir simultaneamente:

| Gate | Regra |
| ---- | ----- |
| `page_impressions_sufficient` | impressões da página ≥ mínimo (default 100) |
| `query_family_demand_sufficient` | maior família ≥ mínimo (default 10 impressões) |
| `baseline_anomaly` | CTR `below_p10` ou `below_comparable` no **próprio** segmento |
| `title_coverage_gap` | candidato eleva a cobertura em ≥ 5 p.p. |
| `position_actionable` | posição conhecida e ≤ 30 |
| `entity_preserved` | candidato mantém a entidade indexada |
| `evidence_confidence` | confiança da evidência ≥ 0.5 |

Degradação: sem demanda/posição → `gather_more_data`; sem anomalia de baseline,
sem gap ou entidade perdida → `no_title_change`; GA4 com pós-clique ruim →
`investigate_cause`. **GA4 ausente não bloqueia** — rebaixa `high` para `medium`.

## Title Candidate Score (FASE 7)
`demand_coverage 35% + intent_fit 20% + rankability 15% + headroom 10% +
historical_success 10% + trend 5% + confidence 5%`. Os pesos são calibráveis
(FASE 13) e versionados (`model_version`, `weights_version`, `sample_count`,
`calibrated_at`); variação relativa máxima por ciclo: ±5% (30–100 outcomes) e
±10% (> 100); **abaixo de 30 outcomes os pesos padrão são mantidos**.

## Módulos
| Arquivo | Escopo |
| ------- | ------ |
| `report/query_families.py` | F1–F4: dicionário de intenção, entidade, famílias, demand share, term/intent support, cobertura do título atual |
| `report/title_engine.py` | F5–F10, F17, F18: combinações, rankability por família, score, gates, Trends/GA4, Evidence Contract, explicabilidade |
| `report/title_generator.py` | F15, F16: templates determinísticos, validador, briefing estruturado para LLM opcional |
| `report/interventions.py` | F11–F14: outcome, tipos de intervenção, calibração versionada, historical success |
| `report/shadow_mode.py` | F21, F23, F24: shadow mode, rollout A/B/C, telemetria |

Reaproveitamento obrigatório (nada de fórmula paralela): `rankability_v2`
(`query_rankability`, `headroom`, `confidence_v2`, `query_distribution`),
`report/baseline.py` (percentis do próprio site), `report/calibration.py`
(`improved`), `tools/intent.py` (normalização), `tools/title_opportunities.py`
(`INTENT_GROUPS`, `entity_of`, motor atual para o shadow), `market_intelligence`
(Trends com cache persistente).

## CLI
- `title-engine [--shadow] [--explain] [--persist] [--write] [--mode ...]` —
  roda o motor (observação por padrão; **nunca publica título**).
- `title-weights --persist` — ciclo fechado de calibração: outcomes →
  pesos versionados (`signal:title_weights`) → próximo ciclo usa os pesos.

Persistência usa os stores existentes: `opportunity_outcomes` (cases, com o
case inteiro em `evidence`), `app_settings/signal:*` (telemetria, shadow,
pesos). Sem schema paralelo.

## Endurecimento pós-revisão (revisão do commit c860757)

Inconsistências apontadas na revisão e o que mudou:

| # | Problema | Correção |
| - | -------- | -------- |
| 1 | **Baseline temporalmente inconsistente**: `build_baseline` filtrava só `window_end` (última janela, podendo ser 1 dia) contra páginas GSC de 28 dias, e agregava janelas diferentes com o mesmo fim | janela é o PAR `(window_start, window_end)`; `build_baseline_from_pages()` calcula o contexto de CTR das MESMAS linhas de página recém-coletadas (`title-engine` usa essa forma) |
| 2 | **Título podia não representar o candidato pontuado** (combinação de 3 intenções, título com 2; sem template de terceira intenção) | `finalize_titles()` REMEDE a cobertura de cada título gerado (`title_coverage`), rejeita o que não atinge o candidato (tolerância 2 p.p.) e re-pontua SOBRE O TEXTO; template de trio adicionado; sem título válido → `no_title_change` com `candidate_failed_reason` |
| 3 | **Calibração não aprendia os sete fatores**: faltavam valores numéricos e `historical_success` usava `title_score` como proxy (circular); `confidence` era string | `candidate_features["score_factors"]` persiste os SETE fatores exatos + `confidence_score` numérico (rótulo legado é convertido); proxy circular removido |
| 4 | Motor novo não estava no `schedule` | passo `title-engine-shadow` no ciclo diário (observe + shadow + persist; NUNCA publica), controlado por `TITLE_ENGINE_IN_SCHEDULE` |
| 5 | **Rankability parcialmente empírica**: `h1/heading/body/related` eram constantes fixas e `topic_authority` não era passado | CLI usa `build_cluster_signals` + `topic_authority` + `build_query_signals` (corpus real) por família; sem corpus o campo fica `None` = desconhecido (e `semantic_fit` renormaliza sobre o que foi medido, em vez de tratar ausência como zero) |
| 6 | **Bug preexistente**: `observed_difficulty` (0 = fácil) somado positivamente ao rankability — mais difícil ⇒ score maior | invertido para `observed_ease` (facilidade), com teste monotônico (mais autoridade nunca reduz) |
| 7 | Share de família sem métrica de observação | `query_observation_ratio = Σ impressões das queries / impressões da página` (+ `observation_status`), entra no contrato e rebaixa `high` quando `< 20%` |
| 8 | **Matching lexical agressivo** (prefixo genérico de 5 chars: `metro` de altura casava `Metroid`) | casamento por variantes + radical ≥ 6 chars com sobra de FLEXÃO conhecida (`_DERIVED_SUFFIXES`); regressões de `Metroid` e `Dragon Ball/Quest` |
| 9 | `compatible_entity` aceitava UM token em comum (over-merge de franquias) | overlap ≥ 60% sobre o lado menor; entidade canônica do corpus quando disponível |
| 10 | Fallback de headroom `p50 or 0.06` (inventava 6% e ignorava `p50 = 0` real) | `page_headroom()`: sem P50 utilizável → neutro 0.5 com status `unknown`/`degenerate`; nunca um CTR inventado |
| 11 | `historical_success` igual para todas as combinações da página | calculado POR CANDIDATO (faixa de posição × nº de intenções × intenção primária) via `historical_success_fn` |
| 12 | Linhas `title_regression` injetadas com `impressions=0`/`position=None` perdiam o GSC real e caíam em `gather_more_data` | `pages_by_url` reaproveita a linha real da coleta; zeros só quando a URL não tem dado no período |

Testes desses casos: `tests/test_title_engine_hardening.py` (+ integração estendida em
`tests/test_title_engine_integration.py`).

## Segunda rodada de correções (revisão do c706e87)

| # | Problema | Correção |
| - | -------- | -------- |
| 5a | `family_rankability` usava `setdefault` para o Topic Authority — `setdefault` NÃO substitui chave existente com `None`, e `build_query_signals` devolve `topic_authority: None`: o TA calculado não entrava no `observed_ease` | guard explícito (`if topic_authority is not None and signals.get(...) is None`) + teste com `topic_authority=None` nos sinais |
| 5b | `build_query_signals` inicializava os sinais semânticos em `0.0` (ausência de medição entrava como medição ruim, apesar da renormalização) | inicialização em `None`; só o que foi medido é preenchido |
| 5c | Semântica vinha de UMA query representante da família | novo `build_family_query_signals()`: média dos fits PONDERADA por impressões das queries da família (até 3), com tração somada e melhor posição |
| 5d | `corpus_available`/`semantic_evidence` da confiança vinham de `bool(families)` (GSC não prova corpus) | viram entradas explícitas: a CLI passa corpus real (`cluster_signals`) e fração de famílias com semântica medida |
| 7 | Tração/posições do rankability somavam janelas históricas (`query_pages` sem filtro de janela) | `window_start`+`window_end` em `build_query_signals` e em `cluster_coverage` (novo param `window_end`); a CLI resolve o par vigente com `latest_window_pair()` e usa UM par por decisão, registrado em `signal_window` |
| 9 | `observation.observed_impressions` recebia `observed_share_universe` (um SHARE, ~0.85) | `decide_title(observed_impressions=...)` — impressões reais (fallback: soma das famílias) |
| 12 | O re-score do título (`finalize_titles`) não recebia `historical_success` e voltava ao neutro 0.5 — e era esse valor que ia para a calibração | a CLI repassa o histórico da combinação que selecionou o candidato |

## Terceira rodada de correções (revisão do 5d94daa)

| # | Problema | Correção |
| - | -------- | -------- |
| 1 | `latest_window_pair()` escolhia a janela mais recente por `ORDER BY window_end DESC, window_start DESC` — com duas coletas terminando no MESMO dia (28d e 1d), preferia a MAIS CURTA (o mesmo desalinhamento temporal da primeira rodada) | `resolve_signal_window(storage, start, end)`: usa a janela DO PRÓPRIO RUN quando ela está persistida (`aligned=true`, `source=run_window`) e cai para o par mais recente só com `aligned=false` + motivo explícito — nunca degrada para tração zero em silêncio. CLI passa `start`/`end` da coleta |
| 2 | **Dupla contagem da tração**: `build_query_signals` somava `impressions` por VARIANTE de `expand_query()` e `build_family_query_signals` somava isso entre as queries da família — a expansão de "quantos anos tem gojo" já alcança "gojo idade", então 1.300 impressões viravam 1.700+ e inflavam `query_traction` | separação explícita: TRAÇÃO vem de `family["impressions"]`/`clicks`/`weighted_position` (GSC real, agregado em `build_families`); as top queries servem SÓ para a média semântica, ponderada por `family["query_impressions"]` (impressão da própria query, não soma de variantes). Campo `traction_source` registra a origem |
| 3 | `semantic["title_fit"] = 0.9 if best.get("title")` media apenas "o documento tem título" | `query_title_alignment(query, doc_title)` (FASE 4): entidade 40% + intenção 40% + tokens significativos 20%, com componentes não medíveis fora do cálculo; sem título → `None` (desconhecido) |
| — | `build_family_query_signals` dependia da ordem das queries vindas do chamador | `build_families` expõe `top_queries` (ordenado por impressões) e `query_impressions`, então o top-3 é estável independentemente do chamador |

## Quarta rodada de correções (revisão do 938473d)

| # | Problema | Correção |
| - | -------- | -------- |
| 1 | `signal_window.aligned=false` era só informativo: a decisão podia sair `review_title`/`high` com rankability/cluster de OUTRA janela | gate novo `signal_window_aligned` (`None` = não informado): a CLI passa `signal_window["aligned"]`; se `false` a decisão cai para `investigate_cause` (dados existem, só não estão alinhados no tempo) e a confiança nunca é `high`, com nota no motivo |
| 2 | **Semantic fit podia vir de OUTRA página**: `hybrid_search(...)[0]` escolhia o melhor documento de TODO o corpus | `build_query_semantic_signals(storage, query, target_url=...)`: medição determinística no corpus DA PÁGINA (título, h1, headings, texto); URL fora do corpus → campos `None` (`target_url_unavailable`), sem fallback para outra página; o match tolera host diferente (GSC `www.` × corpus `prod.`) pelo caminho normalizado (`inventory.reconcile.normalize_url`), registrado em `semantic_match`/`semantic_url` |
| 3 | SQL redundante: `build_family_query_signals` chamava `build_query_signals`, que refazia `expand_query()` + `SELECT` por variante só para descartar a tração | o caminho da família usa apenas `build_query_semantic_signals` (nenhuma consulta a `query_pages`): tração vem do agregado da família; teste com conexão instrumentada garante que só tabelas `corpus_*` são consultadas |

## Consequências
- A decisão fica **reproduzível e auditável** a partir de `evidence` + `checks`
  + `confidence` (Evidence Contract), com explicação em texto
  ("por que esta alteração está sendo proposta?").
- O funil pode responder "a página tem 4.320 impressões observadas; 42% é
  'idade', 36% 'poderes'; o título atual cobre 36%; 'idade + poderes' cobriria
  78%" em vez de "esta query individual tem o maior score".
- **Nada é publicado automaticamente** até o shadow mode demonstrar coerência e
  a Etapa C ser habilitada (`TITLE_ENGINE_MODE=auto`, só `high` + histórico
  suficiente + risco baixo).
- Custo: nenhum token na análise; tokens só se `TITLE_GENERATION_MODE=hybrid`
  **e** um writer for injetado.

## Validação
- Unitários: `tests/test_query_families.py`, `test_title_engine.py`,
  `test_title_generator.py`, `test_interventions.py`, `test_shadow_mode.py`.
- Integração ponta a ponta (GSC → baseline → famílias → score → gates →
  decisão → geração → outcome → calibração → novo ciclo com pesos calibrados):
  `tests/test_title_engine_integration.py`.
- Amostra estratificada para inspeção humana (FASE 22):
  `title-engine --explain --write` produz `title-engine-candidates.json` com
  decisões, score, razões e títulos sugeridos por página.
