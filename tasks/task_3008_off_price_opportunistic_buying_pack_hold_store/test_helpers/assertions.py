"""Entity assertions and domain invariant checkers (PRD §2.4 common fields)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_versioned(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def _assert_ledger(data: dict, entity: str):
    """Append-only ledger entities carry only id + created_at (no updated_at, no version)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity} must not carry updated_at"
    assert "version" not in data, f"{entity} must not carry version"


def assert_merchandise_season(data: dict):
    _assert_versioned(data, "MerchandiseSeason")
    assert isinstance(data["season_code"], str) and data["season_code"]
    assert data["status"] in ["DRAFT", "OPEN", "CLOSED"]
    for field in (
        "committed_forward_cents",
        "committed_packaway_cents",
        "spent_forward_cents",
        "spent_packaway_cents",
    ):
        assert isinstance(data[field], int) and data[field] >= 0


def assert_season_invariants(data: dict):
    """Open-to-buy ledger figures are non-negative integer cents."""
    assert data["committed_forward_cents"] >= 0
    assert data["committed_packaway_cents"] >= 0
    assert data["spent_forward_cents"] >= 0
    assert data["spent_packaway_cents"] >= 0


def assert_vendor(data: dict):
    _assert_versioned(data, "Vendor")
    assert data["discretion_level"] in ["STANDARD", "CONFIDENTIAL", "QUIET"]
    assert data["vendor_tier"] in ["A", "B", "C"]
    assert isinstance(data["ticket_discretion_required"], bool)


def assert_price_zone(data: dict):
    _assert_versioned(data, "PriceZone")
    assert data["zone_code"] in ["NE", "MW", "SE", "TX", "MT", "WC"]
    assert data["compare_at_multiplier"] > 1
    assert 1 <= data["markdown_cadence_weeks"] <= 8
    assert data["clearance_weeks"] > data["markdown_cadence_weeks"]
    assert data["clearance_weeks"] <= 52


def assert_lot(data: dict):
    _assert_versioned(data, "Lot")
    assert data["status"] in ["OFFERED", "EVALUATED", "ACCEPTED", "PASSED", "CANCELLED"]
    assert data["lot_type"] in ["CLOSEOUT", "CANCELLATION", "PACKAWAY"]
    assert data["disposition"] in ["IMMEDIATE", "PACKAWAY"]
    assert isinstance(data["mixed_lot"], bool)


def assert_lot_line(data: dict):
    _assert_versioned(data, "LotLine")
    assert data["department"] in ["APPAREL", "HOME", "BEAUTY", "ACCESSORIES"]
    assert data["quantity"] > 0


def assert_warehouse(data: dict):
    _assert_versioned(data, "Warehouse")
    assert data["pallet_capacity"] > 0
    assert data["monthly_holding_rate_per_pallet_cents"] >= 0


def assert_packaway_hold(data: dict):
    _assert_versioned(data, "PackawayHold")
    assert data["status"] in ["STORED", "AGING_REVIEW", "RELEASED", "LIQUIDATED"]
    assert data["age_bucket"] in ["FRESH", "AGING", "STALE"]
    assert isinstance(data["review_count"], int) and data["review_count"] >= 0
    assert isinstance(data["accrued_holding_cost_cents"], int) and data["accrued_holding_cost_cents"] >= 0


def assert_store(data: dict):
    _assert_versioned(data, "Store")
    assert data["cluster_code"] in ["URBAN_PREMIUM", "SUBURBAN_FAMILY", "VALUE_RURAL"]
    assert data["storage_capacity_units"] > 0
    assert isinstance(data["clearance_outlet"], bool)


def assert_allocation_plan(data: dict):
    _assert_versioned(data, "AllocationPlan")
    assert data["status"] in ["DRAFT", "APPROVED", "EXECUTED", "SUPERSEDED", "CANCELLED"]
    assert data["total_units"] > 0


def assert_store_sku(data: dict):
    _assert_versioned(data, "StoreSku")
    assert data["status"] in ["ON_FLOOR", "MARKED_DOWN", "CLEARANCE", "SOLD_OUT", "LIQUIDATED"]
    assert isinstance(data["units_on_hand"], int) and data["units_on_hand"] >= 0


def assert_ticket(data: dict):
    _assert_ledger(data, "Ticket")
    assert data["status"] in ["ACTIVE", "VOIDED"]
    assert isinstance(data["ticket_retail_cents"], int)
    assert isinstance(data["compare_at_omitted"], bool)
    assert isinstance(data["vendor_name_on_ticket"], bool)


def assert_receipt(data: dict):
    _assert_versioned(data, "Receipt")
    assert data["status"] in ["OPEN", "RECEIVED"]


def assert_receipt_line(data: dict):
    _assert_ledger(data, "ReceiptLine")
    assert isinstance(data["declared_qty"], int) and data["declared_qty"] > 0


def assert_shrink_case(data: dict):
    _assert_versioned(data, "ShrinkCase")
    assert data["status"] in ["OPEN", "CONFIRMED", "VOIDED"]
    assert data["shrink_type"] in [
        "UNSCANNED_UNIT",
        "MIXED_LOT_OVERAGE",
        "MIXED_LOT_SHORTAGE",
        "DAMAGE",
    ]
    assert data["merge_mode"] in ["FIFO", "HIGH_VALUE_SORT"]


def assert_liquidation_order(data: dict):
    _assert_versioned(data, "LiquidationOrder")
    assert data["status"] in ["DRAFT", "APPROVED", "EXECUTED", "CANCELLED"]
    assert data["reason"] in ["CLEARANCE_WEEKS_EXCEEDED", "PACKAWAY_STALE"]


def assert_markdown_event(data: dict):
    _assert_ledger(data, "MarkdownEvent")
    assert data["event_type"] in ["CADENCE", "FORCE_CLEARANCE"]
    assert data["markdown_cents"] == data["old_price_cents"] - data["new_price_cents"]
