"""Regressão: o audit incremental detecta mudança de CONTEÚDO, não só de URL.

O bug original usava fingerprint = sha256(lista_de_URLs): uma alteração em um
post que continua no sitemap (ex.: título/conteúdo/editado) não mudava o hash e
o audit pulava — deixando alterações reais sem auditoria.
"""
from hermes_seo_agent.cli import _audit_content_fingerprint


def _entries():
    return [("https://x.com/post/zelda/", "2026-01-10T00:00:00Z"),
            ("https://x.com/post/mario/", "")]


def _post(mod):
    return {"link": "https://x.com/post/zelda/", "modified": mod}


def test_same_content_same_fingerprint():
    fp1 = _audit_content_fingerprint(_entries(), [_post("2026-01-10T00:00:00Z")])
    fp2 = _audit_content_fingerprint(_entries(), [_post("2026-01-10T00:00:00Z")])
    assert fp1 == fp2


def test_post_modified_change_changes_fingerprint():
    a = _audit_content_fingerprint(_entries(), [_post("2026-01-10T00:00:00Z")])
    b = _audit_content_fingerprint(_entries(), [_post("2026-02-01T00:00:00Z")])
    assert a != b, "post editado deve mudar o fingerprint e forçar o audit"


def test_sitemap_lastmod_change_changes_fingerprint():
    a = _audit_content_fingerprint(_entries(), [])
    b = _audit_content_fingerprint(
        [("https://x.com/post/zelda/", "2026-02-01T00:00:00Z"),
         ("https://x.com/post/mario/", "")], [])
    assert a != b, "lastmod do sitemap mudou -> fingerprint deve mudar"


def test_fingerprint_is_deterministic_and_ordered():
    e1 = [("https://x.com/a/", ""), ("https://x.com/b/", "x")]
    e2 = [("https://x.com/b/", "x"), ("https://x.com/a/", "")]
    assert _audit_content_fingerprint(e1, []) == _audit_content_fingerprint(e2, [])
