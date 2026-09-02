"""TOTP (RFC 6238): vetores oficiais + verify com janela."""
from hermes_seo_agent.auth.totp import TOTP, generate_secret

# RFC 6238 Anexo B — segredo ASCII "12345678901234567890" em base32
RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


def test_rfc6238_vectors_8_digits():
    totp = TOTP(RFC_SECRET, digits=8)
    vectors = [
        (59, "94287082"),
        (1111111109, "07081804"),
        (1111111111, "14050471"),
        (1234567890, "89005924"),
        (2000000000, "69279037"),
        (20000000000, "65353130"),
    ]
    for ts, expected in vectors:
        assert totp.at(ts) == expected, f"ts={ts}"


def test_verify_accepts_within_window():
    totp = TOTP(RFC_SECRET)
    # código gerado em ts == um instante exato do período
    ts = 1111111111
    code = totp.at(ts)
    assert totp.verify(code, ts=ts) is True
    # tolerância de clock (~-1 step) ainda valida
    assert totp.verify(totp.at(ts - 30), ts=ts) is True
    # código errado / malformado
    assert totp.verify("000000", ts=ts) is False
    assert totp.verify("abcd", ts=ts) is False
    assert totp.verify("", ts=ts) is False


def test_replay_guard_requires_single_use_upstream():
    # o TOTP em si não guarda uso único — quem chama (AuthService) deve marcar
    totp = TOTP(RFC_SECRET)
    ts = 1111111111
    code = totp.at(ts)
    # mesmo código é sempre válido no mesmo período (sem estado); consumir é
    # responsabilidade da camada de serviço (marcar last_used/mfa).
    assert totp.verify(code, ts=ts) is True


def test_generate_secret_is_base32():
    s = generate_secret()
    assert all(ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" for ch in s)
    assert len(s) == 32
