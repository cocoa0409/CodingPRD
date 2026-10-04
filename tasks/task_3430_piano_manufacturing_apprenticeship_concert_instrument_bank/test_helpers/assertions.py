"""Per-entity response assertions and domain invariant checkers.

Field names are PRD-exact. Common fields follow PRD section 2.5: every primary
resource carries id, created_at, updated_at, version; the build stage log
carries only id and created_at.
"""
import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ArtistStatus,
    ArtistTier,
    BuildModel,
    BuildOrderStatus,
    BuildStage,
    ConditionGrade,
    EndorsementStatus,
    InstrumentStatus,
    LoanStatus,
    OperationType,
    RestorationOrigin,
    RestorationStatus,
    WoodBatchStatus,
    WoodSpecies,
)

SERIAL_NUMBER_PATTERN = re.compile(r"^PIN-\d{8}$")  # PRD section 3.2: PIN-########


def _enum_values(enum_cls):
    return [member.value for member in enum_cls]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def _assert_nullable_iso(data: dict, field: str):
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), f"{field} must be ISO 8601 or null"


def assert_wood_batch(data: dict):
    _assert_common_fields(data)
    assert data["species"] in _enum_values(WoodSpecies)
    assert isinstance(data["moisture_content_pct"], (int, float))
    assert data["status"] in _enum_values(WoodBatchStatus)
    assert is_iso8601_timestamp(data["drying_started_at"]), "drying_started_at must be ISO 8601"
    _assert_nullable_iso(data, "conditioned_at")


def assert_build_order(data: dict):
    _assert_common_fields(data)
    assert data["model"] in _enum_values(BuildModel)
    assert data.get("wood_batch_id") is None or is_valid_uuid(data["wood_batch_id"])
    assert data["status"] in _enum_values(BuildOrderStatus)
    _assert_nullable_iso(data, "seasoning_started_at")
    assert isinstance(data.get("commissioned_note", ""), str)
    assert isinstance(data["wip_value_cents"], int)


def assert_build_stage_log(data: dict):
    """Stage logs are append-only: only id + created_at of the common fields."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "stage log must not carry updated_at"
    assert "version" not in data, "stage log must not carry version"
    assert is_valid_uuid(data.get("build_order_id", "")), "build_order_id must be a UUID"
    assert data["to_stage"] in _enum_values(BuildStage)
    assert data["operation_type"] in _enum_values(OperationType)
    assert isinstance(data["hours_applied"], (int, float)) and 0 < data["hours_applied"] <= 500
    assert data["actor_role"] in ["MasterCraftsman", "Apprentice"]
    assert isinstance(data["actor_id"], str) and data["actor_id"]
    assert data.get("supervising_craftsman_id") is None or isinstance(
        data["supervising_craftsman_id"], str
    )
    assert is_iso8601_timestamp(data["logged_at"]), "logged_at must be ISO 8601"


def assert_craftsman(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["specialty"] in _enum_values(OperationType)


def assert_apprentice(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]


def assert_supervision_entry(entry: dict):
    assert entry.get("supervising_craftsman_id") is None or isinstance(
        entry["supervising_craftsman_id"], str
    )
    assert isinstance(entry["hours"], (int, float)) and entry["hours"] > 0
    assert isinstance(entry["specialty_match"], bool)
    assert is_iso8601_timestamp(entry["logged_at"]), "logged_at must be ISO 8601"


def assert_skill_endorsement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("apprentice_id", "")), "apprentice_id must be a UUID"
    assert data["operation_type"] in _enum_values(OperationType)
    assert data["status"] in _enum_values(EndorsementStatus)
    assert isinstance(data["logged_hours"], (int, float)) and data["logged_hours"] >= 0
    assert isinstance(data["effective_hours"], (int, float)) and data["effective_hours"] >= 0
    assert isinstance(data["supervision_log"], list)
    for entry in data["supervision_log"]:
        assert_supervision_entry(entry)
    assert data.get("endorsed_by_craftsman_id") is None or is_valid_uuid(
        data["endorsed_by_craftsman_id"]
    )


def assert_instrument(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("build_order_id", "")), "build_order_id must be a UUID"
    assert data["model"] in _enum_values(BuildModel)
    assert isinstance(data["serial_number"], str) and SERIAL_NUMBER_PATTERN.match(
        data["serial_number"]
    ), f"serial_number must match PIN-########, got {data.get('serial_number')!r}"
    assert data["status"] in _enum_values(InstrumentStatus)
    assert data["condition_grade"] in _enum_values(ConditionGrade)
    assert isinstance(data["certified_authentic"], bool)


def assert_artist(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["tier"] in _enum_values(ArtistTier)
    assert isinstance(data["performance_quota"], int) and data["performance_quota"] > 0
    assert isinstance(data["performances_logged"], int) and data["performances_logged"] >= 0
    assert data["status"] in _enum_values(ArtistStatus)
    assert is_iso8601_timestamp(data["next_review_date"]), "next_review_date must be ISO 8601"
    assert isinstance(data["standing_realized"], int) and data["standing_realized"] >= 0
    assert isinstance(data["standing_forward"], int) and data["standing_forward"] >= 0
    assert (
        data["standing_forward"] >= data["standing_realized"]
    ), "standing_forward is never below standing_realized"


def assert_concert_loan(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("artist_id", "")), "artist_id must be a UUID"
    assert data["desired_model"] in _enum_values(BuildModel)
    assert is_iso8601_timestamp(data["tour_start"]), "tour_start must be ISO 8601"
    assert is_iso8601_timestamp(data["tour_end"]), "tour_end must be ISO 8601"
    assert data.get("instrument_id") is None or is_valid_uuid(data["instrument_id"])
    assert data.get("technician_id") is None or is_valid_uuid(data["technician_id"])
    assert data["status"] in _enum_values(LoanStatus)
    assert data.get("fee_cents") is None or isinstance(data["fee_cents"], int)


def assert_restoration_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("instrument_id", "")), "instrument_id must be a UUID"
    assert is_valid_uuid(data.get("lead_craftsman_id", "")), "lead_craftsman_id must be a UUID"
    assert data["origin"] in _enum_values(RestorationOrigin)
    assert isinstance(data["diagnosis"], str)
    assert data["status"] in _enum_values(RestorationStatus)
    assert isinstance(data["authentic_parts_value_cents"], int)
    assert isinstance(data["total_parts_value_cents"], int)
    assert data["total_parts_value_cents"] >= data["authentic_parts_value_cents"] >= 0
    assert isinstance(data["waiver_accepted"], bool)
    assert data.get("authenticity_pct") is None or isinstance(
        data["authenticity_pct"], (int, float)
    )
    assert data.get("final_authentic_value_cents") is None or isinstance(
        data["final_authentic_value_cents"], int
    )
    assert data.get("final_total_parts_value_cents") is None or isinstance(
        data["final_total_parts_value_cents"], int
    )


def assert_valuation(data: dict):
    """Dual-variant WIP valuation read body (PRD section 3.2)."""
    assert isinstance(data["actual_wip_cents"], int)
    assert isinstance(data["provisional_wip_cents"], int)
    assert isinstance(data["delta_cents"], int)
    assert (
        data["provisional_wip_cents"] >= data["actual_wip_cents"]
    ), "provisional is always at least actual"
    assert data["delta_cents"] == data["provisional_wip_cents"] - data["actual_wip_cents"]


def assert_clock_result(data: dict):
    assert is_iso8601_timestamp(data.get("current_utc", "")), "current_utc must be ISO 8601"
