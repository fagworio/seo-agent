"""Control plane auth: password hashing, sessions (cookie HttpOnly), RBAC, MFA.

Backend é a fonte de verdade de autorização. A UI pode ocultar botões, mas a
camada de serviço/API sempre aplica `require_permission`.
"""
