"""Password hashing (scrypt) + política de senha."""
import pytest

from hermes_seo_agent.auth.passwords import (
    PasswordHasher,
    PasswordPolicy,
    PasswordPolicyError,
    default_policy,
)


def _fast() -> PasswordHasher:
    return PasswordHasher(n=2 ** 12)  # mais rápido para os testes


def test_hash_and_verify_roundtrip():
    h = _fast()
    stored = h.hash("uma senha forte!")
    assert stored.startswith("scrypt$")
    assert "uma senha forte!" not in stored
    assert h.verify("uma senha forte!", stored) is True
    assert h.verify("senha errada", stored) is False


def test_parameters_self_describing():
    # verificar lê os parâmetros (n/r/p) do próprio hash
    h = PasswordHasher(n=2 ** 12, r=8, p=2)
    stored = h.hash("segredo")
    verify = PasswordHasher()  # default params, diferentes do hash
    assert verify.verify("segredo", stored) is True


def test_never_stores_plaintext_or_sha256_only():
    h = _fast()
    stored = h.hash("palavra-passe-123")
    assert "palavra-passe-123" not in stored


def test_policy_no_mfa_requires_15():
    h = _fast()
    with pytest.raises(PasswordPolicyError):
        h.validate("curta", mfa_enabled=False)
    h.validate("senha-longa-de-15-char", mfa_enabled=False)


def test_policy_with_mfa_allows_8():
    h = _fast()
    h.validate("12345678", mfa_enabled=True)
    with pytest.raises(PasswordPolicyError):
        h.validate("1234567", mfa_enabled=True)


def test_policy_max_length():
    h = _fast()
    with pytest.raises(PasswordPolicyError):
        h.validate("x" * 65, mfa_enabled=True)


def test_default_policy_values():
    p = default_policy()
    assert p.min_length_no_mfa == 15
    assert p.min_length_with_mfa == 8
    assert p.max_length == 64
