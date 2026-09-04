# ADR-0010 — Operações de dados: verify / refresh / analyze / revalidate

## Status
Proposto (implementação incremental no Control Center).

## Contexto
O Control Center precisa permitir que o operador mantenha os dados atualizados e
revalide melhorias, mas **sem criar um subsistema paralelo de "sync"**. O modelo
existente já cobre a maior parte do ciclo: `AgentRun` (execuções), `IntegrationStatus`
(saúde das fontes), `page_snapshots` (before/after), `opportunity_outcomes`
(revalidação/medição) e `activity` (auditoria).

A ambiguidade entre "verificar", "coletar", "reanalisar" e "revalidar" levava a
ações que misturam responsabilidades (ex.: um único "refresh" que também escreve
no site). Esta ADR fixa a nomenclatura e a separação de responsabilidades.

## Decisão
São **quatro operações distintas** (verbos do domínio):

| Operação      | Função                                                          | Escreve no site? |
| ------------- | --------------------------------------------------------------- | ---------------- |
| `verify`      | Testa a configuração e acessibilidade das fontes (WP, sitemap, GSC, GA4, CrUX). Não coleta. | Não |
| `refresh`     | Busca e **persiste** novos dados das fontes (incremental).       | Não |
| `analyze`     | Recalcula findings/oportunidades a partir dos dados já persistidos. | Não |
| `revalidate`  | Lê o estado atual (técnico + Google + GA4) e compara com o baseline para medir before/after. | Não |

Nenhuma das quatro reaplica a correção. **Escrita no site** permanece exclusiva
do `safe_fix` (executor), com aprovação humana e dry-run.

## Fluxo canônico
```
refresh (coletar) → reconcile → analyze → oportunidades → decisão humana
→ safe_fix (executar) → aguardar dados → revalidate → medir
```
Isto é o mesmo ciclo `Detectar → Entender → Decidir → Executar → Verificar → Medir`.

## Mapeamento ao que já existe
- `verify` → `GET /api/v1/integrations?live=true[&source=...]` (IntegrationStatus.check).
- `refresh` → novo `intent` de `AgentRun` (`refresh_data`), reutilizando os conectores existentes.
- `analyze` → `AgentRun` com `mode=analyze` (já existe).
- `revalidate` → pipeline `opportunity_outcomes` (`waiting_7d → ready → measured`).

## Consequências
- Um botão "Atualizar dados" dispara um `AgentRun` (`refresh_data`); **não** chama
  coletores diretamente no browser.
- `verify` não é `refresh`: verificar conexão não persiste nada.
- `revalidate` só lê e mede; nunca reaplica.
- Permissões: `integration.read` (ver fontes), `integration.manage` (verificar/
  atualizar fonte individual), `agent.run` (atualizar tudo/análise/revalidar);
  `technical.safe_fix` continua restrito à execução de correções.
