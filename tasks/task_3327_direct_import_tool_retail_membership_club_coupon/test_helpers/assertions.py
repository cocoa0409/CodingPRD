"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_item(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["brand_tier"] in ("VALUE", "MID", "PROFESSIONAL")
    assert data["lifecycle_status"] in ("DRAFT", "ACTIVE", "QUARANTINED", "DISCONTINUED")
    assert isinstance(data["unit_retail_cents"], int) and data["unit_retail_cents"] > 0
    assert isinstance(data["member_price_cents"], int) and data["member_price_cents"] > 0
    assert data["member_price_cents"] <= data["unit_retail_cents"]
    assert isinstance(data["open_recall_count"], int) and data["open_recall_count"] >= 0


def assert_purchase_order(data: dict):
    _assert_common(data)
    assert isinstance(data["po_number"], str) and data["po_number"]
    assert data["status"] in ("DRAFT", "ISSUED", "PARTIALLY_RECEIVED", "RECEIVED", "CANCELLED")
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1


def assert_container(data: dict):
    _assert_common(data)
    assert isinstance(data["container_number"], str) and data["container_number"]
    assert data["status"] in ("BOOKED", "DEPARTED", "AT_PORT", "CUSTOMS_HOLD",
                              "CLEARED", "RECEIVED", "CANCELLED")
    assert isinstance(data["unallocated_quantities"], dict)


def assert_store(data: dict):
    _assert_common(data)
    assert isinstance(data["store_code"], str) and data["store_code"]
    assert data["format"] in ("SMALL_FORMAT", "STANDARD")
    assert data["market_tier"] in ("PRIMARY", "SECONDARY")
    assert isinstance(data["receiving_capacity_units"], int)
    assert data["receiving_capacity_units"] >= 1


def assert_allocation(data: dict):
    _assert_common(data)
    assert data["status"] in ("PLANNED", "COMMITTED", "RELEASED", "BLOCKED")
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["store_credit_cents"], int)
    assert data["store_credit_cents"] >= 0


def assert_membership(data: dict):
    _assert_common(data)
    assert data["tier"] in ("CLUB", "CLUB_PLUS")
    assert data["status"] in ("ACTIVE", "LAPSED", "CANCELLED")
    assert isinstance(data["settled_savings_cents"], int)
    assert isinstance(data["optimistic_savings_cents"], int)


def assert_coupon(data: dict):
    _assert_common(data)
    assert data["channel"] in ("PRINT", "EMAIL", "APP")
    assert data["audience"] in ("ALL", "MEMBERS_ONLY")
    assert data["discount_type"] in ("PERCENT_OFF_ITEM", "AMOUNT_OFF_ITEM",
                                     "PERCENT_OFF_BASKET", "FIXED_AMOUNT_OFF_BASKET")
    assert data["status"] in ("DRAFT", "ACTIVE", "PAUSED", "EXPIRED", "EXHAUSTED")
    assert isinstance(data["budget_spent_cents"], int)
    assert isinstance(data["budget_reserved_cents"], int)


def assert_sale(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "COMPLETED", "RETURNED_PARTIAL",
                              "RETURNED_FULL", "VOID")
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["coupon_discount_cents"], int)
    assert isinstance(data["total_cents"], int)


def assert_sale_line(data: dict):
    _assert_common(data)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["line_total_cents"], int)


def assert_warranty_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ("FILED", "UNDER_REVIEW", "APPROVED", "DENIED", "SETTLED")
    assert isinstance(data["appeal_count"], int) and data["appeal_count"] >= 0


def assert_recall(data: dict):
    _assert_common(data)
    assert data["severity"] in ("NOTICE", "STOP_SALE", "HAZARD")
    assert data["status"] in ("DRAFT", "ACTIVE", "CLOSED")
