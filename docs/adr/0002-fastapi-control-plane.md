# ADR-0002: FastAPI control plane (/api/v1)

## Status
Aceito.

## Contexto
O CLI, o Hermes e a UI devem compartilhar a mesma lógica de negócio. Não queremos
que o Next.js leia SQLite diretamente. Precisamos de uma fronteira de API que
exponha **conceitos de produto**, não comandos CLI.

## Decisão
- Criar aplicação **FastAPI** em `hermes_seo_agent/api/`, servida em `/api/v1/`.
- Reusar os serviços existentes (`OpportunityFeedService`, `IntegrationStatusService`,
  executor, agentes) em vez de duplicar regras.
- Contrato **OpenAPI** gerado a partir de modelos Pydantic; tipos TypeScript
  gerados a partir dele (sem duplicar DTOs à mão).
- Sem rotas `api/random-endpoint`; tudo versionado em `/api/v1/`.

## Consequências
- CLI, Hermes e UI ganham a mesma fonte de verdade.
- O frontend consome DTOs human-readable, não saída de CLI.
- Segurança (auth/RBAC/CSRF) é enforced server-side na camada FastAPI.
