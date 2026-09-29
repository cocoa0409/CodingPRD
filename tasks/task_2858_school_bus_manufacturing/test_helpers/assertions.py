"""Entity assertions, envelope helpers and domain invariant checkers."""

import re
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


# ==========================================================================
# Numeric helpers mirroring the PRD's stated rounding conventions
# ==========================================================================
def round_half_up(value, places: int = 0):
    """Round half away from zero at `places` decimals, as the PRD requires at
    every named rounding point."""
    quant = Decimal(1).scaleb(-places)
    result = Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)
    return int(result) if places == 0 else float(result)


def truncate_toward_zero(value, places: int = 1) -> float:
    """Drop digits beyond `places` without rounding, as the derated route range
    requires."""
    factor = Decimal(10) ** places
    d = Decimal(str(value)) * factor
    return float(int(d) / factor)


# ==========================================================================
# Timestamp helpers
# ==========================================================================
def parse_instant(value: str) -> datetime:
    """Parse an ISO-8601 UTC instant with or without fractional seconds."""
    assert isinstance(value, str) and value, f"Expected an ISO-8601 instant, got {value!r}"
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str, label: str = "instant") -> None:
    """Compare two ISO-8601 instants by value, so a difference in how many
    fractional digits are rendered is not treated as a mismatch."""
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_instant_on_date(actual: str, expected_date: str, label: str = "instant") -> None:
    """Assert that an instant falls on the given calendar date (UTC)."""
    got = parse_instant(actual).date().isoformat()
    assert got == expected_date, f"{label}: expected date {expected_date}, got {got}"


def assert_timestamp_millisecond_precision(value: str, label: str = "timestamp") -> None:
    """The PRD renders `created_at` and every other instant with exactly three
    fractional digits."""
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", value), (
        f"{label} must be an ISO-8601 UTC instant with three fractional digits, got {value!r}"
    )


# ==========================================================================
# Envelope helpers
# ==========================================================================
def assert_envelope_meta(body: dict) -> None:
    """Every response carries a `meta` with a correlation id and a timestamp."""
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"], (
        "meta.api_request_id must be a non-empty string"
    )
    assert meta["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), (
        "meta.api_request_timestamp must be an ISO-8601 instant"
    )


def assert_response_type(response, expected: str) -> None:
    body = response.json()
    assert body.get("response_type") == expected, (
        f"Expected response_type {expected!r}, got {body.get('response_type')!r}"
    )


def assert_pagination_meta(meta: dict, limit: int, offset: int, total_count: int,
                           has_more: bool) -> None:
    assert meta["limit"] == limit, f"Expected limit {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"Expected offset {offset}, got {meta['offset']}"
    assert meta["total_count"] == total_count, (
        f"Expected total_count {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"Expected has_more {has_more}, got {meta['has_more']}"
    )


# ==========================================================================
# Common-field assertions
# ==========================================================================
def assert_common_fields(data: dict, expected_version: Optional[int] = None) -> None:
    """`id`, `created_at`, `updated_at` and `version` are present on every
    resource except an appended bid revision."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert not str(data["id"]).lower().startswith(("bm_", "sp_", "bid_", "ord_")), (
        "id must carry no type prefix"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO-8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO-8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"Expected version {expected_version}, got {data['version']}"
        )


def assert_append_only_fields(data: dict) -> None:
    """An appended bid revision carries only an identifier and a creation
    instant from the common set — no `updated_at` and no `version`."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO-8601"
    assert "updated_at" not in data or data["updated_at"] is None, (
        "an appended revision must not carry updated_at"
    )
    assert "version" not in data or data["version"] is None, (
        "an appended revision must not carry version"
    )


# ==========================================================================
# Per-resource assertions
# ==========================================================================
def assert_state_spec_profile(data: dict) -> None:
    assert_common_fields(data)
    assert re.match(r"^[A-Z]{2}$", data["state_code"]), (
        f"state_code must be two uppercase letters, got {data['state_code']!r}"
    )
    assert re.match(r"^\d{4}-\d{4}$", data["school_year"]), (
        f"school_year must look like YYYY-YYYY, got {data['school_year']!r}"
    )
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED")
    assert data["min_seat_capacity"] >= 1
    assert data["min_emergency_exit_count"] >= 1
    assert data["min_joint_strength_kn"] > 0
    assert data["required_route_range_mi"] > 0
    assert isinstance(data["requires_eight_lamp_system"], bool)
    assert isinstance(data["requires_crossing_arm"], bool)
    assert isinstance(data["requires_lap_shoulder_belts"], bool)
    assert isinstance(data["requires_rollover_protection"], bool)
    assert isinstance(data["requires_joint_strength_test"], bool)
    assert data["required_mirror_config"] in ("STANDARD", "CROSSVIEW", "CROSSVIEW_HEATED")
    assert data["terrain_class"] in ("FLAT", "ROLLING", "MOUNTAIN")


def assert_bus_model(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["model_code"], str) and data["model_code"]
    assert data["body_class"] in ("TYPE_A", "TYPE_C", "TYPE_D")
    assert data["base_seat_capacity"] >= 1
    assert data["base_emergency_exit_count"] >= 1
    assert data["base_price_cents"] > 0 and isinstance(data["base_price_cents"], int)
    assert data["body_joint_strength_kn"] > 0
    assert data["max_battery_bays"] >= 0
    assert data["curb_weight_lb"] > 0


def assert_propulsion_package(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["package_code"], str) and data["package_code"]
    assert is_valid_uuid(data["compatible_bus_model_id"])
    assert data["propulsion_type"] in ("DIESEL", "PROPANE", "ELECTRIC")
    assert isinstance(data["option_price_cents"], int) and data["option_price_cents"] >= 0
    assert 0 <= data["cold_weather_derate_pct"] < 1, (
        "cold_weather_derate_pct must be at least zero and strictly below one"
    )
    assert 0 <= data["reserve_floor_pct"] < 1, (
        "reserve_floor_pct must be at least zero and strictly below one"
    )


def assert_solicitation(data: dict) -> None:
    assert_common_fields(data)
    assert data["buyer_type"] in ("DISTRICT", "COOPERATIVE")
    assert data["status"] in ("OPEN", "CLOSED", "AWARDED")
    assert data["unit_count"] >= 1
    assert data["price_cap_cents_per_unit"] > 0


def assert_bid(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "REVISION_REQUESTED", "AWARDED", "REJECTED"
    )
    assert data["spec_compliance_status"] in (
        "CONFORMING", "EXCEPTIONS_TAKEN", "NONCONFORMING"
    )
    assert isinstance(data["provisional_unit_price_cents"], int)
    assert data["provisional_unit_price_cents"] > 0
    assert isinstance(data["nominal_range_mi"], int), (
        "nominal_range_mi is a whole number of miles"
    )
    assert_one_decimal_place(data["derated_route_range_mi"], "derated_route_range_mi")
    assert_one_decimal_place(data["offered_joint_strength_kn"], "offered_joint_strength_kn")
    assert data["offered_joint_strength_kn"] > 0
    assert data["offered_mirror_config"] in ("STANDARD", "CROSSVIEW", "CROSSVIEW_HEATED")
    assert 0 <= data["revision_round"] <= 3
    assert data["exception_count"] >= 0


def assert_bid_revision(data: dict) -> None:
    assert_append_only_fields(data)
    assert data["round_index"] >= 0
    assert isinstance(data["is_superseded"], bool)
    assert isinstance(data["unit_price_cents"], int)


def assert_contract_order(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "FULFILLED", "CANCELLED")
    assert data["delivery_posture"] in ("ON_TRACK", "AT_RISK", "BREACHED")
    assert isinstance(data["awarded_unit_price_cents"], int)
    assert isinstance(data["total_contract_cents"], int)
    assert data["created_unit_count"] >= 0
    assert data["delivered_unit_count"] >= 0
    assert data["at_risk_unit_count"] >= 0
    assert data["liquidated_damages_cents"] >= 0
    assert data["created_unit_count"] <= data["unit_count"], (
        "a contract order may never mint more units than it was awarded"
    )
    assert data["delivered_unit_count"] <= data["created_unit_count"]
    assert_one_decimal_place(data["awarded_joint_strength_kn"], "awarded_joint_strength_kn")


def assert_production_line(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ("RUNNING", "DOWN_FOR_MAINTENANCE")
    assert isinstance(data["supported_body_classes"], list)
    assert len(data["supported_body_classes"]) >= 1
    assert data["horizon_slot_day_capacity"] >= 1
    assert data["changeover_buffer_days"] >= 0
    assert data["committed_slot_days"] >= 0


def assert_build_slot(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in (
        "PLANNED", "COMMITTED", "IN_PROGRESS", "COMPLETED", "RELEASED"
    )
    assert data["slot_days"] >= 1
    assert data["end_date"] > data["start_date"], (
        "a slot window ends strictly after it starts"
    )
    assert data["propulsion_type"] in ("DIESEL", "PROPANE", "ELECTRIC")


def assert_bus_unit(data: dict) -> None:
    assert_common_fields(data)
    assert data["production_status"] in (
        "PLANNED", "SLOTTED", "BODY_JOINED", "BUILT", "DELIVERED"
    )
    assert data["certification_status"] in (
        "PENDING", "CERTIFIED", "NONCONFORMING", "WAIVED"
    )
    assert data["service_status"] in ("NONE", "RECALL_OPEN", "RECALL_CLOSED")
    assert data["driver_training_status"] in ("PENDING", "COMPLETED")
    assert isinstance(data["is_legacy_import"], bool)
    assert isinstance(data["vin"], str) and data["vin"]
    assert_one_decimal_place(data["derated_route_range_mi"], "derated_route_range_mi")
    assert isinstance(data["nominal_range_mi"], int)


def assert_test_bay(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["supported_test_types"], list)
    assert len(data["supported_test_types"]) >= 1
    for test_type in data["supported_test_types"]:
        assert test_type in (
            "BRAKE", "EMERGENCY_EXIT", "ELECTRICAL", "JOINT_STRENGTH", "ROLLOVER"
        )
    assert data["max_concurrent_electrical"] >= 1


def assert_quality_test(data: dict) -> None:
    assert_common_fields(data)
    assert data["test_type"] in (
        "BRAKE", "EMERGENCY_EXIT", "ELECTRICAL", "JOINT_STRENGTH", "ROLLOVER"
    )
    assert data["status"] in ("SCHEDULED", "PASSED", "FAILED", "VOIDED")
    assert data["window_end"] >= data["window_start"], (
        "a test window ends no earlier than it starts"
    )


def assert_dealer(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["licensed_state_codes"], list)
    assert len(data["licensed_state_codes"]) >= 1
    assert data["training_capacity_per_month"] >= 0
    assert data["certification_standing"] in ("GOOD", "RESTRICTED", "SUSPENDED")
    assert data["delivered_unit_count"] >= 0
    assert data["open_recall_unit_count"] >= 0


def assert_recall_campaign(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "LAUNCHED", "COMPLETED")
    assert data["defect_category"] in (
        "BRAKE_LINE_CORROSION",
        "EMERGENCY_EXIT_LATCH",
        "WIRING_HARNESS",
        "BATTERY_CONTACTOR",
    )
    assert data["affected_propulsion_type"] in ("DIESEL", "PROPANE", "ELECTRIC")
    assert data["kits_per_unit"] >= 1
    assert data["total_kits"] >= 1
    assert data["build_window_end"] >= data["build_window_start"]
    assert_kit_pool_conserved(data)


def assert_remedy_task(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ("OPEN", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert data["escalation_level"] in ("DEALER_DIRECTED", "FACTORY_DIRECTED")
    assert data["kits_reserved"] >= 0


# ==========================================================================
# Domain invariants
# ==========================================================================
def assert_one_decimal_place(value, label: str) -> None:
    """The PRD carries joint strength and derated route range to exactly one
    decimal place."""
    assert value is not None, f"{label} must be present"
    scaled = Decimal(str(value)) * 10
    assert scaled == scaled.to_integral_value(), (
        f"{label} must carry one decimal place, got {value}"
    )


def assert_two_decimal_places(value, label: str) -> None:
    assert value is not None, f"{label} must be present"
    assert_cost_precision(float(value), 2)


def assert_kit_pool_conserved(campaign: dict) -> None:
    """`available_kits` is `total_kits` less reserved less consumed."""
    expected = campaign["total_kits"] - campaign["reserved_kits"] - campaign["consumed_kits"]
    assert campaign["available_kits"] == expected, (
        "available_kits must equal total_kits minus reserved_kits minus consumed_kits: "
        f"{campaign['total_kits']} - {campaign['reserved_kits']} - "
        f"{campaign['consumed_kits']} != {campaign['available_kits']}"
    )


def assert_line_ledger(line: dict, expected_days: int) -> None:
    assert line["committed_slot_days"] == expected_days, (
        f"Expected committed_slot_days {expected_days}, got {line['committed_slot_days']}"
    )
    assert line["committed_slot_days"] <= line["horizon_slot_day_capacity"], (
        "the booked slot-day total may never exceed the line's horizon capacity"
    )


def assert_order_posture(order: dict, posture: str, at_risk: int,
                         damages: int = None) -> None:
    assert order["delivery_posture"] == posture, (
        f"Expected delivery_posture {posture}, got {order['delivery_posture']}"
    )
    assert order["at_risk_unit_count"] == at_risk, (
        f"Expected at_risk_unit_count {at_risk}, got {order['at_risk_unit_count']}"
    )
    if damages is not None:
        assert order["liquidated_damages_cents"] == damages, (
            f"Expected liquidated_damages_cents {damages}, "
            f"got {order['liquidated_damages_cents']}"
        )


def assert_unit_dimensions(unit: dict, production: str = None, certification: str = None,
                           service: str = None, training: str = None) -> None:
    """The three status dimensions plus driver training move independently."""
    if production is not None:
        assert unit["production_status"] == production, (
            f"Expected production_status {production}, got {unit['production_status']}"
        )
    if certification is not None:
        assert unit["certification_status"] == certification, (
            f"Expected certification_status {certification}, "
            f"got {unit['certification_status']}"
        )
    if service is not None:
        assert unit["service_status"] == service, (
            f"Expected service_status {service}, got {unit['service_status']}"
        )
    if training is not None:
        assert unit["driver_training_status"] == training, (
            f"Expected driver_training_status {training}, "
            f"got {unit['driver_training_status']}"
        )


def assert_unchanged(before: dict, after: dict, *fields: str) -> None:
    for field in fields:
        assert before.get(field) == after.get(field), (
            f"{field} must be unchanged: was {before.get(field)!r}, "
            f"now {after.get(field)!r}"
        )
