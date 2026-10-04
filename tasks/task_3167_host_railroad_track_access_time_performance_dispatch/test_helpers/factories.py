"""Payload factories - one per creatable resource, input fields only."""

from typing import Any, Dict

DEFAULTS = {
    "HOST_NAME": "Great Plains Rail",
    "REPORTING_MARK": "GPR",
    "CORRIDOR_CODE": "GP-1",
    "CORRIDOR_NAME": "River Cities",
    "ANNUAL_COST_CENTS": 10_000_000,
}


def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}


def host_railroad_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": DEFAULTS["HOST_NAME"],
        "reporting_mark": DEFAULTS["REPORTING_MARK"],
    }
    payload.update(overrides)
    return payload


def corridor_payload(host_railroad_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "host_railroad_id": host_railroad_id,
        "code": DEFAULTS["CORRIDOR_CODE"],
        "name": DEFAULTS["CORRIDOR_NAME"],
        "endpoint_a": "CHI",
        "endpoint_b": "KCY",
        "service_type": "STATE_SUPPORTED",
        "annual_cost_cents": DEFAULTS["ANNUAL_COST_CENTS"],
    }
    payload.update(overrides)
    return payload


def track_segment_payload(corridor_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "corridor_id": corridor_id,
        "sequence_no": 1,
        "milepost_start": 0.0,
        "milepost_end": 10.0,
        "state_code": "IL",
        "track_class": "SINGLE",
        "capacity_trains_per_day": 20,
        "pure_run_minutes": 21,
        "dwell_after_minutes": 0,
    }
    payload.update(overrides)
    return payload


def operating_agreement_payload(host_railroad_id: str, corridor_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "host_railroad_id": host_railroad_id,
        "corridor_id": corridor_id,
        "effective_from": "2026-09-01T00:00:00Z",
        "effective_to": "2027-09-01T00:00:00Z",
        "on_time_threshold_minutes": 15,
        "penalty_rate_cents_per_minute": 50,
        "incentive_rate_cents_per_train_mile": 12,
        "otp_target_pct": 0.80,
        "running_time_allowance_pct": 0.25,
    }
    payload.update(overrides)
    return payload


def timetable_payload(corridor_id: str, operating_agreement_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "corridor_id": corridor_id,
        "operating_agreement_id": operating_agreement_id,
        "service_date_start": "2026-09-02",
        "service_date_end": "2026-09-02",
        "trains_per_day": 1,
        "departure_time_of_day": "08:00",
        "headway_minutes": 120,
    }
    payload.update(overrides)
    return payload


def depart_payload(actual_departure_at: str) -> Dict[str, Any]:
    return {"actual_departure_at": actual_departure_at}


def complete_payload(actual_arrival_at: str) -> Dict[str, Any]:
    return {"actual_arrival_at": actual_arrival_at}


def actualize_payload(actual_entry_at: str, actual_exit_at: str) -> Dict[str, Any]:
    return {"actual_entry_at": actual_entry_at, "actual_exit_at": actual_exit_at}


def delay_incident_payload(train_run_id: str, cause_code: str, delay_minutes: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "train_run_id": train_run_id,
        "cause_code": cause_code,
        "delay_minutes": delay_minutes,
    }
    payload.update(overrides)
    return payload


def capital_project_payload(operating_agreement_id: str, track_segment_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "operating_agreement_id": operating_agreement_id,
        "track_segment_id": track_segment_id,
        "project_type": "SIDING",
        "funded_amount_cents": 50_000_000,
        "added_frequency_capacity": 4,
    }
    payload.update(overrides)
    return payload


def maintenance_window_payload(track_segment_id: str, window_start_at: str, window_end_at: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "track_segment_id": track_segment_id,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
        "equipment_unit_id": "EQ-1",
        "clearance_buffer_minutes": 15,
    }
    payload.update(overrides)
    return payload


def service_disruption_payload(corridor_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "corridor_id": corridor_id,
        "disruption_type": "TRACK_FAILURE",
        "started_at": "2026-09-02T08:00:00Z",
        "reaccommodation_policy": "BUS_BRIDGE",
    }
    payload.update(overrides)
    return payload


def funding_agreement_payload(corridor_id: str, state_code: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "corridor_id": corridor_id,
        "state_code": state_code,
        "period_start": "2026-09-01",
        "period_end": "2026-09-30",
    }
    payload.update(overrides)
    return payload


def settlement_statement_payload(operating_agreement_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "operating_agreement_id": operating_agreement_id,
        "period_start": "2026-09-01",
        "period_end": "2026-09-30",
    }
    payload.update(overrides)
    return payload
