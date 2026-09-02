#!/usr/bin/env python3
"""Heuristic SEO Agent frontend guardrail scanner.

Reports design/architecture smells. Warnings are review hints, not compilation errors.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

EXTS = {".ts", ".tsx", ".js", ".jsx", ".css", ".scss"}
SKIP = {"node_modules", ".next", "dist", "build", "coverage", "generated"}

HEX = re.compile(r"(?<![\w-])#[0-9a-fA-F]{3,8}\b")
ARBITRARY_TW_COLOR = re.compile(r"(?:bg|text|border|ring)-\[#[0-9a-fA-F]{3,8}\]")
DIRECT_FETCH = re.compile(r"\bfetch\s*\(")
ANY_TYPE = re.compile(r"(?<![\w])any(?![\w])")


def iter_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in EXTS:
            continue
        if any(part in SKIP for part in path.parts):
            continue
        yield path


def is_token_file(path: Path) -> bool:
    lower = "/".join(path.parts).lower()
    return any(k in lower for k in ("token", "theme", "globals.css", "design-system"))


def is_api_file(path: Path) -> bool:
    lower = "/".join(path.parts).lower()
    return "/api/" in f"/{lower}/" or "/lib/http" in f"/{lower}"


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    if not root.exists():
        print(f"Path not found: {root}", file=sys.stderr)
        return 2

    warnings: list[str] = []
    for path in iter_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = path.relative_to(root)
        for line_no, line in enumerate(text.splitlines(), 1):
            if not is_token_file(path) and (HEX.search(line) or ARBITRARY_TW_COLOR.search(line)):
                warnings.append(f"{rel}:{line_no}: hardcoded color outside token/theme layer")
            if path.suffix in {".tsx", ".jsx"} and not is_api_file(path) and DIRECT_FETCH.search(line):
                warnings.append(f"{rel}:{line_no}: direct fetch() in component; prefer typed API/query layer")
            if path.suffix in {".ts", ".tsx"} and ANY_TYPE.search(line) and "// guardrail: allow-any" not in line:
                if re.search(r"[:<,]\s*any\b|\bas any\b", line):
                    warnings.append(f"{rel}:{line_no}: explicit any; isolate/justify boundary typing")

    if warnings:
        print("SEO Agent UI guardrail warnings:")
        for item in warnings:
            print(f"- {item}")
        print(f"\n{len(warnings)} warning(s). Review manually; this scanner does not fail the build.")
    else:
        print("SEO Agent UI guardrails: no heuristic warnings found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
