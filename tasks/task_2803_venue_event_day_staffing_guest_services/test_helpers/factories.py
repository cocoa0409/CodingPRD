"""Request-payload builders.

Rules observed everywhere in this module:
  * every cents field is emitted as a JSON integer, never a string;
  * ratios are emitted as JSON numbers;
  * optional fields are omitted entirely unless the caller passes them, so the
    server's declared defaults are exercised rather than masked;
  * ``**overrides`` is merged last so a test can inject a deliberately invalid
    value (wrong type, out-of-range, reversed interval) into any field.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    DEFAULT_GRATUITY_POOL_CENTS,
    DEFAULT_REFUND_BUDGET_TOTAL_CENTS,
)

_SENTINEL = object()


def _prune(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value is the omission sentinel."""
    return {k: v for k, v in payload.items() if v is not _SENTINEL}


# ---------------------------------------------------------------- Event
def event_payload(
    name: str = "Autumn Main Stage Concert",
    event_date: str = "2026-09-12T00:00:00Z",
    doors_open_at: str = "2026-09-12T16:00:00Z",
    doors_close_at: str = "2026-09-12T23:00:00Z",
    expected_attendance: int = 6000,
    historical_actual_attendance: Any = _SENTINEL,
    refund_budget_total_cents: Any = _SENTINEL,
    gratuity_pool_cents: Any = _SENTINEL,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "name": name,
        "event_date": event_date,
        "doors_open_at": doors_open_at,
        "doors_close_at": doors_close_at,
        "expected_attendance": expected_attendance,
        "historical_actual_attendance": historical_actual_attendance,
        "refund_budget_total_cents": refund_budget_total_cents,
        "gratuity_pool_cents": gratuity_pool_cents,
    }
    payload.update(overrides)
    return _prune(payload)


def event_with_budget_payload(
    refund_budget_total_cents: int = DEFAULT_REFUND_BUDGET_TOTAL_CENTS,
    gratuity_pool_cents: int = DEFAULT_GRATUITY_POOL_CENTS,
    **overrides: Any,
) -> Dict[str, Any]:
    return event_payload(
        refund_budget_total_cents=int(refund_budget_total_cents),
        gratuity_pool_cents=int(gratuity_pool_cents),
        **overrides,
    )


def event_lifecycle_payload(
    target_status: str, expected_event_version: Any = _SENTINEL, **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "target_status": target_status,
        "expected_event_version": expected_event_version,
    }
    payload.update(overrides)
    return _prune(payload)


def payout_run_payload(phase: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"phase": phase}
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------- PositionType
def position_type_payload(
    code: str = "USHER",
    display_name: str = "Usher",
    base_hourly_rate_cents: int = 2200,
    attendance_ratio_per_1000: float = 1.5,
    min_headcount: int = 4,
    required_certifications: Any = _SENTINEL,
    is_tip_eligible: Any = _SENTINEL,
    is_contracted_position: Any = _SENTINEL,
    **overrides: Any,
) -> Dict[str, Any]:
    # `required_certifications` is a required field of the filing, so it is always
    # sent; an empty list is the "no credential needed" family.  Only the two
    # booleans carry declared defaults and may therefore be omitted.
    if required_certifications is _SENTINEL:
        required_certifications = []
    payload = {
        "code": code,
        "display_name": display_name,
        "base_hourly_rate_cents": int(base_hourly_rate_cents),
        "attendance_ratio_per_1000": attendance_ratio_per_1000,
        "min_headcount": int(min_headcount),
        "required_certifications": required_certifications,
        "is_tip_eligible": is_tip_eligible,
        "is_contracted_position": is_contracted_position,
    }
    payload.update(overrides)
    return _prune(payload)


def _family_payload(defaults: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Merge caller overrides over a canonical family's defaults.

    The merge happens before the call so that overriding a field the canonical
    family already pins (its rate, ratio or floor) replaces that value rather
    than being passed twice.
    """
    merged = dict(defaults)
    merged.update(overrides)
    return position_type_payload(**merged)


def usher_payload(**overrides: Any) -> Dict[str, Any]:
    return _family_payload(
        {
            "code": "USHER",
            "display_name": "Usher",
            "base_hourly_rate_cents": 2200,
            "attendance_ratio_per_1000": 1.5,
            "min_headcount": 4,
        },
        overrides,
    )


def ticket_taker_payload(**overrides: Any) -> Dict[str, Any]:
    return _family_payload(
        {
            "code": "TICKET_TAKER",
            "display_name": "Ticket Taker",
            "base_hourly_rate_cents": 2000,
            "attendance_ratio_per_1000": 0.8,
            "min_headcount": 3,
        },
        overrides,
    )


def elevator_operator_payload(**overrides: Any) -> Dict[str, Any]:
    return _family_payload(
        {
            "code": "ELEVATOR_OPERATOR",
            "display_name": "Elevator Operator",
            "base_hourly_rate_cents": 2600,
            "attendance_ratio_per_1000": 0.2,
            "min_headcount": 2,
        },
        overrides,
    )


def guest_services_rep_payload(**overrides: Any) -> Dict[str, Any]:
    return _family_payload(
        {
            "code": "GUEST_SERVICES_REP",
            "display_name": "Guest Services Representative",
            "base_hourly_rate_cents": 2400,
            "attendance_ratio_per_1000": 0.35,
            "min_headcount": 2,
        },
        overrides,
    )


# ---------------------------------------------------------------- StaffingPlan
def staffing_plan_payload(
    event_id: str, plan_variant: str = "FORECAST_BASED", **overrides: Any
) -> Dict[str, Any]:
    payload = {"event_id": event_id, "plan_variant": plan_variant}
    payload.update(overrides)
    return _prune(payload)


def plan_activate_payload(expected_event_version: Any = _SENTINEL, **overrides: Any):
    payload = {"expected_event_version": expected_event_version}
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------- PositionSlot
def position_slot_payload(
    plan_id: str,
    position_type_id: str,
    zone_code: str = "Z101",
    shift_start: str = "2026-09-12T16:00:00Z",
    shift_end: str = "2026-09-12T22:00:00Z",
    required_headcount_override: Any = _SENTINEL,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "plan_id": plan_id,
        "position_type_id": position_type_id,
        "zone_code": zone_code,
        "shift_start": shift_start,
        "shift_end": shift_end,
        "required_headcount_override": required_headcount_override,
    }
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------- StaffMember
def staff_member_payload(
    full_name: str = "Dana Whitfield",
    employment_type: str = "PART_TIME_EMPLOYEE",
    seniority_date: str = "2024-03-01T00:00:00Z",
    hourly_rate_cents: int = 2200,
    in_backfill_pool: Any = _SENTINEL,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "full_name": full_name,
        "employment_type": employment_type,
        "seniority_date": seniority_date,
        "hourly_rate_cents": int(hourly_rate_cents),
        "in_backfill_pool": in_backfill_pool,
    }
    payload.update(overrides)
    return _prune(payload)


def status_change_payload(
    target_status: str, reason: Any = _SENTINEL, **overrides: Any
) -> Dict[str, Any]:
    payload = {"target_status": target_status, "reason": reason}
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------- Certification
def certification_payload(
    staff_member_id: str,
    cert_type: str = "EVACUATION_PROCEDURES",
    issued_on: str = "2026-01-01T00:00:00Z",
    expires_on: str = "2027-01-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "staff_member_id": staff_member_id,
        "cert_type": cert_type,
        "issued_on": issued_on,
        "expires_on": expires_on,
    }
    payload.update(overrides)
    return _prune(payload)


def revoke_payload(reason: Any = _SENTINEL, **overrides: Any) -> Dict[str, Any]:
    payload = {"reason": reason}
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------- ShiftBid
def shift_bid_payload(
    staff_member_id: str, position_slot_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "staff_member_id": staff_member_id,
        "position_slot_id": position_slot_id,
    }
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------- StaffAssignment
def staff_assignment_payload(
    position_slot_id: str, staff_member_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "position_slot_id": position_slot_id,
        "staff_member_id": staff_member_id,
    }
    payload.update(overrides)
    return _prune(payload)


def attendance_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"action": action}
    payload.update(overrides)
    return _prune(payload)


def cancel_backfill_payload(
    cancel_reason: Any = _SENTINEL, **overrides: Any
) -> Dict[str, Any]:
    payload = {"cancel_reason": cancel_reason}
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------- GuestIssue
def guest_issue_payload(
    event_id: str,
    channel: str = "IN_PERSON",
    category: str = "OTHER",
    severity: str = "MEDIUM",
    description: str = "Guest reported an issue at the concourse desk.",
    seat_reference: Any = _SENTINEL,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "event_id": event_id,
        "channel": channel,
        "category": category,
        "severity": severity,
        "description": description,
        "seat_reference": seat_reference,
    }
    payload.update(overrides)
    return _prune(payload)


def issue_assign_payload(staff_member_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"staff_member_id": staff_member_id}
    payload.update(overrides)
    return _prune(payload)


def issue_resolve_payload(
    resolution_type: str, relocation_zone_code: Any = _SENTINEL, **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "resolution_type": resolution_type,
        "relocation_zone_code": relocation_zone_code,
    }
    payload.update(overrides)
    return _prune(payload)


def refund_request_payload(
    refund_requested_cents: int, **overrides: Any
) -> Dict[str, Any]:
    payload = {"refund_requested_cents": int(refund_requested_cents)}
    payload.update(overrides)
    return _prune(payload)


def refund_decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"decision": decision}
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------- Accessibility
def accessibility_resource_payload(
    event_id: str,
    resource_type: str = "WHEELCHAIR_ESCORT",
    zone_code: str = "Z101",
    unit_count: int = 3,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "event_id": event_id,
        "resource_type": resource_type,
        "zone_code": zone_code,
        "unit_count": int(unit_count),
    }
    payload.update(overrides)
    return _prune(payload)


def accessibility_request_payload(
    resource_id: str,
    guest_reference: str = "GUEST-0001",
    window_start: str = "2026-09-12T18:00:00Z",
    window_end: str = "2026-09-12T20:00:00Z",
    units_requested: int = 1,
    companion_seats_requested: Any = _SENTINEL,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "resource_id": resource_id,
        "guest_reference": guest_reference,
        "window_start": window_start,
        "window_end": window_end,
        "units_requested": int(units_requested),
        "companion_seats_requested": companion_seats_requested,
    }
    payload.update(overrides)
    return _prune(payload)


def access_transition_payload(
    target_status: str, denial_reason: Any = _SENTINEL, **overrides: Any
) -> Dict[str, Any]:
    payload = {"target_status": target_status, "denial_reason": denial_reason}
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------- Satisfaction
def satisfaction_response_payload(
    event_id: str,
    zone_code: str = "Z101",
    score: int = 5,
    comment: Any = _SENTINEL,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "event_id": event_id,
        "zone_code": zone_code,
        "score": int(score),
        "comment": comment,
    }
    payload.update(overrides)
    return _prune(payload)


# ---------------------------------------------------------------- misc helpers
def position_type_payloads_for_codes(codes: List[str]) -> List[Dict[str, Any]]:
    """The four canonical position-type payloads, selected by code."""
    builders = {
        "USHER": usher_payload,
        "TICKET_TAKER": ticket_taker_payload,
        "ELEVATOR_OPERATOR": elevator_operator_payload,
        "GUEST_SERVICES_REP": guest_services_rep_payload,
    }
    return [builders[code]() for code in codes]


def omit(payload: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    """Return a copy of payload with the named keys removed."""
    return {k: v for k, v in payload.items() if k not in keys}


def with_fields(payload: Dict[str, Any], **fields: Any) -> Dict[str, Any]:
    merged = dict(payload)
    merged.update(fields)
    return merged


OPTIONAL: Optional[Any] = None
