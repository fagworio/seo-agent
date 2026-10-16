from hermes_seo_agent.cli import _rotate_title_rows


def _rows(*urls):
    return [{"keys": [url], "impressions": 100} for url in urls]


def test_title_rotation_starts_after_persisted_url():
    ordered, start = _rotate_title_rows(
        _rows("https://example.test/a", "https://example.test/b",
              "https://example.test/c"),
        "https://example.test/a",
    )

    assert [row["keys"][0] for row in ordered] == [
        "https://example.test/b", "https://example.test/c", "https://example.test/a"
    ]
    assert start == "https://example.test/b"


def test_title_rotation_recovers_when_last_url_disappears():
    ordered, start = _rotate_title_rows(
        _rows("https://example.test/b", "https://example.test/c"),
        "https://example.test/removed",
    )

    assert [row["keys"][0] for row in ordered] == [
        "https://example.test/b", "https://example.test/c"
    ]
    assert start == "https://example.test/b"
