"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AllocationStatus,
    AisleAssignmentStatus,
    ComparisonRule,
    ConditionGrade,
    DispositionAction,
    DispositionStatus,
    EventStatus,
    LotCommercialStatus,
    LotSafetyStatus,
    MemberTier,
    PerformanceTier,
    PricingVariant,
    PurchaseStatus,
    ScreeningResult,
    ScreeningStatus,
    SourceType,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_vendor(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["vendor_code"], str) and data["vendor_code"]


def assert_jurisdiction_rule(data: dict):
    _assert_common(data)
    assert isinstance(data["jurisdiction_code"], str) and data["jurisdiction_code"]
    assert data["comparison_rule"] in [r.value for r in ComparisonRule]
    assert isinstance(data["max_advertised_discount_pct"], int)
    assert isinstance(data["member_discount_cap_pct"], int)


def assert_store(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["store_code"], str) and data["store_code"]
    assert is_valid_uuid(data.get("jurisdiction_id", ""))
    assert data["performance_tier"] in [t.value for t in PerformanceTier]
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("vendor_id", ""))
    assert is_valid_uuid(data.get("home_jurisdiction_id", ""))
    assert data["source_type"] in [s.value for s in SourceType]
    assert data["condition_grade"] in [g.value for g in ConditionGrade]
    assert isinstance(data["quantity_total"], int) and data["quantity_total"] >= 1
    assert isinstance(data["total_cost_cents"], int)
    assert isinstance(data["est_sellable_qty"], int)
    assert isinstance(data["comparison_price_cents"], int)
    assert isinstance(data["vendor_msrp_cents"], int)
    assert isinstance(data["pace_target_units_per_week"], int)
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    assert data["safety_status"] in [s.value for s in LotSafetyStatus]
    assert data["commercial_status"] in [s.value for s in LotCommercialStatus]
    assert isinstance(data["landed_unit_cost_cents"], int)
    assert isinstance(data["markdown_rounds"], int)
    assert isinstance(data["qty_pool"], int)
    assert isinstance(data["qty_sold"], int)
    assert isinstance(data["qty_liquidated"], int)
    assert isinstance(data["qty_scrapped"], int)


def assert_screening(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("lot_id", ""))
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert isinstance(data["screener_user_id"], str) and data["screener_user_id"]
    assert data["status"] in [s.value for s in ScreeningStatus]
    if data["status"] == ScreeningStatus.COMPLETED.value:
        assert data["result"] in [r.value for r in ScreeningResult]


def assert_allocation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("lot_id", ""))
    assert is_valid_uuid(data.get("store_id", ""))
    assert isinstance(data["qty_requested"], int) and data["qty_requested"] >= 1
    assert isinstance(data["qty_granted"], int) and data["qty_granted"] >= 0
    assert isinstance(data["store_on_hand_qty"], int) and data["store_on_hand_qty"] >= 0
    assert data["status"] in [s.value for s in AllocationStatus]


def assert_aisle_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("store_id", ""))
    assert is_valid_uuid(data.get("lot_id", ""))
    assert isinstance(data["aisle_code"], str) and data["aisle_code"]
    assert isinstance(data["daily_unit_limit"], int) and data["daily_unit_limit"] >= 1
    assert is_iso8601_timestamp(data.get("valid_from", ""))
    assert data["status"] in [s.value for s in AisleAssignmentStatus]


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["member_code"], str) and data["member_code"]
    assert data["tier"] in [t.value for t in MemberTier]
    assert is_valid_uuid(data.get("home_store_id", ""))
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("lot_id", ""))
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert is_iso8601_timestamp(data.get("ends_at", ""))
    assert data["min_tier"] in [t.value for t in MemberTier]
    assert isinstance(data["extra_discount_pct"], int)
    assert data["status"] in [s.value for s in EventStatus]


def assert_purchase(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("store_id", ""))
    assert is_valid_uuid(data.get("lot_id", ""))
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert data["pricing_variant"] in [v.value for v in PricingVariant]
    assert isinstance(data["discount_pct_applied"], int)
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_total_cents"], int)
    assert data["status"] in [s.value for s in PurchaseStatus]


def assert_disposition(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("lot_id", ""))
    assert data["action"] in [a.value for a in DispositionAction]
    assert data["status"] in [s.value for s in DispositionStatus]


def assert_lot_unit_conservation(summary: dict, quantity_total: int):
    """quantity_total == pool + outstanding + sold + liquidated + scrapped."""
    total = (
        summary["qty_pool"]
        + summary["qty_allocated_outstanding"]
        + summary["qty_sold"]
        + summary["qty_liquidated"]
        + summary["qty_scrapped"]
    )
    assert total == quantity_total, (
        f"unit conservation violated: {summary['qty_pool']} + "
        f"{summary['qty_allocated_outstanding']} + {summary['qty_sold']} + "
        f"{summary['qty_liquidated']} + {summary['qty_scrapped']} != {quantity_total}"
    )
