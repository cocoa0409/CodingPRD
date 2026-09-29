"""Payload factories — one per creation/transition endpoint, input fields only.

Money is always sent as an integer count of cents; the two-decimal policy dials
are sent as JSON numbers.
"""
import itertools

from .constants import ISO_WEEK_MONDAYS, TEST_DEFAULTS

_counter = itertools.count(1)


def unique_suffix() -> str:
    """A short suffix that keeps unique keys distinct inside one test."""
    return f"{next(_counter):04d}"


# --------------------------------------------------------------------------
# PolicyCycle
# --------------------------------------------------------------------------
def policy_cycle_payload(**overrides) -> dict:
    defaults = {
        "cycle_label": f"FY26-H2-{unique_suffix()}",
        "effective_from": TEST_DEFAULTS["CYCLE_EFFECTIVE_FROM"],
        "effective_to": TEST_DEFAULTS["CYCLE_EFFECTIVE_TO"],
        "days_in_office_floor": 2,
        "badge_weight": 0.60,
        "network_weight": 0.40,
        "collaboration_target_score": 70.00,
        "equity_variance_threshold_pct": 20.00,
    }
    defaults.update(overrides)
    return defaults


def posture_payload(target_posture: str, note: str = None) -> dict:
    payload = {"target_posture": target_posture}
    if note is not None:
        payload["note"] = note
    return payload


# --------------------------------------------------------------------------
# Team
# --------------------------------------------------------------------------
def team_payload(policy_cycle_id: str, **overrides) -> dict:
    defaults = {
        "policy_cycle_id": policy_cycle_id,
        "team_code": f"T-A{unique_suffix()}",
        "expected_days_in_office_per_week": 3,
        "core_collaboration_days": ["TUE", "WED", "THU"],
        "headcount_planned": 12,
        "signal_corroboration_required": False,
    }
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------
# Employee
# --------------------------------------------------------------------------
def employee_payload(team_id: str, manager_user_id: str, hr_partner_user_id: str,
                     **overrides) -> dict:
    suffix = unique_suffix()
    defaults = {
        "team_id": team_id,
        "employee_number": f"E-{suffix}",
        "work_email": f"employee.{suffix}@example.com",
        "home_timezone": TEST_DEFAULTS["HOME_TIMEZONE"],
        "tenure_start_date": TEST_DEFAULTS["TENURE_START_DATE"],
        "demographic_band": "BAND_A",
        "manager_user_id": manager_user_id,
        "hr_partner_user_id": hr_partner_user_id,
    }
    defaults.update(overrides)
    return defaults


def employee_status_payload(target_status: str, note: str = None) -> dict:
    payload = {"target_status": target_status}
    if note is not None:
        payload["note"] = note
    return payload


# --------------------------------------------------------------------------
# EligibilityClassification
# --------------------------------------------------------------------------
def classification_payload(employee_id: str, expected_employee_version: int,
                           **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "requested_class": "HYBRID",
        "justification_code": "ROLE_DESIGN",
        "effective_from": "2026-09-01",
        "expected_employee_version": expected_employee_version,
    }
    defaults.update(overrides)
    return defaults


def classification_decision_payload(decision: str, decision_note: str = None) -> dict:
    payload = {"decision": decision}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return payload


# --------------------------------------------------------------------------
# AttendanceWeek / ComplianceSignal
# --------------------------------------------------------------------------
def attendance_week_payload(employee_id: str, iso_week: str = "2026-W37",
                            **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "iso_week": iso_week,
        "week_start_date": ISO_WEEK_MONDAYS.get(iso_week),
    }
    defaults.update(overrides)
    return defaults


def signal_payload(observed_date: str, signal_source: str = "BADGE",
                   **overrides) -> dict:
    defaults = {
        "signal_source": signal_source,
        "site_code": TEST_DEFAULTS["SITE_CODE"],
        "observed_date": observed_date,
        "minutes_present": TEST_DEFAULTS["FULL_DAY_MINUTES"],
        "dedupe_key": f"{signal_source}-{observed_date}-{unique_suffix()}",
    }
    defaults.update(overrides)
    return defaults


def amend_payload(amendment_reason: str = "Badge feed backfill") -> dict:
    return {"amendment_reason": amendment_reason}


# --------------------------------------------------------------------------
# ExceptionRequest
# --------------------------------------------------------------------------
def exception_request_payload(employee_id: str, **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "category": "CAREGIVING",
        "requested_relief_days": 2,
        "start_date": "2026-09-07",
        "end_date": "2026-09-11",
        "rationale": "Dependent care arrangement for the stated window.",
    }
    defaults.update(overrides)
    return defaults


def request_info_payload(info_needed: str = "Please supply supporting detail.") -> dict:
    return {"info_needed": info_needed}


def respond_info_payload(response_note: str = "Supporting detail attached.") -> dict:
    return {"response_note": response_note}


def adjudicate_payload(decision: str, granted_relief_days: int = None,
                       closure_reason: str = None) -> dict:
    payload = {"decision": decision}
    if granted_relief_days is not None:
        payload["granted_relief_days"] = granted_relief_days
    if closure_reason is not None:
        payload["closure_reason"] = closure_reason
    return payload


def revoke_payload(closure_reason: str = "Arrangement no longer needed.") -> dict:
    return {"closure_reason": closure_reason}


# --------------------------------------------------------------------------
# RemoteLocationRequest
# --------------------------------------------------------------------------
def relocation_request_payload(employee_id: str, **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "jurisdiction_code": "US_TX",
        "data_classification_tier": "PUBLIC",
        "proposed_start_date": "2026-10-01",
    }
    defaults.update(overrides)
    return defaults


def tax_review_payload(review_outcome: str = "CLEARED", licensing_gap_count: int = 0,
                       tax_nexus_registration_cost_cents: int = 0) -> dict:
    return {
        "review_outcome": review_outcome,
        "licensing_gap_count": licensing_gap_count,
        "tax_nexus_registration_cost_cents": tax_nexus_registration_cost_cents,
    }


def security_review_payload(review_outcome: str = "CLEARED",
                            control_gap_count: int = 0) -> dict:
    return {
        "review_outcome": review_outcome,
        "control_gap_count": control_gap_count,
    }


def relocation_decision_payload(decision: str) -> dict:
    return {"decision": decision}


# --------------------------------------------------------------------------
# Neighborhood / SeatAllocation / DeskAssignment
# --------------------------------------------------------------------------
def neighborhood_payload(policy_cycle_id: str, anchor_team_id: str,
                         **overrides) -> dict:
    seat_count = overrides.pop("seat_count", 10)
    defaults = {
        "policy_cycle_id": policy_cycle_id,
        "anchor_team_id": anchor_team_id,
        "neighborhood_code": f"NB-{unique_suffix()}",
        "site_code": TEST_DEFAULTS["SITE_CODE"],
        "seat_count": seat_count,
        "buffer_seats": 1,
        "desk_index_from": 1,
        "desk_index_to": seat_count,
    }
    defaults.update(overrides)
    return defaults


def seat_allocation_payload(neighborhood_id: str, team_id: str,
                            expected_neighborhood_version: int,
                            **overrides) -> dict:
    defaults = {
        "neighborhood_id": neighborhood_id,
        "team_id": team_id,
        "allocated_seats": 5,
        "window_start_week": "2026-W37",
        "window_end_week": "2026-W39",
        "expected_neighborhood_version": expected_neighborhood_version,
    }
    defaults.update(overrides)
    return defaults


def release_payload(release_reason: str = "Zone reconfigured.") -> dict:
    return {"release_reason": release_reason}


def desk_assignment_payload(seat_allocation_id: str, employee_id: str,
                            desk_index: int = 1, **overrides) -> dict:
    defaults = {
        "seat_allocation_id": seat_allocation_id,
        "employee_id": employee_id,
        "desk_index": desk_index,
        "start_date": "2026-09-07",
        "end_date": "2026-09-11",
    }
    defaults.update(overrides)
    return defaults


def auto_desk_payload(employee_id: str, start_date: str = "2026-09-07",
                      end_date: str = "2026-09-11") -> dict:
    return {
        "employee_id": employee_id,
        "start_date": start_date,
        "end_date": end_date,
    }


# --------------------------------------------------------------------------
# EscalationCase levers
# --------------------------------------------------------------------------
def escalation_action_payload(action_note: str = "Formal action recorded.") -> dict:
    return {"action_note": action_note}


def hold_payload(discretionary_hold: bool,
                 action_note: str = "Hold toggled.") -> dict:
    return {
        "discretionary_hold": discretionary_hold,
        "action_note": action_note,
    }


# --------------------------------------------------------------------------
# RecalibrationReview
# --------------------------------------------------------------------------
def recalibration_review_payload(policy_cycle_id: str, **overrides) -> dict:
    defaults = {
        "policy_cycle_id": policy_cycle_id,
        "review_label": f"RC-{unique_suffix()}",
        "proposed_days_in_office_delta": 0,
    }
    defaults.update(overrides)
    return defaults


def recalibration_decision_payload(decision: str, expected_policy_cycle_version: int,
                                   decision_reason: str = None) -> dict:
    payload = {
        "decision": decision,
        "expected_policy_cycle_version": expected_policy_cycle_version,
    }
    if decision_reason is not None:
        payload["decision_reason"] = decision_reason
    return payload
