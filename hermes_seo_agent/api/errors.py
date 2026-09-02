"""Erros da API: frame consistente {error:{code,message,request_id}}.

Nunca vazamos traceback Python para o frontend. Cada resposta de erro carrega um
código estável e um request_id para rastreabilidade.
"""

from __future__ import annotations


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message


class Unauthenticated(ApiError):
    def __init__(self, message: str = "Autenticação necessária.") -> None:
        super().__init__(401, "UNAUTHENTICATED", message)


class Forbidden(ApiError):
    def __init__(self, message: str = "Você não possui permissão para esta ação.") -> None:
        super().__init__(403, "PERMISSION_DENIED", message)


class InvalidCsrf(ApiError):
    def __init__(self) -> None:
        super().__init__(403, "CSRF_INVALID", "Token CSRF ausente ou inválido.")


class TooManyRequests(ApiError):
    def __init__(self) -> None:
        super().__init__(429, "RATE_LIMITED", "Muitas tentativas. Aguarde e tente novamente.")


class NotFound(ApiError):
    def __init__(self, message: str = "Recurso não encontrado.") -> None:
        super().__init__(404, "NOT_FOUND", message)


class BadRequest(ApiError):
    def __init__(self, message: str = "Requisição inválida.") -> None:
        super().__init__(400, "BAD_REQUEST", message)
