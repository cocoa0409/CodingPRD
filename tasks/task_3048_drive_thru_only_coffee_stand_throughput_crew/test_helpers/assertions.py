"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

STAND_STATUSES = ["PROPOSED", "APPROVED", "OPEN", "THROTTLED", "SUSPENDED", "CLOSED"]
AGREEMENT_STATUSES = ["NOMINATED", "APPROVED", "ACTIVE", "SUSPENDED", "TERMINATED"]
RECIPE_CHANNELS = ["CORE", "SEASONAL", "SECRET"]
RECIPE_STATUSES = ["ACTIVE", "RETIRED"]
DISTRIBUTION_STATUSES = ["STAGED", "ACTIVATED", "SUSPENDED", "WITHDRAWN"]
LOYALTY_TIERS = ["NONE", "SILVER", "GOLD"]
SHIFT_STATUSES = ["DRAFT", "PUBLISHED", "IN_PROGRESS", "RECONCILED", "LOCKED"]
ASSIGNMENT_STATUSES = ["ASSIGNED", "CHECKED_IN", "NO_SHOW", "CANCELLED"]
ASSIGNMENT_ROLES = ["TAKER", "BAR", "RUNNER", "LEAD"]
ORDER_SOURCES = ["WINDOW", "LOYALTY_APP"]
ORDER_QUEUE_STATUSES = ["QUEUED", "MERGED", "AT_WINDOW", "SERVED", "ABANDONED"]
ORDER_PAYMENT_STATUSES = [
    "UNPAID", "AUTHORIZED", "CAPTURED", "REFUND_PENDING", "REFUNDED", "VOIDED",
]
ORDER_BUILD_STATUSES = ["QUEUED", "BUILDING", "READY", "HANDED_OFF"]
ORDER_ITEM_BUILD_STATUSES = ["PENDING", "BUILDING", "READY", "CANCELLED"]
PAYMENT_STATUSES = ["AUTHORIZED", "CAPTURED", "REFUND_PENDING", "REFUNDED", "VOIDED"]
WINDOW_STATUSES = ["OPEN", "CLOSED_PASS", "CLOSED_BREACH"]


def _assert_common_fields(data: dict):
    """PRD §2.4: every resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')}"
    )


def assert_region(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["code"], str) and data["code"]


def assert_stand(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("region_id", "")), "region_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["min_ingress_gap_seconds"], int)
    assert isinstance(data["lane_configs"], list) and 1 <= len(data["lane_configs"]) <= 2
    assert data["status"] in STAND_STATUSES
    assert isinstance(data["consecutive_breach_windows"], int)
    assert isinstance(data["lane_occupancy"], dict)


def assert_crew_member(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert is_valid_uuid(data.get("home_stand_id", "")), "home_stand_id must be a UUID"
    assert isinstance(data["hired_on"], str) and data["hired_on"]
    assert isinstance(data["food_handler_cert_expires_on"], str)


def assert_agreement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("stand_id", ""))
    assert is_valid_uuid(data.get("crew_member_id", ""))
    assert 0 < data["revenue_share_pct"] < 1
    assert data["status"] in AGREEMENT_STATUSES


def assert_recipe(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["channel"] in RECIPE_CHANNELS
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 1
    assert isinstance(data["base_build_seconds"], int) and data["base_build_seconds"] >= 1
    assert data["temperature_class"] in ["HOT", "ICED", "BLENDED"]
    assert data["status"] in RECIPE_STATUSES


def assert_distribution(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("recipe_id", ""))
    assert is_valid_uuid(data.get("stand_id", ""))
    assert data["status"] in DISTRIBUTION_STATUSES


def assert_loyalty_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert is_valid_uuid(data.get("home_stand_id", ""))
    assert isinstance(data["points"], int) and data["points"] >= 0
    assert data["tier"] in LOYALTY_TIERS
    assert isinstance(data["lifetime_captured_cents"], int)


def assert_shift(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("stand_id", ""))
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert is_iso8601_timestamp(data.get("ends_at", ""))
    assert isinstance(data["is_peak"], bool)
    assert data["status"] in SHIFT_STATUSES


def assert_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("shift_id", ""))
    assert is_valid_uuid(data.get("crew_member_id", ""))
    assert data["role"] in ASSIGNMENT_ROLES
    assert data["status"] in ASSIGNMENT_STATUSES


def assert_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("stand_id", ""))
    assert data["source"] in ORDER_SOURCES
    assert data["queue_status"] in ORDER_QUEUE_STATUSES
    assert data["payment_status"] in ORDER_PAYMENT_STATUSES
    assert data["build_status"] in ORDER_BUILD_STATUSES
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["discount_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["outstanding_build_seconds"], int)
    # Order-level arithmetic invariant: total = subtotal - discount (PRD §3.6)
    assert data["total_cents"] == data["subtotal_cents"] - data["discount_cents"], (
        f"total {data['total_cents']} != subtotal {data['subtotal_cents']} "
        f"- discount {data['discount_cents']}"
    )


def assert_order_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("recipe_id", ""))
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["modifier_names"], list)
    assert data["build_status"] in ORDER_ITEM_BUILD_STATUSES
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_gross_cents"], int)
    assert isinstance(data["line_discount_cents"], int)
    assert isinstance(data["line_net_cents"], int)
    assert isinstance(data["build_time_seconds"], int)


def assert_payment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert data["status"] in PAYMENT_STATUSES
    assert isinstance(data["authorized_cents"], int)
    assert isinstance(data["captured_cents"], int)
    assert isinstance(data["refunded_cents"], int)
    # PRD §3.7: cumulative refunds never exceed the captured amount
    assert data["refunded_cents"] <= data["captured_cents"], (
        f"refunded {data['refunded_cents']} > captured {data['captured_cents']}"
    )


def assert_window(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("stand_id", ""))
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert is_iso8601_timestamp(data.get("ends_at", ""))
    assert isinstance(data["target_cars"], int)
    assert data["status"] in WINDOW_STATUSES
