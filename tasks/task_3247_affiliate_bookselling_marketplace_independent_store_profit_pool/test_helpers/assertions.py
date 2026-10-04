"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    BookFormat,
    BookStatus,
    FulfillmentStatus,
    LedgerKind,
    ListStatus,
    PartnerKind,
    PartnerStatus,
    PaymentStatus,
    PoolStatus,
    PromotionStatus,
    PublisherStatus,
    ReasonCode,
    ReturnStatus,
    ShareMode,
    StoreStatus,
    TicketStatus,
)


def _assert_common(data: dict, versioned: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    if versioned:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            "updated_at must be ISO 8601"
        )
        assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_publisher(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert 0.0 <= data["discount_pct"] <= 0.60
    assert isinstance(data["returns_allowed"], bool)
    assert isinstance(data["return_window_days"], int)
    assert 0.0 <= data["return_credit_pct"] <= 1.0
    assert data["status"] in {s.value for s in PublisherStatus}


def assert_book(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("publisher_id", ""))
    assert isinstance(data["isbn"], str) and data["isbn"]
    assert data["format"] in {f.value for f in BookFormat}
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] > 0
    assert data["status"] in {s.value for s in BookStatus}
    if data["format"] == "PRINT":
        assert data.get("ebook_partner_rev_share_pct") in (None,)
    else:
        share = data.get("ebook_partner_rev_share_pct")
        assert share is not None and 0.0 <= share <= 0.50


def assert_store(data: dict):
    _assert_common(data)
    assert isinstance(data["shop_name"], str) and data["shop_name"]
    assert isinstance(data["slug"], str) and data["slug"]
    assert 0.10 <= data["commission_pct"] <= 0.30
    assert isinstance(data["pool_opt_in"], bool)
    assert data["payout_threshold_cents"] >= 2500
    assert data["status"] in {s.value for s in StoreStatus}
    assert isinstance(data["accrued_balance_cents"], int)


def assert_partner(data: dict):
    _assert_common(data)
    assert data["partner_kind"] in {k.value for k in PartnerKind}
    assert 0.05 <= data["commission_pct"] <= 0.15
    assert data["payout_threshold_cents"] >= 1000
    assert data["status"] in {s.value for s in PartnerStatus}
    assert isinstance(data["accrued_balance_cents"], int)


def assert_book_list(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("owner_store_id", ""))
    assert isinstance(data["title"], str)
    assert isinstance(data["items"], list)
    assert data["status"] in {s.value for s in ListStatus}
    assert isinstance(data["publish_count"], int) and data["publish_count"] >= 0


def assert_priced_line(line: dict):
    assert isinstance(line["quantity"], int) and line["quantity"] >= 1
    assert isinstance(line["unit_price_cents"], int)
    assert isinstance(line["line_total_cents"], int)
    assert isinstance(line["wholesale_unit_cents"], int)
    assert isinstance(line["returned_quantity"], int) and line["returned_quantity"] >= 0


def assert_order(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str) and data["customer_id"]
    store_attr = data.get("attributed_store_id")
    partner_attr = data.get("attributed_partner_id")
    assert (store_attr is None) != (partner_attr is None), (
        "exactly one attribution must be set"
    )
    assert data["payment_status"] in {s.value for s in PaymentStatus}
    assert data["fulfillment_status"] in {s.value for s in FulfillmentStatus}
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["wholesale_cost_cents"], int)
    assert isinstance(data["platform_margin_cents"], int)
    assert isinstance(data["commission_cents"], int)
    assert isinstance(data["refunded_cents"], int)
    assert isinstance(data["retained_cents"], int)


def assert_return_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert isinstance(data["line_index"], int) and data["line_index"] >= 0
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["reason_code"] in {r.value for r in ReasonCode}
    assert data["status"] in {s.value for s in ReturnStatus}


def assert_ledger_entry(data: dict):
    # Append-only ledger: only id + created_at, no updated_at / version.
    _assert_common(data, versioned=False)
    assert "updated_at" not in data, "ledger entries carry no updated_at"
    assert "version" not in data, "ledger entries carry no version"
    store_attr = data.get("affiliate_store_id")
    partner_attr = data.get("affiliate_partner_id")
    assert (store_attr is None) != (partner_attr is None), (
        "exactly one beneficiary must be set"
    )
    assert data["kind"] in {k.value for k in LedgerKind}
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["reversed"], bool)


def assert_pool_distribution(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("period_start", ""))
    assert is_iso8601_timestamp(data.get("period_end", ""))
    assert isinstance(data["pool_cents"], int) and data["pool_cents"] > 0
    assert data["share_mode"] in {m.value for m in ShareMode}
    assert data["status"] in {s.value for s in PoolStatus}
    assert isinstance(data["eligible_store_count"], int)
    assert isinstance(data["remainder_cents"], int)
    assert isinstance(data["share_lines"], list)


def assert_payout(data: dict):
    _assert_common(data)
    store_attr = data.get("affiliate_store_id")
    partner_attr = data.get("affiliate_partner_id")
    assert (store_attr is None) != (partner_attr is None)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in {"PENDING", "PROCESSING", "PAID", "FAILED"}


def assert_ticket(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert isinstance(data["opened_by_customer_id"], str)
    assert data["issue_kind"] in {
        "LATE_SHIPMENT",
        "DAMAGED_ITEM",
        "WRONG_ITEM",
        "BILLING",
    }
    assert data["status"] in {s.value for s in TicketStatus}


def assert_promotion(data: dict):
    _assert_common(data)
    assert isinstance(data["book_isbn"], str) and data["book_isbn"]
    assert 0.05 <= data["discount_pct"] <= 0.40
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert data["status"] in {s.value for s in PromotionStatus}


def assert_order_money_invariants(order: dict):
    """Domain invariants that must hold on every order read."""
    assert order["retained_cents"] == order["gross_cents"] - order["refunded_cents"], (
        "retained_cents always equals gross_cents minus refunded_cents"
    )
    assert order["refunded_cents"] >= 0
    assert order["gross_cents"] >= 0
