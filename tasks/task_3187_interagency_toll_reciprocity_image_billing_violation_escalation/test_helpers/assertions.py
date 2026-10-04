"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_agency(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["agency_code"], str) and data["agency_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["home_state"], str) and data["home_state"]
    assert isinstance(data["reciprocity_fee_bps"], int)
    assert isinstance(data["settlement_currency"], str)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int)


def assert_rate_schedule(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("agency_id", ""))
    assert isinstance(data["plaza_code"], str)
    assert data["vehicle_class"] in ("CLASS_2", "CLASS_5", "CLASS_7")
    assert isinstance(data["base_rate_cents"], int)
    assert isinstance(data["axle_multiplier"], (int, float))
    assert isinstance(data["peak_multiplier"], (int, float))
    assert isinstance(data["image_fee_cents"], int)
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_discount_plan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("agency_id", ""))
    assert isinstance(data["plan_code"], str)
    assert isinstance(data["discount_pct"], (int, float))
    assert isinstance(data["daily_discount_cap_cents"], int)
    assert isinstance(data["applies_to_agency_codes"], list)
    assert isinstance(data["min_trips_per_month"], int)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("home_agency_id", ""))
    assert isinstance(data["holder_name"], str)
    assert isinstance(data["holder_email"], str)
    assert isinstance(data["discount_plan_id"], str)
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["low_balance_threshold_cents"], int)
    assert isinstance(data["replenishment_amount_cents"], int)
    assert isinstance(data["replenishment_fail_count"], int)
    assert isinstance(data["discount_used_today_cents"], int)
    assert isinstance(data["trips_this_month"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert data["suspended_reason"] in (None, "REPLENISHMENT_FAILED", "VIOLATION_ESCALATION")
    assert is_iso8601_timestamp(data["created_at"])
    assert isinstance(data["version"], int)


def assert_transponder(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("account_id", ""))
    assert isinstance(data["tag_number"], str)
    assert data["vehicle_class"] in ("CLASS_2", "CLASS_5", "CLASS_7")
    assert isinstance(data["plate_number"], str)
    assert isinstance(data["plate_state"], str)
    assert data["status"] in ("ACTIVE", "REPORTED_LOST", "RETIRED")


def assert_toll_transaction(data: dict):
    # Append-only (PRD §2.4): no updated_at, no version.
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data["created_at"])
    assert "updated_at" not in data, "TollTransaction must not carry updated_at"
    assert "version" not in data, "TollTransaction must not carry version"
    assert data["detection_method"] in ("TRANSPONDER", "IMAGE")
    assert data["billed_vehicle_class"] in ("CLASS_2", "CLASS_5", "CLASS_7")
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["discount_amount_cents"], int)
    assert isinstance(data["charged_amount_cents"], int)
    assert data["charged_amount_cents"] == data["gross_amount_cents"] - data["discount_amount_cents"]
    assert data["status"] in ("POSTED", "SETTLED", "VOIDED", "DISPUTED")
    assert isinstance(data["plaza_code"], str)
    assert is_iso8601_timestamp(data["trip_timestamp"])
    assert isinstance(data["is_peak"], bool)
    assert isinstance(data["idempotency_key"], str)


def assert_image_bill(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["plate_number"], str)
    assert isinstance(data["plate_state"], str)
    assert isinstance(data["billed_amount_cents"], int)
    assert isinstance(data["misread_flag"], bool)
    assert data["status"] in ("PENDING_LOOKUP", "BILLED", "REBILLED", "VOIDED", "ESCALATED")


def assert_violation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["plate_number"], str)
    assert isinstance(data["plate_state"], str)
    assert isinstance(data["toll_amount_cents"], int)
    assert isinstance(data["notice_count"], int)
    assert isinstance(data["admin_fees_cents"], int)
    assert isinstance(data["total_outstanding_cents"], int)
    assert isinstance(data["registration_hold_referred"], bool)
    assert data["status"] in ("OPEN", "NOTICED", "ESCALATED", "HOLD_REFERRED", "PAID", "DISMISSED")


def assert_dispute(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["dispute_type"] in ("VEHICLE_CLASSIFICATION", "MISREAD_PLATE", "RENTAL_VEHICLE")
    assert isinstance(data["filed_day"], int)
    assert data["status"] in ("FILED", "UNDER_REVIEW", "UPHOLD", "REJECTED", "WITHDRAWN")


def assert_settlement_file(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("from_agency_id", ""))
    assert is_valid_uuid(data.get("to_agency_id", ""))
    assert isinstance(data["settlement_day"], int)
    assert isinstance(data["line_count"], int)
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["fee_amount_cents"], int)
    assert isinstance(data["net_amount_cents"], int)
    assert data["gross_amount_cents"] == data["fee_amount_cents"] + data["net_amount_cents"], (
        "no cent may be created or destroyed: gross == fee + net"
    )
    assert isinstance(data["exception_count"], int)
    assert data["status"] in (
        "GENERATED", "TRANSMITTED", "ACKNOWLEDGED", "RECONCILED", "DISPUTED_SETTLEMENT"
    )


def assert_plate_data_agreement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("requesting_agency_id", ""))
    assert is_valid_uuid(data.get("providing_agency_id", ""))
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])
    assert isinstance(data["covers_states"], list)
    assert isinstance(data["per_lookup_fee_cents"], int)
    assert data["status"] in ("ACTIVE", "EXPIRED", "REVOKED")
