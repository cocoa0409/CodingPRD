"""Request-payload builders.

Every builder returns a plain dict of the fields the PRD says a caller supplies, and
accepts ``**overrides`` so a test can replace a value, add an unexpected field, or
force an explicit null. Numeric fields are always JSON numbers, never strings.
Instants are always full ISO-8601 UTC instants, never date-only strings.
"""
import itertools
from typing import Any, Dict, List, Optional

from .constants import (
    CANONICAL_MONTHLY_CALL_POOL,
    CANONICAL_PRODUCT_NAME,
    CANONICAL_REQUESTED_MONTHLY_CALLS,
    CANONICAL_SAMPLE_APP_SLUG,
    CANONICAL_SCOPE,
    CANONICAL_SEMVER,
    CANONICAL_SUSTAINED_RPM_POOL,
    CURRENT_DOCS_REVISION,
    DEFAULT_REQUIRED_TOS_VERSION,
    JUSTIFICATION_PARTNER,
    JUSTIFICATION_STANDARD,
)

_counter = itertools.count(1)


def _next() -> int:
    return next(_counter)


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = {k: v for k, v in base.items() if v is not None}
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------------ developers
def developer_payload(
    org_name: Optional[str] = None,
    contact_email: Optional[str] = None,
    region_code: str = "US",
    **overrides: Any,
) -> Dict[str, Any]:
    n = _next()
    return _merge(
        {
            "org_name": org_name if org_name is not None else f"Northwind Integrations {n}",
            "contact_email": (
                contact_email if contact_email is not None else f"dev{n}@northwind.example"
            ),
            "region_code": region_code,
        },
        overrides,
    )


def onboarding_acknowledgement_payload(
    docs_version: int = CURRENT_DOCS_REVISION,
    tos_version: int = DEFAULT_REQUIRED_TOS_VERSION,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"docs_version": docs_version, "tos_version": tos_version}, overrides)


def ecosystem_participation_payload(
    certification_level: Optional[str] = None,
    certification_expires_at: Optional[str] = None,
    hackathon_awards_delta: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "certification_level": certification_level,
            "certification_expires_at": certification_expires_at,
            "hackathon_awards_delta": hackathon_awards_delta,
        },
        overrides,
    )


def directory_submission_payload(
    directory_summary: str = "Catalogue synchronisation for regional storefronts.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"directory_summary": directory_summary}, overrides)


def directory_review_payload(
    decision: str = "APPROVE", review_note: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    return _merge({"decision": decision, "review_note": review_note}, overrides)


def revoke_access_payload(
    revocation_reason: str = "Repeated terms-of-service violations upheld on appeal.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"revocation_reason": revocation_reason}, overrides)


# ---------------------------------------------------------------------- api products
def scope_entry(scope: str = CANONICAL_SCOPE, sensitivity: str = "PUBLIC") -> Dict[str, Any]:
    return {"scope": scope, "sensitivity": sensitivity}


def api_product_payload(
    name: Optional[str] = None,
    data_sensitivity: str = "PUBLIC",
    scope_catalog: Optional[List[Dict[str, Any]]] = None,
    sample_app_slugs: Optional[List[str]] = None,
    sustained_rpm_pool: int = CANONICAL_SUSTAINED_RPM_POOL,
    monthly_call_pool: int = CANONICAL_MONTHLY_CALL_POOL,
    required_tos_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "name": name if name is not None else f"{CANONICAL_PRODUCT_NAME} {_next()}",
            "data_sensitivity": data_sensitivity,
            "scope_catalog": scope_catalog if scope_catalog is not None else [scope_entry()],
            "sample_app_slugs": (
                sample_app_slugs if sample_app_slugs is not None else [CANONICAL_SAMPLE_APP_SLUG]
            ),
            "sustained_rpm_pool": sustained_rpm_pool,
            "monthly_call_pool": monthly_call_pool,
            "required_tos_version": required_tos_version,
        },
        overrides,
    )


def program_adjustment_payload(
    sustained_rpm_pool: Optional[int] = None,
    monthly_call_pool: Optional[int] = None,
    required_tos_version: Optional[int] = None,
    adjustment_reason: str = "Quarterly capacity review.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "sustained_rpm_pool": sustained_rpm_pool,
            "monthly_call_pool": monthly_call_pool,
            "required_tos_version": required_tos_version,
            "adjustment_reason": adjustment_reason,
        },
        overrides,
    )


def api_version_payload(
    semver: str = CANONICAL_SEMVER, breaking_change: Optional[bool] = None, **overrides: Any
) -> Dict[str, Any]:
    return _merge({"semver": semver, "breaking_change": breaking_change}, overrides)


def migration_guide_payload(
    migration_guide_url: str = "https://developers.example/catalog/migrate/1-to-2",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"migration_guide_url": migration_guide_url}, overrides)


def announce_deprecation_payload(notice_days: int, **overrides: Any) -> Dict[str, Any]:
    return _merge({"notice_days": notice_days}, overrides)


# ----------------------------------------------------------------- access applications
def access_application_payload(
    developer_id: str,
    target_api_version_id: str,
    requested_tier: str = "PARTNER",
    requested_scopes: Optional[List[str]] = None,
    requested_monthly_calls: int = CANONICAL_REQUESTED_MONTHLY_CALLS,
    justification_text: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    if justification_text is None:
        justification_text = (
            JUSTIFICATION_PARTNER if requested_tier in ("PARTNER", "PRIVILEGED")
            else JUSTIFICATION_STANDARD
        )
    return _merge(
        {
            "developer_id": developer_id,
            "target_api_version_id": target_api_version_id,
            "requested_tier": requested_tier,
            "requested_scopes": (
                requested_scopes if requested_scopes is not None else [CANONICAL_SCOPE]
            ),
            "requested_monthly_calls": requested_monthly_calls,
            "justification_text": justification_text,
        },
        overrides,
    )


def submit_application_payload(
    justification_text: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    return _merge({"justification_text": justification_text}, overrides)


def request_changes_payload(
    changes_requested_note: str = "Please quantify the expected nightly synchronisation volume.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"changes_requested_note": changes_requested_note}, overrides)


def decide_application_payload(
    decision: str = "APPROVE",
    approved_tier: Optional[str] = None,
    granted_scopes: Optional[List[str]] = None,
    decision_reason: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "decision": decision,
            "approved_tier": approved_tier,
            "granted_scopes": granted_scopes,
            "decision_reason": decision_reason,
        },
        overrides,
    )


# ----------------------------------------------------------------- quota assignments
def quota_assignment_payload(
    access_application_id: str, expected_api_product_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "access_application_id": access_application_id,
            "expected_api_product_version": expected_api_product_version,
        },
        overrides,
    )


def suspend_payload(
    suspension_reason: str = "Administrative hold pending commercial review.", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"suspension_reason": suspension_reason}, overrides)


def usage_window_payload(
    window_start: str, total_calls: int, burst_calls: int = 0, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "window_start": window_start,
            "total_calls": total_calls,
            "burst_calls": burst_calls,
        },
        overrides,
    )


def upgrade_request_payload(
    requested_sustained_rpm: int,
    expected_quota_assignment_version: int,
    justification_text: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "requested_sustained_rpm": requested_sustained_rpm,
            "justification_text": (
                justification_text if justification_text is not None else JUSTIFICATION_STANDARD
            ),
            "expected_quota_assignment_version": expected_quota_assignment_version,
        },
        overrides,
    )


# -------------------------------------------------------------------- sandbox leases
def sandbox_lease_payload(
    developer_id: str,
    api_product_id: str,
    starts_at: str,
    lease_days: int = 7,
    sample_app_slug: str = CANONICAL_SAMPLE_APP_SLUG,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "developer_id": developer_id,
            "api_product_id": api_product_id,
            "starts_at": starts_at,
            "lease_days": lease_days,
            "sample_app_slug": sample_app_slug,
        },
        overrides,
    )


# ------------------------------------------------------------------- violation cases
def violation_case_payload(
    developer_id: str,
    category: str = "SCOPE_OVERREACH",
    severity: str = "MEDIUM",
    summary: str = "Requests observed against a scope that was never granted.",
    quota_assignment_id: Optional[str] = None,
    evidence_window_ids: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "developer_id": developer_id,
            "category": category,
            "severity": severity,
            "summary": summary,
            "quota_assignment_id": quota_assignment_id,
            "evidence_window_ids": evidence_window_ids,
        },
        overrides,
    )


def adjudicate_payload(
    outcome: str = "UPHELD",
    decision_note: str = "Access logs confirm the finding.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"outcome": outcome, "decision_note": decision_note}, overrides)


def appeal_payload(
    appeal_reason: str = "The calls originated from a decommissioned staging client.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"appeal_reason": appeal_reason}, overrides)


# --------------------------------------------------------------------- support cases
def support_case_payload(
    api_product_id: str,
    kind: str = "PARTNER_TICKET",
    severity: str = "S2",
    title: str = "Catalogue reads returning intermittent errors",
    started_at: str = "2026-08-02T00:00:00Z",
    developer_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "kind": kind,
            "api_product_id": api_product_id,
            "severity": severity,
            "title": title,
            "started_at": started_at,
            "developer_id": developer_id,
        },
        overrides,
    )


def communication_payload(
    sent_at: str, body: str = "Investigating elevated error rates on catalogue reads.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"sent_at": sent_at, "body": body}, overrides)


def escalate_payload(
    escalation_note: Optional[str] = "Escalating to the next partner tier.", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"escalation_note": escalation_note}, overrides)


def resolve_support_payload(
    resolution_note: str = "Edge tier rolled back; catalogue reads healthy.", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"resolution_note": resolution_note}, overrides)


# -------------------------------------------------------------------- feedback items
def feedback_item_payload(
    developer_id: str,
    api_product_id: str,
    category: str = "DEFECT",
    body: str = "Cursor pagination on the catalogue read endpoint skips the final page.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "developer_id": developer_id,
            "api_product_id": api_product_id,
            "category": category,
            "body": body,
        },
        overrides,
    )


def triage_payload(
    decision_note: Optional[str] = "Reproduced against the current release.", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"decision_note": decision_note}, overrides)


def roadmap_decision_payload(
    decision: str = "ACCEPT",
    decision_note: Optional[str] = "Scheduled for the next platform iteration.",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"decision": decision, "decision_note": decision_note}, overrides)
