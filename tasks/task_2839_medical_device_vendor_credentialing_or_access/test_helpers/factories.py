"""Request payload builders.

Each builder produces the request body of one endpoint with sensible domain
defaults, and every keyword argument overrides one field. Monetary amounts are
emitted as JSON integers (section 2.6 counts cents), and every timestamp is a
full ISO 8601 UTC instant rather than a bare calendar date, because the PRD
declares instants everywhere it declares time.
"""

from __future__ import annotations

import itertools
from typing import Any, Dict

from .constants import (
    COMPLEXITY_SIMPLE,
    CREDENTIAL_TYPE_INFLUENZA,
    LOGICAL_CLOCK_DEFAULT_UTC,
    REQUESTED_ROLE_TECHNICAL_SUPPORT,
    RESTRICTION_STANDARD,
    SEVERITY_MINOR,
    INCIDENT_TYPE_UNBADGED_ACCESS,
    shift_instant,
)
from .types import JsonDict

_counter = itertools.count(1)


def unique_suffix() -> int:
    """A process-unique integer, for natural keys that must not collide in one test."""
    return next(_counter)


def _clean(payload: Dict[str, Any]) -> JsonDict:
    """Drop keys whose value is the sentinel ``...`` so callers can omit fields."""
    return {key: value for key, value in payload.items() if value is not ...}


# ── Facilities (section 3.1) ──────────────────────────────────────────────────
def facility_payload(
    code: str,
    name: str = ...,
    spd_turnaround_hours: Any = ...,
    spd_bay_count: Any = ...,
    badge_lead_minutes: Any = ...,
    badge_grace_minutes: Any = ...,
    restricted_escort_required: Any = ...,
) -> JsonDict:
    """A facility creation body; every optional input defaults on the server."""
    return _clean(
        {
            "name": f"{code} Surgical Center" if name is ... else name,
            "code": code,
            "spd_turnaround_hours": spd_turnaround_hours,
            "spd_bay_count": spd_bay_count,
            "badge_lead_minutes": badge_lead_minutes,
            "badge_grace_minutes": badge_grace_minutes,
            "restricted_escort_required": restricted_escort_required,
        }
    )


# ── Vendors and representatives (section 3.1) ─────────────────────────────────
def vendor_payload(vendor_code: str, legal_name: str = ...) -> JsonDict:
    """A vendor creation body."""
    return _clean(
        {
            "legal_name": (
                f"{vendor_code} Medical Devices Incorporated"
                if legal_name is ...
                else legal_name
            ),
            "vendor_code": vendor_code,
        }
    )


def vendor_rep_payload(
    vendor_id: str,
    full_name: str = "Riley Vendor",
    email: Any = ...,
) -> JsonDict:
    """A representative registration body."""
    slug = full_name.split()[0].lower()
    return _clean(
        {
            "vendor_id": vendor_id,
            "full_name": full_name,
            "email": f"{slug}.{unique_suffix()}@vendor.example" if email is ... else email,
        }
    )


def revoke_access_payload(reason: str = "Policy violation on site") -> JsonDict:
    """A representative access revocation body."""
    return {"reason": reason}


# ── Credentials (section 3.2) ─────────────────────────────────────────────────
def credential_payload(
    vendor_rep_id: str,
    credential_type: str = CREDENTIAL_TYPE_INFLUENZA,
    issued_at_utc: Any = ...,
    expires_at_utc: Any = ...,
    document_reference: Any = ...,
) -> JsonDict:
    """A credential filing body, valid well past the default logical clock."""
    return _clean(
        {
            "vendor_rep_id": vendor_rep_id,
            "credential_type": credential_type,
            "issued_at_utc": (
                shift_instant(LOGICAL_CLOCK_DEFAULT_UTC, days=-30)
                if issued_at_utc is ...
                else issued_at_utc
            ),
            "expires_at_utc": (
                shift_instant(LOGICAL_CLOCK_DEFAULT_UTC, days=365)
                if expires_at_utc is ...
                else expires_at_utc
            ),
            "document_reference": (
                f"DOC-{credential_type}-{unique_suffix()}"
                if document_reference is ...
                else document_reference
            ),
        }
    )


def credential_decision_payload(
    decision: str = "VERIFY", rejection_reason: Any = ...
) -> JsonDict:
    """A credential verification or rejection body."""
    return _clean({"decision": decision, "rejection_reason": rejection_reason})


# ── Surgical cases (section 3.3) ──────────────────────────────────────────────
def surgical_case_payload(
    facility_id: str,
    case_number: str,
    scheduled_start_utc: str,
    scheduled_end_utc: str,
    procedure_name: Any = ...,
    restriction_level: Any = RESTRICTION_STANDARD,
    implant_required: Any = ...,
) -> JsonDict:
    """A surgical case creation body with an explicit scheduled window."""
    return _clean(
        {
            "facility_id": facility_id,
            "case_number": case_number,
            "procedure_name": (
                f"Procedure for {case_number}" if procedure_name is ... else procedure_name
            ),
            "scheduled_start_utc": scheduled_start_utc,
            "scheduled_end_utc": scheduled_end_utc,
            "restriction_level": restriction_level,
            "implant_required": implant_required,
        }
    )


def reschedule_payload(
    new_scheduled_start_utc: str, new_scheduled_end_utc: str
) -> JsonDict:
    """A case reschedule body."""
    return {
        "new_scheduled_start_utc": new_scheduled_start_utc,
        "new_scheduled_end_utc": new_scheduled_end_utc,
    }


def cancel_payload(cancellation_reason: str = "Surgeon unavailable") -> JsonDict:
    """A case cancellation body."""
    return {"cancellation_reason": cancellation_reason}


# ── Authorizations (section 3.4) ──────────────────────────────────────────────
def authorization_payload(
    surgical_case_id: str,
    vendor_rep_id: str,
    requested_role: str = REQUESTED_ROLE_TECHNICAL_SUPPORT,
) -> JsonDict:
    """A case representative authorization request body."""
    return {
        "surgical_case_id": surgical_case_id,
        "vendor_rep_id": vendor_rep_id,
        "requested_role": requested_role,
    }


def authorization_decision_payload(
    decision: str = "APPROVE", escort_user_id: Any = ...
) -> JsonDict:
    """An authorization approval or denial body."""
    return _clean({"decision": decision, "escort_user_id": escort_user_id})


def authorization_revoke_payload(revoked_reason: Any = ...) -> JsonDict:
    """An authorization revocation body; the reason defaults on the server."""
    return _clean({"revoked_reason": revoked_reason})


# ── Product introduction requests (section 3.6) ───────────────────────────────
def pir_payload(
    vendor_id: str,
    facility_id: str,
    product_catalog_number: str,
    unit_cost_cents: int,
    expected_vendor_version: int,
    product_name: Any = ...,
    manufacturer: Any = ...,
    is_implant: Any = ...,
    supersedes_request_id: Any = ...,
) -> JsonDict:
    """A product introduction request body; ``unit_cost_cents`` is a JSON integer."""
    return _clean(
        {
            "vendor_id": vendor_id,
            "facility_id": facility_id,
            "product_name": (
                f"Product {product_catalog_number}" if product_name is ... else product_name
            ),
            "product_catalog_number": product_catalog_number,
            "manufacturer": (
                "Northbridge Manufacturing" if manufacturer is ... else manufacturer
            ),
            "is_implant": is_implant,
            "unit_cost_cents": unit_cost_cents,
            "expected_vendor_version": expected_vendor_version,
            "supersedes_request_id": supersedes_request_id,
        }
    )


def clinical_review_payload(
    decision: str = "ENDORSE", review_note: Any = ...
) -> JsonDict:
    """A clinical review body."""
    return _clean({"decision": decision, "review_note": review_note})


def value_analysis_payload(
    decision: str = "APPROVE", decision_note: Any = ...
) -> JsonDict:
    """A value analysis committee decision body."""
    return _clean({"decision": decision, "decision_note": decision_note})


# ── Loaner sets (section 3.7) ─────────────────────────────────────────────────
def loaner_set_payload(
    surgical_case_id: str,
    approved_product_id: str,
    tray_count: int,
    expected_case_version: int,
    reprocessing_complexity: str = COMPLEXITY_SIMPLE,
) -> JsonDict:
    """A loaner set registration body; ``tray_count`` is a JSON integer."""
    return {
        "surgical_case_id": surgical_case_id,
        "approved_product_id": approved_product_id,
        "tray_count": tray_count,
        "reprocessing_complexity": reprocessing_complexity,
        "expected_case_version": expected_case_version,
    }


def receive_payload(delivered_at_utc: Any = ...) -> JsonDict:
    """A loaner set receipt body; omitting the instant defers to the logical clock."""
    return _clean({"delivered_at_utc": delivered_at_utc})


# ── Kiosk check-ins (section 3.5) ─────────────────────────────────────────────
def check_in_payload(case_rep_authorization_id: str) -> JsonDict:
    """A kiosk check-in body."""
    return {"case_rep_authorization_id": case_rep_authorization_id}


def attach_escort_payload(escort_user_id: str) -> JsonDict:
    """An escort attachment body."""
    return {"escort_user_id": escort_user_id}


# ── Incidents (section 3.8) ───────────────────────────────────────────────────
def incident_payload(
    surgical_case_id: str,
    vendor_rep_id: str,
    incident_type: str = INCIDENT_TYPE_UNBADGED_ACCESS,
    severity: str = SEVERITY_MINOR,
    narrative: Any = ...,
    approved_product_id: Any = ...,
) -> JsonDict:
    """A compliance incident report body."""
    return _clean(
        {
            "surgical_case_id": surgical_case_id,
            "vendor_rep_id": vendor_rep_id,
            "incident_type": incident_type,
            "severity": severity,
            "narrative": (
                f"Observed {incident_type} of {severity} severity"
                if narrative is ...
                else narrative
            ),
            "approved_product_id": approved_product_id,
        }
    )


def adjudicate_payload(
    outcome: str = "SUBSTANTIATED", adjudication_note: Any = ...
) -> JsonDict:
    """An incident adjudication body."""
    return _clean({"outcome": outcome, "adjudication_note": adjudication_note})


# ── Access appeals (section 3.9) ──────────────────────────────────────────────
def access_appeal_payload(
    vendor_rep_id: str, grounds: str = "The revocation rested on a mistaken identity"
) -> JsonDict:
    """An access appeal filing body."""
    return {"vendor_rep_id": vendor_rep_id, "grounds": grounds}


def appeal_decision_payload(
    decision: str = "UPHOLD", decision_rationale: Any = ...
) -> JsonDict:
    """An appeal decision body."""
    return _clean({"decision": decision, "decision_rationale": decision_rationale})


# ── Compliance sweeps (section 3.9) ───────────────────────────────────────────
def compliance_sweep_payload() -> JsonDict:
    """A compliance sweep trigger body; the sweep takes no inputs of its own."""
    return {}
