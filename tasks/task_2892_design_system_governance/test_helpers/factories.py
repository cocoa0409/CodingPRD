"""
Request-payload builders.

Each builder produces the smallest body the API declares as valid for its
endpoint and lets a test override any field. Optional fields are omitted unless
a caller supplies them, so a test that wants to observe a declared default can
simply leave the field out. Numeric fields are always emitted as JSON numbers
and instants always as full ISO 8601 UTC instants.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import (
    AUDIT_METHOD_AUTOMATED,
    DECISION_APPROVE,
    EXCEPTION_ONE_OFF_COMPONENT,
    KIND_ENHANCEMENT,
    MATURITY_BETA,
    PLATFORM_WEB,
    SCAN_KIND_CODE_SCAN,
    STAGE_DESIGN_CRITIQUE,
    TOKEN_CATEGORIES,
    VERDICT_APPROVE,
    WCAG_AA,
)
from .types import Payload

_counter = itertools.count(1)


def unique_suffix() -> str:
    """A short suffix that makes slugs and package names unique within a test."""
    return f"{next(_counter):04d}"


def _merge(base: Payload, overrides: Dict[str, Any]) -> Payload:
    """Apply overrides, dropping any key whose override value is the sentinel."""
    body = dict(base)
    for key, value in overrides.items():
        if value is _OMIT:
            body.pop(key, None)
        else:
            body[key] = value
    return body


class _Omit:
    """Sentinel meaning "leave this field out of the body entirely"."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<OMIT>"


_OMIT = _Omit()
OMIT = _OMIT


# ─── Teams and adoption ───────────────────────────────

def team_payload(
    name: str = "Design Guild",
    slug: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    """A team registration body; optional scope and budget are omitted by default."""
    base: Payload = {
        "name": name,
        "slug": slug or f"design-guild-{unique_suffix()}",
    }
    return _merge(base, overrides)


def adoption_scan_payload(
    window_start_at: str,
    window_end_at: str,
    system_instance_count: int = 80,
    legacy_instance_count: int = 20,
    one_off_instance_count: int = 0,
    scan_kind: str = SCAN_KIND_CODE_SCAN,
    **overrides: Any,
) -> Payload:
    """One adoption measurement over a closed window."""
    base: Payload = {
        "scan_kind": scan_kind,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
        "system_instance_count": system_instance_count,
        "legacy_instance_count": legacy_instance_count,
        "one_off_instance_count": one_off_instance_count,
    }
    return _merge(base, overrides)


# ─── Token sets and tokens ────────────────────────────

def token_set_payload(
    name: str = "Core Tokens",
    slug: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    """A token set body; `default_brand` and `default_mode` are omitted by default."""
    base: Payload = {
        "name": name,
        "slug": slug or f"core-tokens-{unique_suffix()}",
    }
    return _merge(base, overrides)


def leaf_token_payload(
    token_set_id: str,
    name: str,
    raw_value: str,
    expected_token_set_version: int,
    category: str = TOKEN_CATEGORIES[0],
    **overrides: Any,
) -> Payload:
    """A raw-valued token: `raw_value` set, no alias target."""
    base: Payload = {
        "token_set_id": token_set_id,
        "name": name,
        "category": category,
        "raw_value": raw_value,
        "expected_token_set_version": expected_token_set_version,
    }
    return _merge(base, overrides)


def alias_token_payload(
    token_set_id: str,
    name: str,
    alias_of_token_id: str,
    expected_token_set_version: int,
    category: str = TOKEN_CATEGORIES[0],
    **overrides: Any,
) -> Payload:
    """An alias token: `alias_of_token_id` set, no raw value."""
    base: Payload = {
        "token_set_id": token_set_id,
        "name": name,
        "category": category,
        "alias_of_token_id": alias_of_token_id,
        "expected_token_set_version": expected_token_set_version,
    }
    return _merge(base, overrides)


def token_repoint_raw_payload(
    raw_value: str, expected_token_set_version: int, **overrides: Any
) -> Payload:
    """Re-point a token onto a replacement raw value."""
    base: Payload = {
        "raw_value": raw_value,
        "expected_token_set_version": expected_token_set_version,
    }
    return _merge(base, overrides)


def token_repoint_alias_payload(
    alias_of_token_id: str, expected_token_set_version: int, **overrides: Any
) -> Payload:
    """Re-point a token onto a new alias target."""
    base: Payload = {
        "alias_of_token_id": alias_of_token_id,
        "expected_token_set_version": expected_token_set_version,
    }
    return _merge(base, overrides)


# ─── Components, implementations, dependencies ────────

def component_payload(
    owning_team_id: str,
    name: str = "Badge",
    slug: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    """A component registration body; `docs_state` is omitted by default."""
    base: Payload = {
        "name": name,
        "slug": slug or f"badge-{unique_suffix()}",
        "owning_team_id": owning_team_id,
    }
    return _merge(base, overrides)


def implementation_payload(
    platform: str = PLATFORM_WEB,
    package_name: Optional[str] = None,
    package_version: str = "1.0.0",
    **overrides: Any,
) -> Payload:
    """A platform implementation body; `token_compliance_ratio` omitted by default."""
    base: Payload = {
        "platform": platform,
        "package_name": package_name or f"@ds/component-{unique_suffix()}",
        "package_version": package_version,
    }
    return _merge(base, overrides)


def ship_payload(
    package_version: str = "1.0.0",
    token_compliance_ratio: float = 0.95,
    **overrides: Any,
) -> Payload:
    """A ship body: the released version and the ratio measured against it."""
    base: Payload = {
        "package_version": package_version,
        "token_compliance_ratio": token_compliance_ratio,
    }
    return _merge(base, overrides)


def audit_payload(
    violations_critical: int = 0,
    violations_serious: int = 0,
    violations_moderate: int = 0,
    method: str = AUDIT_METHOD_AUTOMATED,
    wcag_level: str = WCAG_AA,
    evidence_url: str = "https://evidence.example.com/report",
    **overrides: Any,
) -> Payload:
    """One accessibility audit record."""
    base: Payload = {
        "method": method,
        "wcag_level": wcag_level,
        "violations_critical": violations_critical,
        "violations_serious": violations_serious,
        "violations_moderate": violations_moderate,
        "evidence_url": evidence_url,
    }
    return _merge(base, overrides)


def dependency_payload(
    provider_component_id: str, pinned_provider_major: int = 1, **overrides: Any
) -> Payload:
    """A dependency edge from the path component to a provider."""
    base: Payload = {
        "provider_component_id": provider_component_id,
        "pinned_provider_major": pinned_provider_major,
    }
    return _merge(base, overrides)


def dependency_repin_payload(pinned_provider_major: int, **overrides: Any) -> Payload:
    """A re-pin body for an existing dependency edge."""
    return _merge({"pinned_provider_major": pinned_provider_major}, overrides)


def promote_payload(
    target_maturity_level: str = MATURITY_BETA, **overrides: Any
) -> Payload:
    """A maturity promotion body naming the one-step target level."""
    return _merge({"target_maturity_level": target_maturity_level}, overrides)


# ─── Contribution proposals ───────────────────────────

def proposal_payload(
    author_team_id: str,
    target_component_id: str,
    pinned_token_set_id: str,
    title: str = "Refine the badge",
    proposal_kind: str = KIND_ENHANCEMENT,
    **overrides: Any,
) -> Payload:
    """A proposal body; `touches_public_api` is omitted by default."""
    base: Payload = {
        "title": title,
        "author_team_id": author_team_id,
        "target_component_id": target_component_id,
        "pinned_token_set_id": pinned_token_set_id,
        "proposal_kind": proposal_kind,
    }
    return _merge(base, overrides)


def evidence_payload(
    evidence_kinds: List[str],
    evidence_url: str = "https://evidence.example.com/acceptance",
    **overrides: Any,
) -> Payload:
    """An acceptance-evidence body attaching one or more evidence kinds."""
    base: Payload = {"evidence_kinds": list(evidence_kinds), "evidence_url": evidence_url}
    return _merge(base, overrides)


def review_payload(
    stage: str = STAGE_DESIGN_CRITIQUE,
    verdict: str = VERDICT_APPROVE,
    notes: str = "Reviewed against the governance checklist.",
    **overrides: Any,
) -> Payload:
    """One review verdict at a named gate."""
    base: Payload = {"stage": stage, "verdict": verdict, "notes": notes}
    return _merge(base, overrides)


def accept_payload(
    release_id: str, expected_component_version: int, **overrides: Any
) -> Payload:
    """An acceptance body naming the draft release and the read component version."""
    base: Payload = {
        "release_id": release_id,
        "expected_component_version": expected_component_version,
    }
    return _merge(base, overrides)


# ─── Releases ─────────────────────────────────────────

def release_payload(semver_base: str = "1.0.0", **overrides: Any) -> Payload:
    """A release body; `channel` is omitted by default."""
    return _merge({"semver_base": semver_base}, overrides)


# ─── Deprecation plans ────────────────────────────────

def deprecation_plan_payload(
    announced_at: str,
    sunset_at: str,
    removal_at: str,
    **overrides: Any,
) -> Payload:
    """A deprecation plan body with the three strictly increasing instants."""
    base: Payload = {
        "announced_at": announced_at,
        "sunset_at": sunset_at,
        "removal_at": removal_at,
    }
    return _merge(base, overrides)


def migration_guide_payload(
    migration_guide_url: str = "https://docs.example.com/migrations/badge",
    publish: bool = True,
    **overrides: Any,
) -> Payload:
    """A migration-guide body; `publish` decides whether the plan announces."""
    base: Payload = {"migration_guide_url": migration_guide_url, "publish": publish}
    return _merge(base, overrides)


def rescind_payload(
    reason: str = "The replacement slipped a quarter.", **overrides: Any
) -> Payload:
    """A rescission body carrying the operator's reason."""
    return _merge({"reason": reason}, overrides)


# ─── Exception grants ─────────────────────────────────

def exception_grant_payload(
    requesting_team_id: str,
    substitute_for_component_id: str,
    expires_at: str,
    exception_kind: str = EXCEPTION_ONE_OFF_COMPONENT,
    platform_scope: str = PLATFORM_WEB,
    justification: str = "The system component cannot express this layout yet.",
    **overrides: Any,
) -> Payload:
    """An exception-grant request body."""
    base: Payload = {
        "requesting_team_id": requesting_team_id,
        "substitute_for_component_id": substitute_for_component_id,
        "exception_kind": exception_kind,
        "platform_scope": platform_scope,
        "justification": justification,
        "expires_at": expires_at,
    }
    return _merge(base, overrides)


def decision_payload(decision: str = DECISION_APPROVE, **overrides: Any) -> Payload:
    """A grant decision body; `decision_notes` is omitted by default."""
    return _merge({"decision": decision}, overrides)


def repay_payload(
    remediation_notes: str = "Replaced the one-off with the system component.",
    **overrides: Any,
) -> Payload:
    """A repayment body carrying the remediation record."""
    return _merge({"remediation_notes": remediation_notes}, overrides)
