"""TOTP (RFC 6238) sobre HMAC-SHA1, usando a lib `cryptography`.

Implementação direta da spec (não é criptografia artesanal), testável contra os
vetores RFC 6238. OTP nunca deve aparecer em logs; TTL curto, janela de ±1 step
para tolerância de clock, uso único garantido pelo lado do chamador.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time


def generate_secret() -> str:
    """Segredo base32 (RFC 4648), sem padding, pronto para autenticador."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _base32_decode(secret: str) -> bytes:
    s = secret.upper().replace(" ", "").rstrip("=")
    s += "=" * ((-len(s)) % 8)
    return base64.b32decode(s)


def _totp_code(secret: str, counter: int, digits: int) -> str:
    msg = struct.pack(">Q", counter)
    digest = hmac.new(_base32_decode(secret), msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10 ** digits)).zfill(digits)


class TOTP:
    def __init__(self, secret: str, *, digits: int = 6, period: int = 30) -> None:
        self.secret = secret
        self.digits = digits
        self.period = period

    def at(self, ts: int) -> str:
        return _totp_code(self.secret, ts // self.period, self.digits)

    def now(self, *, ts: int | None = None) -> str:
        return self.at(ts if ts is not None else int(time.time()))

    def counter_value(self, ts: int) -> int:
        return ts // self.period

    def code_for_counter(self, counter: int) -> str:
        return _totp_code(self.secret, counter, self.digits)

    def verify(self, code: str, *, window: int = 1, ts: int | None = None) -> bool:
        if not code or not code.isdigit():
            return False
        if len(code) != self.digits:
            return False
        ts = ts if ts is not None else int(time.time())
        counter = ts // self.period
        for offset in range(-window, window + 1):
            candidate = self.code_for_counter(counter + offset)
            if secrets.compare_digest(candidate, code):
                return True
        return False
