"""Payload factories - one per creatable resource, input fields only.

Computed and system-managed fields are never emitted: posting them would only
prove the server ignores them. Defaults are chosen to be valid against the
fresh-deployment clock of PRD section 2.4 (2026-09-01T00:00:00Z), so a factory
payload is submittable without touching the clock first.

Identifiers that must be unique per resource family (org_code, rule_code) get
a per-process monotonically increasing suffix; tests that need a specific code
pass it explicitly via an override.
"""

import itertools
from typing import Any, Dict, Optional

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


# --- Organizations (PRD section 3.5) ------------------------------------------

def create_organization_payload(**overrides: Any) -> Dict[str, Any]:
    n = _seq()
    payload: Dict[str, Any] = {
        "org_code": f"ORG-{n:05d}",
        "name": f"Test Organization {n}",
        "org_type": "BROKER_DEALER",
    }
    payload.update(overrides)
    return payload


def suspend_organization_payload(reason: str = "regulatory action", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


# --- Rule proposals and comment letters (PRD sections 3.1-3.3) -----------------

def create_rule_proposal_payload(**overrides: Any) -> Dict[str, Any]:
    n = _seq()
    payload: Dict[str, Any] = {
        "rule_code": f"G-{9000 + n}",
        "title": f"Test Rule {n}",
        "body": f"Rule text {n}",
        "category": "DEALER_CONDUCT",
    }
    payload.update(overrides)
    return payload


def open_comment_period_payload(
    comment_period_days: int = 21, expedited: Optional[bool] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"comment_period_days": comment_period_days}
    if expedited is not None:
        payload["expedited"] = expedited
    payload.update(overrides)
    return payload


def patch_rule_proposal_payload(expected_rule_proposal_version: int, **edits: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"expected_rule_proposal_version": expected_rule_proposal_version}
    payload.update(edits)
    return payload


def decide_proposal_payload(decision: str = "APPROVE", reason: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


def create_comment_letter_payload(**overrides: Any) -> Dict[str, Any]:
    n = _seq()
    payload: Dict[str, Any] = {
        "author_name": f"Commenter {n}",
        "body": f"Comment body {n}",
        "sentiment": "SUPPORT",
    }
    payload.update(overrides)
    return payload


def moderate_comment_letter_payload(action: str = "PUBLISH", reason: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


# --- Disclosure submissions (PRD section 3.4) ----------------------------------

def create_disclosure_submission_payload(issuer_org_id: str, **overrides: Any) -> Dict[str, Any]:
    n = _seq()
    payload: Dict[str, Any] = {
        "issuer_org_id": issuer_org_id,
        "submission_type": "VOLUNTARY",
        "document_uri": f"doc://filing-{n}",
        "cusip": "123456789",
    }
    payload.update(overrides)
    return payload


def create_event_notice_payload(
    issuer_org_id: str,
    event_category: str = "PAYMENT_DEFAULT",
    event_occurred_at: str = "2026-08-30T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """EVENT_NOTICE filing; the default event date precedes the fresh-deployment
    clock, so the notice is submittable without advancing time."""
    return create_disclosure_submission_payload(
        issuer_org_id,
        submission_type="EVENT_NOTICE",
        event_category=event_category,
        event_occurred_at=event_occurred_at,
        **overrides,
    )


def create_annual_financial_payload(
    issuer_org_id: str,
    period_start: str = "2025-01-01T00:00:00Z",
    period_end: str = "2025-12-31T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """ANNUAL_FINANCIAL filing over a closed coverage interval."""
    return create_disclosure_submission_payload(
        issuer_org_id,
        submission_type="ANNUAL_FINANCIAL",
        period_start=period_start,
        period_end=period_end,
        **overrides,
    )


def review_submission_payload(
    outcome: str = "PUBLISH", deficiency_reason: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    if deficiency_reason is not None:
        payload["deficiency_reason"] = deficiency_reason
    payload.update(overrides)
    return payload


# --- Professionals, exams, continuing education (PRD section 3.6) --------------

def create_professional_payload(employer_org_id: str, **overrides: Any) -> Dict[str, Any]:
    n = _seq()
    payload: Dict[str, Any] = {
        "full_name": f"Professional {n}",
        "employer_org_id": employer_org_id,
        "professional_class": "MUNICIPAL_DEALER_REP",
    }
    payload.update(overrides)
    return payload


def set_standing_payload(standing: str = "SUSPENDED", reason: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"standing": standing}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


def ce_credits_payload(credits_total: float = 12, ethics_credits: float = 2, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"credits_total": credits_total, "ethics_credits": ethics_credits}
    payload.update(overrides)
    return payload


def create_exam_attempt_payload(professional_id: str, series_code: str = "MSRB_52", score: int = 80, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "professional_id": professional_id,
        "series_code": series_code,
        "score": score,
    }
    payload.update(overrides)
    return payload


# --- Trade reports (PRD section 3.5) -------------------------------------------

def create_trade_report_payload(
    dealer_org_id: str,
    executed_at: str = "2026-09-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """Trade report. The default execution instant equals the fresh-deployment
    clock, so the report is timely and submittable without advancing time."""
    payload: Dict[str, Any] = {
        "dealer_org_id": dealer_org_id,
        "cusip": "123456789",
        "trade_type": "INTER_DEALER",
        "par_amount": 100_000,
        "price": 100.0,
        "executed_at": executed_at,
    }
    payload.update(overrides)
    return payload


# --- Data subscriptions (PRD section 3.7) ---------------------------------------

def create_data_subscription_payload(licensee_org_id: str, **overrides: Any) -> Dict[str, Any]:
    n = _seq()
    payload: Dict[str, Any] = {
        "product_code": "TRADE_REALTIME",
        "licensee_org_id": licensee_org_id,
        "subscriber_principal": f"sub-{n:05d}",
        "license_scope": "INTERNAL",
        "seats": 3,
    }
    payload.update(overrides)
    return payload


def transition_subscription_payload(to_state: str = "ACTIVE", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_state": to_state}
    payload.update(overrides)
    return payload


# --- Enforcement referrals (PRD section 3.8) ------------------------------------

def create_enforcement_referral_payload(
    rule_code: str,
    subject_org_id: Optional[str] = None,
    subject_professional_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    n = _seq()
    payload: Dict[str, Any] = {
        "rule_code": rule_code,
        "violation_summary": f"Suspected violation {n}",
    }
    if subject_org_id is not None:
        payload["subject_org_id"] = subject_org_id
    if subject_professional_id is not None:
        payload["subject_professional_id"] = subject_professional_id
    payload.update(overrides)
    return payload


def advance_referral_payload(
    to_state: str = "REFERRED",
    guidance_text: Optional[str] = None,
    closure_notes: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_state": to_state}
    if guidance_text is not None:
        payload["guidance_text"] = guidance_text
    if closure_notes is not None:
        payload["closure_notes"] = closure_notes
    payload.update(overrides)
    return payload


# --- Solicitation records (PRD section 3.8) -------------------------------------

def create_solicitation_record_payload(advisor_org_id: str, **overrides: Any) -> Dict[str, Any]:
    n = _seq()
    payload: Dict[str, Any] = {
        "advisor_org_id": advisor_org_id,
        "municipal_entity_name": f"City of Example {n}",
        "compensation_type": "FIXED",
        "compensation_cents": 100_000,
        "disclosure_provided": True,
    }
    payload.update(overrides)
    return payload


# --- Logical clock (PRD section 2.4) ---------------------------------------------

def set_clock_payload(to_iso8601: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
