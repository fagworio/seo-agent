"""R7 (Competitor Corpus) e R8 (Content Gap Engine) — determinístico."""
from hermes_seo_agent.storage.db import Storage
from hermes_seo_agent.report.competitor import extract_entries, resolve_topic_keys
from hermes_seo_agent.report.content_gap import build_gaps, content_gaps


GRAPH = [{"entity": "dragon ball", "urls": ["https://x.com/a/"]},
         {"entity": "one piece", "urls": ["https://x.com/b/"]}]

_SITEMAP = ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            '<url><loc>https://omelete.com.br/dragon-ball-daima-temporada-2/</loc>'
            '<lastmod>2026-01-05</lastmod></url>'
            '<url><loc>https://omelete.com.br/one-piece-gear-5/</loc>'
            '<lastmod>2026-01-06</lastmod></url>'
            '<url><loc>https://omelete.com.br/persona-6-review/</loc>'
            '<lastmod>2026-01-07</lastmod></url>'
            '</urlset>')


def test_extract_entries_parses_sitemap_and_resolves_topics():
    entries = extract_entries(_SITEMAP, "omelete.com.br", GRAPH)
    assert len(entries) == 3
    first = entries[0]
    assert first["url"] == "https://omelete.com.br/dragon-ball-daima-temporada-2/"
    assert first["published_at"] == "2026-01-05"
    assert "dragon ball" in first["entities"]
    # persona 6 não está no nosso graph -> fallback de slug
    assert entries[2]["entities"] and entries[2]["entities"] != []


def test_resolve_topic_keys_prefers_our_graph():
    keys = resolve_topic_keys("https://ign.com/dragon-ball-super-episodios/", "", GRAPH)
    assert "dragon ball" in keys
    keys2 = resolve_topic_keys("https://ign.com/persona-6-characters/", "", GRAPH)
    assert keys2 != []  # fallback por slug


def test_build_gaps_types():
    our_meta = {
        "dragon ball": {"n": 1, "freshness_days": 30, "questions": 0},
        "one piece": {"n": 5, "freshness_days": 120, "questions": 0},
    }
    comp_coverage = {
        "dragon ball": {"omelete": 10, "ign": 8},
        "persona 6": {"ign": 5},
        "one piece": {"omelete": 15},
    }
    gaps = build_gaps(our_meta, comp_coverage)
    types = {g["type"] for g in gaps}
    assert "missing_topic" in types            # persona 6 não cobrimos
    assert "weak_coverage" in types            # dragon ball fraco
    assert "competitor_dominance" in types     # one piece dominado
    assert "outdated_coverage" in types        # one piece velho
    persona = next(g for g in gaps if g["topic"] == "persona 6")
    assert persona["type"] == "missing_topic"


def test_gap_score_percent():
    gaps = build_gaps({"persona": {"n": 0, "freshness_days": None, "questions": 0}},
                      {"persona": {"ign": 5}}, as_percent=True)
    assert 0 <= gaps[0]["gap_score"] <= 100


def _seed_competitor(storage: Storage) -> int:
    entries = [
        {"domain": "omelete.com.br", "url": f"https://omelete.com.br/dragon-ball-{i}/",
         "title": "Dragon Ball", "published_at": "2026-01-01", "entities": ["dragon ball"]}
        for i in range(2)
    ]
    entries += [
        {"domain": "ign.com", "url": f"https://ign.com/persona-6-{i}/",
         "title": "Persona 6", "published_at": "2026-01-03", "entities": ["persona 6"]}
        for i in range(3)
    ]
    return storage.upsert_competitor_documents(entries)


def test_content_gaps_end_to_end():
    s = Storage(":memory:")
    _seed_competitor(s)
    # nosso corpus só cobre "dragon ball" (1 doc) e "one piece"
    for url, entity in [("https://x.com/a/", "dragon ball"),
                        ("https://x.com/b/", "one piece")]:
        s.conn.execute(
            "INSERT INTO corpus_entities (url, entity, entity_type) VALUES (?, ?, 'franchise')",
            (url, entity))
        s.conn.execute(
            "INSERT INTO corpus_documents (url, title, body_text, content_hash, built_at) "
            "VALUES (?, ?, 'corpo', 'h', '2026-02-01')", (url, "Título"))
    s.conn.commit()
    report = content_gaps(s)
    assert report["total"] >= 1
    assert report["by_type"].get("missing_topic", 0) >= 1  # persona 6
    s.close()


def test_storage_competitor_documents():
    s = Storage(":memory:")
    n = _seed_competitor(s)
    assert n == 5
    coverage = s.competitor_topic_coverage()
    assert coverage.get("dragon ball", {}).get("omelete.com.br") == 2
    docs = s.list_competitor_documents(domain="ign.com")
    assert len(docs) == 3 and docs[0]["entities"] == ["persona 6"]
    s.close()
