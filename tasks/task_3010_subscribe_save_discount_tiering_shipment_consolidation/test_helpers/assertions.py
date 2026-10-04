"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_ACCOUNT_STATUSES = ["ACTIVE", "SUSPENDED", "CLOSED"]
_AVAILABILITY_STATUSES = ["IN_STOCK", "OUT_OF_STOCK", "DISCONTINUED"]
_SUBSCRIPTION_STATUSES = ["ACTIVE", "PAUSED", "PENDING_CANCEL", "CANCELLED"]
_PLAN_STATUSES = ["OPEN", "LOCKED", "SHIPPED", "DELIVERED", "RESOLVED", "CANCELLED"]
_LINE_STATUSES = ["SCHEDULED", "SKIPPED", "AUTO_SKIPPED", "SHIPPED", "REFUNDED", "RESHIPPED"]
_SKIP_REASONS = ["CUSTOMER", "PRICE_CAP", "UNAVAILABLE"]
_COUPON_STATUSES = ["ACTIVE", "DISABLED"]
_PROMOTION_STATUSES = ["ACTIVE", "DISABLED"]
_OFFER_STATUSES = ["OFFERED", "ACCEPTED", "DECLINED", "EXPIRED"]
_CLAIM_STATUSES = ["REPORTED", "APPROVED_RESHIP", "REJECTED", "COMPLETED"]
_RESHIPMENT_STATUSES = ["PENDING", "DISPATCHED", "DELIVERED"]
_NOTIFICATION_TYPES = [
    "OFFER_CREATED", "OFFER_EXPIRED", "PRICE_INCREASE",
    "PRICE_CAP_SKIP", "PLAN_SHIPPED", "RESHIP_DISPATCHED",
]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def _assert_append_only_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["region"], str) and data["region"]
    assert isinstance(data["preferred_delivery_day"], int)
    assert 1 <= data["preferred_delivery_day"] <= 28
    assert data["account_status"] in _ACCOUNT_STATUSES
    assert isinstance(data["credit_balance_cents"], int)
    assert data["credit_balance_cents"] >= 0


def assert_product(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region"], str) and data["region"]
    assert isinstance(data["subscription_eligible"], bool)
    assert isinstance(data["discontinued"], bool)
    assert data["availability_status"] in _AVAILABILITY_STATUSES
    if data.get("current_price_cents") is not None:
        assert isinstance(data["current_price_cents"], int)


def assert_price_event(data: dict):
    _assert_append_only_fields(data)
    assert "updated_at" not in data, "PriceEvent must not carry updated_at"
    assert "version" not in data, "PriceEvent must not carry version"
    assert isinstance(data["price_cents"], int) and data["price_cents"] > 0
    assert isinstance(data["effective_from"], str)


def assert_inventory_placement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["region"], str)
    for field in ("received_total_units", "on_hand_units", "reserved_units", "shipped_units"):
        assert isinstance(data[field], int) and data[field] >= 0


def assert_subscription(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["product_id"], str)
    assert 1 <= data["cadence_months"] <= 6
    assert 1 <= data["quantity"] <= 30
    assert isinstance(data["start_date"], str)
    assert isinstance(data["next_delivery_date"], str)
    assert data["status"] in _SUBSCRIPTION_STATUSES
    if data.get("price_cap_cents") is not None:
        assert isinstance(data["price_cap_cents"], int) and data["price_cap_cents"] > 0
    if data.get("subscribe_price_cents") is not None:
        assert isinstance(data["subscribe_price_cents"], int)


def assert_delivery_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["delivery_month"], str)
    assert isinstance(data["delivery_date"], str)
    assert data["plan_status"] in _PLAN_STATUSES
    assert isinstance(data["active_line_count"], int) and data["active_line_count"] >= 0
    assert data["tier_discount_pct"] in (0, 0.0, 0.05, 0.10)
    if data.get("estimated_total_cents") is not None:
        assert isinstance(data["estimated_total_cents"], int)
    if data.get("charged_total_cents") is not None:
        assert isinstance(data["charged_total_cents"], int)
    assert isinstance(data["gross_line_total_cents"], int)
    assert isinstance(data["refunded_total_cents"], int)
    assert isinstance(data["applied_coupon_codes"], list)


def assert_plan_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["is_bonus"], bool)
    assert isinstance(data["was_substituted"], bool)
    assert data["line_status"] in _LINE_STATUSES
    if data.get("skip_reason") is not None:
        assert data["skip_reason"] in _SKIP_REASONS


def assert_coupon(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert data["discount_type"] in ("PERCENT", "FLAT")
    assert data["coupon_status"] in _COUPON_STATUSES


def assert_promotion(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["bonus_product_id"], str)
    assert isinstance(data["min_line_count"], int)
    assert data["promotion_status"] in _PROMOTION_STATUSES


def assert_retention_offer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["subscription_id"], str)
    assert data["offer_type"] == "CREDIT"
    assert data["credit_amount_cents"] == 500
    assert data["offer_status"] in _OFFER_STATUSES
    assert isinstance(data["expires_on"], str)


def assert_damage_claim(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["damaged_line_ids"], list)
    assert data["claim_status"] in _CLAIM_STATUSES


def assert_reshipment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["claim_id"], str)
    assert isinstance(data["reshipped_line_ids"], list)
    assert data["reshipment_status"] in _RESHIPMENT_STATUSES


def assert_demand_forecast(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["region"], str)
    assert isinstance(data["forecast_month"], str)
    assert isinstance(data["committed_units"], int) and data["committed_units"] >= 0
    assert isinstance(data["provisional_units"], int) and data["provisional_units"] >= 0


def assert_notification(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["customer_id"], str)
    assert data["notification_type"] in _NOTIFICATION_TYPES
    assert isinstance(data["message"], str)


def assert_inventory_conservation(placement: dict):
    """PRD §2.10: received_total_units == on_hand + reserved + shipped."""
    total = (
        placement["on_hand_units"]
        + placement["reserved_units"]
        + placement["shipped_units"]
    )
    assert total == placement["received_total_units"], (
        f"Inventory conservation violated: {placement['on_hand_units']} + "
        f"{placement['reserved_units']} + {placement['shipped_units']} != "
        f"{placement['received_total_units']}"
    )


def assert_plan_money_invariant(plan: dict, lines: list):
    """PRD §3.9: gross == SHIPPED/RESHIPPED charges + refunded + still-SCHEDULED charges."""
    shipped_or_reshipped = sum(
        line["line_charged_cents"]
        for line in lines
        if line["line_status"] in ("SHIPPED", "RESHIPPED") and line["line_charged_cents"] is not None
    )
    still_scheduled = sum(
        line["line_charged_cents"]
        for line in lines
        if line["line_status"] == "SCHEDULED" and line["line_charged_cents"] is not None
    )
    expected = shipped_or_reshipped + plan["refunded_total_cents"] + still_scheduled
    assert plan["gross_line_total_cents"] == expected, (
        f"Money invariant violated: gross {plan['gross_line_total_cents']} != "
        f"{shipped_or_reshipped} + {plan['refunded_total_cents']} + {still_scheduled}"
    )
