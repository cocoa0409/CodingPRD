"""Request payload builders.

Typing rules honoured throughout, from PRD §2.4 and §2.6:

* money is an integer count of cents — never a string, never a float;
* every ``*_utc`` field is a full ISO 8601 instant, never a date-only string;
* ``operational_date`` is the one date-only field, a ``YYYY-MM-DD`` string;
* client-supplied percentages are JSON numbers with two decimals.
"""

from itertools import count
from typing import Any, Optional

from .types import JsonDict

_SERIAL_COUNTER = count(1)
_BADGE_COUNTER = count(1)
_CURVE_COUNTER = count(1)
_FLIGHT_COUNTER = count(1)

FAR_FUTURE_CALIBRATION_UTC = "2027-01-01T00:00:00Z"


def unique_serial(prefix: str = "SN") -> str:
    return f"{prefix}-{next(_SERIAL_COUNTER)}"


def unique_badge(prefix: str = "B") -> str:
    return f"{prefix}-{9000 + next(_BADGE_COUNTER)}"


def unique_curve_name(prefix: str = "Curve") -> str:
    return f"{prefix} {next(_CURVE_COUNTER)}"


def unique_flight_number(prefix: str = "ZZ") -> str:
    return f"{prefix}{100 + next(_FLIGHT_COUNTER)}"


def _without_none(payload: JsonDict) -> JsonDict:
    return {key: value for key, value in payload.items() if value is not None}


# ── Logical clock ─────────────────────────────────────────────────────────────
def clock_payload(current_utc: str) -> JsonDict:
    return {"current_utc": current_utc}


# ── Checkpoint (PRD §3.1) ─────────────────────────────────────────────────────
def checkpoint_payload(**overrides: Any) -> JsonDict:
    payload: JsonDict = {
        "name": "T1 Main",
        "terminal_code": "T1",
        "total_lane_positions": 6,
        "wait_threshold_minutes_standard": 15,
        "wait_threshold_minutes_expedited": 8,
        "connecting_pax_discount_pct": 0,
        "secondary_slot_capacity": 2,
        "plan_cost_cap_cents": 10000000,
    }
    payload.update(overrides)
    return payload


def checkpoint_patch_payload(**fields: Any) -> JsonDict:
    """A PATCH body carrying only the fields the caller names."""
    return dict(fields)


# ── Lane (PRD §3.1) ───────────────────────────────────────────────────────────
def lane_payload(checkpoint_id: str, **overrides: Any) -> JsonDict:
    payload: JsonDict = {
        "checkpoint_id": checkpoint_id,
        "lane_type": "STANDARD",
        "position_index": 1,
        "required_officer_count": 1,
        "max_concurrent_officers": 2,
        "secondary_positions": 1,
    }
    payload.update(overrides)
    return payload


def stand_down_payload(
    target_state: str, paused_reason_code: Optional[str] = None
) -> JsonDict:
    return _without_none(
        {"target_state": target_state, "paused_reason_code": paused_reason_code}
    )


# ── Equipment unit (PRD §3.1, §3.6) ───────────────────────────────────────────
def equipment_payload(
    lane_id: str,
    equipment_type: str,
    serial_number: Optional[str] = None,
    calibration_due_utc: str = FAR_FUTURE_CALIBRATION_UTC,
) -> JsonDict:
    return {
        "lane_id": lane_id,
        "equipment_type": equipment_type,
        "serial_number": serial_number or unique_serial(equipment_type[:2]),
        "calibration_due_utc": calibration_due_utc,
    }


def report_state_payload(state: str, note: Optional[str] = None) -> JsonDict:
    return _without_none({"state": state, "note": note})


# ── Officer (PRD §3.1, §3.7) ──────────────────────────────────────────────────
def officer_payload(
    badge_number: Optional[str] = None,
    full_name: str = "Ada Lane",
    certifications: Optional[list] = None,
    base_rate_cents_per_minute: int = 100,
    weekly_regular_minutes_cap: int = 2400,
    weekly_overtime_minutes_cap: int = 600,
) -> JsonDict:
    return {
        "badge_number": badge_number or unique_badge(),
        "full_name": full_name,
        "certifications": certifications or ["STANDARD_LANE", "ADVANCED_IMAGING"],
        "base_rate_cents_per_minute": base_rate_cents_per_minute,
        "weekly_regular_minutes_cap": weekly_regular_minutes_cap,
        "weekly_overtime_minutes_cap": weekly_overtime_minutes_cap,
    }


def duty_status_payload(duty_status: str) -> JsonDict:
    return {"duty_status": duty_status}

# ── Show-up curve (PRD §3.1) ──────────────────────────────────────────────────
def curve_bucket(
    minutes_before_start: int, minutes_before_end: int, share_pct: int
) -> JsonDict:
    return {
        "minutes_before_start": minutes_before_start,
        "minutes_before_end": minutes_before_end,
        "share_pct": share_pct,
    }


def show_up_curve_payload(
    name: Optional[str] = None,
    carrier_type: str = "DOMESTIC",
    season_code: str = "PEAK",
    window_start_minutes_before: int = 30,
    window_end_minutes_before: int = 0,
    buckets: Optional[list] = None,
) -> JsonDict:
    """Defaults to the single 30-to-0 bucket carrying the whole population."""
    return {
        "name": name or unique_curve_name("Late Domestic"),
        "carrier_type": carrier_type,
        "season_code": season_code,
        "window_start_minutes_before": window_start_minutes_before,
        "window_end_minutes_before": window_end_minutes_before,
        "buckets": buckets if buckets is not None else [curve_bucket(30, 0, 100)],
    }


# ── Flight schedule entry (PRD §3.2) ──────────────────────────────────────────
def flight_payload(
    checkpoint_id: str,
    show_up_curve_id: str,
    scheduled_departure_utc: str,
    flight_number: Optional[str] = None,
    seats_sold: int = 10,
    load_factor_pct: float = 100.00,
    carrier_type: str = "DOMESTIC",
) -> JsonDict:
    return {
        "checkpoint_id": checkpoint_id,
        "show_up_curve_id": show_up_curve_id,
        "flight_number": flight_number or unique_flight_number(),
        "scheduled_departure_utc": scheduled_departure_utc,
        "seats_sold": seats_sold,
        "load_factor_pct": load_factor_pct,
        "carrier_type": carrier_type,
    }


# ── Time band (PRD §3.2) ──────────────────────────────────────────────────────
def time_band_payload(
    checkpoint_id: str,
    band_start_utc: str,
    expedited_share_pct: int = 0,
    seasonal_multiplier: Optional[float] = 1.00,
) -> JsonDict:
    return _without_none(
        {
            "checkpoint_id": checkpoint_id,
            "band_start_utc": band_start_utc,
            "expedited_share_pct": expedited_share_pct,
            "seasonal_multiplier": seasonal_multiplier,
        }
    )


def forecast_payload(variant: str) -> JsonDict:
    return {"variant": variant}


# ── Staffing plan (PRD §3.3, §3.4) ────────────────────────────────────────────
def staffing_plan_payload(
    checkpoint_id: str, operational_date: str, expected_checkpoint_version: int
) -> JsonDict:
    return {
        "checkpoint_id": checkpoint_id,
        "operational_date": operational_date,
        "expected_checkpoint_version": expected_checkpoint_version,
    }


def plan_decision_payload(
    decision: str, rejection_reason_code: Optional[str] = None
) -> JsonDict:
    return _without_none(
        {"decision": decision, "rejection_reason_code": rejection_reason_code}
    )


def plan_lifecycle_payload(action: str) -> JsonDict:
    return {"action": action}


# ── Lane assignment (PRD §3.3, §3.7) ──────────────────────────────────────────
def lane_assignment_payload(
    staffing_plan_id: str, lane_id: str, officer_id: str, time_band_id: str
) -> JsonDict:
    return {
        "staffing_plan_id": staffing_plan_id,
        "lane_id": lane_id,
        "officer_id": officer_id,
        "time_band_id": time_band_id,
    }


def duty_action_payload(action: str) -> JsonDict:
    return {"action": action}


def break_action_payload(action: str) -> JsonDict:
    return {"action": action}


# ── Wait observation (PRD §3.8) ───────────────────────────────────────────────
def wait_observation_payload(
    lane_type: str = "STANDARD",
    sampled_wait_seconds: int = 300,
    measurement_method: str = "BLE_SENSOR",
    sample_size: int = 10,
) -> JsonDict:
    return {
        "lane_type": lane_type,
        "sampled_wait_seconds": sampled_wait_seconds,
        "measurement_method": measurement_method,
        "sample_size": sample_size,
    }


# ── Escalation ticket resolution (PRD §3.8) ───────────────────────────────────
def ticket_resolution_payload(
    resolution: str,
    resolved_lane_id: Optional[str] = None,
    diverted_pax_count: Optional[int] = None,
    resolution_note: Optional[str] = None,
) -> JsonDict:
    return _without_none(
        {
            "resolution": resolution,
            "resolved_lane_id": resolved_lane_id,
            "diverted_pax_count": diverted_pax_count,
            "resolution_note": resolution_note,
        }
    )


# ── Screening referral (PRD §3.9) ─────────────────────────────────────────────
def referral_payload(
    lane_id: str,
    referral_reason: str = "RANDOM",
    passenger_category: str = "ADULT",
    requires_private_screening: Optional[bool] = False,
) -> JsonDict:
    return _without_none(
        {
            "lane_id": lane_id,
            "referral_reason": referral_reason,
            "passenger_category": passenger_category,
            "requires_private_screening": requires_private_screening,
        }
    )


def referral_begin_payload(resolving_officer_id: str) -> JsonDict:
    return {"resolving_officer_id": resolving_officer_id}


def referral_resolution_payload(
    outcome: str, resolution_note: Optional[str] = None
) -> JsonDict:
    return _without_none({"outcome": outcome, "resolution_note": resolution_note})


# ── Surge detail (PRD §3.5) ───────────────────────────────────────────────────
def surge_detail_payload(
    staffing_plan_id: str,
    officer_id: str,
    window_start_utc: str,
    detail_minutes: int,
    expected_officer_version: int,
    event_code: str = "SPORTING_EVENT",
) -> JsonDict:
    return {
        "staffing_plan_id": staffing_plan_id,
        "officer_id": officer_id,
        "event_code": event_code,
        "window_start_utc": window_start_utc,
        "detail_minutes": detail_minutes,
        "expected_officer_version": expected_officer_version,
    }


def surge_decision_payload(
    decision: str, denial_reason_code: Optional[str] = None
) -> JsonDict:
    return _without_none(
        {"decision": decision, "denial_reason_code": denial_reason_code}
    )
