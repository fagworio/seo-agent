"""WordPress REST client (read-only in Phase 1).

Mirrors unicornio-agent's client: Application Passwords via Basic auth,
`context=edit` where needed, server-side status filtering, pagination.
"""

from __future__ import annotations

from typing import Any

from ..config import Config
from .base import ConnectorError, HttpClient


class SafetyError(RuntimeError):
    """Raised when a write would violate a safety invariant (e.g. dry-run)."""


class WordPressClient:
    def __init__(self, config: Config, http: HttpClient | None = None):
        self.config = config
        self.base_url = f"{config.wordpress_url}{config.wordpress_api_base}"
        self.http = http or HttpClient(
            timeout=config.http_timeout,
            auth=(config.app_user, config.app_password) if config.app_user else None,
        )

    # -- reads ---------------------------------------------------------------

    def list_posts(
        self,
        *,
        status: str = "publish",
        per_page: int = 100,
        max_pages: int = 1000,
        fields: str = "id,slug,status,link,modified",
    ) -> list[dict[str, Any]]:
        """Fetch all posts of a status, following pagination via next link."""
        if not 1 <= per_page <= 100:
            raise ValueError("per_page must be in [1, 100]")
        posts: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            response = self.http.get(
                f"{self.base_url}/posts",
                params={"status": status, "per_page": per_page, "page": page, "_fields": fields},
            )
            if response.status_code == 400:
                # Some installations reject `status` on public queries; this
                # client authenticates, so keep it strict.
                raise ConnectorError(f"WordPress rejected status={status!r}: {response.text[:200]}")
            if response.status_code == 404:
                break  # page beyond last
            response.raise_for_status()
            batch = response.json()
            if not isinstance(batch, list) or not batch:
                break
            posts.extend(batch)
            total_pages = int(response.headers.get("X-WP-TotalPages", "0"))
            if page >= total_pages:
                break
        return posts

    def get_post(self, post_id: int, *, context: str = "edit") -> dict[str, Any]:
        if isinstance(post_id, bool) or not isinstance(post_id, int) or post_id < 1:
            raise ValueError("WordPress id must be a positive integer")
        response = self.http.get(f"{self.base_url}/posts/{post_id}", params={"context": context})
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise ConnectorError("WordPress returned an invalid post object")
        return value

    def get_post_by_slug(self, slug: str, *, context: str = "edit") -> dict[str, Any] | None:
        """Find a published post by slug (used to map static URL -> post_id)."""
        slug = (slug or "").strip().strip("/").split("/")[-1]
        if not slug:
            return None
        response = self.http.get(
            f"{self.base_url}/posts",
            params={"slug": slug, "status": "publish", "context": context, "per_page": 1},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        return None

    def get_media(self, media_id: int) -> dict[str, Any]:
        if isinstance(media_id, bool) or not isinstance(media_id, int) or media_id < 1:
            raise ValueError("WordPress id must be a positive integer")
        response = self.http.get(f"{self.base_url}/media/{media_id}")
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise ConnectorError("WordPress returned an invalid media object")
        return value

    def list_media(self, per_page: int = 100, max_pages: int = 10) -> list[dict[str, Any]]:
        media: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            response = self.http.get(
                f"{self.base_url}/media",
                params={"per_page": per_page, "page": page, "_fields": "id,source_url,alt_text,title"},
            )
            if response.status_code == 404:
                break
            response.raise_for_status()
            batch = response.json()
            if not isinstance(batch, list) or not batch:
                break
            media.extend(batch)
            total_pages = int(response.headers.get("X-WP-TotalPages", "0"))
            if page >= total_pages:
                break
        return media

    # -- safe writes (Phase 4 executor; blocked by dry-run) ------------------

    def update_media_alt(self, media_id: int, alt_text: str) -> dict[str, Any]:
        """Set alt_text on a media item — a low-risk, reversible safe_fix."""
        if self.config.dry_run:
            raise SafetyError("dry-run blocks WordPress media writes")
        if not isinstance(alt_text, str) or not alt_text.strip():
            raise ValueError("alt_text must be a non-empty string")
        response = self.http.post(
            f"{self.base_url}/media/{self._id(media_id)}",
            json_body={"alt_text": alt_text.strip()},
        )
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise ConnectorError("WordPress returned an invalid media object")
        return value

    def update_post_meta(self, post_id: int, meta: dict[str, Any]) -> dict[str, Any]:
        """Patch meta (e.g. Rank Math fields) on a post — reversible safe_fix.

        Refuses to touch `status` (mirrors unicornio-agent's invariant).
        """
        if self.config.dry_run:
            raise SafetyError("dry-run blocks WordPress post writes")
        if not isinstance(meta, dict) or not meta:
            raise ValueError("meta must be a non-empty dict")
        if "status" in meta:
            raise SafetyError("status must never be included in a meta payload")
        response = self.http.post(
            f"{self.base_url}/posts/{self._id(post_id)}",
            json_body={"meta": meta},
        )
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise ConnectorError("WordPress returned an invalid post object")
        return value

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> "WordPressClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    @staticmethod
    def _id(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError("WordPress id must be a positive integer")
        return value
