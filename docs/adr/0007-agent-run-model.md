# ADR-0007: Modelo de execução de agente (agent_run + steps + events)

## Status
Aceito.

## Contexto
A transparência de automação é área de produto de primeira classe. Um run deve
responder: o que o agente fez, o que mudou vs. execução comparável, o que falhou
e o que permanece válido — sem forçar leitura de logs crus.

## Decisão
- Modelo persistente: `agents`, `agent_runs`, `agent_run_steps`, `agent_run_events`.
- Estados: `queued | running | success | partial | failed | cancelled`.
- Hierarquia de lista: running → failed/partial → recentes → históricos.
- Detalhe: Summary, Stages, Results, Changes, Logs (logs por último).
- **MVP**: polling 3s do run-detail apenas enquanto `queued|running`, parar em
  estados terminais. **Futuro**: SSE para progresso unidirecional (REST continua
  sendo a fonte de recovery/deep-link).
- Auditoria de execução registra `quem iniciou, trigger, agente, comando lógico,
  modo, parâmetros seguros, início, fim, status, resultado` — **nunca credenciais**.

## Consequências
- Erros traduzidos em: o que falhou, o que afeta, o que permanece válido,
  retry/recovery.
- Logs crus ficam atrás de disclosure progressivo.
