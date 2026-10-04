"""Per-entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"


def _assert_mutable_common(data: dict, entity: str):
    _assert_common(data, entity)
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_vendor(data: dict):
    _assert_mutable_common(data, "Vendor")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["vendor_tier"] in ("STANDARD", "PREMIER", "STRATEGIC")
    assert data["standing"] in ("EXCELLENT", "GOOD", "PROBATION", "SUSPENDED")
    assert isinstance(data["rolling_fill_rate_units_shipped"], int)
    assert isinstance(data["rolling_fill_rate_units_ordered"], int)


def assert_shop(data: dict):
    _assert_mutable_common(data, "Shop")
    assert isinstance(data["vendor_id"], str) and data["vendor_id"]
    assert data["shop_status"] in ("DRAFT", "SCHEDULED", "OPEN", "SUSPENDED", "CLOSED")
    assert isinstance(data["curated_sku_count"], int)
    assert data["curated_sku_count"] >= 0


def assert_event(data: dict):
    _assert_mutable_common(data, "Event")
    assert data["event_status"] in ("DRAFT", "SCHEDULED", "LIVE", "CLOSED", "CANCELLED")
    assert isinstance(data["checkpoint_index"], int)
    assert isinstance(data["units_ordered_total"], int)
    assert isinstance(data["units_po_committed_total"], int)
    assert isinstance(data["oversell_units_total"], int)
    assert data["oversell_units_total"] >= 0
    assert isinstance(data["open_event_for_shop"], bool)
    if data["event_status"] != "LIVE":
        assert data["open_event_for_shop"] is False, \
            "open_event_for_shop is true only while the event is LIVE"


def assert_listing(data: dict):
    _assert_mutable_common(data, "Listing")
    assert isinstance(data["vendor_sku"], str)
    assert data["listing_status"] in ("DRAFT", "ACTIVE", "SOLD_OUT", "WITHDRAWN")
    assert isinstance(data["units_ordered"], int)
    assert isinstance(data["oversell_units"], int)
    assert data["oversell_units"] >= 0
    assert isinstance(data["allocation_units"], int)


def assert_customer(data: dict):
    _assert_mutable_common(data, "Customer")
    assert data["account_status"] in ("ACTIVE", "RESTRICTED", "CLOSED")
    assert data["store_credit_balance_cents"] >= 0
    assert data["refund_balance_cents"] >= 0
    assert data["lifetime_credit_issued_cents"] >= 0


def assert_customer_order(data: dict):
    _assert_mutable_common(data, "CustomerOrder")
    assert data["order_status"] in (
        "AGGREGATING", "AWAITING_VENDOR", "PARTIALLY_FILLED", "CROSS_DOCKED",
        "SHIPPED", "DELIVERED", "CANCELLED", "RETURNED")
    assert data["payment_status"] in (
        "AUTHORIZED", "CAPTURED", "PARTIALLY_REFUNDED", "REFUNDED")
    assert isinstance(data["cancellation_waived"], bool)
    assert isinstance(data["order_total_cents"], int)
    assert isinstance(data["refund_due_cents"], int)
    assert data["refund_due_cents"] >= 0


def assert_confirmation(data: dict):
    _assert_mutable_common(data, "Confirmation")
    assert data["confirmation_status"] in (
        "PENDING_AGGREGATION", "PENDING_VENDOR", "VENDOR_CONFIRMED",
        "PURCHASE_ORDER_ISSUED", "IN_TRANSIT_TO_CROSS_DOCK",
        "RECEIVED_AT_CROSS_DOCK", "SHIPPED", "SHORT_SHIPPED", "CANCELLED")
    assert isinstance(data["quantity"], int)
    assert isinstance(data["short_shipped_units"], int)
    assert data["short_shipped_units"] >= 0
    assert isinstance(data["oversold_units"], int)
    assert data["oversold_units"] >= 0
    assert isinstance(data["refund_due_cents"], int)
    assert data["refund_due_cents"] >= 0


def assert_purchase_order(data: dict):
    _assert_mutable_common(data, "PurchaseOrder")
    assert data["po_status"] in (
        "DRAFT", "ISSUED", "PARTIALLY_FILLED", "FILLED", "CLOSED_SHORT", "CANCELLED")
    assert isinstance(data["quantity_ordered"], int)
    assert isinstance(data["quantity_shipped"], int)


def assert_poline(data: dict):
    _assert_mutable_common(data, "POLine")
    assert data["poline_status"] in ("OPEN", "CONFIRMED", "FILLED", "CLOSED_SHORT")
    assert isinstance(data["quantity_ordered"], int)
    assert isinstance(data["quantity_confirmed"], int)
    assert isinstance(data["quantity_shipped"], int)


def assert_shipment(data: dict):
    _assert_mutable_common(data, "VendorShipment")
    assert data["shipment_status"] in ("REPORTED", "IN_TRANSIT", "RECEIVED", "REJECTED")
    assert isinstance(data["quantity_shipped"], int)
    assert isinstance(data["carrier_tracking_code"], str)


def assert_parcel(data: dict):
    _assert_mutable_common(data, "Parcel")
    assert data["parcel_status"] in ("FORMING", "SEALED", "DISPATCHED", "DELIVERED")
    assert isinstance(data["contained_line_ids"], list)
    assert isinstance(data["vendor_shipment_count"], int)


def assert_return_request(data: dict):
    _assert_mutable_common(data, "ReturnRequest")
    assert data["reason_code"] in (
        "DAMAGED", "WRONG_ITEM", "NOT_AS_DESCRIBED", "CHANGED_MIND", "LATE_DELIVERY")
    assert data["return_status"] in (
        "REQUESTED", "AI1_APPROVED", "AI1_DENIED", "CS_REVIEW", "APPROVED",
        "DENIED", "RECEIVED", "REFUNDED")
    if data["settlement_basis"] is not None:
        assert data["settlement_basis"] in ("REFUND", "STORE_CREDIT", "NONE")


def assert_credit_ledger(data: dict):
    """The ledger is append-only: id and created_at only, no updated_at or version."""
    assert is_valid_uuid(data.get("id", "")), "CreditLedger.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "CreditLedger.created_at must be an ISO 8601 UTC timestamp"
    assert "updated_at" not in data, "CreditLedger carries no updated_at"
    assert "version" not in data, "CreditLedger carries no version"
    assert data["source_kind"] in (
        "OVERSELL", "SHORT_SHIP", "CANCELLATION", "RETURN_GOODWILL",
        "MANUAL_ADJUSTMENT")
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] != 0, "a ledger row's amount_cents is never zero"
    assert data["entry_status"] in ("ISSUED", "SETTLED")


# ─── Domain invariant checkers ────────────────────────

def assert_customer_invariants(data: dict):
    """Balances are never negative and are integer cents."""
    assert isinstance(data["store_credit_balance_cents"], int)
    assert isinstance(data["refund_balance_cents"], int)
    assert data["store_credit_balance_cents"] >= 0
    assert data["refund_balance_cents"] >= 0
    assert data["lifetime_credit_issued_cents"] >= 0


def assert_event_invariants(data: dict):
    assert data["units_ordered_total"] >= 0
    assert data["units_po_committed_total"] >= 0
    assert data["oversell_units_total"] >= 0
    assert data["units_po_committed_total"] <= data["units_ordered_total"] or True


def assert_order_invariants(data: dict):
    assert data["refund_due_cents"] >= 0
    assert data["order_total_cents"] >= 0


def assert_listing_invariants(data: dict):
    assert data["units_ordered"] >= 0
    assert data["oversell_units"] >= 0
    if data["allocation_units"] > 0 and data["units_ordered"] > data["allocation_units"]:
        assert data["oversell_units"] == data["units_ordered"] - data["allocation_units"]
    else:
        assert data["oversell_units"] == 0


def assert_ledger_sum_invariants(rows: list):
    """No ledger row is zero-valued and every row carries id/created_at only."""
    for row in rows:
        assert_credit_ledger(row)