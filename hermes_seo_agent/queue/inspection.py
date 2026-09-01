"""Inspection queue builder — deterministic priority assignment + budget logic.

Priority tiers (README "URL Inspection strategy for large sites"):
  1. Newly published URLs older than the grace period.
  2. URLs in sitemap with zero Search Console impressions.
  3. URLs that recently lost impressions/clicks.
  4. URLs returning non-200 responses.
  5. URLs with canonical/sitemap conflicts.
  6. Old URLs not inspected recently.
Lower number = inspected first. All logic is pure and testable.
"""

from __future__ import annotations

import datetime
from typing import Any

from ..inventory.reconcile import normalize_url


def assign_priority(
    *,
    is_new_past_grace: bool = False,
    zero_impressions: bool = False,
    lost_traffic: bool = False,
    non_200: bool = False,
    conflict: bool = False,
    stale: bool = False,
) -> int:
    """Return the highest-priority tier (lowest number) that applies."""
    for tier, flag in (
        (1, is_new_past_grace),
        (2, zero_impressions),
        (3, lost_traffic),
        (4, non_200),
        (5, conflict),
        (6, stale),
    ):
        if flag:
            return tier
    return 6


def is_new_past_grace(modified_iso: str | None, *, grace_hours: int, now: datetime.datetime | None = None) -> bool:
    """URL published recently but older than the grace period (tier 1)."""
    if not modified_iso:
        return False
    try:
        modified = datetime.datetime.fromisoformat(modified_iso.replace("Z", "+00:00"))
    except ValueError:
        return False
    if modified.tzinfo is None:
        modified = modified.replace(tzinfo=datetime.timezone.utc)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    age = now - modified
    if age < datetime.timedelta(0):
        return False  # future-dated (scheduled)
    return datetime.timedelta(hours=grace_hours) <= age <= datetime.timedelta(days=30)


def lost_traffic(previous_impressions: float, current_impressions: float, *, decline_ratio: float = 0.5) -> bool:
    """Impressions dropped by at least `decline_ratio` vs the previous period."""
    if previous_impressions <= 0:
        return False
    return current_impressions <= previous_impressions * (1 - decline_ratio)


def build_queue_entries(
    urls: list[str],
    *,
    modified_by_url: dict[str, str] | None = None,
    impressions_by_url: dict[str, float] | None = None,
    prev_impressions_by_url: dict[str, float] | None = None,
    non_200_urls: set[str] | None = None,
    conflict_urls: set[str] | None = None,
    stale_urls: set[str] | None = None,
    grace_hours: int = 24,
    now: datetime.datetime | None = None,
) -> list[dict[str, Any]]:
    """Build priority-tagged queue entries for the given URLs.

    All input maps are keyed by normalized path (see inventory.reconcile).
    URLs never seen before (not in stale_urls) are tier 6 by default.
    """
    modified_by_url = modified_by_url or {}
    impressions_by_url = impressions_by_url or {}
    prev_impressions_by_url = prev_impressions_by_url or {}
    non_200_urls = non_200_urls or set()
    conflict_urls = conflict_urls or set()
    stale_urls = stale_urls or set()

    entries: list[dict[str, Any]] = []
    for url in urls:
        key = normalize_url(url)
        priority = assign_priority(
            is_new_past_grace=is_new_past_grace(
                modified_by_url.get(key), grace_hours=grace_hours, now=now
            ),
            zero_impressions=key in impressions_by_url and impressions_by_url[key] <= 0,
            lost_traffic=lost_traffic(
                prev_impressions_by_url.get(key, 0), impressions_by_url.get(key, 0)
            ),
            non_200=key in non_200_urls,
            conflict=key in conflict_urls,
            stale=key in stale_urls,
        )
        entries.append({"url": url, "priority": priority, "source": "inventory"})
    return entries


def remaining_budget(daily_budget: int, used: int) -> int:
    return max(0, daily_budget - used)
