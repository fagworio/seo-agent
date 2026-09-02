"""Security primitives: token opaco, hash, constant-time compare."""
from hermes_seo_agent.auth.security import (
    constant_time_eq,
    generate_csrf_token,
    generate_session_token,
    hash_ip,
    hash_token,
    hash_user_agent,
)


def test_session_token_is_opaque_and_unique():
    a = generate_session_token()
    b = generate_session_token()
    assert a != b
    assert len(a) >= 32


def test_token_hash_is_deterministic_and_not_reversible():
    t = generate_session_token()
    assert hash_token(t) == hash_token(t)
    assert hash_token(t) != t
    assert len(hash_token(t)) == 64  # sha256 hex


def test_csrf_token():
    assert generate_csrf_token() != generate_csrf_token()


def test_ip_and_ua_hashed():
    assert hash_ip("1.2.3.4") != "1.2.3.4"
    # estabilidade
    assert hash_ip("1.2.3.4") == hash_ip("1.2.3.4")
    assert hash_ip("") is None
    assert hash_ip(None) is None
    assert hash_user_agent(None) is None


def test_constant_time_eq():
    assert constant_time_eq("abc", "abc") is True
    assert constant_time_eq("abc", "abd") is False
