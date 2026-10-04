"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)

from .types import (
    MemberStatus,
    TradeAccountStatus,
    ProductStatus,
    LineKind,
    SourceBookStatus,
    OrderStatus,
    PricingTier,
    FabricTier,
    ProductionStatus,
    ProductionSlotStatus,
    ConsultationStatus,
    AppointmentStatus,
    ReturnStatus,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["auto_renew"], bool)
    assert data["status"] in [s.value for s in MemberStatus]
    assert is_iso8601_timestamp(data["current_period_start"])
    assert is_iso8601_timestamp(data["current_period_end"])
    assert data.get("grace_end") is None or is_iso8601_timestamp(data["grace_end"])
    assert isinstance(data["fee_paid_total_cents"], int)
    assert isinstance(data["lifetime_gross_savings_cents"], int)
    assert isinstance(data["lifetime_net_savings_cents"], int)
    assert data["pricing_tier"] in [t.value for t in PricingTier]


def assert_trade_account(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["business_name"], str) and len(data["business_name"]) > 0
    assert isinstance(data["credential_document_id"], str)
    assert isinstance(data["license_number"], str)
    assert data["status"] in [s.value for s in TradeAccountStatus]
    assert data.get("tier") is None or data["tier"] in ["TIER_1", "TIER_2"]
    assert data.get("decided_at") is None or is_iso8601_timestamp(data["decided_at"])


def assert_gallery(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["region"], str) and len(data["region"]) > 0
    assert isinstance(data["daily_route_minutes_capacity"], int)
    assert data["daily_route_minutes_capacity"] >= 0
    assert isinstance(data["booked_route_minutes"], dict)
    assert isinstance(data["reserved_production_minutes"], int)


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["list_price_cents"], int)
    assert_cost_precision(data["list_price_cents"])
    assert data["line_kind"] in [k.value for k in LineKind]
    assert data["status"] in [s.value for s in ProductStatus]
    assert isinstance(data["promo_active"], bool)


def assert_source_book(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert isinstance(data["product_ids"], list)
    assert is_iso8601_timestamp(data["print_ready_date"])
    assert data["status"] in [s.value for s in SourceBookStatus]
    assert data.get("released_at") is None or is_iso8601_timestamp(data["released_at"])


def assert_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("gallery_id", "")), "gallery_id must be a UUID"
    assert data.get("member_id") is None or is_valid_uuid(data["member_id"])
    assert data.get("trade_account_id") is None or is_valid_uuid(data["trade_account_id"])
    assert data["pricing_tier"] in [t.value for t in PricingTier]
    assert data["status"] in [s.value for s in OrderStatus]
    assert is_iso8601_timestamp(data["quote_expires_at"])
    assert isinstance(data["consultation_extensions_used"], int)
    for field in (
        "quote_total_cents",
        "subtotal_cents",
        "white_glove_fee_cents",
        "total_cents",
        "deposit_due_cents",
        "deposit_paid_cents",
        "cancel_refund_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"
        assert_cost_precision(data[field])
    assert data.get("confirmed_at") is None or is_iso8601_timestamp(data["confirmed_at"])
    assert data.get("delivered_at") is None or is_iso8601_timestamp(data["delivered_at"])


def assert_order_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert data["fabric_tier"] in [f.value for f in FabricTier]
    assert isinstance(data["unit_list_price_cents"], int)
    assert_cost_precision(data["unit_list_price_cents"])
    assert isinstance(data["line_charged_cents"], int)
    assert_cost_precision(data["line_charged_cents"])
    assert data["production_status"] in [s.value for s in ProductionStatus]
    assert data.get("production_slot_id") is None or is_valid_uuid(data["production_slot_id"])
    assert isinstance(data["deposit_cents"], int)
    assert_cost_precision(data["deposit_cents"])


def assert_production_slot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("gallery_id", "")), "gallery_id must be a UUID"
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert data["status"] in [s.value for s in ProductionSlotStatus]
    assert data.get("committed_order_line_id") is None or is_valid_uuid(
        data["committed_order_line_id"]
    )


def assert_design_consultation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be a UUID"
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert is_iso8601_timestamp(data["scheduled_at"])
    assert data["status"] in [s.value for s in ConsultationStatus]
    assert data.get("design_plan_notes") is None or isinstance(data["design_plan_notes"], str)
    assert data.get("completed_at") is None or is_iso8601_timestamp(data["completed_at"])


def assert_delivery_appointment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert is_valid_uuid(data.get("gallery_id", "")), "gallery_id must be a UUID"
    assert isinstance(data["delivery_date"], str) and len(data["delivery_date"]) == 10
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] >= 1
    assert isinstance(data["room_placement"], bool)
    assert isinstance(data["assembly_required"], bool)
    assert isinstance(data["packaging_removed"], bool)
    assert data["status"] in [s.value for s in AppointmentStatus]
    assert data.get("failure_reason") is None or isinstance(data["failure_reason"], str)
    assert data.get("replaced_by_id") is None or is_valid_uuid(data["replaced_by_id"])


def assert_return_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert isinstance(data["order_line_ids"], list)
    assert data["status"] in [s.value for s in ReturnStatus]
    assert isinstance(data["restocking_fee_cents"], int)
    assert_cost_precision(data["restocking_fee_cents"])
    assert isinstance(data["refund_cents"], int)
    assert_cost_precision(data["refund_cents"])
    assert data.get("reason") is None or isinstance(data["reason"], str)
    assert data.get("decided_at") is None or is_iso8601_timestamp(data["decided_at"])


def assert_member_savings_invariants(member: dict):
    """lifetime_net_savings_cents is always gross minus fee_paid_total (PRD §3.1)."""
    assert (
        member["lifetime_net_savings_cents"]
        == member["lifetime_gross_savings_cents"] - member["fee_paid_total_cents"]
    ), "net savings must equal gross savings minus fees paid"
