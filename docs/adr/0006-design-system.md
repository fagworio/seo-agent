# ADR-0006: Design system (design tokens semânticos, dark + light)

## Status
Aceito.

## Contexto
O produto é operacional (estilo Linear): denso, quieto, ordenado, focado em
tarefa. Precisamos de componentes reutilizáveis e temas dark/light de primeira
classe a partir do mesmo modelo de tokens.

## Decisão
- **Tokens semânticos** via CSS variables (nunca hex hardcoded em componentes):
  `background, surface, surface-raised, border, foreground, muted, primary,
  success, warning, danger, info`, além do acento e das variantes suaves.
- Tipografia Inter/system; escala 32/40..11/16; números KPI tabulares.
- Ritmo de espaçamento base 8px; radius 6-8 (controles), 8-10 (cards),
  10-12 (drawers); densidade em 3 modos (Overview, Work queue, Evidence).
- Ícones lineares 16-20px; status sempre cor + texto/ícone (nunca cor sozinha).
- **Dark e light usam exatamente o mesmo componente**; troca é só de tokens.
- Guardrail `scripts/ui_guardrails.py` alerta hex hardcoded fora da camada
  token/theme, `fetch()` em componente, `any` sem justificativa.

## Consequências
- Consistência de hierarquia, densidade e componentes entre temas.
- Acessibilidade (contraste, foco, status) tratada como critério de conclusão.
