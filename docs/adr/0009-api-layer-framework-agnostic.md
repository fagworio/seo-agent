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
- **A API `/api/v1` está materializada** em `hermes_seo_agent/api/`: `Router` puro
  (roteamento, sessão por cookie, CSRF synchronizer token, RBAC deny-by-default,
  rate limiting) sobre `AuthService`/`ControlPlaneService`/`AgentRunService`, mais um
  transporte HTTP stdlib (`ThreadingHTTPServer` com uma Storage/Router por request —
  a conexão SQLite é usada no próprio thread). Há um subcomando `hermes-seo-agent serve`.
- A validação é por teste de unidade do Router + um smoke end-to-end por HTTP real
  (login MFA → cookie → me → today → logout com CSRF → 401).
- O segurança não é "artesanal": segue OWASP (sessão server-side, MFA RFC 6238,
  CSRF, rate limiting, RBAC deny-by-default), mesmo com transporte stdlib.
- Reavaliar este ADR quando `fastapi` estiver instalável: ligar `Router.handle` como
  roteadores finos do FastAPI (mesma semântica), trocando apenas o transporte.
