"""Payload factories — one per entity, input fields only."""
from typing import List, Optional

from .constants import (
    FULL_MAINTENANCE_REQUIRED_TASK_CODES,
    OIL_AND_GREASE_REQUIRED_TASK_CODES,
    TEST_DEFAULTS,
)


def create_contract_payload(**overrides) -> dict:
    """Body for POST /elevator-program/contracts."""
    payload = {
        "building_name": "Harborview Tower",
        "building_address": "1 Harbor St",
        "jurisdiction_code": TEST_DEFAULTS["JURISDICTION_CODE"],
        "fire_district_code": TEST_DEFAULTS["FIRE_DISTRICT_CODE"],
        "building_manager_user_id": "bm-1",
        "contractor_user_id": "sc-1",
        "scope_type": "FULL_MAINTENANCE",
        "penalty_schedule": "SCHEDULE_A",
        "monthly_base_fee_cents": TEST_DEFAULTS["MONTHLY_BASE_FEE_CENTS"],
        "callback_response_minutes": TEST_DEFAULTS["CALLBACK_RESPONSE_MINUTES"],
        "entrapment_response_minutes": TEST_DEFAULTS["ENTRAPMENT_RESPONSE_MINUTES"],
        "term_start_date": TEST_DEFAULTS["TERM_START_DATE"],
        "term_end_date": TEST_DEFAULTS["TERM_END_DATE"],
    }
    payload.update(overrides)
    return payload


def create_car_payload(contract_id: str, **overrides) -> dict:
    """Body for POST /elevator-program/cars."""
    payload = {
        "contract_id": contract_id,
        "car_code": "CAR-01",
        "car_type": "TRACTION",
        "capacity_lbs": TEST_DEFAULTS["CAPACITY_LBS"],
    }
    payload.update(overrides)
    return payload


def create_visit_payload(car_id: str, **overrides) -> dict:
    """Body for POST /elevator-program/visits."""
    payload = {
        "car_id": car_id,
        "period_month": "2026-08",
        "scheduled_date": "2026-08-15",
    }
    payload.update(overrides)
    return payload


def task_items(codes: List[str], completed: bool = True, note: str = "ok") -> List[dict]:
    """Build a task_items array from a list of task codes."""
    return [
        {"task_code": code, "completed": completed, "note": note} for code in codes
    ]


def full_maintenance_task_items(note: str = "ok") -> List[dict]:
    """All seven task codes a FULL_MAINTENANCE contract requires, completed."""
    return task_items(FULL_MAINTENANCE_REQUIRED_TASK_CODES, True, note)


def oil_and_grease_task_items(note: str = "ok") -> List[dict]:
    """All three task codes an OIL_AND_GREASE contract requires, completed."""
    return task_items(OIL_AND_GREASE_REQUIRED_TASK_CODES, True, note)


def create_callback_payload(car_id: str, **overrides) -> dict:
    """Body for POST /elevator-program/callbacks."""
    payload = {
        "car_id": car_id,
        "callback_type": "MALFUNCTION",
        "out_of_service": True,
    }
    payload.update(overrides)
    return payload


def create_inspection_payload(car_id: str, **overrides) -> dict:
    """Body for POST /elevator-program/inspections."""
    payload = {
        "car_id": car_id,
        "inspection_type": "PERIODIC",
        "scheduled_date": "2026-08-01",
    }
    payload.update(overrides)
    return payload


def create_project_payload(contract_id: str, **overrides) -> dict:
    """Body for POST /elevator-program/projects."""
    payload = {
        "contract_id": contract_id,
        "title": "Controller modernization",
        "budget_cents": 9_000_000,
        "target_completion_date": "2026-09-25",
    }
    payload.update(overrides)
    return payload


def create_downtime_window_payload(
    car_id: str,
    window_start: str,
    window_end: str,
    window_type: str = "REPAIR",
    project_id: Optional[str] = None,
    **overrides,
) -> dict:
    """Body for POST /elevator-program/downtime-windows."""
    payload = {
        "car_id": car_id,
        "window_type": window_type,
        "window_start": window_start,
        "window_end": window_end,
    }
    if project_id is not None:
        payload["project_id"] = project_id
    payload.update(overrides)
    return payload


def create_part_payload(**overrides) -> dict:
    """Body for POST /elevator-program/parts."""
    payload = {
        "part_number": "DO-4501",
        "description_text": "Door operator relay",
        "part_class": "COMPONENT",
        "unit_price_cents": 45_000,
        "lead_time_days": 20,
    }
    payload.update(overrides)
    return payload


def create_part_order_payload(
    car_id: str, part_id: str, expected_car_version: int, **overrides
) -> dict:
    """Body for POST /elevator-program/part-orders."""
    payload = {
        "car_id": car_id,
        "part_id": part_id,
        "quantity": 1,
        "expected_car_version": expected_car_version,
    }
    payload.update(overrides)
    return payload


def create_penalty_payload(
    contract_id: str, period_month: str, expected_contract_version: int, **overrides
) -> dict:
    """Body for POST /elevator-program/penalties."""
    payload = {
        "contract_id": contract_id,
        "period_month": period_month,
        "expected_contract_version": expected_contract_version,
    }
    payload.update(overrides)
    return payload


def create_renegotiation_payload(contract_id: str, **overrides) -> dict:
    """Body for POST /elevator-program/renegotiations."""
    payload = {
        "contract_id": contract_id,
        "proposed_monthly_fee_cents": 340_000,
        "proposed_callback_response_minutes": 45,
        "proposed_scope_type": "FULL_MAINTENANCE",
    }
    payload.update(overrides)
    return payload


def counter_renegotiation_payload(**overrides) -> dict:
    """Body for POST /elevator-program/renegotiations/{roundId}/counter."""
    payload = {
        "proposed_monthly_fee_cents": 380_000,
        "proposed_callback_response_minutes": 50,
        "proposed_scope_type": "FULL_MAINTENANCE",
    }
    payload.update(overrides)
    return payload
