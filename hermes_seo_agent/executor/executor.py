"""Phase 4 executor — applies safe_fix actions with hard safety invariants.

Rules enforced here are CODE, not convention:
  * deletes are rejected by construction (no delete fix type exists);
  * every action is idempotent (fingerprint) and recorded in the audit trail;
  * every action carries an explicit rollback payload;
  * blast radius caps safe actions per cycle;
  * DRY_RUN=true blocks all writes (preview only).
The executor never guesses a fix: only actions carrying a supported ``fix``
spec are executed — intent comes from the agent/AI, mechanics are this code.
"""

from __future__ import annotations

import hashlib
from typing import Any

from ..config import Config
from ..connectors.wordpress import WordPressClient
from ..storage.db import Storage

SUPPORTED_FIX_TYPES = ("wp_media_alt", "wp_post_meta", "wp_post_content_patch")


class Executor:
    def __init__(self, config: Config, wp: WordPressClient, storage: Storage):
        self.config = config
        self.wp = wp
        self.storage = storage

    def apply_safe_actions(
        self,
        actions: list[dict[str, Any]],
        *,
        cycle_id: str,
        max_actions: int | None = None,
        verify: Any = None,
    ) -> dict[str, Any]:
        """Execute (or preview) safe actions, bounded by the blast radius.

        ``verify`` is an optional post-write confirmation callable
        ``verify(fix, after) -> bool``. When it returns False the action is
        recorded as status='unverified' (NOT executed): it does not block a
        retry, and the caller must treat it as a failure (fix the root cause,
        e.g. mu-plugin/permissions, then retry).
        """
        cap = max_actions if max_actions is not None else self.config.max_safe_fix_per_cycle
        actions = actions[:cap]
        executed: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        previewed: list[dict[str, Any]] = []
        unverified: list[dict[str, Any]] = []

        for action in actions:
            rule_id = action.get("rule_id", "")
            url = action.get("url", "")
            fix = action.get("fix") or {}
            # Fingerprint inclui o CONTEÚDO do fix (ex.: post_id + meta_key +
            # novo_valor), não só o detail — dois títulos com o mesmo número de
            # caracteres NÃO colidem mais como "already executed".
            fingerprint = _fingerprint(rule_id, url, action.get("detail", ""), fix)

            if fix.get("type") not in SUPPORTED_FIX_TYPES:
                skipped.append({**action, "reason": "no supported fix spec"})
                continue

            if self.storage.action_executed(fingerprint):
                skipped.append({**action, "reason": "already executed (idempotent)"})
                continue

            if self.config.dry_run:
                previewed.append(
                    {**action, "fingerprint": fingerprint,
                     "note": "dry-run: would execute this fix"}
                )
                continue

            try:
                result = self._execute(fix)
            except Exception as exc:  # a failing fix must not kill the cycle
                skipped.append({**action, "reason": f"failed: {exc}"})
                continue

            before, after, rollback = result
            if verify is not None:
                try:
                    confirmed = bool(verify(fix, after))
                except Exception:
                    confirmed = False
                if not confirmed:
                    # Escrita ocorreu, mas a confirmação REST pós-write falhou:
                    # registra como UNVERIFIED (retry permitido, não executed).
                    self.storage.record_action(
                        cycle_id=cycle_id, rule_id=rule_id, url=url,
                        level="safe_fix", fingerprint=fingerprint,
                        before=before, after=after, rollback=rollback,
                        status="unverified", fix=fix,
                    )
                    self.storage.log_audit(
                        actor="executor",
                        action_type=f"safe_fix:{fix['type']}:unverified",
                        entity=url,
                        before=before,
                        after=after,
                    )
                    unverified.append(
                        {**action, "fingerprint": fingerprint,
                         "reason": "confirmação REST pós-write falhou (unverified)"}
                    )
                    continue

            self.storage.record_action(
                cycle_id=cycle_id,
                rule_id=rule_id,
                url=url,
                level="safe_fix",
                fingerprint=fingerprint,
                before=before,
                after=after,
                rollback=rollback,
                fix=fix,
            )
            self.storage.log_audit(
                actor="executor",
                action_type=f"safe_fix:{fix['type']}",
                entity=url,
                before=before,
                after=after,
            )
            executed.append({**action, "fingerprint": fingerprint})

        return {
            "executed": executed,
            "previewed": previewed,
            "skipped": skipped,
            "unverified": unverified,
            "dry_run": self.config.dry_run,
        }

    # -- fix implementations -------------------------------------------------

    def _execute(self, fix: dict[str, Any]) -> tuple[Any, Any, Any]:
        fix_type = fix["type"]
        if fix_type == "wp_media_alt":
            return self._fix_media_alt(int(fix["media_id"]), str(fix["alt_text"]))
        if fix_type == "wp_post_meta":
            return self._fix_post_meta(int(fix["post_id"]), dict(fix["meta"]))
        if fix_type == "wp_post_content_patch":
            return self._fix_post_content_patch(fix)
        raise ValueError(f"unsupported fix type: {fix_type}")

    def _fix_media_alt(self, media_id: int, alt_text: str) -> tuple[Any, Any, Any]:
        media = self.wp.get_media(media_id)
        before = {"alt_text": (media.get("alt_text") or "")}
        after = {"alt_text": alt_text}
        rollback = {"type": "wp_media_alt", "media_id": media_id, "alt_text": before["alt_text"]}
        self.wp.update_media_alt(media_id, alt_text)
        return before, after, rollback

    def _fix_post_meta(self, post_id: int, meta: dict[str, Any]) -> tuple[Any, Any, Any]:
        post = self.wp.get_post(post_id)
        existing_meta = dict(post.get("meta") or {})
        before = {k: existing_meta.get(k) for k in meta}
        after = dict(meta)
        rollback = {"type": "wp_post_meta", "post_id": post_id,
                    "meta": {k: existing_meta.get(k) for k in meta}}
        self.wp.update_post_meta(post_id, meta)
        return before, after, rollback

    def _fix_post_content_patch(self, fix: dict[str, Any]) -> tuple[Any, Any, Any]:
        """B9 — insere um link interno no conteúdo com precondições de segurança.

        - hash do conteúdo deve bater com `expected_content_hash` (senão STALE);
        - se o link de destino já existe, é no-op (não duplica);
        - se o trecho de contexto sumiu, STALE;
        - rollback = conteúdo original (restauração total).
        """
        post_id = int(fix["post_id"])
        expected_hash = fix.get("expected_content_hash", "")
        target_url = fix.get("target_url", "")
        context_before = fix.get("context_before", "")
        insertion = fix.get("insertion", "")

        post = self.wp.get_post(post_id)
        content_obj = post.get("content") or {}
        content = content_obj.get("raw", "") or content_obj.get("rendered", "")
        before = {"content": content}

        if expected_hash:
            current_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if current_hash != expected_hash:
                raise ValueError("STALE: conteúdo alterado desde a aprovação")

        if target_url and target_url in content:
            return before, {"content": content}, {
                "type": "wp_post_content_patch", "post_id": post_id, "content": content}

        if context_before and context_before not in content:
            raise ValueError("STALE: trecho de contexto não encontrado")

        if context_before:
            idx = content.index(context_before) + len(context_before)
            new_content = content[:idx] + insertion + content[idx:]
        else:
            new_content = insertion + content

        self.wp.update_post_content(post_id, new_content)
        after = {"content": new_content}
        rollback = {"type": "wp_post_content_patch", "post_id": post_id, "content": content}
        return before, after, rollback


def _fingerprint(rule_id: str, url: str, detail: str,
                 fix: dict[str, Any] | None = None) -> str:
    """Deterministic action fingerprint.

    Includes the fix CONTENT (canonical JSON) so idempotence reflects what the
    action actually writes — post_id + meta_key + novo_valor — not just the
    free-text detail. Same action twice -> same fingerprint; different value
    (even same detail/length) -> different fingerprint.
    """
    import json as _json

    fix_part = _json.dumps(fix, sort_keys=True, ensure_ascii=False) if fix else ""
    raw = f"{rule_id}|{url}|{detail}|{fix_part}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]
