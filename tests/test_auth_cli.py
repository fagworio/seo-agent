"""CLI user: create-admin (bootstrap), create, list, roles."""
import json

from hermes_seo_agent.cli import main


def _run(argv, monkeypatch, capsys, db):
    monkeypatch.setenv("SQLITE_PATH", str(db))
    code = main(argv)
    out = capsys.readouterr().out
    return code, json.loads(out)


def test_create_admin_bootstraps_and_returns_mfa_secret(tmp_path, monkeypatch, capsys):
    db = tmp_path / "cli.db"
    code, out = _run(
        ["user", "create-admin", "--email", "admin@x.com", "--name", "Admin",
         "--password", "senha123"],
        monkeypatch, capsys, db,
    )
    assert code == 0
    assert out["status"] == "ok"
    assert out["user"]["email"] == "admin@x.com"
    assert out["user"]["mfa_secret"]


def test_create_user_assigns_roles_and_list(tmp_path, monkeypatch, capsys):
    db = tmp_path / "cli.db"
    _run(["user", "create-admin", "--email", "admin@x.com", "--name", "Admin",
          "--password", "senha123"], monkeypatch, capsys, db)
    code, out = _run(
        ["user", "create", "--email", "op@x.com", "--name", "Op",
         "--password", "senha-bem-longa-12345", "--roles", "operator,editor"],
        monkeypatch, capsys, db,
    )
    assert code == 0
    assert sorted(out["user"]["roles"]) == ["editor", "operator"]

    code, out = _run(["user", "list"], monkeypatch, capsys, db)
    emails = [u["email"] for u in out["users"]]
    assert "admin@x.com" in emails and "op@x.com" in emails


def test_roles_replaces_and_rotates(tmp_path, monkeypatch, capsys):
    db = tmp_path / "cli.db"
    _run(["user", "create-admin", "--email", "admin@x.com", "--name", "Admin",
          "--password", "senha123"], monkeypatch, capsys, db)
    _run(["user", "create", "--email", "op@x.com", "--name", "Op",
          "--password", "senha-bem-longa-12345", "--roles", "operator"],
         monkeypatch, capsys, db)
    code, out = _run(["user", "roles", "--user-id", "2", "--roles", "viewer"],
                     monkeypatch, capsys, db)
    assert code == 0
    assert out["user"]["roles"] == ["viewer"]
