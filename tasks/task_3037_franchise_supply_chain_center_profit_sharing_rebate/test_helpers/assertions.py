"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AgreementStatus,
    AgreementType,
    CapacityPlanStatus,
    CenterPosture,
    ComplianceTier,
    DayOfWeek,
    LedgerEntryType,
    LedgerStatus,
    OrderLineStatus,
    PriceBookStatus,
    ProductCategory,
    ProductStatus,
    PromotionStatus,
    PurchaseOrderStatus,
    RebateEligibility,
    RebatePoolStatus,
    RouteStatus,
    StopStatus,
    StoreStatus,
    StoreTier,
    SupplyCenterStatus,
    VarianceSeverity,
    VarianceStatus,
)


def _assert_common(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}: id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}: created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}: updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, f"{label}: version must be a positive int"


def assert_supply_center(data: dict):
    _assert_common(data, "SupplyCenter")
    assert isinstance(data.get("center_code"), str) and data["center_code"]
    assert isinstance(data.get("display_name"), str)
    assert isinstance(data.get("base_weekly_capacity_units"), int)
    assert isinstance(data.get("ops_run_index"), int) and data["ops_run_index"] >= 0
    assert isinstance(data.get("rebate_pool_balance_cents"), int)
    assert isinstance(data.get("rebate_pool_locked_cents"), int)
    assert data.get("posture") in {p.value for p in CenterPosture}
    assert data.get("status") in {s.value for s in SupplyCenterStatus}


def assert_store(data: dict):
    _assert_common(data, "Store")
    assert isinstance(data.get("store_number"), str) and data["store_number"]
    assert isinstance(data.get("operator_name"), str)
    assert isinstance(data.get("credit_limit_cents"), int)
    assert isinstance(data.get("outstanding_balance_cents"), int)
    assert data.get("compliance_tier") in {t.value for t in ComplianceTier}
    assert data.get("rebate_eligibility_status") in {e.value for e in RebateEligibility}
    assert data.get("status") in {s.value for s in StoreStatus}


def assert_product(data: dict):
    _assert_common(data, "Product")
    assert isinstance(data.get("sku"), str) and data["sku"]
    assert isinstance(data.get("name"), str)
    assert data.get("category") in {c.value for c in ProductCategory}
    assert isinstance(data.get("base_cost_cents_per_unit"), int)
    assert data.get("status") in {s.value for s in ProductStatus}


def assert_delivery_route(data: dict):
    _assert_common(data, "DeliveryRoute")
    assert isinstance(data.get("route_code"), str)
    assert data.get("day_of_week") in {d.value for d in DayOfWeek}
    assert isinstance(data.get("truck_capacity_units"), int)
    assert isinstance(data.get("assigned_store_ids"), list)
    assert data.get("status") in {s.value for s in RouteStatus}


def assert_delivery_stop(data: dict):
    _assert_common(data, "DeliveryStop")
    assert isinstance(data.get("sequence_number"), int)
    assert data.get("status") in {s.value for s in StopStatus}


def assert_purchase_order(data: dict):
    _assert_common(data, "PurchaseOrder")
    assert data.get("status") in {s.value for s in PurchaseOrderStatus}
    assert isinstance(data.get("subtotal_cents"), int)
    assert isinstance(data.get("markup_cents"), int)
    assert isinstance(data.get("delivery_fee_cents"), int)
    assert isinstance(data.get("total_cents"), int)
    assert isinstance(data.get("theoretical_usage_cents"), int)
    assert isinstance(data.get("actual_usage_cents"), int)


def assert_order_line(data: dict):
    _assert_common(data, "OrderLine")
    assert isinstance(data.get("quantity"), int)
    assert isinstance(data.get("unit_price_cents"), int)
    assert isinstance(data.get("extended_price_cents"), int)
    assert isinstance(data.get("theoretical_usage_cents"), int)
    assert data.get("status") in {s.value for s in OrderLineStatus}


def assert_price_book(data: dict):
    _assert_common(data, "PriceBook")
    assert data.get("store_tier") in {t.value for t in StoreTier}
    assert isinstance(data.get("markup_pct"), (int, float))
    assert isinstance(data.get("min_quantity"), int)
    assert data.get("status") in {s.value for s in PriceBookStatus}


def assert_rebate_pool(data: dict):
    _assert_common(data, "RebatePool")
    assert isinstance(data.get("quarter"), str)
    assert isinstance(data.get("pool_total_cents"), int)
    assert isinstance(data.get("distributed_cents"), int)
    assert isinstance(data.get("holdback_cents"), int)
    assert data.get("status") in {s.value for s in RebatePoolStatus}


def assert_rebate_ledger(data: dict):
    _assert_common(data, "RebateLedger")
    assert data.get("entry_type") in {t.value for t in LedgerEntryType}
    assert isinstance(data.get("amount_cents"), int)
    assert isinstance(data.get("running_balance_cents"), int)
    assert data.get("status") in {s.value for s in LedgerStatus}


def assert_compliance_agreement(data: dict):
    _assert_common(data, "ComplianceAgreement")
    assert data.get("agreement_type") in {t.value for t in AgreementType}
    assert isinstance(data.get("exclusive_purchase_threshold"), (int, float))
    assert isinstance(data.get("breach_count"), int)
    assert data.get("status") in {s.value for s in AgreementStatus}


def assert_promotion_event(data: dict):
    _assert_common(data, "PromotionEvent")
    assert isinstance(data.get("promotion_code"), str)
    assert isinstance(data.get("surge_multiplier"), (int, float))
    assert isinstance(data.get("affected_product_ids"), list)
    assert isinstance(data.get("capacity_reserved_units"), int)
    assert data.get("status") in {s.value for s in PromotionStatus}


def assert_capacity_plan(data: dict):
    _assert_common(data, "CapacityPlan")
    assert isinstance(data.get("baseline_units"), int)
    assert isinstance(data.get("surge_units"), int)
    assert isinstance(data.get("allocated_units"), int)
    assert isinstance(data.get("available_units"), int)
    assert data.get("status") in {s.value for s in CapacityPlanStatus}


def assert_food_cost_variance(data: dict):
    _assert_common(data, "FoodCostVariance")
    assert isinstance(data.get("theoretical_cents"), int)
    assert isinstance(data.get("actual_cents"), int)
    assert isinstance(data.get("variance_cents"), int)
    assert data.get("severity") in {s.value for s in VarianceSeverity}
    assert data.get("status") in {s.value for s in VarianceStatus}


def assert_capacity_plan_invariants(data: dict):
    """available_units must always equal baseline + surge - allocated."""
    assert data["available_units"] == (
        data["baseline_units"] + data["surge_units"] - data["allocated_units"]
    ), (
        f"available_units {data['available_units']} != "
        f"baseline {data['baseline_units']} + surge {data['surge_units']} - allocated {data['allocated_units']}"
    )
