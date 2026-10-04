"""Entity assertions and domain invariant checkers.

``assert_<entity>`` checks the wire shape of one resource: identifier and
timestamp formats, enum membership, and the presence of the fields the
contract declares. Invariant checkers cover cross-field rules such as the
coin ledger balance and store refund ledgers.
"""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_mutable_common_fields(data: dict, entity: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer"
    )


def assert_category(data: dict) -> None:
    _assert_mutable_common_fields(data, "Category")
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["sku_cap"], int) and 1 <= data["sku_cap"] <= 5
    assert isinstance(data["active_sku_count"], int) and data["active_sku_count"] >= 0
    assert data["status"] in ("OPEN", "LOCKED")


def assert_supplier(data: dict) -> None:
    _assert_mutable_common_fields(data, "Supplier")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["quality_score"], (int, float))
    assert 0 <= data["quality_score"] <= 100
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_product(data: dict) -> None:
    _assert_mutable_common_fields(data, "Product")
    assert isinstance(data["category_id"], str) and data["category_id"]
    assert isinstance(data["sku_code"], str) and data["sku_code"]
    assert data["kind"] in ("CORE", "FINDS")
    assert isinstance(data["shelf_ready_packaging"], bool)
    assert isinstance(data["barcode_count"], int) and data["barcode_count"] >= 1
    assert isinstance(data["unit_cost_cents"], int)
    assert isinstance(data["price_cents"], int)
    assert data["primary_supplier_id"] is None or isinstance(data["primary_supplier_id"], str)
    assert data["secondary_supplier_id"] is None or isinstance(data["secondary_supplier_id"], str)
    if data["primary_supplier_id"] is not None and data["secondary_supplier_id"] is not None:
        assert data["primary_supplier_id"] != data["secondary_supplier_id"], (
            "dual-source rule: secondary supplier must differ from primary"
        )
    assert data["status"] in ("PROPOSED", "ACTIVE", "DISCONTINUED")


def assert_tender(data: dict) -> None:
    _assert_mutable_common_fields(data, "SupplierTender")
    assert isinstance(data["product_id"], str) and data["product_id"]
    assert isinstance(data["bid_ceiling_cents"], int)
    assert isinstance(data["min_sources"], int)
    assert data["status"] in ("DRAFT", "OPEN", "CLOSED", "EVALUATING", "AWARDED", "CANCELLED")
    assert data["winning_primary_bid_id"] is None or isinstance(data["winning_primary_bid_id"], str)
    assert data["winning_secondary_bid_id"] is None or isinstance(data["winning_secondary_bid_id"], str)


def assert_bid(data: dict) -> None:
    _assert_mutable_common_fields(data, "TenderBid")
    assert isinstance(data["tender_id"], str) and data["tender_id"]
    assert isinstance(data["supplier_id"], str) and data["supplier_id"]
    assert isinstance(data["unit_cost_cents"], int)
    assert data["award_score"] is None or isinstance(data["award_score"], (int, float))
    assert data["status"] in (
        "SUBMITTED", "ELIGIBLE", "DISQUALIFIED",
        "AWARDED_PRIMARY", "AWARDED_SECONDARY", "NOT_SELECTED",
    )


def assert_panel(data: dict) -> None:
    _assert_mutable_common_fields(data, "BlindQualityPanel")
    assert isinstance(data["bid_id"], str) and data["bid_id"]
    assert isinstance(data["sample_code"], str) and data["sample_code"]
    assert data["score"] is None or (isinstance(data["score"], int) and 0 <= data["score"] <= 100)
    assert data["status"] in ("SCHEDULED", "SCORED", "LOCKED")


def assert_store(data: dict) -> None:
    _assert_mutable_common_fields(data, "Store")
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["tier"] in ("STANDARD", "HIGH_VOLUME")
    assert isinstance(data["weekly_labor_budget_cents"], int)
    assert isinstance(data["coins_outstanding"], int)
    assert isinstance(data["coin_liability_cents"], int)
    assert isinstance(data["refund_liability_cents"], int)
    assert isinstance(data["refund_paid_cents"], int)
    assert isinstance(data["finds_sell_through_pct"], (int, float))
    assert data["status"] in ("ACTIVE", "CLOSED")


def assert_employee(data: dict) -> None:
    _assert_mutable_common_fields(data, "Employee")
    assert isinstance(data["store_id"], str) and data["store_id"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["role"] in ("CASHIER", "STOCKER", "SHIFT_LEAD")
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_finds_buy(data: dict) -> None:
    _assert_mutable_common_fields(data, "FindsBuy")
    assert isinstance(data["product_id"], str) and data["product_id"]
    assert isinstance(data["week_start_date"], str) and data["week_start_date"]
    assert isinstance(data["week_end_date"], str) and data["week_end_date"]
    assert data["week_end_date"] >= data["week_start_date"], (
        "week_end_date must not precede week_start_date"
    )
    assert isinstance(data["total_quantity"], int) and data["total_quantity"] >= 1
    assert isinstance(data["allocated_quantity"], int)
    assert isinstance(data["remaining_quantity"], int)
    assert data["status"] in ("PLANNED", "ALLOCATED", "ON_SALE", "SOLD_OUT", "CLOSED")


def assert_allocation(data: dict) -> None:
    _assert_mutable_common_fields(data, "FindsAllocation")
    assert isinstance(data["finds_buy_id"], str) and data["finds_buy_id"]
    assert isinstance(data["store_id"], str) and data["store_id"]
    assert isinstance(data["allocated_quantity"], int) and data["allocated_quantity"] >= 0
    assert isinstance(data["sold_quantity"], int) and data["sold_quantity"] >= 0
    assert isinstance(data["remaining_quantity"], int)
    assert data["remaining_quantity"] == data["allocated_quantity"] - data["sold_quantity"], (
        "remaining_quantity must equal allocated_quantity minus sold_quantity"
    )
    assert data["clearance_markdown_pct"] is None or isinstance(data["clearance_markdown_pct"], (int, float))
    assert data["clearance_value_cents"] is None or isinstance(data["clearance_value_cents"], int)
    assert data["status"] in ("RESERVED", "ON_SALE", "SOLD_OUT", "CLEARANCE", "CLOSED")


def assert_cart_coin_event(data: dict) -> None:
    """Append-only ledger entry: id and created_at only — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "CartCoinEvent.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), "CartCoinEvent.created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only ledger entry must not carry updated_at"
    assert "version" not in data, "append-only ledger entry must not carry version"
    assert isinstance(data["store_id"], str) and data["store_id"]
    assert data["event_type"] in ("INSERT", "RETURN", "CORRAL_COLLECT", "AUDIT_ADJUST")
    assert isinstance(data["coin_count"], int)


def assert_register_shift(data: dict) -> None:
    _assert_mutable_common_fields(data, "RegisterShift")
    assert isinstance(data["store_id"], str) and data["store_id"]
    assert isinstance(data["cashier_id"], str) and data["cashier_id"]
    assert is_iso8601_timestamp(data.get("started_at", "")), "started_at must be ISO 8601"
    assert data["closed_at"] is None or is_iso8601_timestamp(data["closed_at"])
    assert isinstance(data["items_scanned"], int) and data["items_scanned"] >= 0
    assert isinstance(data["voids"], int) and data["voids"] >= 0
    assert isinstance(data["provisional_scan_rate"], (int, float))
    assert data["final_scan_rate"] is None or isinstance(data["final_scan_rate"], (int, float))
    assert data["compliance"] is None or data["compliance"] in ("COMPLIANT", "BELOW_STANDARD")
    assert data["status"] in ("OPEN", "CLOSED")


def assert_labor_window(data: dict) -> None:
    _assert_mutable_common_fields(data, "LaborWindow")
    assert isinstance(data["store_id"], str) and data["store_id"]
    assert isinstance(data["aisle_zone"], str) and data["aisle_zone"]
    assert data["role"] in ("CASHIER", "STOCKER", "SHIFT_LEAD")
    assert is_iso8601_timestamp(data.get("starts_at", "")), "starts_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("ends_at", "")), "ends_at must be ISO 8601"
    assert isinstance(data["cost_cents"], int) and data["cost_cents"] >= 0
    assert data["status"] in ("PLANNED", "CONFIRMED", "CANCELLED")


def assert_claim(data: dict) -> None:
    _assert_mutable_common_fields(data, "QualityClaim")
    assert isinstance(data["product_id"], str) and data["product_id"]
    assert isinstance(data["store_id"], str) and data["store_id"]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["purchase_date"], str) and data["purchase_date"]
    assert data["reason"] in ("QUALITY_DEFECT", "DAMAGED", "OTHER")
    assert data["refund_amount_cents"] is None or isinstance(data["refund_amount_cents"], int)
    assert data["status"] in (
        "FILED", "UNDER_REVIEW", "DISPUTED", "APPROVED", "PAID", "REJECTED", "RESCINDED"
    )


# ── Domain invariants ─────────────────────────────────────────────────────


def assert_store_coin_invariants(data: dict) -> None:
    """Coin liability always equals outstanding coins times the quarter deposit."""
    assert data["coins_outstanding"] >= 0, "coins_outstanding must never go negative"
    assert data["coin_liability_cents"] == data["coins_outstanding"] * 25, (
        "coin_liability_cents must equal coins_outstanding * 25"
    )


def assert_store_refund_invariants(data: dict) -> None:
    """Refund ledgers never go negative."""
    assert data["refund_liability_cents"] >= 0, "refund_liability_cents must never go negative"
    assert data["refund_paid_cents"] >= 0, "refund_paid_cents must never go negative"


def assert_two_dp(value: float, expected: float, label: str = "value") -> None:
    """Rates and percentages are reported to exactly 2 decimal places, round-half-up."""
    assert value is not None, f"{label} must not be null"
    assert abs(float(value) - expected) < 0.005, (
        f"{label} must equal {expected} at 2 decimal places, got {value}"
    )
