"""Payload factories — one per write endpoint, `source: input` fields only.

Money is always sent as JSON numbers (integer cents, or decimals for the rate
and mileage fields the PRD declares as decimals) — never as strings.
"""

from typing import Any, Dict

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def create_language_payload(**overrides) -> Dict[str, Any]:
    """POST /languages — code, name, tier_class, oral_exam_available,
    telephonic_vendor_available?"""
    payload = {
        "code": TEST_DEFAULTS["LANGUAGE_CODE"],
        "name": TEST_DEFAULTS["LANGUAGE_NAME"],
        "tier_class": "DESIGNATED",
        "oral_exam_available": True,
        "telephonic_vendor_available": False,
    }
    payload.update(overrides)
    return payload


def create_rare_language_payload(**overrides) -> Dict[str, Any]:
    """POST /languages for a RARE language with no oral instrument."""
    payload = {
        "code": TEST_DEFAULTS["RARE_LANGUAGE_CODE"],
        "name": TEST_DEFAULTS["RARE_LANGUAGE_NAME"],
        "tier_class": "RARE",
        "oral_exam_available": False,
        "telephonic_vendor_available": True,
    }
    payload.update(overrides)
    return payload


def create_courthouse_payload(**overrides) -> Dict[str, Any]:
    """POST /courthouses — the canonical CERTIFIED_VRI main courthouse."""
    payload = {
        "name": TEST_DEFAULTS["COURTHOUSE_NAME"],
        "county_code": TEST_DEFAULTS["COURTHOUSE_COUNTY"],
        "courtroom_count": 12,
        "remote_equipment_tier": "CERTIFIED_VRI",
        "vri_concurrent_capacity": 1,
        "pay_budget_cents": TEST_DEFAULTS["PAY_BUDGET_CENTS"],
        "status": "OPEN",
    }
    payload.update(overrides)
    return payload


def create_north_courthouse_payload(**overrides) -> Dict[str, Any]:
    """POST /courthouses — a second courthouse in another county with no VRI kit."""
    payload = {
        "name": TEST_DEFAULTS["NORTH_COURTHOUSE_NAME"],
        "county_code": TEST_DEFAULTS["NORTH_COURTHOUSE_COUNTY"],
        "courtroom_count": 3,
        "remote_equipment_tier": "NONE",
        "vri_concurrent_capacity": 0,
        "pay_budget_cents": TEST_DEFAULTS["NORTH_PAY_BUDGET_CENTS"],
        "status": "OPEN",
    }
    payload.update(overrides)
    return payload


def patch_courthouse_payload(**overrides) -> Dict[str, Any]:
    """PATCH /courthouses/{id} — every field optional; pass only what changes."""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def create_rate_schedule_payload(**overrides) -> Dict[str, Any]:
    """POST /rate-schedules — the canonical open-ended schedule from 2026-01-01."""
    payload = {
        "effective_from": TEST_DEFAULTS["RATE_EFFECTIVE_FROM"],
        "master_hourly_cents": TEST_DEFAULTS["MASTER_HOURLY_CENTS"],
        "certified_hourly_cents": TEST_DEFAULTS["CERTIFIED_HOURLY_CENTS"],
        "registered_hourly_cents": TEST_DEFAULTS["REGISTERED_HOURLY_CENTS"],
        "provisional_hourly_cents": TEST_DEFAULTS["PROVISIONAL_HOURLY_CENTS"],
        "minimum_call_hours": TEST_DEFAULTS["MINIMUM_CALL_HOURS"],
        "travel_mileage_rate_cents": TEST_DEFAULTS["TRAVEL_MILEAGE_RATE_CENTS"],
        "travel_free_radius_miles": TEST_DEFAULTS["TRAVEL_FREE_RADIUS_MILES"],
        "remote_rate_multiplier": TEST_DEFAULTS["REMOTE_RATE_MULTIPLIER"],
        "late_cancellation_hours": TEST_DEFAULTS["LATE_CANCELLATION_HOURS"],
        "late_cancellation_pay_hours": TEST_DEFAULTS["LATE_CANCELLATION_PAY_HOURS"],
        "rare_premium_low_pct": TEST_DEFAULTS["RARE_PREMIUM_LOW_PCT"],
        "rare_premium_high_pct": TEST_DEFAULTS["RARE_PREMIUM_HIGH_PCT"],
        "rare_premium_bracket_cents": TEST_DEFAULTS["RARE_PREMIUM_BRACKET_CENTS"],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Roster and credentialing
# ---------------------------------------------------------------------------
def create_interpreter_payload(**overrides) -> Dict[str, Any]:
    """POST /interpreters — full_name, email, phone?, home_county_code,
    accepts_in_person?, accepts_remote?"""
    payload = {
        "full_name": "Ana Reyes",
        "email": "ana.reyes@courts.example.gov",
        "home_county_code": TEST_DEFAULTS["COURTHOUSE_COUNTY"],
        "accepts_in_person": True,
        "accepts_remote": True,
    }
    payload.update(overrides)
    return payload


def ethics_training_payload(**overrides) -> Dict[str, Any]:
    """POST /interpreters/{id}/ethics-training — completed_on, provider."""
    payload = {
        "completed_on": "2026-08-01",
        "provider": TEST_DEFAULTS["ETHICS_PROVIDER"],
    }
    payload.update(overrides)
    return payload


def create_credential_payload(interpreter_id: str, language_id: str,
                              expected_interpreter_version: int,
                              target_tier: str = "CERTIFIED",
                              **overrides) -> Dict[str, Any]:
    """POST /credentials — interpreter_id, language_id, target_tier,
    expected_interpreter_version (all four non-optional)."""
    payload = {
        "interpreter_id": interpreter_id,
        "language_id": language_id,
        "target_tier": target_tier,
        "expected_interpreter_version": expected_interpreter_version,
    }
    payload.update(overrides)
    return payload


def exam_attempt_payload(exam_type: str = "WRITTEN", score: float = 86,
                         taken_on: str = "2026-08-01", **overrides) -> Dict[str, Any]:
    """POST /credentials/{id}/exam-attempts — exam_type, score, taken_on."""
    payload = {"exam_type": exam_type, "score": score, "taken_on": taken_on}
    payload.update(overrides)
    return payload


def renew_credential_payload(cycle_credit_hours: float = 16.0,
                             **overrides) -> Dict[str, Any]:
    """POST /credentials/{id}/renew — cycle_credit_hours."""
    payload = {"cycle_credit_hours": cycle_credit_hours}
    payload.update(overrides)
    return payload


def revoke_credential_payload(reason: str = "Sustained ethics violation.",
                              **overrides) -> Dict[str, Any]:
    """POST /credentials/{id}/revoke — reason."""
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Calendar, matching and service
# ---------------------------------------------------------------------------
def create_hearing_payload(courthouse_id: str, language_id: str,
                           **overrides) -> Dict[str, Any]:
    """POST /hearings — every field non-optional."""
    payload = {
        "courthouse_id": courthouse_id,
        "language_id": language_id,
        "case_number": "CR-2026-0001",
        "hearing_type": "TRIAL",
        "in_custody": True,
        "scheduled_start": "2026-09-10T09:00:00.000Z",
        "scheduled_end": "2026-09-10T11:00:00.000Z",
        "requested_delivery_mode": "IN_PERSON",
    }
    payload.update(overrides)
    return payload


def create_assignment_payload(hearing_id: str, expected_hearing_version: int,
                              interpreter_id: str = None,
                              **overrides) -> Dict[str, Any]:
    """POST /assignments — hearing_id, interpreter_id?, delivery_mode,
    vendor_served?, estimated_one_way_miles?, expected_hearing_version."""
    payload: Dict[str, Any] = {
        "hearing_id": hearing_id,
        "delivery_mode": "IN_PERSON",
        "estimated_one_way_miles": 10.0,
        "expected_hearing_version": expected_hearing_version,
    }
    if interpreter_id is not None:
        payload["interpreter_id"] = interpreter_id
    payload.update(overrides)
    return payload


def continue_hearing_payload(reason_code: str = "COURT_CONGESTION",
                             **overrides) -> Dict[str, Any]:
    """POST /hearings/{id}/continue — reason_code."""
    payload = {"reason_code": reason_code}
    payload.update(overrides)
    return payload


def decline_assignment_payload(reason_code: str = "INTERPRETER_DECLINED",
                               **overrides) -> Dict[str, Any]:
    """POST /assignments/{id}/decline — reason_code."""
    payload = {"reason_code": reason_code}
    payload.update(overrides)
    return payload


def cancel_assignment_payload(reason_code: str = "COORDINATOR_CANCELLED",
                              **overrides) -> Dict[str, Any]:
    """POST /assignments/{id}/cancel — reason_code."""
    payload = {"reason_code": reason_code}
    payload.update(overrides)
    return payload


def complete_assignment_payload(actual_end_utc: str,
                                one_way_miles: float = None,
                                **overrides) -> Dict[str, Any]:
    """POST /assignments/{id}/complete — actual_end_utc, one_way_miles?."""
    payload: Dict[str, Any] = {"actual_end_utc": actual_end_utc}
    if one_way_miles is not None:
        payload["one_way_miles"] = one_way_miles
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------
def pay_pay_claim_payload(payment_reference: str = "WARRANT-2026-0001",
                          **overrides) -> Dict[str, Any]:
    """POST /pay-claims/{id}/pay — payment_reference."""
    payload = {"payment_reference": payment_reference}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Discipline
# ---------------------------------------------------------------------------
def create_complaint_payload(interpreter_id: str, **overrides) -> Dict[str, Any]:
    """POST /complaints — interpreter_id, assignment_id?, category, severity,
    narrative."""
    payload = {
        "interpreter_id": interpreter_id,
        "category": "ACCURACY",
        "severity": "MINOR",
        "narrative": "Party reports two mistranslated terms during the plea colloquy.",
    }
    payload.update(overrides)
    return payload


def review_complaint_payload(recommendation: str = "SUBSTANTIATE",
                             findings: str = "Recording confirms the reported defect.",
                             **overrides) -> Dict[str, Any]:
    """POST /complaints/{id}/review — recommendation, findings."""
    payload = {"recommendation": recommendation, "findings": findings}
    payload.update(overrides)
    return payload


def adjudicate_complaint_payload(disposition: str = "SUBSTANTIATED",
                                 sanction_type: str = None,
                                 suspension_days: int = None,
                                 **overrides) -> Dict[str, Any]:
    """POST /complaints/{id}/adjudicate — disposition, sanction_type?,
    suspension_days?."""
    payload: Dict[str, Any] = {"disposition": disposition}
    if sanction_type is not None:
        payload["sanction_type"] = sanction_type
    if suspension_days is not None:
        payload["suspension_days"] = suspension_days
    payload.update(overrides)
    return payload


def appeal_complaint_payload(grounds: str = "The record does not support the finding.",
                             **overrides) -> Dict[str, Any]:
    """POST /complaints/{id}/appeal — grounds."""
    payload = {"grounds": grounds}
    payload.update(overrides)
    return payload


def appeal_decision_payload(outcome: str = "UPHELD", **overrides) -> Dict[str, Any]:
    """POST /complaints/{id}/appeal-decision — outcome."""
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Reporting and operations
# ---------------------------------------------------------------------------
def create_unmet_need_report_payload(courthouse_id: str, period_start: str,
                                     period_end: str, **overrides) -> Dict[str, Any]:
    """POST /unmet-need-reports — courthouse_id, period_start, period_end."""
    payload = {
        "courthouse_id": courthouse_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601: str, **overrides) -> Dict[str, Any]:
    """POST /_clock/set_current_utc — to_iso8601."""
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
