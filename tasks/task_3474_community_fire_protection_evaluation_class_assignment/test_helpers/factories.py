"""Payload factories — one per creatable resource, input fields only.

Factories never send computed or system fields (``status``, ``version``,
``credited_points`` …); the server owns those. Defaults are chosen to be
valid against the default logical clock (2026-09-01): flow-test dates fall
before it and are fresh against the default data freeze, coverage windows
start after it, and cycle windows open on it.
"""
import itertools
from typing import Any, Dict, List, Optional

from .constants import DEFAULT_CLOCK_DATE
from .test_users import DEFAULT_ANALYST_ID, DEFAULT_REGISTRAR_ID

_name_counter = itertools.count(1)

# Default cycle window: opens on the default clock date, freezes three
# months later (fresh flow-test cutoff is then 2021-12-01).
DEFAULT_OPEN_DATE = DEFAULT_CLOCK_DATE
DEFAULT_FREEZE_DATE = "2026-12-01"

# Default flow test: dated before the default clock, fresh at the default
# freeze; static 80 / residual 60 / measured 1000 normalizes to 1810 gpm.
DEFAULT_TEST_DATE = "2026-08-15"

# Default coverage window: strictly after the default clock date.
DEFAULT_COVERAGE_START = "2027-01-01"
DEFAULT_COVERAGE_END = "2027-06-30"


def _unique_name(prefix: str) -> str:
    return f"{prefix}-{next(_name_counter)}"


def evidence_item(doc_type: str = "REPORT", uri: str = "s3://docs/evidence.pdf") -> Dict[str, str]:
    return {"doc_type": doc_type, "uri": uri}


def community_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": _unique_name("Community"),
        "state_code": "TX",
        "population": 4000,
        "area_sq_miles": 40,
        "rural_area_pct": 20,
        "dept_type": "CAREER",
        "needed_fire_flow_gpm": 1000,
        "storage_capacity_gal": 0,
        "supply_works_capacity_gpm": 500,
        "daily_consumption_gpm": 100,
    }
    payload.update(overrides)
    return payload


def attest_comms_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "operators_on_duty_min": 0,
        "avg_alarm_to_dispatch_seconds": 999,
        "redundant_circuits": False,
        "backup_power": False,
    }
    payload.update(overrides)
    return payload


def evaluation_cycle_payload(community_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "community_id": community_id,
        "field_analyst_id": DEFAULT_ANALYST_ID,
        "scheduled_open_date": DEFAULT_OPEN_DATE,
        "data_freeze_date": DEFAULT_FREEZE_DATE,
    }
    payload.update(overrides)
    return payload


def cycle_transition_payload(target_state: str) -> Dict[str, Any]:
    return {"target_state": target_state}


def score_sheet_create_payload(expected_cycle_version: int) -> Dict[str, Any]:
    return {"expected_cycle_version": expected_cycle_version}


def publish_classification_payload(score_sheet_id: str) -> Dict[str, Any]:
    return {"score_sheet_id": score_sheet_id}


def activate_classification_payload(effective_from: str = DEFAULT_CLOCK_DATE) -> Dict[str, Any]:
    return {"effective_from": effective_from}


def department_data_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "career_on_duty_per_shift": 0,
        "training_hours_per_firefighter_annual": 0,
        "coverage_pct_within_5mi": 0,
    }
    payload.update(overrides)
    return payload


def apparatus_payload(department_id: str, kind: str = "ENGINE", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"department_id": department_id, "kind": kind}
    payload.update(overrides)
    return payload


def apparatus_status_payload(status: str) -> Dict[str, Any]:
    return {"status": status}


def water_system_patch_payload(**overrides: Any) -> Dict[str, Any]:
    return dict(overrides)


def hydrant_payload(system_id: str, location_descriptor: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "system_id": system_id,
        "location_descriptor": location_descriptor or _unique_name("Hydrant"),
    }
    payload.update(overrides)
    return payload


def hydrant_status_payload(status: str) -> Dict[str, Any]:
    return {"status": status}


def flow_test_payload(system_id: str, hydrant_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "system_id": system_id,
        "hydrant_id": hydrant_id,
        "test_date": DEFAULT_TEST_DATE,
        "static_psi": 80,
        "residual_psi": 60,
        "measured_flow_gpm": 1000,
    }
    payload.update(overrides)
    return payload


def flow_test_transition_payload(target_state: str, **corrections: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"target_state": target_state}
    payload.update(corrections)
    return payload


def risk_reduction_credit_payload(cycle_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "cycle_id": cycle_id,
        "program_type": "PUBLIC_EDUCATION",
        "activity_points": 1.0,
        "evidence_note": "program documentation",
    }
    payload.update(overrides)
    return payload


def credit_transition_payload(target_state: str) -> Dict[str, Any]:
    return {"target_state": target_state}


def property_risk_profile_payload(community_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "community_id": community_id,
        "address": _unique_name("Addr") + " St",
        "distance_to_nearest_hydrant_ft": 300,
        "distance_to_nearest_station_road_miles": 1.0,
        "construction_type": "FRAME",
        "insured_value_cents": 100_000_000,
    }
    payload.update(overrides)
    return payload


def premium_quote_payload(property_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "property_id": property_id,
        "coverage_amount_cents": 1_000_000,
        "base_rate_bp": 300,
        "term_months": 6,
        "coverage_start_date": DEFAULT_COVERAGE_START,
        "coverage_end_date": DEFAULT_COVERAGE_END,
    }
    payload.update(overrides)
    return payload


def bind_quote_payload(expected_community_version: int) -> Dict[str, Any]:
    return {"expected_community_version": expected_community_version}


def reevaluation_request_payload(community_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "community_id": community_id,
        "justification": "Documented improvements completed",
        "evidence_items": [evidence_item()],
    }
    payload.update(overrides)
    return payload


def request_transition_payload(target_state: str, note: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"target_state": target_state}
    if note is not None:
        payload["note"] = note
    return payload


def approve_reevaluation_payload(
    expected_community_version: int,
    field_analyst_id: str = DEFAULT_ANALYST_ID,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_community_version": expected_community_version,
        "field_analyst_id": field_analyst_id,
    }
    if note is not None:
        payload["note"] = note
    return payload


def appeal_payload(classification_id: str, community_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "classification_id": classification_id,
        "community_id": community_id,
        "grounds": "DATA_ERROR",
        "evidence_items": [evidence_item()],
    }
    payload.update(overrides)
    return payload


def appeal_transition_payload(
    target_state: str,
    adjudication_note: Optional[str] = None,
    new_score_sheet_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"target_state": target_state}
    if adjudication_note is not None:
        payload["adjudication_note"] = adjudication_note
    if new_score_sheet_id is not None:
        payload["new_score_sheet_id"] = new_score_sheet_id
    return payload


def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}
