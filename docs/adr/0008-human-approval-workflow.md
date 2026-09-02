# ADR-0008: Fluxo de aprovação humana (approval_required como fila)

## Status
Aceito.

## Contexto
O projeto distingue três atores — Agent, Human, System — e três classes de ação:
`observe`, `safe_fix`, `approval_required`. Aprovação deve preceder qualquer
escrita; delete nunca é automático.

## Decisão
- `approval_required` é **fila humana** (Caixa de Trabalho), não um gatilho.
- Ações seguem o ciclo canônico único:
  `detected → review_required → approved/rejected/snoozed → executing →
  implemented → waiting_data → measured → completed`
  (+ `expired|failed|reverted`).
- Para escrita, antes de confirmar: preview, escopo afetado, classe de ação,
  risco, reversibilidade, e o policy gate.
- **Safe Fix** nunca permite "Fix now" sem preview; fluxo:
  `finding → preview → before/after → impacto → rollback? → approve → execute → verify`.
- Backend impõe a permissão (`require_permission("technical.safe_fix")`)
  independente do que a UI mostre ou oculte.

## Consequências
- A UI guarda o contexto da lista ao abrir detalhe (drawer).
- Publicação de conteúdo nunca é automática.
- Medição ("measured") é o fim do ciclo, não "executed".
