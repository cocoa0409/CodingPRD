"""Shape and invariant assertions.

The entity assertions check the audit quartet the PRD requires on every row
except a ledger entry, plus the enumerated fields whose sets the PRD fixes.
The invariant helpers express the cross-entity arithmetic the PRD states as
conservation rules — ledger sums, market census, plan roll-ups.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .api_client import canonical_instant
from .types import (
    AllocationStatus,
    ConditionStatus,
    ConsignmentStatus,
    DamageStatus,
    EntryType,
    FleetStatus,
    OrderStatus,
    PlanStatus,
    PolicyStatus,
    Posture,
    SourceEntityType,
    TaskStatus,
)

# --------------------------------------------------------------------------
# List envelopes
# --------------------------------------------------------------------------


def list_page(response) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Rows plus the pagination block of a list response."""
    return validate_paginated(response)


def list_rows(response) -> List[Dict[str, Any]]:
    """Just the rows of a list response whose window is not under test."""
    rows, _meta = validate_paginated(response)
    return rows


def validate_unpaginated(response, expected_status: int = 200) -> List[Dict[str, Any]]:
    """A list read whose window metadata is not the subject of the test.

    Some reads are exercised only for their row content; this helper checks
    the envelope and the array payload without asserting on the window keys.
    """
    data = validate_success(response, expected_status)
    assert isinstance(data, list), f"expected an array payload, got {type(data)!r}"
    return data


def total_count(response) -> int:
    _rows, meta = validate_paginated(response)
    return meta["total_count"]


# --------------------------------------------------------------------------
# Common audit fields
# --------------------------------------------------------------------------


def assert_common_fields(row: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """id, created_at, updated_at and version, per PRD section 2.5."""
    assert is_valid_uuid(row["id"]), f"id is not a UUID: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
    assert is_iso8601_timestamp(row["updated_at"]), row["updated_at"]
    assert isinstance(row["version"], int) and not isinstance(row["version"], bool)
    assert row["version"] >= 1, f"version must start at 1, got {row['version']}"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"expected version {expected_version}, got {row['version']}"
        )


def assert_three_digit_millis(value: str) -> None:
    """An instant carries exactly three fractional digits, per section 2.5."""
    assert isinstance(value, str), value
    assert "." in value, f"instant is missing fractional digits: {value!r}"
    fraction = value.split(".", 1)[1].rstrip("Z")
    assert len(fraction) == 3, f"expected three fractional digits, got {value!r}"


def assert_instant_equals(actual: Optional[str], expected: Optional[str]) -> None:
    """Compare instants after normalising sub-second width on both sides."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"expected instant {expected!r}, got {actual!r}"
    )


def assert_version_bump(before: Dict[str, Any], after: Dict[str, Any], steps: int = 1) -> None:
    assert after["version"] == before["version"] + steps, (
        f"expected version {before['version'] + steps}, got {after['version']}"
    )


def assert_no_version_bump(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    assert after["version"] == before["version"], (
        f"version moved from {before['version']} to {after['version']} "
        "on a request that should have changed nothing"
    )


def assert_nulls(row: Dict[str, Any], fields: Sequence[str]) -> None:
    for field in fields:
        assert row[field] is None, f"expected {field} to be null, got {row[field]!r}"


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------


def assert_market(row: Dict[str, Any], expected: Optional[Dict[str, Any]] = None) -> None:
    assert_common_fields(row)
    assert row["status"] in ("ACTIVE", "SUSPENDED"), row["status"]
    assert row["region"] in ("EAST", "CENTRAL", "WEST"), row["region"]
    assert isinstance(row["in_service_unit_count"], int)
    for field in (
        "transport_hub_distance_km",
        "transfer_cost_per_km_cents",
        "storage_cost_per_day_cents",
        "prep_capacity_per_day",
        "registration_lead_days",
    ):
        assert isinstance(row[field], int), f"{field} must be an integer: {row[field]!r}"
    if expected:
        for key, value in expected.items():
            assert row[key] == value, f"market {key}: expected {value!r}, got {row[key]!r}"


def assert_vehicle_segment(row: Dict[str, Any], expected: Optional[Dict[str, Any]] = None) -> None:
    assert_common_fields(row)
    assert isinstance(row["target_utilization_pct"], (int, float)) and not isinstance(
        row["target_utilization_pct"], bool
    ), "target_utilization_pct must be a JSON number"
    assert row["mileage_band_hard_limit_km"] > row["mileage_band_soft_limit_km"]
    if expected:
        for key, value in expected.items():
            assert row[key] == value, f"segment {key}: expected {value!r}, got {row[key]!r}"


def assert_manufacturer_program(
    row: Dict[str, Any], expected: Optional[Dict[str, Any]] = None
) -> None:
    assert_common_fields(row)
    assert row["program_type"] in ("PROGRAM", "RISK"), row["program_type"]
    assert row["status"] in ("ACTIVE", "CLOSED"), row["status"]
    if row["program_type"] == "RISK":
        assert row["repurchase_guarantee_pct"] == 0, (
            "a RISK program must carry a zero repurchase guarantee"
        )
    if expected:
        for key, value in expected.items():
            assert row[key] == value, f"program {key}: expected {value!r}, got {row[key]!r}"


def assert_remarketing_channel(
    row: Dict[str, Any], expected: Optional[Dict[str, Any]] = None
) -> None:
    assert_common_fields(row)
    assert row["code"] in ("AUCTION", "RETAIL_LOT", "DEALER_DIRECT", "PROGRAM_REPURCHASE")
    assert row["status"] in ("ACTIVE", "SUSPENDED"), row["status"]
    assert isinstance(row["recondition_required"], bool)
    if expected:
        for key, value in expected.items():
            assert row[key] == value, f"channel {key}: expected {value!r}, got {row[key]!r}"


def assert_depreciation_policy(
    row: Dict[str, Any], expected: Optional[Dict[str, Any]] = None
) -> None:
    assert_common_fields(row)
    assert row["status"] in (PolicyStatus.DRAFT, PolicyStatus.ACTIVE, PolicyStatus.SUPERSEDED)
    assert isinstance(row["created_by_user_id"], str) and row["created_by_user_id"]
    if row["status"] == PolicyStatus.DRAFT:
        assert row["activated_by_user_id"] is None
    if expected:
        for key, value in expected.items():
            assert row[key] == value, f"policy {key}: expected {value!r}, got {row[key]!r}"


def assert_fleet_plan(row: Dict[str, Any], expected: Optional[Dict[str, Any]] = None) -> None:
    assert_common_fields(row)
    assert row["status"] in (PlanStatus.DRAFT, PlanStatus.LOCKED, PlanStatus.CLOSED)
    assert row["posture"] in (Posture.OPEN, Posture.RESTRICTED, Posture.FROZEN)
    assert row["season"] in ("PEAK", "SHOULDER", "OFF_PEAK")
    for field in ("planned_unit_count", "allocated_unit_count", "in_fleeted_unit_count"):
        assert isinstance(row[field], int), f"{field} must be an integer"
    if expected:
        for key, value in expected.items():
            assert row[key] == value, f"plan {key}: expected {value!r}, got {row[key]!r}"


def assert_purchase_allocation(
    row: Dict[str, Any], expected: Optional[Dict[str, Any]] = None
) -> None:
    assert_common_fields(row)
    assert row["status"] in (
        AllocationStatus.ORDERED,
        AllocationStatus.PARTIALLY_INFLEETED,
        AllocationStatus.INFLEETED,
        AllocationStatus.CANCELLED,
    )
    assert row["created_vehicle_count"] <= row["unit_count"], (
        "created_vehicle_count is capped at the allocation's unit_count"
    )
    if expected:
        for key, value in expected.items():
            assert row[key] == value, f"allocation {key}: expected {value!r}, got {row[key]!r}"


def assert_vehicle(row: Dict[str, Any], expected: Optional[Dict[str, Any]] = None) -> None:
    assert_common_fields(row)
    assert row["fleet_status"] in (
        FleetStatus.ON_ORDER,
        FleetStatus.IN_FLEETING,
        FleetStatus.IN_SERVICE,
        FleetStatus.IN_TRANSIT,
        FleetStatus.HELD_FOR_SALE,
        FleetStatus.SOLD,
        FleetStatus.TOTAL_LOSS,
    ), row["fleet_status"]
    assert row["condition_status"] in (
        ConditionStatus.SOUND,
        ConditionStatus.DAMAGE_REPORTED,
        ConditionStatus.RECONDITIONING,
        ConditionStatus.RECONDITIONED,
        ConditionStatus.TOTALED,
    ), row["condition_status"]
    assert len(row["vin"]) == 16, f"a VIN is exactly sixteen characters: {row['vin']!r}"
    for field in (
        "odometer_km",
        "rented_days_total",
        "available_days_total",
        "revenue_to_date_cents",
        "total_recondition_cents",
        "capitalized_cost_cents",
    ):
        assert isinstance(row[field], int), f"{field} must be an integer: {row[field]!r}"
    if expected:
        for key, value in expected.items():
            assert row[key] == value, f"vehicle {key}: expected {value!r}, got {row[key]!r}"


def assert_in_fleeting_task(
    row: Dict[str, Any], expected: Optional[Dict[str, Any]] = None
) -> None:
    assert_common_fields(row)
    assert row["status"] in (TaskStatus.PENDING, TaskStatus.COMPLETED, TaskStatus.WAIVED)
    assert row["task_type"] in ("REGISTRATION", "LICENSING", "PREPARATION")
    if row["task_type"] != "PREPARATION":
        assert row["bay_code"] is None
        assert row["window_start"] is None
        assert row["window_end"] is None
    if expected:
        for key, value in expected.items():
            assert row[key] == value, f"task {key}: expected {value!r}, got {row[key]!r}"


def assert_redistribution_order(
    row: Dict[str, Any], expected: Optional[Dict[str, Any]] = None
) -> None:
    assert_common_fields(row)
    assert row["status"] in (
        OrderStatus.DRAFT,
        OrderStatus.PROPOSED,
        OrderStatus.REJECTED,
        OrderStatus.AUTHORIZED,
        OrderStatus.IN_TRANSIT,
        OrderStatus.RECEIVED,
        OrderStatus.CANCELLED,
    ), row["status"]
    assert isinstance(row["revision_count"], int) and row["revision_count"] >= 0
    assert row["revision_count"] <= 3, "revision_count is bounded at three"
    assert isinstance(row["estimated_transport_cost_cents"], int)
    if expected:
        for key, value in expected.items():
            assert row[key] == value, f"order {key}: expected {value!r}, got {row[key]!r}"


def assert_damage_event(row: Dict[str, Any], expected: Optional[Dict[str, Any]] = None) -> None:
    assert_common_fields(row)
    assert row["status"] in (
        DamageStatus.REPORTED,
        DamageStatus.RECOVERY_PENDING,
        DamageStatus.RECOVERED,
        DamageStatus.WRITTEN_OFF,
        DamageStatus.TOTAL_LOSS_DECLARED,
    ), row["status"]
    assert row["damage_type"] in ("COLLISION", "HAIL", "VANDALISM", "MECHANICAL")
    assert isinstance(row["total_loss_required"], bool)
    assert isinstance(row["net_book_value_at_report_cents"], int)
    if expected:
        for key, value in expected.items():
            assert row[key] == value, f"damage event {key}: expected {value!r}, got {row[key]!r}"


def assert_consignment(row: Dict[str, Any], expected: Optional[Dict[str, Any]] = None) -> None:
    assert_common_fields(row)
    assert row["status"] in (
        ConsignmentStatus.DRAFT,
        ConsignmentStatus.RECONDITION_PENDING,
        ConsignmentStatus.LISTED,
        ConsignmentStatus.SOLD_PENDING_SETTLEMENT,
        ConsignmentStatus.SETTLED,
        ConsignmentStatus.WITHDRAWN,
    ), row["status"]
    assert isinstance(row["floor_price_cents"], int)
    assert isinstance(row["created_by_user_id"], str) and row["created_by_user_id"]
    if expected:
        for key, value in expected.items():
            assert row[key] == value, f"consignment {key}: expected {value!r}, got {row[key]!r}"


def assert_ledger_entry(row: Dict[str, Any], expected: Optional[Dict[str, Any]] = None) -> None:
    """A ledger row carries id and created_at and nothing else from the quartet."""
    assert is_valid_uuid(row["id"]), row["id"]
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
    assert "version" not in row, "a ledger entry must not expose a version field"
    assert "updated_at" not in row, "a ledger entry must not expose an updated_at field"
    assert is_iso8601_timestamp(row["posted_at"]), row["posted_at"]
    assert isinstance(row["amount_cents"], int), row["amount_cents"]
    assert row["entry_type"] in (
        EntryType.CAPITALIZATION,
        EntryType.PREP_COST,
        EntryType.TRANSPORT_COST,
        EntryType.RECONDITION_COST,
        EntryType.RECONDITION_REVERSAL,
        EntryType.CHANNEL_FEE,
        EntryType.DAMAGE_RECOVERY,
        EntryType.SALVAGE_PROCEEDS,
        EntryType.DISPOSAL_PROCEEDS,
        EntryType.DISPOSAL_GAIN_LOSS,
    ), row["entry_type"]
    assert row["source_entity_type"] in (
        SourceEntityType.VEHICLE,
        SourceEntityType.IN_FLEETING_TASK,
        SourceEntityType.REDISTRIBUTION_ORDER,
        SourceEntityType.DAMAGE_EVENT,
        SourceEntityType.CONSIGNMENT,
    ), row["source_entity_type"]
    assert isinstance(row["memo"], str)
    if expected:
        for key, value in expected.items():
            assert row[key] == value, f"ledger {key}: expected {value!r}, got {row[key]!r}"


# --------------------------------------------------------------------------
# Computed reads
# --------------------------------------------------------------------------

VALUATION_FIELDS = (
    "holding_days",
    "holding_months",
    "odometer_km",
    "capitalized_cost_cents",
    "policy_net_book_value_cents",
    "program_guaranteed_value_cents",
    "net_book_value_cents",
    "accumulated_depreciation_cents",
    "applied_variant",
    "mileage_band",
    "open_damage_cents",
)


def assert_valuation(data: Dict[str, Any], expected: Optional[Dict[str, Any]] = None) -> None:
    """Both variants are always reported alongside the inputs used."""
    for field in VALUATION_FIELDS:
        assert field in data, f"valuation is missing {field}"
    assert data["applied_variant"] in ("POLICY_SCHEDULE", "PROGRAM_GUARANTEE")
    assert data["mileage_band"] in ("WITHIN_SOFT", "OVER_SOFT", "OVER_HARD")
    if data["applied_variant"] == "PROGRAM_GUARANTEE":
        assert data["net_book_value_cents"] == data["program_guaranteed_value_cents"]
    else:
        assert data["net_book_value_cents"] == data["policy_net_book_value_cents"]
    assert (
        data["accumulated_depreciation_cents"]
        == data["capitalized_cost_cents"] - data["net_book_value_cents"]
    ), "accumulated depreciation follows the applied variant"
    if expected:
        for key, value in expected.items():
            assert data[key] == value, f"valuation {key}: expected {value!r}, got {data[key]!r}"


PERFORMANCE_FIELDS = (
    "planned_unit_count",
    "allocated_unit_count",
    "in_fleeted_unit_count",
    "posture",
    "season_days",
    "utilization_pct_planned",
    "revenue_per_unit_cents_planned",
    "utilization_pct_actual",
    "revenue_per_unit_cents_actual",
    "rpu_variance_cents",
)


def assert_plan_performance(
    data: Dict[str, Any], expected: Optional[Dict[str, Any]] = None
) -> None:
    for field in PERFORMANCE_FIELDS:
        assert field in data, f"performance report is missing {field}"
    assert data["season_days"] in (92, 122, 151), data["season_days"]
    if expected:
        for key, value in expected.items():
            assert data[key] == value, f"performance {key}: expected {value!r}, got {data[key]!r}"


RECOMMENDATION_FIELDS = (
    "recommended_channel_id",
    "recommended_channel_code",
    "projected_net_proceeds_cents",
    "eligible_channel_count",
    "ranked_channel_codes",
    "excluded_channel_codes",
)


def assert_channel_recommendation(
    data: Dict[str, Any], expected: Optional[Dict[str, Any]] = None
) -> None:
    for field in RECOMMENDATION_FIELDS:
        assert field in data, f"recommendation is missing {field}"
    assert isinstance(data["ranked_channel_codes"], list)
    assert isinstance(data["excluded_channel_codes"], list)
    assert data["eligible_channel_count"] == len(data["ranked_channel_codes"]), (
        "the eligible count is the length of the ranking"
    )
    if data["ranked_channel_codes"]:
        assert data["recommended_channel_code"] == data["ranked_channel_codes"][0], (
            "the recommendation is the head of the ranking"
        )
    if expected:
        for key, value in expected.items():
            assert data[key] == value, (
                f"recommendation {key}: expected {value!r}, got {data[key]!r}"
            )


# --------------------------------------------------------------------------
# Ledger invariants
# --------------------------------------------------------------------------


def entries_of_type(rows: Sequence[Dict[str, Any]], entry_type: str) -> List[Dict[str, Any]]:
    return [row for row in rows if row["entry_type"] == entry_type]


def sum_amount(rows: Sequence[Dict[str, Any]]) -> int:
    return sum(row["amount_cents"] for row in rows)


def assert_single_entry(
    rows: Sequence[Dict[str, Any]], entry_type: str, amount_cents: int
) -> Dict[str, Any]:
    """Exactly one row of that type, carrying exactly that signed amount."""
    matches = entries_of_type(rows, entry_type)
    assert len(matches) == 1, (
        f"expected exactly one {entry_type} row, found {len(matches)}"
    )
    assert matches[0]["amount_cents"] == amount_cents, (
        f"{entry_type}: expected {amount_cents}, got {matches[0]['amount_cents']}"
    )
    return matches[0]


def assert_no_entry_of_type(rows: Sequence[Dict[str, Any]], entry_type: str) -> None:
    matches = entries_of_type(rows, entry_type)
    assert not matches, f"expected no {entry_type} row, found {len(matches)}"


def assert_recondition_total(rows: Sequence[Dict[str, Any]], expected: int) -> None:
    """The signed sum of RECONDITION_COST and RECONDITION_REVERSAL rows."""
    total = sum_amount(
        entries_of_type(rows, EntryType.RECONDITION_COST)
        + entries_of_type(rows, EntryType.RECONDITION_REVERSAL)
    )
    assert total == expected, f"expected a reconditioning total of {expected}, got {total}"


def assert_entry_types_in_order(
    rows: Sequence[Dict[str, Any]], expected_types: Sequence[str]
) -> None:
    actual = [row["entry_type"] for row in rows]
    assert actual == list(expected_types), (
        f"expected ledger types {list(expected_types)}, got {actual}"
    )
