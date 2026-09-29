"""Request payload builders.

Money is always an integer number of cents and never a string (PRD §2.6).
Instants are full ISO 8601 UTC instants with three fractional digits (PRD §2.5),
never date-only strings; the date-only fields are exactly `issued_on`,
`expires_on`, `current_period_start_on`, `granted_on`, `completed_on` and
`as_of`, which carry `YYYY-MM-DD`.
"""

from .constants import (
    CANON_BASE_PRICE_CENTS,
    CANON_CONSENT_VERSION,
    CANON_DURATION_MINUTES,
    CANON_LICENSE_NUMBER,
    CANON_PRACTICE_STATE,
    CANON_RETAIL_AMOUNT_CENTS,
    CANON_RETAIL_LINE,
    CANON_ROOM_HOURLY_COST_CENTS,
    CANON_SKILL_CODE,
    CANON_THERAPIST_HOURLY_COST_CENTS,
    CANON_TURNOVER_MINUTES,
)


def _merge(payload: dict, overrides: dict) -> dict:
    """Apply overrides; a None value removes the key so optional-field omission
    can be exercised."""
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not None}


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def clock_payload(current_utc: str) -> dict:
    return {"current_utc": current_utc}


# ---------------------------------------------------------------------------
# Menu and inventory
# ---------------------------------------------------------------------------

def treatment_type_payload(code="HYDRO90", **overrides) -> dict:
    return _merge({
        "code": code,
        "name": "Marine Hydrotherapy 90",
        "duration_minutes": CANON_DURATION_MINUTES,
        "room_class_required": "HYDRO",
        "required_skill_code": CANON_SKILL_CODE,
        "required_scope_level": "ADVANCED",
        "base_price_cents": CANON_BASE_PRICE_CENTS,
        "contraindication_codes": ["ACUTE_HYPERTENSION"],
        "retail_product_line": CANON_RETAIL_LINE,
        "required_consent_version": CANON_CONSENT_VERSION,
        "high_demand": True,
    }, overrides)


def treatment_room_payload(code="HYDRO-1", **overrides) -> dict:
    return _merge({
        "code": code,
        "room_class": "HYDRO",
        "capacity_guests": 1,
        "turnover_buffer_minutes": CANON_TURNOVER_MINUTES,
        "hourly_fixed_cost_cents": CANON_ROOM_HOURLY_COST_CENTS,
    }, overrides)


def room_status_payload(status: str) -> dict:
    return {"status": status}


# ---------------------------------------------------------------------------
# Roster and credentials
# ---------------------------------------------------------------------------

def therapist_payload(full_name="Leilani Akana", **overrides) -> dict:
    return _merge({
        "full_name": full_name,
        "employment_type": "EMPLOYEE",
        "commission_tier": "SENIOR",
        "base_hourly_cost_cents": CANON_THERAPIST_HOURLY_COST_CENTS,
        "practice_state_code": CANON_PRACTICE_STATE,
    }, overrides)


def suspend_payload(**overrides) -> dict:
    return _merge({}, overrides)


def license_payload(license_number=CANON_LICENSE_NUMBER, **overrides) -> dict:
    return _merge({
        "license_number": license_number,
        "license_type": "LMT",
        "state_code": CANON_PRACTICE_STATE,
        "issued_on": "2024-01-01",
        "expires_on": "2026-12-31",
        "current_period_start_on": "2024-01-01",
        "ce_hours_required": 0,
    }, overrides)


def review_payload(decision: str, review_note=None) -> dict:
    """PRD §3.3: "submits a `decision` of either `VERIFIED` or `REJECTED`
    together with an optional `review_note`"."""
    payload = {"decision": decision}
    if review_note is not None:
        payload["review_note"] = review_note
    return payload


def resubmit_payload(**overrides) -> dict:
    return _merge({}, overrides)


def ce_record_payload(course_code="ETH-101", category="ETHICS", ce_hours=2.0,
                      completed_on="2025-03-01") -> dict:
    return {
        "course_code": course_code,
        "category": category,
        "ce_hours": ce_hours,
        "completed_on": completed_on,
    }


def certification_payload(skill_code=CANON_SKILL_CODE, scope_level="ADVANCED",
                          granted_on="2024-01-01", expires_on="2027-12-31") -> dict:
    return {
        "skill_code": skill_code,
        "scope_level": scope_level,
        "granted_on": granted_on,
        "expires_on": expires_on,
    }


def revoke_payload(reason_note=None) -> dict:
    return {} if reason_note is None else {"reason_note": reason_note}


def shift_block_payload(block_type="AVAILABLE",
                        start_at="2026-08-10T08:00:00.000Z",
                        end_at="2026-08-10T22:00:00.000Z", note=None) -> dict:
    payload = {"block_type": block_type, "start_at": start_at, "end_at": end_at}
    if note is not None:
        payload["note"] = note
    return payload


# ---------------------------------------------------------------------------
# Guest and intake
# ---------------------------------------------------------------------------

def guest_payload(full_name="Nia Kalani", resort_room_number="1204", **overrides) -> dict:
    return _merge({
        "full_name": full_name,
        "resort_room_number": resort_room_number,
        "loyalty_tier": "PLATINUM",
        "folio_limit_cents": 500000,
    }, overrides)


def intake_form_payload(expected_guest_version: int, condition_codes=None,
                        medications=None) -> dict:
    payload = {"expected_guest_version": expected_guest_version}
    if condition_codes is not None:
        payload["condition_codes"] = condition_codes
    if medications is not None:
        payload["medications"] = medications
    return payload


def consent_payload(consent_version=CANON_CONSENT_VERSION) -> dict:
    return {"consent_version": consent_version}


def override_payload(override_reason="director clinical review") -> dict:
    return {"override_reason": override_reason}


def amend_payload(condition_codes=None, medications=None) -> dict:
    payload = {}
    if condition_codes is not None:
        payload["condition_codes"] = condition_codes
    if medications is not None:
        payload["medications"] = medications
    return payload


# ---------------------------------------------------------------------------
# Appointments and downstream
# ---------------------------------------------------------------------------

def appointment_payload(guest_id, treatment_type_id, room_id, start_at,
                        therapist_id=None) -> dict:
    payload = {
        "guest_id": guest_id,
        "treatment_type_id": treatment_type_id,
        "room_id": room_id,
        "start_at": start_at,
    }
    if therapist_id is not None:
        payload["therapist_id"] = therapist_id
    return payload


def complete_payload(actual_duration_minutes: int, gratuity_cents=None) -> dict:
    payload = {"actual_duration_minutes": actual_duration_minutes}
    if gratuity_cents is not None:
        payload["gratuity_cents"] = gratuity_cents
    return payload


def cancel_payload(cancel_reason=None) -> dict:
    return {} if cancel_reason is None else {"cancel_reason": cancel_reason}


def retail_attachment_payload(product_sku="MARINE-SERUM-30",
                              product_line=CANON_RETAIL_LINE,
                              amount_cents=CANON_RETAIL_AMOUNT_CENTS) -> dict:
    return {
        "product_sku": product_sku,
        "product_line": product_line,
        "amount_cents": amount_cents,
    }


def resolve_payload(outcome: str) -> dict:
    return {"outcome": outcome}


def settlement_payload(expected_appointment_version: int) -> dict:
    """PRD §3.9: "the payload carries `expected_appointment_version` and nothing
    else"."""
    return {"expected_appointment_version": expected_appointment_version}


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def report_window(from_at: str, to_at: str, **extra) -> dict:
    params = {"from_at": from_at, "to_at": to_at}
    params.update({k: v for k, v in extra.items() if v is not None})
    return params
