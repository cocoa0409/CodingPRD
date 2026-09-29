"""Request-payload builders.

Two conventions are enforced here because getting either wrong breaks every
test that depends on a factory:

1. Money and every other decimal quantity is emitted as a JSON *number*
   (`3.4500`, `500000.00`), never as a string. PRD §2.5 declares these as
   decimal quantities carried at a fixed number of decimal places, not as text.
2. Fields the PRD declares as instants (`last_mit_passed_at`, `detected_at`,
   `scheduled_start_at`, `window_start_at`, ...) are emitted as full ISO 8601
   UTC instants such as `2026-08-01T00:00:00Z`, never as bare calendar dates.
   Fields the PRD declares as calendar dates (`gas_day`, `term_start_date`,
   `period_end_date`, ...) stay in `YYYY-MM-DD` form.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    CASH_OUT_MONTHLY_AGGREGATE,
    DELIVERABILITY_CURVE_INTERPOLATED,
    DIRECTION_INJECTION,
    EVENT_TYPE_LEAK,
    F_BOUND_CUSHION_GAS_DTH,
    F_BOUND_TOTAL_CAPACITY_DTH,
    F_MINI_BASE_PRESSURE_PSIG,
    F_MINI_CUSHION_GAS_DTH,
    F_MINI_MAX_PRESSURE_PSIG,
    F_MINI_OPENING_WORKING_GAS_DTH,
    F_MINI_PRESSURE_SPAN_PSIG,
    F_MINI_TOTAL_CAPACITY_DTH,
    F_STD_BASE_PRESSURE_PSIG,
    F_STD_CUSHION_GAS_DTH,
    F_STD_MAX_PRESSURE_PSIG,
    F_STD_OPENING_WORKING_GAS_DTH,
    F_STD_PRESSURE_SPAN_PSIG,
    F_STD_TOTAL_CAPACITY_DTH,
    MIT_TEST_TYPE_PRESSURE,
    REPORT_TYPE_INVENTORY,
    RUN_MODE_INJECTION,
    SEASON_INJECTION,
    SERVICE_CLASS_FIRM,
    SEVERITY_SERIOUS,
    WELL_TYPE_INJECTION_WITHDRAWAL,
)

Payload = Dict[str, Any]


def _merge(base: Payload, overrides: Payload) -> Payload:
    """Apply overrides; an override of None removes the key entirely, which is
    how a test omits an optional input to exercise its declared default."""
    result = dict(base)
    for key, value in overrides.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = value
    return result


# ─── Deliverability curves (PRD §2.7) ──────────────────────────────────────

def curve_point(
    inventory_pct: float, withdrawal_dth_per_day: int, injection_dth_per_day: int
) -> Payload:
    return {
        "inventory_pct": inventory_pct,
        "withdrawal_dth_per_day": withdrawal_dth_per_day,
        "injection_dth_per_day": injection_dth_per_day,
    }


def two_point_curve(withdrawal_full: int, injection_empty: int) -> List[Payload]:
    """The minimum legal curve: first point at 0, last at 100."""
    return [
        curve_point(0, 0, injection_empty),
        curve_point(100, withdrawal_full, 0),
    ]


F_STD_CURVE = [
    curve_point(0, 0, 400000),
    curve_point(25, 150000, 350000),
    curve_point(50, 300000, 250000),
    curve_point(75, 450000, 150000),
    curve_point(100, 600000, 0),
]

F_BOUND_CURVE = [
    curve_point(0, 0, 120000),
    curve_point(25, 30000, 100000),
    curve_point(50, 60000, 80000),
    curve_point(75, 90000, 60000),
    curve_point(100, 120000, 0),
]

F_MINI_CURVE = two_point_curve(300000, 300000)


# ─── Storage fields (PRD §3.1) ─────────────────────────────────────────────

def storage_field_payload(**overrides: Any) -> Payload:
    """The F_MINI reservoir: 1,000,000 total against 500,000 cushion, so the
    working gas ceiling is 500,000 and an opening 250,000 sits at 50.00%."""
    return _merge(
        {
            "name": "Cavern Mini",
            "field_code": "F-MINI",
            "total_capacity_dth": F_MINI_TOTAL_CAPACITY_DTH,
            "cushion_gas_dth": F_MINI_CUSHION_GAS_DTH,
            "base_pressure_psig": F_MINI_BASE_PRESSURE_PSIG,
            "pressure_span_psig": F_MINI_PRESSURE_SPAN_PSIG,
            "max_pressure_psig": F_MINI_MAX_PRESSURE_PSIG,
            "season": SEASON_INJECTION,
            "opening_working_gas_dth": F_MINI_OPENING_WORKING_GAS_DTH,
            "deliverability_method": DELIVERABILITY_CURVE_INTERPOLATED,
            "deliverability_curve": list(F_MINI_CURVE),
        },
        overrides,
    )


def f_std_field_payload(**overrides: Any) -> Payload:
    """The standard reservoir: 10,000,000 total against 2,000,000 cushion, so
    an opening 3,000,000 of the 8,000,000 ceiling sits at 37.50%."""
    return _merge(
        {
            "name": "Aurora Dome",
            "field_code": "F-AUR",
            "total_capacity_dth": F_STD_TOTAL_CAPACITY_DTH,
            "cushion_gas_dth": F_STD_CUSHION_GAS_DTH,
            "base_pressure_psig": F_STD_BASE_PRESSURE_PSIG,
            "pressure_span_psig": F_STD_PRESSURE_SPAN_PSIG,
            "max_pressure_psig": F_STD_MAX_PRESSURE_PSIG,
            "season": SEASON_INJECTION,
            "opening_working_gas_dth": F_STD_OPENING_WORKING_GAS_DTH,
            "deliverability_method": DELIVERABILITY_CURVE_INTERPOLATED,
            "deliverability_curve": list(F_STD_CURVE),
        },
        overrides,
    )


def f_bound_field_payload(**overrides: Any) -> Payload:
    """The tight reservoir: 1,000,000 total against 900,000 cushion, so the
    whole working gas ceiling is only 100,000 and it opens empty."""
    return _merge(
        {
            "name": "Bound Ridge",
            "field_code": "F-BND",
            "total_capacity_dth": F_BOUND_TOTAL_CAPACITY_DTH,
            "cushion_gas_dth": F_BOUND_CUSHION_GAS_DTH,
            "base_pressure_psig": F_STD_BASE_PRESSURE_PSIG,
            "pressure_span_psig": F_STD_PRESSURE_SPAN_PSIG,
            "max_pressure_psig": F_STD_MAX_PRESSURE_PSIG,
            "season": SEASON_INJECTION,
            "opening_working_gas_dth": 0,
            "deliverability_method": DELIVERABILITY_CURVE_INTERPOLATED,
            "deliverability_curve": list(F_BOUND_CURVE),
        },
        overrides,
    )


def season_payload(season: str) -> Payload:
    return {"season": season}


# ─── Wellbores (PRD §3.1) ──────────────────────────────────────────────────

def well_payload(storage_field_id: str, **overrides: Any) -> Payload:
    """`last_mit_passed_at` is an instant, so it carries a full time-of-day."""
    return _merge(
        {
            "storage_field_id": storage_field_id,
            "well_name": "MINI-1",
            "well_type": WELL_TYPE_INJECTION_WITHDRAWAL,
            "rated_rate_dth_per_day": 600000,
            "last_mit_passed_at": "2026-06-01T00:00:00Z",
        },
        overrides,
    )


def service_change_payload(to_operational_state: str, reason: Optional[str] = None) -> Payload:
    payload: Payload = {"to_operational_state": to_operational_state}
    if reason is not None:
        payload["reason"] = reason
    return payload


# ─── Mechanical integrity tests (PRD §3.2) ─────────────────────────────────

def mit_payload(well_id: str, **overrides: Any) -> Payload:
    return _merge(
        {
            "well_id": well_id,
            "test_type": MIT_TEST_TYPE_PRESSURE,
            "scheduled_start_at": "2026-08-02T00:00:00Z",
            "scheduled_end_at": "2026-08-02T06:00:00Z",
        },
        overrides,
    )


def mit_result_payload(outcome: str, result_pressure_psig: Optional[int] = 2000) -> Payload:
    payload: Payload = {"outcome": outcome}
    if result_pressure_psig is not None:
        payload["result_pressure_psig"] = result_pressure_psig
    return payload


def remediation_completion_payload(verification_notes: str = "Independent verification passed") -> Payload:
    return {"verification_notes": verification_notes}


# ─── Compressor units and runs (PRD §3.3) ──────────────────────────────────

def compressor_unit_payload(storage_field_id: str, **overrides: Any) -> Payload:
    """`derate_factor` is a decimal number between 0.00 and 0.50 inclusive."""
    return _merge(
        {
            "storage_field_id": storage_field_id,
            "unit_code": "U-1",
            "rated_horsepower": 6000,
            "derate_factor": 0.00,
        },
        overrides,
    )


def compressor_run_payload(compressor_unit_id: str, **overrides: Any) -> Payload:
    """The window bounds are instants, not calendar dates."""
    return _merge(
        {
            "compressor_unit_id": compressor_unit_id,
            "window_start_at": "2026-08-02T00:00:00Z",
            "window_end_at": "2026-08-02T08:00:00Z",
            "allocated_horsepower": 3000,
            "mode": RUN_MODE_INJECTION,
        },
        overrides,
    )


# ─── Shippers and contracts (PRD §3.4) ─────────────────────────────────────

def shipper_payload(**overrides: Any) -> Payload:
    """`penalty_threshold_usd` is money, so it is a JSON number."""
    return _merge(
        {
            "legal_name": "Northline Gas Marketing",
            "duns_number": "123456789",
            "penalty_threshold_usd": 500000.00,
        },
        overrides,
    )


def second_shipper_payload(**overrides: Any) -> Payload:
    return _merge(
        {
            "legal_name": "Southgate Energy Trading",
            "duns_number": "223456789",
            "penalty_threshold_usd": 500000.00,
        },
        overrides,
    )


def contract_payload(shipper_id: str, storage_field_id: str, **overrides: Any) -> Payload:
    """Rates are 4-decimal JSON numbers; the term bounds are calendar dates."""
    return _merge(
        {
            "shipper_id": shipper_id,
            "storage_field_id": storage_field_id,
            "contract_code": "CN-1",
            "service_class": SERVICE_CLASS_FIRM,
            "max_storage_quantity_dth": 1000000,
            "max_daily_injection_dth": 100000,
            "max_daily_withdrawal_dth": 100000,
            "term_start_date": "2026-08-01",
            "term_end_date": "2026-12-31",
            "commodity_rate_usd_per_dth": 0.0450,
            "index_price_usd_per_dth": 3.4500,
            "cash_out_method": CASH_OUT_MONTHLY_AGGREGATE,
        },
        overrides,
    )


def cash_out_payload(period_start_date: str, period_end_date: str) -> Payload:
    return {"period_start_date": period_start_date, "period_end_date": period_end_date}


def cash_out_reversal_payload(reason: str = "Metering correction accepted by the shipper") -> Payload:
    return {"reason": reason}


# ─── Nominations (PRD §3.5) ────────────────────────────────────────────────

def nomination_payload(
    contract_id: str, expected_contract_version: int, **overrides: Any
) -> Payload:
    """`gas_day` is a calendar date in `YYYY-MM-DD` form."""
    return _merge(
        {
            "contract_id": contract_id,
            "gas_day": "2026-08-02",
            "direction": DIRECTION_INJECTION,
            "nominated_volume_dth": 50000,
            "expected_contract_version": expected_contract_version,
        },
        overrides,
    )


def submit_nomination_payload(nominated_volume_dth: Optional[int] = None) -> Payload:
    """Submission may optionally carry a revised, lower volume."""
    if nominated_volume_dth is None:
        return {}
    return {"nominated_volume_dth": nominated_volume_dth}


# ─── Gas movement tickets (PRD §3.6) ───────────────────────────────────────

def ticket_payload(nomination_id: str, well_id: str, actual_volume_dth: int) -> Payload:
    return {
        "nomination_id": nomination_id,
        "well_id": well_id,
        "actual_volume_dth": actual_volume_dth,
    }


def ticket_confirm_payload(expected_storage_field_version: int) -> Payload:
    return {"expected_storage_field_version": expected_storage_field_version}


def ticket_reversal_payload(reversal_reason: str = "Metering error found on the chart") -> Payload:
    return {"reversal_reason": reversal_reason}


# ─── Emergency events (PRD §3.8) ───────────────────────────────────────────

def emergency_event_payload(storage_field_id: str, **overrides: Any) -> Payload:
    """`detected_at` is an instant."""
    return _merge(
        {
            "storage_field_id": storage_field_id,
            "event_type": EVENT_TYPE_LEAK,
            "severity": SEVERITY_SERIOUS,
            "detected_at": "2026-08-01T00:00:00Z",
        },
        overrides,
    )


def advance_payload(
    to_status: str,
    responder_notes: Optional[str] = None,
    evacuation_radius_m: Optional[int] = None,
) -> Payload:
    payload: Payload = {"to_status": to_status}
    if responder_notes is not None:
        payload["responder_notes"] = responder_notes
    if evacuation_radius_m is not None:
        payload["evacuation_radius_m"] = evacuation_radius_m
    return payload


# ─── Regulatory reports (PRD §3.9) ─────────────────────────────────────────

def regulatory_report_payload(
    storage_field_id: str, measured_inventory_dth: float, **overrides: Any
) -> Payload:
    """`measured_inventory_dth` is a 3-decimal volume as a JSON number."""
    return _merge(
        {
            "storage_field_id": storage_field_id,
            "report_type": REPORT_TYPE_INVENTORY,
            "period_start_date": "2026-08-01",
            "period_end_date": "2026-08-31",
            "measured_inventory_dth": measured_inventory_dth,
        },
        overrides,
    )


def agency_response_payload(
    agency_outcome: str, agency_response_note: Optional[str] = None
) -> Payload:
    payload: Payload = {"agency_outcome": agency_outcome}
    if agency_response_note is not None:
        payload["agency_response_note"] = agency_response_note
    return payload
