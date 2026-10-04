"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_store(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["zone_codes"], list)
    assert isinstance(data["default_window_capacity_slots"], int)


def assert_product_model(data: dict):
    assert_common_fields(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["category"] in (
        "MATTRESS", "ADJUSTABLE_BASE", "AIR_CHAMBER", "PUMP", "ELECTRONICS",
        "BEDDING",
    )
    assert isinstance(data["price_cents"], int)
    assert isinstance(data["warranty_months"], int)


def assert_customer(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("home_store_id", ""))
    assert data["subscription_tier"] in ("FREE", "PLUS", "PREMIUM")
    assert data["subscription_status"] in ("ACTIVE", "CANCELLED")
    assert isinstance(data["store_credit_cents"], int)
    assert isinstance(data["entitlements"], list)


def assert_fit_assessment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("store_id", ""))
    assert data["sleep_position"] in ("SIDE", "BACK", "STOMACH", "COMBINATION")
    assert data["weight_band"] in ("UNDER_130", "BAND_130_230", "OVER_230")
    assert isinstance(data["partner_sleeper"], bool)
    assert data["preferred_feel"] in ("PLUSH", "MEDIUM", "FIRM")
    assert data["status"] in ("DRAFT", "COMPLETED", "SUPERSEDED")


def assert_order(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("fit_assessment_id", ""))
    assert isinstance(data["line_items"], list)
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["discount_cents"], int)
    assert isinstance(data["delivery_fee_cents"], int)
    assert isinstance(data["total_due_cents"], int)
    assert isinstance(data["total_paid_cents"], int)
    assert data["order_status"] in (
        "PLACED", "CONFIRMED", "FULFILLING", "DELIVERED", "CLOSED",
        "RETURNED", "CANCELLED",
    )
    assert data["payment_status"] in ("UNPAID", "PAID", "FINANCED", "REFUNDED")


def assert_delivery_window(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("store_id", ""))
    assert isinstance(data["team_id"], str)
    assert isinstance(data["capacity_slots"], int)
    assert isinstance(data["reserved_slots"], int)
    assert 0 <= data["reserved_slots"] <= data["capacity_slots"]


def assert_delivery_visit(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("delivery_window_id", ""))
    assert isinstance(data["slot_need"], int)
    assert data["status"] in (
        "SCHEDULED", "WAITLISTED", "VERIFIED", "FAILED_SETUP", "CANCELLED",
    )


def assert_device(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["kind"] in ("BASE", "PUMP", "CHAMBER", "SENSOR")
    assert data["pairing_status"] in ("UNPAIRED", "PAIRED")
    assert data["connectivity"] in ("ONLINE", "OFFLINE")
    assert isinstance(data["final_nights_count"], int)


def assert_sleep_night(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("device_id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["night_date"], str)
    assert isinstance(data["minutes_asleep"], int)
    assert isinstance(data["restlessness_events"], int)
    assert isinstance(data["avg_heart_rate"], int)
    assert data["status"] in ("PROVISIONAL", "FINAL")


def assert_trial_return(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert data["refund_destination"] in ("ORIGINAL_PAYMENT", "STORE_CREDIT")
    assert isinstance(data["initiated_night_index"], int)
    assert data["status"] in ("INITIATED", "REFUNDED", "REJECTED")


def assert_warranty_claim(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("device_id", ""))
    assert data["component_category"] in (
        "CHAMBER", "PUMP", "ELECTRONICS", "STRUCTURAL",
    )
    assert data["proration_variant"] in ("TIME_BASED", "NIGHTS_USED")
    assert isinstance(data["months_in_service"], int)
    assert isinstance(data["final_nights_used"], int)
    assert data["status"] in ("FILED", "APPROVED", "DENIED", "APPEALED")


def assert_financing_plan(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert data["offer_type"] in ("ZERO_APR", "DEFERRED_INTEREST", "STANDARD")
    assert data["term_months"] in (12, 24, 36)
    assert isinstance(data["principal_cents"], int)
    assert isinstance(data["monthly_payment_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert isinstance(data["balance_cents"], int)
    assert data["status"] in (
        "OFFERED", "ACCEPTED", "ACTIVE", "DELINQUENT", "PAID_OFF",
        "SETTLED_EARLY", "DEFAULTED", "VOIDED",
    )
