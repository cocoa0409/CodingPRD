"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 instant, tolerating 'Z' and optional fractional digits."""
    assert isinstance(value, str), f"expected ISO string, got {value!r}"
    v = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def assert_same_instant(actual: str, expected: str, label: str = "instant"):
    """Two ISO 8601 strings denote the same instant (format-tolerant)."""
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"{label}: expected instant {expected}, got {actual}"
    )


def assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version starts at 1"


def assert_color(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["hex_code"], str) and data["hex_code"].startswith("#")
    assert isinstance(data["is_core_curriculum"], bool)
    assert data["status"] in ["PROPOSED", "IN_VOTE", "ACTIVE", "RETIRE_VOTE", "RETIRED", "ARCHIVED"]


def assert_pigment_batch(data: dict):
    assert_common_fields(data)
    assert isinstance(data["pigment_name"], str) and data["pigment_name"]
    assert isinstance(data["supplier_name"], str) and data["supplier_name"]
    assert data["hazard_class"] in ["STANDARD", "SENSITIVE", "RESTRICTED"]
    assert data["received_quantity_kg"] > 0
    assert data["certification_mark"] in ["ACMI_AP", "ACMI_CL", "NONE"]
    assert data["status"] in ["QUARANTINE", "CERTIFIED", "REJECTED"]
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]


def assert_formula(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("color_id", "")), "color_id must be a UUID"
    assert data["intended_use"] in ["CRAYON", "MARKER", "COLORED_PENCIL"]
    assert isinstance(data["pigment_recipe"], list) and len(data["pigment_recipe"]) >= 1
    assert data["status"] in ["DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED", "REJECTED", "SUPERSEDED"]
    assert isinstance(data["licensed_use_count"], int) and data["licensed_use_count"] >= 0


def assert_vote_campaign(data: dict):
    assert_common_fields(data)
    assert data["kind"] in ["INTRODUCTION", "RETIREMENT"]
    assert data["status"] in ["SCHEDULED", "OPEN", "TALLYED"]
    assert data["votes_yes_weighted"] >= 0 and data["votes_total_weighted"] >= 0
    assert isinstance(data["turnout_count"], int) and data["turnout_count"] >= 0


def assert_safety_test(data: dict):
    assert_common_fields(data)
    assert data["test_standard"] in ["ASTM_D4236", "EN71_3"]
    assert isinstance(data["test_seq"], int) and data["test_seq"] >= 1
    assert data["status"] in ["SCHEDULED", "PASSED", "FAILED"]


def assert_assortment_spec(data: dict):
    assert_common_fields(data)
    assert data["kind"] in ["RETAIL", "CLASSROOM", "LICENSED"]
    assert isinstance(data["entries"], list) and len(data["entries"]) >= 1
    assert isinstance(data["wholesale_price_cents"], int) and data["wholesale_price_cents"] >= 1
    assert data["box_size"] in [8, 16, 24, 64]
    assert data["status"] in ["ACTIVE", "DEPRECATED"]
    assert isinstance(data["boxes_available"], int) and data["boxes_available"] >= 0
    assert isinstance(data["boxes_reserved"], int) and data["boxes_reserved"] >= 0


def assert_production_run(data: dict):
    assert_common_fields(data)
    assert data["stage"] in ["PLANNED", "MOLDING", "LABELING", "PACKING",
                             "COMPLETED", "ON_HOLD", "CANCELLED", "QUARANTINED"]
    assert isinstance(data["planned_boxes"], int) and data["planned_boxes"] >= 1
    assert isinstance(data["run_seq"], int) and data["run_seq"] >= 1


def assert_inventory_lot(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["AVAILABLE", "DEPLETED", "QUARANTINED"]
    assert isinstance(data["lot_seq"], int) and data["lot_seq"] >= 1
    for f in ("boxes_received", "boxes_on_hand", "boxes_committed", "boxes_shipped"):
        assert isinstance(data[f], int) and data[f] >= 0


def assert_lot_mass_balance(lot: dict):
    """Per-lot conservation: on_hand + committed + shipped == received."""
    total = lot["boxes_on_hand"] + lot["boxes_committed"] + lot["boxes_shipped"]
    assert total == lot["boxes_received"], (
        f"lot mass balance broken: {lot['boxes_on_hand']} + {lot['boxes_committed']} "
        f"+ {lot['boxes_shipped']} != {lot['boxes_received']}"
    )


def assert_retail_allocation(data: dict):
    assert_common_fields(data)
    assert data["priority_tier"] in ["PLATINUM", "GOLD", "STANDARD"]
    assert isinstance(data["requested_boxes"], int) and data["requested_boxes"] >= 1
    assert data["status"] in ["REQUESTED", "COMMITTED", "FULFILLED", "RELEASED", "EXPIRED", "SHORTED"]
    assert isinstance(data["request_seq"], int) and data["request_seq"] >= 1


def assert_licensed_line(data: dict):
    assert_common_fields(data)
    assert data["royalty_base"] in ["GROSS", "NET"]
    assert 0 < data["royalty_rate"] <= 0.5
    assert data["status"] in ["DRAFT", "LICENSOR_REVIEW", "BRAND_REVIEW", "APPROVED", "REJECTED", "SUSPENDED"]
    assert isinstance(data["licensor_user_id"], str) and data["licensor_user_id"]


def assert_attraction_session(data: dict):
    assert_common_fields(data)
    assert 0 <= data["start_minute"] <= 1339
    assert data["duration_minutes"] >= 30
    assert data["capacity_units"] >= 1
    assert isinstance(data["is_charter"], bool)
    assert data["base_price_cents"] >= 0
    assert isinstance(data["booked_units"], int) and data["booked_units"] >= 0
    assert data["status"] in ["SCHEDULED", "CLOSED"]


def assert_ticket(data: dict):
    assert_common_fields(data)
    assert data["kind"] in ["INDIVIDUAL", "GROUP"]
    assert data["status"] in ["CONFIRMED", "WAITLISTED", "CHECKED_IN", "REFUNDED", "CANCELLED", "NO_SHOW"]
    assert isinstance(data["units"], int) and data["units"] >= 1
    assert isinstance(data["waitlist_seq"], int) and data["waitlist_seq"] >= 1


def assert_recall_case(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["OPEN", "CONTAINED", "CLOSED"]
    assert data["severity"] in ["CLASS_I", "CLASS_II", "CLASS_III"]
    assert isinstance(data["affected_run_count"], int) and data["affected_run_count"] >= 0
    assert isinstance(data["affected_units"], int) and data["affected_units"] >= 0


def assert_error_envelope(response, expected_status: int):
    """Fixed error envelope: response_type error, data.error_id + data.message, meta pair."""
    assert response.status_code == expected_status, (
        f"expected {expected_status}, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body.get("response_type") == "error", f"response_type must be error: {body}"
    assert isinstance(body["data"].get("error_id"), str) and body["data"]["error_id"]
    assert isinstance(body["data"].get("message"), str) and body["data"]["message"]
    assert body["meta"].get("api_request_id"), "meta.api_request_id required"
    assert body["meta"].get("api_request_timestamp"), "meta.api_request_timestamp required"
    return body["data"]
