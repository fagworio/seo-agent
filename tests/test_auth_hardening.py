"""Endurecimento: CSRF, reautenticação, password reset, rate limiting."""
import datetime
from types import SimpleNamespace

from hermes_seo_agent.auth.passwords import PasswordHasher
from hermes_seo_agent.auth.rate_limit import SlidingWindowLimiter
from hermes_seo_agent.auth.service import AuthService
from hermes_seo_agent.storage.db import Storage


class FakeClock:
    def __init__(self, ts: int = 1_700_000_000):
        self.ts = ts

    def __call__(self) -> datetime.datetime:
        return datetime.datetime.fromtimestamp(self.ts, tz=datetime.timezone.utc)

    def advance(self, seconds: int) -> None:
        self.ts += seconds


def _cfg(reauth=900, reset=3600):
    return SimpleNamespace(
        session_idle_seconds=8 * 3600,
        session_absolute_seconds=7 * 24 * 3600,
        auth_max_attempts=5,
        auth_attempt_window_seconds=900,
        reauth_window_seconds=reauth,
        reset_token_seconds=reset,
        mfa_issuer="SEO Agent",
    )


def _make(db, reauth=900, reset=3600, sender=None):
    clock = FakeClock()
    storage = Storage(str(db))
    svc = AuthService(storage, config=_cfg(reauth, reset),
                      hasher=PasswordHasher(n=2 ** 12), clock=clock,
                      reset_token_sender=sender)
    return storage, svc, clock


# -- CSRF ------------------------------------------------------------------
def test_csrf_from_login_verifies(tmp_path):
    storage, svc, _ = _make(tmp_path / "c.db")
    svc.create_user("v@x.com", "V", "senha-bem-longa-12345", ["viewer"])
    res = svc.login("v@x.com", "senha-bem-longa-12345")
    assert res.csrf_token is not None
    assert svc.verify_csrf(res.session_id, res.csrf_token) is True
    assert svc.verify_csrf(res.session_id, "token-errado") is False
    assert svc.verify_csrf(res.session_id, None) is False
    storage.close()


def test_issue_csrf_reissues_and_revokes_old(tmp_path):
    storage, svc, _ = _make(tmp_path / "c2.db")
    svc.create_user("v@x.com", "V", "senha-bem-longa-12345", ["viewer"])
    res = svc.login("v@x.com", "senha-bem-longa-12345")
    old = res.csrf_token
    new = svc.issue_csrf(res.session_id)
    assert new != old
    assert svc.verify_csrf(res.session_id, new) is True
    assert svc.verify_csrf(res.session_id, old) is False
    storage.close()


# -- reautenticação --------------------------------------------------------
def test_recent_strong_auth_after_login(tmp_path):
    storage, svc, _ = _make(tmp_path / "r.db")
    svc.create_user("v@x.com", "V", "senha-bem-longa-12345", ["viewer"])
    res = svc.login("v@x.com", "senha-bem-longa-12345")
    assert svc.verify_recent_strong_auth(res.session_id) is True
    storage.close()


def test_recent_strong_auth_expires_after_window(tmp_path):
    storage, svc, clock = _make(tmp_path / "r2.db", reauth=900)
    svc.create_user("v@x.com", "V", "senha-bem-longa-12345", ["viewer"])
    sid = svc.login("v@x.com", "senha-bem-longa-12345").session_id
    clock.advance(901)
    assert svc.verify_recent_strong_auth(sid) is False
    svc.mark_strong_auth(sid)
    assert svc.verify_recent_strong_auth(sid) is True
    storage.close()


# -- password reset --------------------------------------------------------
def test_password_reset_single_use_and_revokes_sessions(tmp_path):
    sent: list[str] = []
    storage, svc, clock = _make(tmp_path / "p.db", sender=lambda t, e: sent.append(t))
    svc.create_user("v@x.com", "V", "senha-bem-longa-12345", ["viewer"])
    token = svc.login("v@x.com", "senha-bem-longa-12345").session_token

    r = svc.request_password_reset("v@x.com")
    assert r["ok"] is True
    assert len(sent) == 1
    reset_token = sent[0]

    assert svc.reset_password(reset_token, "nova-senha-bem-longa-123") is True
    # token de uso único: segunda vez falha
    assert svc.reset_password(reset_token, "outra-senha-bem-longa-123") is False
    # sessões antigas revogadas
    assert svc.validate_session(token) is None
    # novo login com a nova senha funciona
    assert svc.login("v@x.com", "nova-senha-bem-longa-123").ok is True
    storage.close()


def test_password_reset_generic_for_unknown_email(tmp_path):
    sent: list[str] = []
    storage, svc, _ = _make(tmp_path / "p2.db", sender=lambda t, e: sent.append(t))
    r1 = svc.request_password_reset("existe@x.com")
    r2 = svc.request_password_reset("nao-existe@x.com")
    assert r1["ok"] is True and r2["ok"] is True
    assert r1["message"] == r2["message"]   # mesmo texto -> sem enumeração
    assert sent == []                        # nenhum token para conta inexistente
    storage.close()


def test_password_reset_token_expired(tmp_path):
    sent: list[str] = []
    storage, svc, clock = _make(tmp_path / "p3.db", reset=3600,
                                sender=lambda t, e: sent.append(t))
    svc.create_user("v@x.com", "V", "senha-bem-longa-12345", ["viewer"])
    svc.request_password_reset("v@x.com")
    token = sent[0]
    clock.advance(3601)   # passou do TTL de 1h
    assert svc.reset_password(token, "nova-senha-bem-longa-123") is False
    storage.close()


# -- F15: casos de segurança --------------------------------------------------
def test_disabled_user_rejects_with_generic_error(tmp_path):
    """Usuário desabilitado recebe a MESMA mensagem genérica (não revela estado)."""
    storage, svc, _ = _make(tmp_path / "sec1.db")
    uid = svc.create_user("v@x.com", "V", "senha-bem-longa-12345", ["viewer"])
    storage.conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (uid,))
    storage.conn.commit()
    res = svc.login("v@x.com", "senha-bem-longa-12345")
    assert res.ok is False and res.reason == "invalid"
    assert res.user is None
    storage.close()


def test_unknown_or_stolen_session_token_rejected(tmp_path):
    """Token de sessão desconhecido/roubado -> validate_session None."""
    storage, svc, _ = _make(tmp_path / "sec2.db")
    svc.create_user("v@x.com", "V", "senha-bem-longa-12345", ["viewer"])
    assert svc.validate_session("token-que-nao-existe") is None
    assert svc.validate_session("") is None
    storage.close()


def test_password_reset_token_single_use(tmp_path):
    """Reutilização de token de reset falha (uso único)."""
    sent: list[str] = []
    storage, svc, _ = _make(tmp_path / "sec3.db", sender=lambda t, e: sent.append(t))
    svc.create_user("v@x.com", "V", "senha-bem-longa-12345", ["viewer"])
    svc.request_password_reset("v@x.com")
    token = sent[0]
    assert svc.reset_password(token, "nova-senha-bem-longa-123") is True
    assert svc.reset_password(token, "outra-senha-bem-longa-123") is False
    storage.close()


# -- rate limiting ---------------------------------------------------------
def test_limiter_allows_within_window():
    lmr = SlidingWindowLimiter(max_events=3, window_seconds=60)
    assert lmr.allow("a") is True
    assert lmr.allow("a") is True
    assert lmr.allow("a") is True
    assert lmr.allow("a") is False    # 4º no mesmo janela bloqueia
    assert lmr.remaining("a") == 0
    assert lmr.allow("b") is True     # chave independente


def test_limiter_slides_window():
    clock = {"t": 0.0}
    lmr = SlidingWindowLimiter(max_events=2, window_seconds=60, clock=lambda: clock["t"])
    assert lmr.allow("a") is True
    assert lmr.allow("a") is True
    assert lmr.allow("a") is False
    clock["t"] = 61                   # janela passou
    assert lmr.allow("a") is True


def test_limiter_reset():
    lmr = SlidingWindowLimiter(max_events=1, window_seconds=60)
    lmr.allow("a")
    assert lmr.allow("a") is False
    lmr.reset("a")
    assert lmr.allow("a") is True
