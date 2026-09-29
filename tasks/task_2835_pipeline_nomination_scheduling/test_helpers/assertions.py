"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

TERMINAL_ROLE_KINDS = ["ORIGIN", "DESTINATION", "BOTH"]
SEGMENT_STATUSES = ["OPERATIONAL", "DERATED", "SHUT"]
PRORATION_POLICIES = ["HISTORY_WEIGHTED", "VOLUME_WEIGHTED"]
SHIPPER_STATUSES = ["ACTIVE", "SUSPENDED"]
RECORD_STATUSES = ["FINAL", "PROVISIONAL"]
TARIFF_STATUSES = ["DRAFT", "EFFECTIVE", "SUPERSEDED"]
CYCLE_STATUSES = [
    "OPEN",
    "CLOSED",
    "PRORATED",
    "SCHEDULED",
    "PUBLISHED",
    "RESEQUENCING",
    "SETTLED",
]
NOMINATION_STATUSES = [
    "SUBMITTED",
    "ACCEPTED",
    "PRORATED",
    "SCHEDULED",
    "COMPLETED",
    "REVISION_REQUESTED",
    "WITHDRAWN",
    "SUPERSEDED",
    "REJECTED",
]
ALLOCATION_CLASSES = ["HISTORICAL", "NEW_SHIPPER"]
REJECTION_REASONS = ["BELOW_TENDER_MINIMUM", "BELOW_TENDER_AFTER_PRORATION"]
MOVEMENT_STATUSES = ["PLANNED", "INJECTED", "DELIVERED", "CANCELLED"]
QUALITY_STATUSES = ["PENDING", "PASSED", "REJECTED"]
MAINTENANCE_KINDS = ["PIGGING", "INTEGRITY_DIG", "HYDROTEST", "VALVE_REPAIR"]
MAINTENANCE_STATUSES = ["PLANNED", "NOTIFIED", "ACTIVE", "COMPLETED"]
SETTLEMENT_STATUSES = ["DRAFT", "CERTIFIED", "INVOICED"]
BASIS_MODES = ["SCHEDULED", "DELIVERED"]
IMBALANCE_TIERS = ["TOLERANCE", "STANDARD", "PENALTY"]


def _assert_identity(data: dict, versioned: bool = True) -> None:
    """Common identity fields.

    The PRD gives every resource a bare-UUID `id` and an ISO 8601 `created_at`;
    all but the historical movement record additionally carry `updated_at` and a
    `version` that starts at 1.
    """
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert "_" not in str(data.get("id", "")), "id must carry no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    if versioned:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
        )
        assert isinstance(data.get("version"), int) and data["version"] >= 1, (
            f"version must be an integer of at least 1, got {data.get('version')!r}"
        )


def assert_millisecond_timestamp(value: str, field: str = "timestamp") -> None:
    """PRD 2.4: instants are rendered with exactly three fractional-second digits."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert value.endswith("Z"), f"{field} must end with Z, got {value!r}"
    assert len(value) == 24 and value[19] == ".", (
        f"{field} must carry exactly three fractional digits, got {value!r}"
    )


def assert_terminal(data: dict) -> None:
    _assert_identity(data)
    assert isinstance(data["terminal_code"], str) and data["terminal_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["role_kind"] in TERMINAL_ROLE_KINDS, f"bad role_kind {data['role_kind']!r}"
    assert float(data["shell_capacity_bbl"]) > 0, "shell_capacity_bbl must exceed zero"
    assert float(data["min_operating_inventory_bbl"]) >= 0
    assert int(data["injection_bays"]) >= 1, "injection_bays must be at least 1"
    assert float(data["inventory_bbl"]) >= 0


def assert_product_grade(data: dict) -> None:
    _assert_identity(data)
    assert isinstance(data["grade_code"], str) and data["grade_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert 1 <= int(data["sequence_rank"]) <= 9, "sequence_rank must be 1 through 9"
    assert float(data["max_sulfur_ppm"]) > 0
    assert float(data["max_rvp_psi"]) > 0
    assert isinstance(data["is_transmix_grade"], bool)


def assert_segment(data: dict) -> None:
    _assert_identity(data)
    assert isinstance(data["segment_code"], str) and data["segment_code"]
    assert is_valid_uuid(data["origin_terminal_id"])
    assert is_valid_uuid(data["destination_terminal_id"])
    assert is_valid_uuid(data["linefill_grade_id"])
    assert float(data["capacity_bbl_per_cycle"]) > 0
    assert float(data["transmix_reserve_bbl"]) >= 0
    assert float(data["transmix_cut_bbl"]) >= 0
    assert float(data["min_tender_bbl"]) > 0
    assert float(data["linefill_requirement_bbl"]) >= 0
    assert float(data["linefill_bbl"]) >= 0
    assert data["proration_policy"] in PRORATION_POLICIES
    assert data["operational_status"] in SEGMENT_STATUSES
    assert 0 <= float(data["derate_pct"]) <= 1
    assert float(data["in_transit_bbl"]) >= 0
    assert float(data["transmix_inventory_bbl"]) >= 0
    assert float(data["system_loss_bbl"]) >= 0


def assert_shipper(data: dict) -> None:
    _assert_identity(data)
    assert isinstance(data["shipper_code"], str)
    assert 3 <= len(data["shipper_code"]) <= 12, (
        "shipper_code must be between 3 and 12 characters"
    )
    assert isinstance(data["name"], str) and data["name"]
    assert float(data["credit_limit_usd"]) >= 0
    assert float(data["exposure_usd"]) >= 0
    assert data["status"] in SHIPPER_STATUSES
    if data["status"] == "ACTIVE":
        assert data["suspended_reason"] is None, (
            "an ACTIVE shipper carries a null suspended_reason"
        )


def assert_shipping_history_record(data: dict) -> None:
    """The historical movement record is immutable: only `id` and `created_at`."""
    _assert_identity(data, versioned=False)
    assert "updated_at" not in data, "the historical movement record has no updated_at"
    assert "version" not in data, "the historical movement record has no version"
    assert is_valid_uuid(data["shipper_id"])
    assert is_valid_uuid(data["segment_id"])
    assert isinstance(data["cycle_code"], str) and data["cycle_code"]
    assert float(data["actual_shipped_bbl"]) >= 0
    assert is_iso8601_timestamp(data["cycle_end_at"])
    assert data["record_status"] in RECORD_STATUSES


def assert_tariff(data: dict) -> None:
    _assert_identity(data)
    assert is_valid_uuid(data["segment_id"])
    assert is_valid_uuid(data["grade_id"])
    for rate in (
        "base_rate_usd_per_bbl",
        "tier1_rate_usd_per_bbl",
        "tier2_rate_usd_per_bbl",
    ):
        assert float(data[rate]) > 0, f"{rate} must be strictly greater than zero"
        assert_rate_precision(data[rate], rate)
    assert float(data["tier1_min_bbl"]) > 0
    assert float(data["tier2_min_bbl"]) > float(data["tier1_min_bbl"])
    assert float(data["tender_minimum_bbl"]) > 0
    assert float(data["imbalance_penalty_rate_usd_per_bbl"]) >= 0
    assert is_iso8601_timestamp(data["effective_from"])
    assert data["status"] in TARIFF_STATUSES


def assert_cycle(data: dict) -> None:
    _assert_identity(data)
    assert isinstance(data["cycle_code"], str) and data["cycle_code"]
    assert is_valid_uuid(data["segment_id"])
    for instant in ("window_open_at", "window_close_at", "ship_start_at", "ship_end_at"):
        assert is_iso8601_timestamp(data[instant]), f"{instant} must be ISO 8601"
    assert data["status"] in CYCLE_STATUSES
    assert int(data["effective_capacity_bbl"]) == float(data["effective_capacity_bbl"]), (
        "effective_capacity_bbl is a whole number of barrels"
    )
    assert int(data["schedule_version"]) >= 0
    if data.get("proration_factor") is not None:
        assert float(data["proration_factor"]) >= 0


def assert_nomination(data: dict) -> None:
    _assert_identity(data)
    assert is_valid_uuid(data["cycle_id"])
    assert is_valid_uuid(data["shipper_id"])
    assert is_valid_uuid(data["grade_id"])
    assert is_valid_uuid(data["origin_terminal_id"])
    assert is_valid_uuid(data["destination_terminal_id"])
    assert float(data["nominated_bbl"]) > 0
    assert int(data["allocated_bbl"]) == float(data["allocated_bbl"]), (
        "allocated_bbl is a whole number of barrels"
    )
    assert float(data["history_base_bbl"]) >= 0
    assert data["allocation_class"] in ALLOCATION_CLASSES
    assert data["status"] in NOMINATION_STATUSES
    assert int(data["revision_count"]) >= 0
    if data["status"] != "REJECTED":
        assert data["rejection_reason"] is None, (
            "rejection_reason stays null unless status is REJECTED"
        )
    else:
        assert data["rejection_reason"] in REJECTION_REASONS


def assert_batch_ticket(data: dict) -> None:
    _assert_identity(data)
    assert is_valid_uuid(data["cycle_id"])
    assert is_valid_uuid(data["nomination_id"])
    assert int(data["sequence_position"]) >= 1
    assert float(data["volume_bbl"]) > 0
    assert int(data["transmix_bbl"]) == float(data["transmix_bbl"]), (
        "transmix_bbl is a whole number of barrels"
    )
    assert isinstance(data["requires_flush"], bool)
    assert_millisecond_timestamp(data["injection_window_start"], "injection_window_start")
    assert_millisecond_timestamp(data["injection_window_end"], "injection_window_end")
    assert data["movement_status"] in MOVEMENT_STATUSES
    assert data["quality_status"] in QUALITY_STATUSES
    assert int(data["retest_count"]) >= 0


def assert_maintenance_event(data: dict) -> None:
    _assert_identity(data)
    assert is_valid_uuid(data["segment_id"])
    assert data["kind"] in MAINTENANCE_KINDS
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["window_end"] > data["window_start"], (
        "window_end must be strictly later than window_start"
    )
    assert 0 < float(data["capacity_derate_pct"]) <= 1
    assert data["status"] in MAINTENANCE_STATUSES
    assert int(data["notified_shipper_count"]) >= 0


def assert_settlement(data: dict) -> None:
    _assert_identity(data)
    assert is_valid_uuid(data["cycle_id"])
    assert is_valid_uuid(data["shipper_id"])
    assert data["basis_mode"] in BASIS_MODES
    assert data["imbalance_tier"] in IMBALANCE_TIERS
    assert data["status"] in SETTLEMENT_STATUSES
    for money in (
        "tariff_charge_usd",
        "alt_basis_charge_usd",
        "basis_delta_usd",
        "imbalance_charge_usd",
        "total_billed_usd",
    ):
        assert_money_precision(data[money], money)
    if data["status"] == "DRAFT":
        assert data["certified_by_user_id"] is None, (
            "certified_by_user_id is null while the settlement is DRAFT"
        )


# ------------------------------------------------------------------ precision


def _decimal_places(value) -> int:
    text = f"{float(value):.10f}".rstrip("0")
    if "." not in text:
        return 0
    return len(text.split(".")[1])


def assert_money_precision(value, field: str = "amount") -> None:
    """PRD 2.9: monetary amounts are carried to 2 decimal places."""
    assert _decimal_places(value) <= 2, (
        f"{field} must carry at most 2 decimal places, got {value!r}"
    )


def assert_rate_precision(value, field: str = "rate") -> None:
    """PRD 2.9: tariff rates are carried to 3 decimal places."""
    assert _decimal_places(value) <= 3, (
        f"{field} must carry at most 3 decimal places, got {value!r}"
    )


def assert_ratio_precision(value, field: str = "ratio") -> None:
    """PRD 2.9: proration_factor and imbalance_pct are carried to 6 decimals."""
    assert _decimal_places(value) <= 6, (
        f"{field} must carry at most 6 decimal places, got {value!r}"
    )


def assert_whole_barrels(value, field: str = "volume") -> None:
    """PRD 2.9: allocations and capacities are whole barrels."""
    assert float(value) == int(float(value)), (
        f"{field} must be a whole number of barrels, got {value!r}"
    )


# ------------------------------------------------------------- domain invariants


def assert_capacity_conservation(cycle: dict) -> None:
    """PRD 2.8: allocated_total_bbl plus unallocated_capacity_bbl must equal
    effective_capacity_bbl exactly, in whole barrels, with zero drift."""
    allocated = int(cycle["allocated_total_bbl"])
    unallocated = int(cycle["unallocated_capacity_bbl"])
    effective = int(cycle["effective_capacity_bbl"])
    assert allocated + unallocated == effective, (
        f"capacity identity broken: {allocated} + {unallocated} != {effective}"
    )


def total_book_volume(origin: dict, destination: dict, segment: dict) -> float:
    """PRD 2.7's five accumulators, summed at two-decimal precision."""
    return round(
        float(origin["inventory_bbl"])
        + float(destination["inventory_bbl"])
        + float(segment["in_transit_bbl"])
        + float(segment["transmix_inventory_bbl"])
        + float(segment["system_loss_bbl"]),
        2,
    )


def assert_volumetric_conservation(
    origin: dict, destination: dict, segment: dict, expected_total: float
) -> None:
    """PRD 2.7: the five-accumulator total is asserted after every injection,
    every delivery and every batch cancellation, always at two-decimal precision."""
    actual = total_book_volume(origin, destination, segment)
    assert actual == round(float(expected_total), 2), (
        f"five-accumulator total is {actual}, expected {round(float(expected_total), 2)}"
    )


def assert_envelope_is_object(body: dict) -> None:
    """PRD 2.2: a single-resource read carries response_type of "object"."""
    assert body["response_type"] == "object", (
        f"expected response_type 'object', got {body['response_type']!r}"
    )
    assert body["meta"]["api_request_id"].startswith("req_"), (
        "api_request_id must start with req_"
    )


def assert_envelope_is_error(body: dict) -> None:
    """PRD 2.2: every error response carries response_type of "error"."""
    assert body["response_type"] == "error", (
        f"expected response_type 'error', got {body['response_type']!r}"
    )
    assert body["meta"]["api_request_id"].startswith("req_")
