import pytest

from hermes_seo_agent.cli import _rotate_title_rows, _select_title_rows


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


@pytest.mark.parametrize("size", [120, 300, 1000, 19_000])
def test_title_selection_covers_backlog_without_skipping_targets(size):
    rows = _rows(*(f"https://example.test/{index}" for index in range(size)))
    cursor = ""
    analyzed: list[str] = []

    for _ in range((size + 49) // 50):
        selection = _select_title_rows(
            rows, last_url=cursor, limit=50, scan_limit=250,
            should_skip=lambda _row: (False, ""),
        )
        batch = [row["keys"][0] for row in selection["targets"]]
        analyzed.extend(batch)
        assert len(batch) <= 50
        cursor = selection["last_scanned_url"] or cursor

    assert len(analyzed) == size
    assert len(set(analyzed)) == size


def test_title_selection_uses_scan_budget_only_for_skipped_urls():
    rows = _rows(*(f"https://example.test/{index}" for index in range(300)))

    selection = _select_title_rows(
        rows, limit=50, scan_limit=150,
        should_skip=lambda row: (
            int(row["keys"][0].rsplit("/", 1)[-1]) < 100,
            "pending",
        ),
    )

    assert len(selection["targets"]) == 50
    assert selection["targets"][0]["keys"][0].endswith("/100")
    assert selection["last_scanned_url"].endswith("/149")
    assert len(selection["skipped"]) == 100
