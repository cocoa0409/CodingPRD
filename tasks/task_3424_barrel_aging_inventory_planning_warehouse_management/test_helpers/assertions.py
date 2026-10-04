"""Entity assertions and domain invariant checkers.

Per-entity assert_*() functions check field presence, types, enum membership
and PRD nullability rules (PRD §2.5). Append-only records (slot occupancies,
barrel assessments) carry only id + created_at and are asserted as such.
"""
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import HEAT_FACTOR_BASE, HEAT_FACTOR_PER_FLOOR, VOLUME_DECIMAL_PLACES
from .types import (
    AssessmentKind,
    BlendBatchState,
    CustodyStatus,
    LabelState,
    MaturationStatus,
    MoveReason,
    OccupancyStatus,
    ProgramState,
    ProjectState,
    ReportState,
    ReservationState,
    RickhousePosture,
    SpiritType,
    WoodOrigin,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an int >= 1"


def _assert_append_only_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not carry updated_at (PRD §2.5)"
    assert "version" not in data, "append-only record must not carry version (PRD §2.5)"


def _assert_optional_iso(data: dict, field: str):
    value = data.get(field)
    assert field in data, f"{field} must be present (null until set, PRD §2.5)"
    if value is not None:
        assert is_iso8601_timestamp(value), f"{field} must be ISO 8601 when set"


def _assert_volume(value, field: str):
    assert isinstance(value, (int, float)) and not isinstance(value, bool), f"{field} must be a number"
    assert value >= 0, f"{field} must be >= 0"
    assert_cost_precision(float(value), VOLUME_DECIMAL_PLACES)


def assert_expansion_project(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert isinstance(data["floors"], int) and data["floors"] >= 1
    assert isinstance(data["rows_per_floor"], int) and data["rows_per_floor"] >= 1
    assert isinstance(data["positions_per_row"], int) and data["positions_per_row"] >= 1
    assert isinstance(data["construction_lag_months"], int) and data["construction_lag_months"] >= 1
    assert isinstance(data["planned_annual_distillation_liters"], int) and data["planned_annual_distillation_liters"] >= 0
    assert data["state"] in [s.value for s in ProjectState]
    _assert_optional_iso(data, "approved_at")
    _assert_optional_iso(data, "commissioned_at")


def assert_rickhouse(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("expansion_project_id", "")), "expansion_project_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert isinstance(data["floors"], int) and data["floors"] >= 1
    assert isinstance(data["rows_per_floor"], int) and data["rows_per_floor"] >= 1
    assert isinstance(data["positions_per_row"], int) and data["positions_per_row"] >= 1
    assert data["total_slots"] == data["floors"] * data["rows_per_floor"] * data["positions_per_row"], (
        "total_slots must equal floors * rows_per_floor * positions_per_row (PRD §3.1)"
    )
    assert isinstance(data["occupied_slots"], int) and data["occupied_slots"] >= 0
    assert data["posture"] in [p.value for p in RickhousePosture]


def assert_warehouse_slot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("rickhouse_id", "")), "rickhouse_id must be a UUID"
    assert isinstance(data["floor_index"], int) and data["floor_index"] >= 1
    assert isinstance(data["row_index"], int) and data["row_index"] >= 1
    assert isinstance(data["position_index"], int) and data["position_index"] >= 1
    assert_heat_factor(data)


def assert_heat_factor(slot: dict):
    """heat_factor == round(1.0 + 0.05 * (floor_index - 1), 2) (PRD §3.1)."""
    expected = round(HEAT_FACTOR_BASE + HEAT_FACTOR_PER_FLOOR * (slot["floor_index"] - 1), 2)
    assert slot["heat_factor"] == expected, (
        f"heat_factor must be {expected} for floor_index {slot['floor_index']}, got {slot['heat_factor']}"
    )


def assert_barrel(data: dict):
    _assert_common_fields(data)
    assert data["wood_origin"] in [w.value for w in WoodOrigin]
    assert isinstance(data["seasoning_months"], int) and data["seasoning_months"] >= 0
    assert isinstance(data["char_level"], int) and 1 <= data["char_level"] <= 4
    assert data["spirit_type"] in [s.value for s in SpiritType]
    assert isinstance(data["fill_proof"], (int, float)) and data["fill_proof"] > 0
    _assert_volume(data["fill_volume_liters"], "fill_volume_liters")
    assert data["fill_volume_liters"] > 0
    assert isinstance(data["min_maturation_months"], int) and data["min_maturation_months"] >= 0
    assert is_iso8601_timestamp(data.get("fill_date", "")), "fill_date must be ISO 8601"
    assert data["maturation_status"] in [s.value for s in MaturationStatus]
    assert data["custody_status"] in [s.value for s in CustodyStatus]
    _assert_volume(data["current_volume_ledger_liters"], "current_volume_ledger_liters")
    _assert_volume(data["current_volume_statutory_liters"], "current_volume_statutory_liters")
    assert "current_slot_id" in data, "current_slot_id must be present (null when no OPEN occupancy)"
    if data["current_slot_id"] is not None:
        assert is_valid_uuid(data["current_slot_id"]), "current_slot_id must be a UUID when set"
    _assert_optional_iso(data, "withdrawn_at")
    assert "withdrawn_volume_liters" in data, "withdrawn_volume_liters must be present (null until withdrawal)"
    if data["withdrawn_volume_liters"] is not None:
        _assert_volume(data["withdrawn_volume_liters"], "withdrawn_volume_liters")


def assert_slot_occupancy(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data.get("barrel_id", "")), "barrel_id must be a UUID"
    assert is_valid_uuid(data.get("slot_id", "")), "slot_id must be a UUID"
    assert data["move_reason"] in [m.value for m in MoveReason]
    assert is_iso8601_timestamp(data.get("start_at", "")), "start_at must be ISO 8601"
    _assert_optional_iso(data, "end_at")
    assert data["status"] in [s.value for s in OccupancyStatus]
    # null end_at is exactly what makes an occupancy OPEN (PRD §3.2)
    if data["status"] == OccupancyStatus.OPEN.value:
        assert data["end_at"] is None, "OPEN occupancy must have null end_at"
    else:
        assert data["end_at"] is not None, "CLOSED occupancy must have end_at set"


def assert_barrel_assessment(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data.get("barrel_id", "")), "barrel_id must be a UUID"
    assert data["kind"] in [k.value for k in AssessmentKind]
    assert "measured_volume_liters" in data
    assert "sample_draw_liters" in data
    assert "quality_score" in data, "quality_score must be present (null when omitted, PRD §2.5)"
    if data["measured_volume_liters"] is not None:
        _assert_volume(data["measured_volume_liters"], "measured_volume_liters")
    if data["sample_draw_liters"] is not None:
        assert data["sample_draw_liters"] > 0, "sample_draw_liters must be > 0"
    if data["quality_score"] is not None:
        assert isinstance(data["quality_score"], int) and 0 <= data["quality_score"] <= 100
    assert is_iso8601_timestamp(data.get("assessed_at", "")), "assessed_at must be ISO 8601"


def assert_label(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["age_statement_years"], int) and data["age_statement_years"] >= 0
    assert data["spirit_type"] in [s.value for s in SpiritType]
    assert data["state"] in [s.value for s in LabelState]


def assert_blend_batch(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("label_id", "")), "label_id must be a UUID"
    assert is_iso8601_timestamp(data.get("scheduled_bottling_date", "")), "scheduled_bottling_date must be ISO 8601"
    assert data["state"] in [s.value for s in BlendBatchState]
    _assert_optional_iso(data, "validated_at")
    _assert_optional_iso(data, "committed_at")
    assert "final_blend_volume_liters" in data, "final_blend_volume_liters must be present (null until commit)"
    if data["final_blend_volume_liters"] is not None:
        _assert_volume(data["final_blend_volume_liters"], "final_blend_volume_liters")


def assert_blend_component(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("blend_batch_id", "")), "blend_batch_id must be a UUID"
    assert is_valid_uuid(data.get("barrel_id", "")), "barrel_id must be a UUID"
    assert isinstance(data["drawn_volume_liters"], (int, float)) and data["drawn_volume_liters"] > 0


def assert_private_selection_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["spirit_type"] in [s.value for s in SpiritType]
    assert isinstance(data["min_quality_score"], int) and 0 <= data["min_quality_score"] <= 100
    assert isinstance(data["required_barrel_count"], int) and data["required_barrel_count"] >= 1
    assert isinstance(data["reservation_window_days"], int) and data["reservation_window_days"] >= 1
    assert data["state"] in [s.value for s in ProgramState]
    assert isinstance(data["available_slots"], int) and data["available_slots"] >= 0


def assert_barrel_reservation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", "")), "program_id must be a UUID"
    assert is_valid_uuid(data.get("barrel_id", "")), "barrel_id must be a UUID"
    assert data["state"] in [s.value for s in ReservationState]
    assert is_iso8601_timestamp(data.get("expires_at", "")), "expires_at must be ISO 8601"


def assert_bonded_period_report(data: dict):
    _assert_common_fields(data)
    assert is_iso8601_timestamp(data.get("period_start", "")), "period_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("period_end", "")), "period_end must be ISO 8601"
    assert data["period_start"] < data["period_end"], "period_end must be strictly after period_start"
    for field in (
        "opening_inventory_liters",
        "period_fills_liters",
        "period_withdrawals_liters",
        "loss_actual_liters",
        "loss_statutory_liters",
        "reported_loss_liters",
        "closing_inventory_liters",
    ):
        assert field in data, f"{field} must be present (null until reconciled)"
        if data[field] is not None:
            _assert_volume(data[field], field)
    assert data["state"] in [s.value for s in ReportState]
    for field in ("prepared_by_user_id", "filed_by_user_id", "decided_by_user_id"):
        assert field in data, f"{field} must be present (null until recorded)"
        if data[field] is not None:
            assert isinstance(data[field], str) and data[field]


def assert_barrel_invariants(data: dict):
    """Invariants that must hold on any barrel read (PRD §3.2–§3.4)."""
    assert_barrel(data)
    # The ledger only ever resets downward, subtracts, or restores a prior
    # subtraction (PRD §3.3), so it can never exceed the fill volume.
    assert data["current_volume_ledger_liters"] <= data["fill_volume_liters"], (
        "ledger volume can never exceed fill_volume_liters"
    )
    if data["custody_status"] == CustodyStatus.WITHDRAWN.value:
        assert data["maturation_status"] == MaturationStatus.DUMPED.value, (
            "withdrawal join gate: WITHDRAWN implies DUMPED (PRD §3.4)"
        )
        assert data["withdrawn_at"] is not None
        assert data["withdrawn_volume_liters"] is not None
    if data["maturation_status"] == MaturationStatus.DUMPED.value:
        # dump closes any OPEN occupancy
        assert data["current_slot_id"] is None, "DUMPED barrel must have null current_slot_id"
