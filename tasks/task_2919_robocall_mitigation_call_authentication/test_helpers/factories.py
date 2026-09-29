"""Request-body factories.

Every builder returns a fresh dictionary with valid defaults that callers
override by keyword.  Timestamps are always full ISO-8601 instants, never
date-only strings, and monetary amounts are always JSON integers of cents.
"""

import itertools
from typing import Any, List, Optional

from .constants import (
    CLOCK_DEFAULT,
    MINIMUM_COMPLIANT_PRACTICES,
    NUMBER_1,
    NUMBER_CALLED,
)
from .types import Payload

_counter = itertools.count(1)


def unique_suffix() -> int:
    """A monotonically increasing suffix for unique names and tokens."""
    return next(_counter)


# --- Provider ---------------------------------------------------------------


def provider_payload(
    legal_name: Optional[str] = None,
    provider_type: str = "FACILITIES_BASED",
    **overrides: Any,
) -> Payload:
    payload = {
        "legal_name": legal_name or f"Acme Voice LLC {unique_suffix()}",
        "provider_type": provider_type,
    }
    payload.update(overrides)
    return payload


# --- Certificate ------------------------------------------------------------


def certificate_payload(
    provider_id: str,
    spc_token: Optional[str] = None,
    public_key_fingerprint: Optional[str] = None,
    not_before: str = "2026-07-01T00:00:00Z",
    not_after: str = "2027-07-01T00:00:00Z",
    **overrides: Any,
) -> Payload:
    suffix = unique_suffix()
    payload = {
        "provider_id": provider_id,
        "spc_token": spc_token or f"SPC-{suffix:04d}",
        "public_key_fingerprint": public_key_fingerprint or f"fp-{suffix:04d}",
        "not_before": not_before,
        "not_after": not_after,
    }
    payload.update(overrides)
    return payload


def certificate_renewal_payload(
    spc_token: Optional[str] = None,
    public_key_fingerprint: Optional[str] = None,
    not_before: str = "2026-08-10T00:00:00Z",
    not_after: str = "2027-08-10T00:00:00Z",
    **overrides: Any,
) -> Payload:
    suffix = unique_suffix()
    payload = {
        "spc_token": spc_token or f"SPC-{2000 + suffix}",
        "public_key_fingerprint": public_key_fingerprint or f"fp-{2000 + suffix}",
        "not_before": not_before,
        "not_after": not_after,
    }
    payload.update(overrides)
    return payload


def revocation_payload(revocation_reason: str = "KEY_COMPROMISE", **overrides: Any) -> Payload:
    payload = {"revocation_reason": revocation_reason}
    payload.update(overrides)
    return payload


# --- Mitigation plan --------------------------------------------------------


def mitigation_plan_payload(
    provider_id: str,
    expected_provider_version: int,
    prevention_practices: Optional[List[str]] = None,
    **overrides: Any,
) -> Payload:
    payload = {
        "provider_id": provider_id,
        "prevention_practices": list(
            prevention_practices
            if prevention_practices is not None
            else MINIMUM_COMPLIANT_PRACTICES
        ),
        "expected_provider_version": expected_provider_version,
    }
    payload.update(overrides)
    return payload


def plan_decision_payload(
    decision: str = "ACCEPT",
    deficiency_reasons: Optional[List[str]] = None,
    **overrides: Any,
) -> Payload:
    payload: Payload = {"decision": decision}
    if deficiency_reasons is not None:
        payload["deficiency_reasons"] = list(deficiency_reasons)
    payload.update(overrides)
    return payload


# --- Customer ---------------------------------------------------------------


def customer_payload(
    provider_id: str,
    legal_name: Optional[str] = None,
    contact_email: Optional[str] = None,
    kyc_evidence_level: str = "BUSINESS_REGISTRY_VERIFIED",
    **overrides: Any,
) -> Payload:
    suffix = unique_suffix()
    payload = {
        "provider_id": provider_id,
        "legal_name": legal_name or f"Origination Co {suffix}",
        "contact_email": contact_email or f"ops{suffix}@origination.example",
        "kyc_evidence_level": kyc_evidence_level,
    }
    payload.update(overrides)
    return payload


def kyc_decision_payload(decision: str = "VERIFY", **overrides: Any) -> Payload:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def origination_action_payload(
    action: str, suspension_cause: Optional[str] = None, **overrides: Any
) -> Payload:
    payload: Payload = {"action": action}
    if suspension_cause is not None:
        payload["suspension_cause"] = suspension_cause
    payload.update(overrides)
    return payload


# --- Number assignment ------------------------------------------------------


def number_assignment_payload(
    provider_id: str,
    customer_id: str,
    telephone_number: str = NUMBER_1,
    ownership_evidence: str = "DIRECT_ALLOCATION",
    effective_from: str = CLOCK_DEFAULT,
    effective_to: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "provider_id": provider_id,
        "customer_id": customer_id,
        "telephone_number": telephone_number,
        "ownership_evidence": ownership_evidence,
        "effective_from": effective_from,
    }
    if effective_to is not None:
        payload["effective_to"] = effective_to
    payload.update(overrides)
    return payload


# --- Call attestation -------------------------------------------------------


def call_attestation_payload(
    provider_id: str,
    customer_id: str,
    calling_number: str = NUMBER_1,
    called_number: str = NUMBER_CALLED,
    origination_time: str = CLOCK_DEFAULT,
    **overrides: Any,
) -> Payload:
    payload = {
        "provider_id": provider_id,
        "customer_id": customer_id,
        "calling_number": calling_number,
        "called_number": called_number,
        "origination_time": origination_time,
    }
    payload.update(overrides)
    return payload


# --- Traffic observation ----------------------------------------------------


def traffic_observation_payload(
    provider_id: str,
    customer_id: str,
    window_start: str = "2026-07-01T00:00:00Z",
    window_end: str = "2026-07-02T00:00:00Z",
    total_call_count: int = 1000,
    short_duration_call_count: int = 500,
    unanswered_call_count: int = 500,
    complaint_count: int = 0,
    **overrides: Any,
) -> Payload:
    payload = {
        "provider_id": provider_id,
        "customer_id": customer_id,
        "window_start": window_start,
        "window_end": window_end,
        "total_call_count": total_call_count,
        "short_duration_call_count": short_duration_call_count,
        "unanswered_call_count": unanswered_call_count,
        "complaint_count": complaint_count,
    }
    payload.update(overrides)
    return payload


# --- Traceback request ------------------------------------------------------


def traceback_request_payload(
    provider_id: str,
    calling_number: str = NUMBER_1,
    called_number: str = NUMBER_CALLED,
    origination_time: str = CLOCK_DEFAULT,
    **overrides: Any,
) -> Payload:
    payload = {
        "provider_id": provider_id,
        "calling_number": calling_number,
        "called_number": called_number,
        "origination_time": origination_time,
    }
    payload.update(overrides)
    return payload


def traceback_response_payload(
    identified_customer_id: str, produced_attestation_id: str, **overrides: Any
) -> Payload:
    payload = {
        "identified_customer_id": identified_customer_id,
        "produced_attestation_id": produced_attestation_id,
    }
    payload.update(overrides)
    return payload


# --- Illegal traffic notice -------------------------------------------------


def illegal_traffic_notice_payload(
    provider_id: str,
    calling_number: str = NUMBER_1,
    description: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    payload = {
        "provider_id": provider_id,
        "calling_number": calling_number,
        "description": description or "High-volume prerecorded voice campaign",
    }
    payload.update(overrides)
    return payload


def notice_investigation_payload(customer_id: str, **overrides: Any) -> Payload:
    payload = {"customer_id": customer_id}
    payload.update(overrides)
    return payload


def notice_mitigation_payload(mitigation_action: str, **overrides: Any) -> Payload:
    payload = {"mitigation_action": mitigation_action}
    payload.update(overrides)
    return payload


# --- Blocking event and dispute ---------------------------------------------


def blocking_event_payload(
    provider_id: str,
    customer_id: str,
    calling_number: str = NUMBER_1,
    analytics_score: float = 0.96,
    reason: str = "ANALYTICS_SCORE",
    **overrides: Any,
) -> Payload:
    payload = {
        "provider_id": provider_id,
        "customer_id": customer_id,
        "calling_number": calling_number,
        "analytics_score": analytics_score,
        "reason": reason,
    }
    payload.update(overrides)
    return payload


def blocking_dispute_payload(
    blocking_event_id: str, claim_note: Optional[str] = None, **overrides: Any
) -> Payload:
    payload = {
        "blocking_event_id": blocking_event_id,
        "claim_note": claim_note or "Appointment reminders for consenting patients",
    }
    payload.update(overrides)
    return payload


def dispute_resolution_payload(
    outcome: str, resolution_note: Optional[str] = None, **overrides: Any
) -> Payload:
    payload = {
        "outcome": outcome,
        "resolution_note": resolution_note or "Analytics score independently confirmed",
    }
    payload.update(overrides)
    return payload


# --- Enforcement action -----------------------------------------------------


def enforcement_action_payload(
    provider_id: str,
    basis: str = "LATE_TRACEBACK",
    violation_count: int = 3,
    violation_days: int = 10,
    assessment_basis: str = "PER_VIOLATION",
    **overrides: Any,
) -> Payload:
    payload = {
        "provider_id": provider_id,
        "basis": basis,
        "violation_count": violation_count,
        "violation_days": violation_days,
        "assessment_basis": assessment_basis,
    }
    payload.update(overrides)
    return payload


def adjudication_payload(outcome: str, **overrides: Any) -> Payload:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def payment_payload(amount_cents: int, **overrides: Any) -> Payload:
    # Monetary amounts travel as JSON integers of cents, never as strings.
    payload = {"amount_cents": int(amount_cents)}
    payload.update(overrides)
    return payload


# --- Effectiveness report ---------------------------------------------------


def effectiveness_report_payload(
    provider_id: str,
    expected_provider_version: int,
    period_start: str = "2026-08-01T00:00:00Z",
    period_end: str = "2026-09-01T00:00:00Z",
    variant: str = "PROVISIONAL",
    **overrides: Any,
) -> Payload:
    payload = {
        "provider_id": provider_id,
        "period_start": period_start,
        "period_end": period_end,
        "variant": variant,
        "expected_provider_version": expected_provider_version,
    }
    payload.update(overrides)
    return payload
