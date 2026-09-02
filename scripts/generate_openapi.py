"""Gera o OpenAPI spec do control plane p/ a toolchain do frontend.

Uso: .venv/bin/python scripts/generate_openapi.py
Escreve frontend/api/openapi.json (consumido por `npm run generate:api`).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from hermes_seo_agent.api.app import create_app
from hermes_seo_agent.config import load_config


def main() -> int:
    config = load_config()
    app = create_app(storage_path=config.sqlite_path, config=config)
    spec = app.openapi()
    out = Path("frontend/api/openapi.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out}: {len(spec['paths'])} paths, {len(spec['components']['schemas'])} schemas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
