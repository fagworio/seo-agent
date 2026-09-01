"""SEO impact expectations — deterministic, no AI (Phase 6).

Given a page's current GSC metrics (position, impressions, clicks), compute
the EXPECTED clicks using the industry CTR-by-position benchmark, plus
conservative/realistic/optimistic scenarios. Pure math + a static benchmark
table — never a model call.
"""

from __future__ import annotations

from typing import Any

# Approximate organic CTR by ranking position (Advanced Web Ranking / Backlinko
# studies, rounded). Buckets: position <= key -> ctr.
_BENCHMARK: tuple[tuple[int, float], ...] = (
    (1, 0.35),
    (2, 0.16),
    (3, 0.11),
    (4, 0.075),
    (5, 0.055),
    (6, 0.045),
    (7, 0.04),
    (8, 0.035),
    (9, 0.03),
    (10, 0.025),
)

# Scenario multipliers: fraction of the benchmark the title fix could recover.
SCENARIOS = {
    "conservative": 0.25,
    "realistic": 0.50,
    "optimistic": 0.75,
}


def expected_ctr(position: float | None) -> float | None:
    """Benchmark CTR for a Google position (1 = top)."""
    if position is None:
        return None
    for rank, ctr in _BENCHMARK:
        if position <= rank:
            return ctr
    return 0.01  # page 2+ (position > 10)


def estimate(position: float | None, impressions: float | None, clicks: float | None) -> dict[str, Any]:
    """Deterministic improvement estimate for one page."""
    exp_ctr = expected_ctr(position)
    exp_clicks = None
    gap_clicks = None
    scenarios: dict[str, Any] = {}

    if exp_ctr is not None and impressions is not None:
        exp_clicks = round(float(impressions) * exp_ctr, 1)
        for name, mult in SCENARIOS.items():
            scenarios[f"{name}_clicks"] = round(exp_clicks * mult, 1)

    if exp_clicks is not None and clicks is not None:
        gap_clicks = round(exp_clicks - float(clicks), 1)

    return {
        "expected_ctr": exp_ctr,
        "expected_clicks": exp_clicks,
        "gap_clicks": gap_clicks,
        **scenarios,
    }


def build_expectation(metrics: dict[str, Any]) -> dict[str, Any]:
    """Full expectation record from a GSC page_metrics dict."""
    return {
        **metrics,
        **estimate(
            metrics.get("position"),
            metrics.get("impressions"),
            metrics.get("clicks"),
        ),
    }
