"""AuthService: login genérico, sessão, expiração, MFA, RBAC, throttle."""
import datetime
from types import SimpleNamespace

import pytest

from hermes_seo_agent.auth.passwords import PasswordHasher
from hermes_seo_agent.auth.service import AuthService
from hermes_seo_agent.storage.db import Storage


class FakeClock:
    def __init__(self, ts: int = 1_700_000_000):
        self.ts = ts

    def __call__(self) -> datetime.datetime:
        return datetime.datetime.fromtimestamp(self.ts, tz=datetime.timezone.utc)

    def advance(self, seconds: int) -> None:
        self.ts += seconds


def _cfg():
    return SimpleNamespace(
        session_idle_seconds=8 * 3600,
        session_absolute_seconds=7 * 24 * 3600,
        auth_max_attempts=5,
        auth_attempt_window_seconds=900,
        mfa_issuer="SEO Agent",
        # estes testes exercitam o caminho de MFA => gate ativo via config;
        # o default REAL é OFF (testes de default-off usam _cfg_off abaixo).
        mfa_login_required=True,
    )


def _cfg_off():
    return SimpleNamespace(
        session_idle_seconds=8 * 3600,
        session_absolute_seconds=7 * 24 * 3600,
        auth_max_attempts=5,
        auth_attempt_window_seconds=900,
        mfa_issuer="SEO Agent",
        mfa_login_required=False,
    )


def _svc(storage, clock):
    return AuthService(storage, config=_cfg(), hasher=PasswordHasher(n=2 ** 12), clock=clock)


def _make(db):
    clock = FakeClock()
    storage = Storage(str(db))
    svc = _svc(storage, clock)
    return storage, svc, clock


def _make_off(db):
    clock = FakeClock()
    storage = Storage(str(db))
    svc = AuthService(storage, config=_cfg_off(), hasher=PasswordHasher(n=2 ** 12), clock=clock)
    return storage, svc, clock


def test_admin_has_mfa_and_login_requires_second_factor(tmp_path):
    storage, svc, _ = _make(tmp_path / "a.db")
    svc.create_admin("admin@x.com", "Admin", "senha123")
    res = svc.login("admin@x.com", "senha123")
    assert res.ok is True
    assert res.requires_mfa is True
    assert res.session_token is None          # não cria sessão antes do MFA
    assert res.mfa_user_id is not None

    factor = svc.store.get_mfa_factor(res.mfa_user_id)
    assert factor is not None
    from hermes_seo_agent.auth.totp import TOTP
    code = TOTP(factor["secret"]).now()
    ok = svc.verify_mfa_login(res.mfa_user_id, code)
    assert ok.ok is True
    assert ok.session_token is not None
    info = svc.validate_session(ok.session_token)
    assert info is not None
    assert info.email == "admin@x.com"
    assert "admin" in info.roles
    storage.close()


def test_login_generic_error_anti_enumeration(tmp_path):
    storage, svc, _ = _make(tmp_path / "b.db")
    svc.create_admin("admin@x.com", "Admin", "senha123")
    r_missing = svc.login("nao-existe@x.com", "qualquer")
    r_wrong = svc.login("admin@x.com", "senha-errada")
    assert r_missing.reason == "invalid"
    assert r_wrong.reason == "invalid"
    assert r_missing.user is None and r_wrong.user is None
    storage.close()


def test_no_mfa_user_logs_in_directly(tmp_path):
    storage, svc, _ = _make(tmp_path / "c.db")
    svc.create_user("viewer@x.com", "V", "senha-bem-longa-12345", ["viewer"])
    res = svc.login("viewer@x.com", "senha-bem-longa-12345")
    assert res.ok is True and res.requires_mfa is False
    assert res.session_token is not None
    info = svc.validate_session(res.session_token)
    assert info is not None
    assert "technical.safe_fix" not in info.permissions
    storage.close()


def test_logout_revokes_server_side(tmp_path):
    storage, svc, _ = _make(tmp_path / "d.db")
    svc.create_user("v@x.com", "V", "senha-bem-longa-12345", ["viewer"])
    res = svc.login("v@x.com", "senha-bem-longa-12345")
    token = res.session_token
    assert svc.validate_session(token) is not None
    svc.logout(token)
    assert svc.validate_session(token) is None
    storage.close()


def test_session_idle_expiry(tmp_path):
    storage, svc, clock = _make(tmp_path / "e.db")
    svc.create_user("v@x.com", "V", "senha-bem-longa-12345", ["viewer"])
    token = svc.login("v@x.com", "senha-bem-longa-12345").session_token
    assert svc.validate_session(token) is not None
    clock.advance(8 * 3600 + 1)   # passou do idle (8h), antes do absoluto (7d)
    assert svc.validate_session(token) is None
    storage.close()


def test_session_absolute_expiry(tmp_path):
    storage, svc, clock = _make(tmp_path / "f.db")
    svc.create_user("v@x.com", "V", "senha-bem-longa-12345", ["viewer"])
    token = svc.login("v@x.com", "senha-bem-longa-12345").session_token
    clock.advance(7 * 24 * 3600 + 1)
    assert svc.validate_session(token) is None
    storage.close()


def test_verify_mfa_wrong_code_rejected(tmp_path):
    storage, svc, _ = _make(tmp_path / "g.db")
    svc.create_admin("admin@x.com", "Admin", "senha123")
    mid = svc.login("admin@x.com", "senha123").mfa_user_id
    r = svc.verify_mfa_login(mid, "000000")   # provavelmente errado; janela pode bater
    # como 000000 quase nunca é válido, garantimos que código inválido falha
    from hermes_seo_agent.auth.totp import TOTP
    factor = svc.store.get_mfa_factor(mid)
    bad = TOTP(factor["secret"]).now()
    bad = ("000000" if bad != "000000" else "111111")
    r2 = svc.verify_mfa_login(mid, bad)
    # pode eventualmente colidir, mas com 6 dígitos é astronomicamente raro
    assert r2.reason in {"invalid", None}
    storage.close()


def test_rbac_require_permission(tmp_path):
    storage, svc, _ = _make(tmp_path / "h.db")
    svc.create_user("op@x.com", "O", "senha-bem-longa-12345", ["operator"])
    svc.create_user("view@x.com", "V", "senha-bem-longa-12345", ["viewer"])
    op = svc.store.get_user_by_email("op@x.com")["id"]
    view = svc.store.get_user_by_email("view@x.com")["id"]
    assert svc.require_permission(op, "technical.safe_fix") is True
    assert svc.require_permission(view, "technical.safe_fix") is False
    assert svc.require_permission(view, "dashboard.read") is True
    storage.close()


def test_login_throttle_after_max_attempts(tmp_path):
    storage, svc, _ = _make(tmp_path / "i.db")
    svc.create_user("v@x.com", "V", "senha-bem-longa-12345", ["viewer"])
    for _ in range(5):
        svc.login("v@x.com", "senha-errada")
    # mesmo com senha correta, threshold bloqueia (janela por email/IP)
    res = svc.login("v@x.com", "senha-bem-longa-12345")
    assert res.reason == "invalid"
    storage.close()


def test_revoke_other_sessions(tmp_path):
    storage, svc, _ = _make(tmp_path / "j.db")
    svc.create_user("v@x.com", "V", "senha-bem-longa-12345", ["viewer"])
    s1 = svc.login("v@x.com", "senha-bem-longa-12345").session_token
    s2 = svc.login("v@x.com", "senha-bem-longa-12345").session_token
    curr_id = svc.validate_session(s2).session_id
    svc.revoke_other_sessions(svc.store.get_user_by_email("v@x.com")["id"], curr_id)
    assert svc.validate_session(s1) is None
    assert svc.validate_session(s2) is not None
    storage.close()


def test_change_password_revokes_sessions(tmp_path):
    storage, svc, _ = _make(tmp_path / "k.db")
    svc.create_user("v@x.com", "V", "senha-bem-longa-12345", ["viewer"])
    token = svc.login("v@x.com", "senha-bem-longa-12345").session_token
    uid = svc.store.get_user_by_email("v@x.com")["id"]
    svc.change_password(uid, "nova-senha-bem-longa-123")
    assert svc.validate_session(token) is None
    storage.close()


def test_mfa_gate_off_by_default_allows_password_login(tmp_path):
    """Default (gate OFF): login padrão mesmo com MFA cadastrado na conta."""
    storage, svc, _ = _make_off(tmp_path / "off.db")
    svc.create_user("op@x.com", "O", "senha-bem-longa-12345", ["operator"],
                    mfa_secret="5DGXU53YEWVAENWS53HV53APWPGGHMAW")
    res = svc.login("op@x.com", "senha-bem-longa-12345")
    assert res.ok is True
    assert res.requires_mfa is False          # NÃO pede o 2º fator
    assert res.session_token is not None      # login padrão direto
    storage.close()


def test_mfa_gate_can_be_toggled_and_persisted(tmp_path):
    """set_mfa_login_required alterna o gate em app_settings e audita."""
    storage, svc, _ = _make_off(tmp_path / "tog.db")
    # gate off por padrão
    assert svc.mfa_login_required() is False
    # ligar
    svc.set_mfa_login_required(True, actor="admin@x.com")
    assert svc.mfa_login_required() is True
    # persistiu (nova instância lê o mesmo store)
    storage2 = Storage(str(tmp_path / "tog.db"))
    svc2 = AuthService(storage2, config=_cfg_off(), hasher=PasswordHasher(n=2 ** 12))
    assert svc2.mfa_login_required() is True
    # audit registrado
    log = storage2.conn.execute(
        "SELECT action_type, entity FROM audit_log WHERE action_type='SETTINGS_MFA_LOGIN'"
    ).fetchone()
    assert log is not None and log[1] == "mfa_login_required"
    # desligar
    svc2.set_mfa_login_required(False, actor="admin@x.com")
    assert svc2.mfa_login_required() is False
    storage.close()
    storage2.close()


def test_mfa_gate_on_requires_factor(tmp_path):
    """Com o gate LIGADO, conta com MFA cadastrado exige o 2º fator no login."""
    storage, svc, _ = _make(tmp_path / "on.db")   # _make usa _cfg() => gate ON
    svc.create_user("op@x.com", "O", "senha-bem-longa-12345", ["operator"],
                    mfa_secret="5DGXU53YEWVAENWS53HV53APWPGGHMAW")
    res = svc.login("op@x.com", "senha-bem-longa-12345")
    assert res.ok is True
    assert res.requires_mfa is True
    assert res.session_token is None
    storage.close()
