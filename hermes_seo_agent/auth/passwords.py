"""Password hashing (scrypt) + password policy.

OWASP Password Storage Cheat Sheet ranks Argon2id first; **scrypt** and PBKDF2
are also accepted memory-hard KDFs. The environment's package mirror lacks
``argon2-cffi``, so hashing is isolated behind :class:`PasswordHasher` — swapping
to Argon2id is a one-module change with the same interface.

Parameters are **self-describing** in the stored string (``alg$n$r$p$salt$key``),
so verification reads the parameters that produced the hash. Never store the
raw password or a fast digest (sha256(password)).
"""

from __future__ import annotations

import base64
import secrets
from dataclasses import dataclass

from cryptography.exceptions import InvalidKey
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

_ALG = "scrypt"
_DEFAULT_N = 2 ** 15          # 32768 (~32MiB) — production may raise to 2**17
_DEFAULT_R = 8
_DEFAULT_P = 1
_KEY_LEN = 32


class PasswordPolicyError(ValueError):
    """Senha viola a política de segurança."""


@dataclass(frozen=True)
class PasswordPolicy:
    # Sem MFA exige senha longa (15+); com MFA o 2º fator compensa (8+).
    min_length_no_mfa: int = 15
    min_length_with_mfa: int = 8
    max_length: int = 64


def default_policy() -> PasswordPolicy:
    return PasswordPolicy()


class PasswordHasher:
    """Hasher scrypt com verificação em tempo constante."""

    def __init__(
        self,
        *,
        n: int = _DEFAULT_N,
        r: int = _DEFAULT_R,
        p: int = _DEFAULT_P,
        policy: PasswordPolicy | None = None,
    ) -> None:
        self.n = n
        self.r = r
        self.p = p
        self.policy = policy or default_policy()

    def hash(self, password: str) -> str:
        salt = secrets.token_bytes(16)
        kdf = Scrypt(salt=salt, length=_KEY_LEN, n=self.n, r=self.r, p=self.p)
        key = kdf.derive(password.encode("utf-8"))
        return "$".join(
            [
                _ALG,
                str(self.n),
                str(self.r),
                str(self.p),
                base64.urlsafe_b64encode(salt).decode("ascii"),
                base64.urlsafe_b64encode(key).decode("ascii"),
            ]
        )

    def verify(self, password: str, stored: str) -> bool:
        try:
            alg, n_s, r_s, p_s, salt_b64, key_b64 = stored.split("$")
        except (ValueError, AttributeError):
            return False
        if alg != _ALG:
            return False
        try:
            salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
            expected = base64.urlsafe_b64decode(key_b64.encode("ascii"))
            kdf = Scrypt(
                salt=salt, length=len(expected), n=int(n_s), r=int(r_s), p=int(p_s)
            )
            derived = kdf.derive(password.encode("utf-8"))
        except Exception:
            return False
        return secrets.compare_digest(derived, expected)

    def validate(self, password: str, *, mfa_enabled: bool) -> None:
        """Aplica a política e lança PasswordPolicyError se inválida."""
        if len(password) < 1:
            raise PasswordPolicyError("senha não pode ser vazia")
        min_len = (
            self.policy.min_length_with_mfa
            if mfa_enabled
            else self.policy.min_length_no_mfa
        )
        if len(password) < min_len:
            raise PasswordPolicyError(
                f"senha deve ter pelo menos {min_len} caracteres"
            )
        if len(password) > self.policy.max_length:
            raise PasswordPolicyError(
                f"senha deve ter no máximo {self.policy.max_length} caracteres"
            )
