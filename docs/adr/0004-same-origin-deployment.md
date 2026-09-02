# ADR-0004: Mesma origem (deploy frontend + API juntos)

## Status
Aceito.

## Contexto
Cookies, CORS e sessão ficam significativamente mais simples quando o frontend
e a API compartilham a mesma origem.

## Decisão
- Produção: `https://seo.unicorniohater.com.br/` (Next.js) e
  `https://seo.unicorniohater.com.br/api/v1/` (FastAPI) sob a mesma origem.
- Reverse proxy/CDN encaminha `/api/v1/*` para a FastAPI e as demais rotas para
  o Next.js.
- **CORS cross-origin não é necessário** em produção. Se algum dia for:
  origens explícitas, credentials controlado, nunca `*`.

## Consequências
- Reduz complexidade de cookies/CORS/sessão.
- `SameSite=Strict` é viável sem quebrar navegação.
- O cookie de sessão é escopado à origem por construção.
