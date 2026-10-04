"""Payload factories — one per creatable resource, input fields only.

Entities materialized by cascades (Rickhouse, WarehouseSlot, SlotOccupancy)
have no creation endpoint and therefore no factory.
"""
from .constants import TEST_DEFAULTS
from .types import AssessmentKind


def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


def create_expansion_project_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["PROJECT_NAME"],
        "region_code": TEST_DEFAULTS["REGION_CODE"],
        "floors": TEST_DEFAULTS["FLOORS"],
        "rows_per_floor": TEST_DEFAULTS["ROWS_PER_FLOOR"],
        "positions_per_row": TEST_DEFAULTS["POSITIONS_PER_ROW"],
        "construction_lag_months": TEST_DEFAULTS["CONSTRUCTION_LAG_MONTHS"],
        "planned_annual_distillation_liters": TEST_DEFAULTS["PLANNED_ANNUAL_DISTILLATION_LITERS"],
    }
    payload.update(overrides)
    return payload


def create_barrel_payload(slot_id: str, **overrides) -> dict:
    payload = {
        "slot_id": slot_id,
        "wood_origin": TEST_DEFAULTS["WOOD_ORIGIN"],
        "seasoning_months": TEST_DEFAULTS["SEASONING_MONTHS"],
        "char_level": TEST_DEFAULTS["CHAR_LEVEL"],
        "spirit_type": TEST_DEFAULTS["SPIRIT_TYPE"],
        "fill_proof": TEST_DEFAULTS["FILL_PROOF"],
        "fill_volume_liters": TEST_DEFAULTS["FILL_VOLUME_LITERS"],
        "min_maturation_months": TEST_DEFAULTS["MIN_MATURATION_MONTHS"],
    }
    payload.update(overrides)
    return payload


def create_assessment_payload(kind: str, **overrides) -> dict:
    """Assessment payload with kind-conditional inputs (PRD §3.3):
    EVAPORATION_READING requires measured_volume_liters; QUALITY_SAMPLE
    requires sample_draw_liters and may carry quality_score."""
    payload: dict = {"kind": kind}
    if kind == AssessmentKind.EVAPORATION_READING.value:
        payload["measured_volume_liters"] = overrides.pop(
            "measured_volume_liters", TEST_DEFAULTS["FILL_VOLUME_LITERS"]
        )
    elif kind == AssessmentKind.QUALITY_SAMPLE.value:
        payload["sample_draw_liters"] = overrides.pop(
            "sample_draw_liters", TEST_DEFAULTS["SAMPLE_DRAW_LITERS"]
        )
    payload.update(overrides)
    return payload


def rotate_barrel_payload(to_slot_id: str, expected_barrel_version: int, **overrides) -> dict:
    payload = {
        "to_slot_id": to_slot_id,
        "expected_barrel_version": expected_barrel_version,
    }
    payload.update(overrides)
    return payload


def create_label_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["LABEL_NAME"],
        "age_statement_years": TEST_DEFAULTS["AGE_STATEMENT_YEARS"],
        "spirit_type": TEST_DEFAULTS["SPIRIT_TYPE"],
    }
    payload.update(overrides)
    return payload


def create_blend_batch_payload(label_id: str, scheduled_bottling_date: str, **overrides) -> dict:
    payload = {
        "label_id": label_id,
        "scheduled_bottling_date": scheduled_bottling_date,
    }
    payload.update(overrides)
    return payload


def add_blend_component_payload(
    barrel_id: str, drawn_volume_liters: float, expected_blend_batch_version: int, **overrides
) -> dict:
    payload = {
        "barrel_id": barrel_id,
        "drawn_volume_liters": drawn_volume_liters,
        "expected_blend_batch_version": expected_blend_batch_version,
    }
    payload.update(overrides)
    return payload


def create_program_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["PROGRAM_NAME"],
        "spirit_type": TEST_DEFAULTS["SPIRIT_TYPE"],
        "min_quality_score": TEST_DEFAULTS["MIN_QUALITY_SCORE"],
        "required_barrel_count": TEST_DEFAULTS["REQUIRED_BARREL_COUNT"],
        "reservation_window_days": TEST_DEFAULTS["RESERVATION_WINDOW_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_reservation_payload(barrel_id: str, expected_program_version: int, **overrides) -> dict:
    payload = {
        "barrel_id": barrel_id,
        "expected_program_version": expected_program_version,
    }
    payload.update(overrides)
    return payload


def create_bonded_report_payload(period_start: str, period_end: str, **overrides) -> dict:
    payload = {
        "period_start": period_start,
        "period_end": period_end,
    }
    payload.update(overrides)
    return payload
