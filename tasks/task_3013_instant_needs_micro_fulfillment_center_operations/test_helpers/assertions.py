"""Entity assertions and domain invariant checkers (Instant-Needs MFC)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    """System-managed fields every resource carries (PRD section 2.6)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_site(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["delivery_radius_miles"] > 0
    fee = data["fee_schedule"]
    for key in ("base_cents", "per_mile_cents", "included_miles",
                "peak_surcharge_cents", "min_fee_cents", "max_fee_cents"):
        assert key in fee, f"fee_schedule missing {key}"
    assert isinstance(data["fee_waiver_threshold_cents"], int) and data["fee_waiver_threshold_cents"] >= 0
    assert isinstance(data["batch_max_lines"], int) and data["batch_max_lines"] >= 1
    assert isinstance(data["batch_max_items"], int) and data["batch_max_items"] >= 1
    assert isinstance(data["expiry_horizon_days"], int) and data["expiry_horizon_days"] >= 0
    assert isinstance(data["peak_windows"], list)
    assert data["status"] in ("OPERATING", "SUSPENDED")
    assert data["effective_status"] in ("OPERATING", "SUSPENDED", "OPENED_REPLENISH")


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["price_cents"], int) and data["price_cents"] > 0
    assert data["product_class"] in ("STANDARD", "AGE_RESTRICTED", "PERISHABLE")
    assert data["restricted"] is (data["product_class"] == "AGE_RESTRICTED")
    assert data["perishable"] is (data["product_class"] == "PERISHABLE")
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_inventory_balance(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["site_id"])
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["on_hand"], int)
    assert isinstance(data["reserved"], int)
    assert isinstance(data["min_par_level"], int) and data["min_par_level"] >= 0
    assert isinstance(data["on_order"], int)


def assert_stock_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["site_id"])
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["lot_code"], str) and len(data["lot_code"]) > 0
    assert isinstance(data["received_qty"], int) and data["received_qty"] >= 1
    assert isinstance(data["remaining_qty"], int) and data["remaining_qty"] >= 0
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["status"] in ("FRESH", "EXPIRING", "EXPIRED")


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["wallet_credit_cents"], int) and data["wallet_credit_cents"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_membership(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert data["tier"] == "FAM"
    assert data["status"] in ("ACTIVE", "LAPSED", "CANCELLED")
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    assert is_iso8601_timestamp(data["current_period_start"])
    assert is_iso8601_timestamp(data["current_period_end"])
    assert isinstance(data["periods_paid"], int) and data["periods_paid"] >= 0
    assert isinstance(data["period_orders_count"], int) and data["period_orders_count"] >= 0
    assert isinstance(data["period_credit_earned_cents"], int) and data["period_credit_earned_cents"] >= 0
    assert isinstance(data["auto_renew"], bool)
    assert isinstance(data["tenure_discount_bps"], int) and data["tenure_discount_bps"] >= 0


def assert_replenish_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["site_id"])
    assert isinstance(data["reference"], str) and len(data["reference"]) > 0
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    assert is_iso8601_timestamp(data["expected_at"])
    assert data["status"] in ("DRAFT", "PLACED", "FINALIZED", "CANCELLED")
    assert isinstance(data["idempotency_key"], str) and len(data["idempotency_key"]) > 0


def assert_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["site_id"])
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    assert data["delivery_distance_miles"] >= 0
    assert isinstance(data["contains_age_restricted"], bool)
    assert isinstance(data["subtotal_cents"], int) and data["subtotal_cents"] >= 0
    assert isinstance(data["tax_cents"], int) and data["tax_cents"] >= 0
    assert isinstance(data["delivery_fee_cents"], int) and data["delivery_fee_cents"] >= 0
    assert isinstance(data["loyalty_credit_applied_cents"], int) and data["loyalty_credit_applied_cents"] >= 0
    assert isinstance(data["total_cents"], int)
    assert data["status"] in (
        "PLACED", "PICKING", "AWAITING_HANDOFF", "OUT_FOR_DELIVERY",
        "DELIVERED", "HANDOFF_FAILED", "CANCELLED",
    )


def assert_pick_batch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["site_id"])
    assert is_valid_uuid(data["picker_id"])
    assert isinstance(data["order_ids"], list)
    assert isinstance(data["total_items"], int) and data["total_items"] >= 0
    assert data["status"] in ("OPEN", "SEALED", "CLOSED")


def assert_picker(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["site_id"])
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_driver(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["site_id"])
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["max_run_orders"], int) and data["max_run_orders"] >= 1
    assert data["status"] in ("AVAILABLE", "OFF_DUTY", "SUSPENDED")


def assert_delivery_bag(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert data["delivery_status"] in ("UNASSIGNED", "ASSIGNED", "OUT_FOR_DELIVERY", "DELIVERED", "FAILED")
    assert data["handoff_status"] in ("NONE", "ID_SCANNED", "AGE_VERIFIED", "REFUSED")


def assert_order_money_invariants(order: dict):
    """PRD section 3.5: total is subtotal plus tax plus fee minus absorbed credit."""
    assert order["total_cents"] == (
        order["subtotal_cents"] + order["tax_cents"]
        + order["delivery_fee_cents"] - order["loyalty_credit_applied_cents"]
    ), "total_cents must equal subtotal + tax + fee - absorbed credit"
