# ADR-0009: Camada de API framework-agnóstica (binding FastAPI adiado)

## Status
Aceito (provisório — revisar quando o ambiente tiver FastAPI).

## Contexto
A arquitetura-alvo (ADR-0002) usa FastAPI para servir `/api/v1/`. Porém o mirror
de pacotes do ambiente de build **não disponibiliza** `fastapi`, `starlette`,
`pydantic`, `uvicorn`, `flask`, `aiohttp` nem `quart` (verificado por
`pip download`; só `anyio` existe). Sem Pydantic/FastAPI não é possível rodar a
aplicação FastAPI aqui.

## Decisão
- Construir a **lógica do control plane de forma independente de framework**:
  `AuthService` (e futuros services/opportunity, agent, page, etc.) são Python
  puro, determinísticos e testáveis, sem depender de nenhuma lib web.
- Componentes de segurança já implantados como peças puras:
  `auth/passwords.py`, `auth/totp.py`, `auth/security.py`, `auth/permissions.py`,
  `auth/rate_limit.py` + `AuthService` (sessão, CSRF synchronizer token,
  reautenticação para ações críticas, password reset).
- **Endpoints `/api/v1/*`**: modelar handlers/contratos e, quando o ambiente
  tiver FastAPI, ligá-los como roteadores finos que apenas traduzem
  `Request → AuthService/Service → Response` (cookie HttpOnly, header CSRF,
  frame de erro `{error:{code,message,request_id}}`). A troca de transporte é
  mecânica porque a lógica de negócio/segurança vive nos services.

## Consequências
- Não há aplicação HTTP executável no repositório enquanto o ambiente não tiver
  FastAPI; a validação é por teste de unidade das service/camadas puras.
- O segurança não é "artesanal": segue OWASP (sessão server-side, Argon2id
  desejado/scrypt aceito, MFA RFC 6238, CSRF, rate limiting, RBAC deny-by-default).
- Reavaliar este ADR quando `fastapi` estiver instalável; então materializar
  `hermes_seo_agent/api/` (main.py, routers, dependencies, schemas Pydantic,
  OpenAPI → TypeScript).
