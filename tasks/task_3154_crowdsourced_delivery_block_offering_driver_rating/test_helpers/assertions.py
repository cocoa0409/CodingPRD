"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_station(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["zone_code"], str) and data["zone_code"]
    assert isinstance(data["surge_enabled"], bool)
    assert isinstance(data["pay_liabilities_cents"], int)
    assert data["pay_liabilities_cents"] >= 0


def assert_driver(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["status"] in ["APPLIED", "ACTIVE", "DEACTIVATED"]
    assert data["rating_tier"] in ["STANDARD", "PLUS", "PREMIER"]
    assert isinstance(data["rating_score_x100"], int)
    assert isinstance(data["lifetime_rating_x100"], int)
    assert isinstance(data["reliability_score_bp"], int)
    assert 0 <= data["reliability_score_bp"] <= 10000


def assert_screening(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("driver_id", "")), "driver_id must be a valid UUID"
    assert data["status"] in ["INITIATED", "IN_REVIEW", "CLEARED", "FAILED"]
    assert data.get("failure_reason") is None or isinstance(data["failure_reason"], str)
    assert data.get("decided_at") is None or is_iso8601_timestamp(data["decided_at"])


def assert_vehicle(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("driver_id", "")), "driver_id must be a valid UUID"
    assert isinstance(data["vin"], str) and data["vin"]
    assert data["vehicle_class"] in ["SEDAN", "SUV", "VAN"]
    assert data.get("insurance_expires_on") is None or isinstance(
        data["insurance_expires_on"], str
    )
    assert data["insurance_status"] in ["NONE", "ATTESTED", "EXPIRED"]
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_block(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("station_id", "")), "station_id must be a valid UUID"
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert data["required_vehicle_class"] in ["SEDAN", "SUV", "VAN"]
    assert isinstance(data["base_pay_cents"], int) and data["base_pay_cents"] > 0
    assert isinstance(data["surge_multiplier_bp"], int)
    assert data["surge_multiplier_bp"] >= 10000
    assert isinstance(data["estimated_pay_cents"], int)
    assert data["status"] in [
        "DRAFT", "PUBLISHED", "ASSIGNED", "IN_PROGRESS",
        "COMPLETED", "CANCELLED", "EXPIRED",
    ]
    assert data.get("assigned_driver_id") is None or is_valid_uuid(data["assigned_driver_id"])


def assert_offer(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("block_id", "")), "block_id must be a valid UUID"
    assert is_valid_uuid(data.get("driver_id", "")), "driver_id must be a valid UUID"
    assert data["tier_floor"] in ["STANDARD", "PLUS", "PREMIER"]
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["status"] in ["OFFERED", "ACCEPTED", "DECLINED", "EXPIRED", "REVOKED"]


def assert_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("block_id", "")), "block_id must be a valid UUID"
    assert is_valid_uuid(data.get("driver_id", "")), "driver_id must be a valid UUID"
    assert data.get("offer_id") is None or is_valid_uuid(data["offer_id"])
    assert is_valid_uuid(data.get("vehicle_id", "")), "vehicle_id must be a valid UUID"
    assert data["status"] in [
        "ASSIGNED", "CHECKED_IN", "ROUTE_ASSIGNED", "IN_DELIVERY",
        "COMPLETED", "FORFEITED", "NO_SHOW",
    ]
    assert isinstance(data["surge_multiplier_snapshot_bp"], int)
    assert data["tier_at_accept"] in ["STANDARD", "PLUS", "PREMIER"]
    assert isinstance(data["provisional_pay_cents"], int)
    assert data.get("check_in_at") is None or is_iso8601_timestamp(data["check_in_at"])
    assert data.get("forfeited_at") is None or is_iso8601_timestamp(data["forfeited_at"])
    assert data.get("no_show_at") is None or is_iso8601_timestamp(data["no_show_at"])
    assert data.get("forfeit_cause") in [None, "DRIVER_INITIATED", "SYSTEM_DEACTIVATION"]
    assert isinstance(data["strike_reversed"], bool)


def assert_package(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("assignment_id", "")), "assignment_id must be a valid UUID"
    assert isinstance(data["tracking_code"], str) and data["tracking_code"]
    assert isinstance(data["billable_weight_kg"], (int, float))
    assert data["billable_weight_kg"] > 0
    assert is_iso8601_timestamp(data["promised_by"])
    assert data["status"] in [
        "LOADED", "OUT_FOR_DELIVERY", "DELIVERED",
        "DELIVERY_FAILED", "RETURNED_TO_STATION",
    ]
    assert data.get("delivered_at") is None or is_iso8601_timestamp(data["delivered_at"])
    assert data.get("photo_compliant") in [None, True, False]
    assert data.get("on_time_delivery") in [None, True, False]


def assert_rating_event(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("driver_id", "")), "driver_id must be a valid UUID"
    assert is_valid_uuid(data.get("assignment_id", "")), "assignment_id must be a valid UUID"
    assert data["event_type"] == "COMPLETION_SCORE"
    assert isinstance(data["points"], int) and data["points"] >= 100
    assert is_iso8601_timestamp(data["event_at"])


def assert_pay_statement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("assignment_id", "")), "assignment_id must be a valid UUID"
    assert data["status"] in ["OPEN", "SETTLED", "VOIDED"]
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["tier_bonus_cents"], int)
    assert isinstance(data["surcharges_cents"], int)
    assert isinstance(data["penalties_cents"], int)
    assert isinstance(data["final_pay_cents"], int)
    assert data["tier_applied"] in ["STANDARD", "PLUS", "PREMIER"]
    assert data.get("settled_at") is None or is_iso8601_timestamp(data["settled_at"])
    assert data.get("voided_at") is None or is_iso8601_timestamp(data["voided_at"])
    # final composition invariant
    assert (
        data["final_pay_cents"]
        == data["gross_cents"]
        + data["tier_bonus_cents"]
        + data["surcharges_cents"]
        - data["penalties_cents"]
    )


def assert_appeal(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("driver_id", "")), "driver_id must be a valid UUID"
    assert isinstance(data["reason"], str) and data["reason"]
    assert data["status"] in [
        "SUBMITTED", "UNDER_REVIEW", "EVIDENCE_REQUESTED", "UPHELD", "OVERTURNED",
    ]
    assert isinstance(data["evidence_count"], int) and data["evidence_count"] >= 0
    assert data.get("decision_reason") is None or isinstance(data["decision_reason"], str)


def assert_driver_aggregates_consistent(data: dict):
    """Domain invariants on the driver's derived values."""
    assert 0 <= data["reliability_score_bp"] <= 10000
    if data["rating_tier"] == "PREMIER":
        assert data["rating_score_x100"] >= 470
        assert data["reliability_score_bp"] >= 9500
    elif data["rating_tier"] == "PLUS":
        assert data["rating_score_x100"] >= 430
        assert data["reliability_score_bp"] >= 8500
