# ADR-0003: Autenticação por sessão server-side (cookie HttpOnly)

## Status
Aceito.

## Contexto
OWASP recomenda não armazenar tokens de autenticação em Web Storage e prefere
cookies com `Secure`, `HttpOnly` e `SameSite`. Não queremos JWT no
localStorage/sessionStorage nem credenciais persistidas no navegador.

## Decisão
- **Sessão server-side** com identificador aleatório e opaco, enviado em cookie:
  `__Host-seo_session=<token>; Secure; HttpOnly; SameSite=Strict; Path=/`.
- O backend guarda apenas `SHA-256(session_token)`; o navegador nunca recebe
  `user_id`, roles, refresh token, credenciais de banco, WordPress ou Google.
- **Rotação de sessão no login** (substituir a sessão pré-login para mitigar
  session fixation).
- **Expiração dupla**: idle timeout (8h) e absolute timeout (7d). Logout invalida
  server-side, não apenas apaga o cookie.

## Consequências
- Sessões revogáveis e auditáveis.
- A sessão inteira permanece sob TLS (não só `/login`).
- `SameSite=Strict` pode ser revisado para `Lax` apenas se surgir OAuth
  cross-site; não será feito automaticamente.
