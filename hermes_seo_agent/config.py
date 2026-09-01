"""Validated runtime configuration with fail-closed write safety.

Mirrors the pattern of unicornio-agent: dependency-free env parsing,
explicit whitelists, and write mode requires credentials.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


class ConfigError(ValueError):
    """Raised when runtime configuration is unsafe or malformed."""


@dataclass(frozen=True, repr=False)
class Config:
    # WordPress (source of content)
    wordpress_url: str
    wordpress_api_base: str = "/wp-json/wp/v2"
    app_user: str = ""
    app_password: str = field(default="", repr=False)

    # Static published site (what Google crawls)
    static_site_url: str = "https://www.unicorniohater.com.br"
    sitemap_url: str = "https://www.unicorniohater.com.br/sitemap_index.xml"

    # Google (Phase 2/3)
    gsc_site_url: str = "https://www.unicorniohater.com.br/"
    google_credentials: str = ""          # path to service-account JSON
    gsc_token_provider: object | None = None  # injectable bearer-token callable (tests)
    pagespeed_api_key: str = ""
    crux_api_key: str = ""
    ga4_property_id: str = ""

    # URL Inspection budget
    url_inspection_daily_budget: int = 1800
    url_inspection_grace_period_hours: int = 24
    search_analytics_days: int = 28
    editorial_measurement_min_days: int = 28

    # Alerting (Phase 5)
    alert_webhook_url: str = ""
    alert_high_threshold: int = 10

    # Safety / mode
    dry_run: bool = True
    http_timeout: float = 15.0
    max_redirect_hops: int = 5
    max_urls_per_run: int = 500
    max_safe_fix_per_cycle: int = 10

    # State
    sqlite_path: str = "./state/seo_agent.db"

    def __repr__(self) -> str:
        return (
            "Config("
            f"wordpress_url={self.wordpress_url!r}, "
            f"static_site_url={self.static_site_url!r}, "
            f"sitemap_url={self.sitemap_url!r}, "
            f"app_user={self.app_user!r}, dry_run={self.dry_run!r}, "
            f"max_urls_per_run={self.max_urls_per_run!r})"
        )


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _bool(name: str, default: bool) -> bool:
    value = _env(name)
    if not value:
        return default
    if value.lower() in {"1", "true", "yes", "on"}:
        return True
    if value.lower() in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be a boolean")


def _int(name: str, default: int, minimum: int, maximum: int) -> int:
    value = _env(name)
    try:
        parsed = int(value) if value else default
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _float(name: str, default: float, minimum: float, maximum: float) -> float:
    value = _env(name)
    try:
        parsed = float(value) if value else default
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number") from exc
    if not minimum <= parsed <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _validate_url(name: str, value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError(f"{name} must be an absolute HTTP(S) URL")
    return value.rstrip("/")


def _validate_site_url(name: str, value: str) -> str:
    """Search Console property: URL-prefix (https://.../) or domain (sc-domain:...)."""
    value = value.strip()
    if value.startswith("sc-domain:") and value[len("sc-domain:"):].strip():
        return value
    return _validate_url(name, value)


def _load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader (no python-dotenv dep). Never overrides existing env."""
    path = path or Path(os.environ.get("SEO_ENV_FILE", ".env"))
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_config() -> Config:
    _load_dotenv()

    wordpress_url = _validate_url(
        "WORDPRESS_URL", _env("WORDPRESS_URL", "http://wordpress.dvl.to:8080")
    )
    api_base = _env("WORDPRESS_API_BASE", "/wp-json/wp/v2")
    if not api_base.startswith("/") or "?" in api_base or "#" in api_base:
        raise ConfigError("WORDPRESS_API_BASE must be a safe path")
    api_base = "/" + api_base.strip("/")

    dry_run = _bool("DRY_RUN", True)
    app_user = _env("WORDPRESS_APP_USER")
    app_password = _env("WORDPRESS_APP_PASSWORD")
    if not dry_run and (not app_user or not app_password):
        raise ConfigError("write mode requires WORDPRESS_APP_USER and WORDPRESS_APP_PASSWORD")

    static_site_url = _validate_url(
        "STATIC_SITE_URL", _env("STATIC_SITE_URL", "https://www.unicorniohater.com.br")
    )
    sitemap_url = _validate_url(
        "SITEMAP_URL",
        _env("SITEMAP_URL", f"{static_site_url}/sitemap_index.xml"),
    )

    return Config(
        wordpress_url=wordpress_url,
        wordpress_api_base=api_base,
        app_user=app_user,
        app_password=app_password,
        static_site_url=static_site_url,
        sitemap_url=sitemap_url,
        gsc_site_url=_validate_site_url(
            "GSC_SITE_URL", _env("GSC_SITE_URL", "https://www.unicorniohater.com.br/")
        ),
        google_credentials=_env("GOOGLE_APPLICATION_CREDENTIALS"),
        # GOOGLE_API_KEY is a shared fallback for APIs that accept keys
        # (PageSpeed/CrUX). GSC does NOT accept API keys (needs the SA JSON).
        pagespeed_api_key=_env("PAGESPEED_API_KEY") or _env("GOOGLE_API_KEY"),
        crux_api_key=_env("CRUX_API_KEY") or _env("GOOGLE_API_KEY"),
        ga4_property_id=_env("GA4_PROPERTY_ID"),
        url_inspection_daily_budget=_int("URL_INSPECTION_DAILY_BUDGET", 1800, 1, 100_000),
        url_inspection_grace_period_hours=_int(
            "URL_INSPECTION_GRACE_PERIOD_HOURS", 24, 0, 24 * 365
        ),
        search_analytics_days=_int("SEARCH_ANALYTICS_DAYS", 28, 7, 90),
        editorial_measurement_min_days=_int("EDITORIAL_MEASUREMENT_MIN_DAYS", 28, 1, 365),
        alert_webhook_url=_env("ALERT_WEBHOOK_URL"),
        alert_high_threshold=_int("ALERT_HIGH_THRESHOLD", 10, 1, 10_000),
        dry_run=dry_run,
        http_timeout=_float("HTTP_TIMEOUT", 15.0, 1.0, 120.0),
        max_redirect_hops=_int("MAX_REDIRECT_HOPS", 5, 1, 20),
        max_urls_per_run=_int("MAX_URLS_PER_RUN", 500, 1, 100_000),
        max_safe_fix_per_cycle=_int("MAX_SAFE_FIX_PER_CYCLE", 10, 0, 1000),
        sqlite_path=_env("SQLITE_PATH", "./state/seo_agent.db"),
    )
