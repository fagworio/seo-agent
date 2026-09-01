"""Screaming Frog crawl CSV import (Phase 5, deterministic).

Screaming Frog exports a crawl as CSV with an "Address" column and a "Status
Code" column. This tool normalizes that into a URL list with statuses — useful
as a deeper crawl input for audit (optional; the agent's own crawl works
standalone). No API key; reads the exported file.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


def import_crawl_csv(path: str | Path) -> list[dict[str, Any]]:
    """Parse a Screaming Frog CSV export.

    Returns rows: [{url, status_code, title, ...}] for rows with an Address.
    Column names are matched case-insensitively.
    """
    rows: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            return rows
        lower = {field.strip().lower(): field for field in reader.fieldnames}
        address_col = lower.get("address")
        if not address_col:
            raise ValueError("CSV has no 'Address' column (not a Screaming Frog export?)")
        status_col = lower.get("status code")
        title_col = lower.get("title 1") or lower.get("title")

        for record in reader:
            url = (record.get(address_col) or "").strip()
            if not url:
                continue
            row: dict[str, Any] = {"url": url}
            if status_col:
                try:
                    row["status_code"] = int(record.get(status_col) or 0)
                except ValueError:
                    row["status_code"] = 0
            if title_col and record.get(title_col):
                row["title"] = record.get(title_col).strip()
            rows.append(row)
    return rows


def summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    statuses: dict[int, int] = {}
    for row in rows:
        statuses[row.get("status_code", 0)] = statuses.get(row.get("status_code", 0), 0) + 1
    return {
        "urls": len(rows),
        "ok_200": statuses.get(200, 0),
        "redirects": statuses.get(301, 0) + statuses.get(302, 0) + statuses.get(308, 0),
        "not_found_404": statuses.get(404, 0),
        "errors_5xx": sum(v for k, v in statuses.items() if k >= 500),
        "other": sum(v for k, v in statuses.items() if k not in {0, 200, 301, 302, 308, 404} and not (k >= 500)),
    }
