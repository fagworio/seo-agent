"""Rule registry — single source of truth for the finding taxonomy.

Each rule: id, severity (info|low|medium|high|critical), mode
(deterministic|ai), level (observe|safe_fix|approval_required), and the
suggested action. Only ``deterministic`` rules are evaluated in Phase 1.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    id: str
    severity: str
    mode: str  # deterministic | ai
    level: str  # observe | safe_fix | approval_required
    description: str
    suggested_action: str


RULES: tuple[Rule, ...] = (
    Rule("broken_internal_link", "high", "deterministic", "safe_fix",
         "Internal link returns 404", "remove or update the link"),
    Rule("broken_external_link", "medium", "deterministic", "safe_fix",
         "External link returns 404", "replace or remove the link"),
    Rule("redirect_chain", "medium", "deterministic", "approval_required",
         "URL redirects through more than one hop", "normalize to final target"),
    Rule("redirect_loop", "critical", "deterministic", "approval_required",
         "URL redirect loop detected", "fix the redirect rule"),
    Rule("canonical_missing", "medium", "deterministic", "approval_required",
         "Page has no rel=canonical", "set canonical to the static URL"),
    Rule("canonical_conflict", "high", "deterministic", "approval_required",
         "Canonical differs from expected URL", "align canonical"),
    Rule("noindex_inconsistency", "high", "deterministic", "approval_required",
         "Meta robots conflicts with X-Robots-Tag/robots.txt", "align robots directives"),
    Rule("sitemap_blocked", "high", "deterministic", "approval_required",
         "Sitemap URL is blocked by robots.txt", "fix robots.txt rule"),
    Rule("orphan_page", "medium", "deterministic", "approval_required",
         "URL in sitemap has no WP counterpart", "link internally or noindex"),
    Rule("title_duplicate", "medium", "deterministic", "approval_required",
         "Multiple pages share the same title", "rewrite duplicate titles"),
    Rule("title_missing", "high", "deterministic", "approval_required",
         "Page has no <title>", "add a title"),
    Rule("title_too_long", "low", "deterministic", "approval_required",
         "Title exceeds 65 characters", "shorten title"),
    Rule("meta_missing", "high", "deterministic", "approval_required",
         "Page has no meta description", "add meta description"),
    Rule("meta_too_long", "low", "deterministic", "approval_required",
         "Meta description exceeds 165 characters", "shorten meta description"),
    Rule("wp_static_mismatch", "high", "deterministic", "approval_required",
         "Published WP post missing from static site", "publish to static / rebuild"),
    Rule("static_orphan", "medium", "deterministic", "observe",
         "Static URL has no WP counterpart", "investigate (info only)"),
    Rule("cwv_lcp_poor", "medium", "deterministic", "observe",
         "LCP above 2.5s (field or lab)", "optimize LCP (safe if tooling configured)"),
    Rule("cwv_cls_poor", "medium", "deterministic", "observe",
         "CLS above 0.1 (field or lab)", "optimize CLS (safe if tooling configured)"),
    Rule("cwv_inp_poor", "medium", "deterministic", "observe",
         "INP above 200ms (field or lab)", "optimize INP (safe if tooling configured)"),
    Rule("image_no_alt", "low", "deterministic", "safe_fix",
         "Media item or <img> has no alt text", "set a descriptive alt text"),
    Rule("image_no_dimensions", "low", "deterministic", "safe_fix",
         "<img> without width/height attributes", "add width/height attributes"),
    Rule("low_ctr_opportunity", "medium", "deterministic", "observe",
         "High impressions, low CTR", "consider title rewrite (suggestion)"),
    Rule("zero_click_impression", "medium", "deterministic", "observe",
         "Impressions with no clicks over the window", "review content (suggestion)"),
    Rule("duplicate_content", "high", "deterministic", "approval_required",
         "Normalized title+H1 identical across pages", "canonicalize or consolidate"),
    Rule("thin_content", "medium", "ai", "approval_required",
         "Page content may be semantically thin", "improve content or noindex"),
    Rule("keyword_cannibalization", "high", "ai", "approval_required",
         "Multiple URLs target the same keyword", "consolidate or differentiate"),
)

_BY_ID = {rule.id: rule for rule in RULES}


def get_rule(rule_id: str) -> Rule | None:
    return _BY_ID.get(rule_id)


def deterministic_rules() -> tuple[Rule, ...]:
    return tuple(r for r in RULES if r.mode == "deterministic")
