"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be a positive integer"


def assert_dough_facility(data: dict):
    _assert_common(data, "DoughFacility")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["effective_capacity_units"], int) \
        and data["effective_capacity_units"] > 0


def assert_dough_type(data: dict):
    _assert_common(data, "DoughType")
    assert isinstance(data["code"], str) and data["code"]
    assert data["category"] in ("CONVENTIONAL", "ARTISAN")
    assert isinstance(data["shelf_life_hours"], int) and data["shelf_life_hours"] > 0
    assert isinstance(data["order_cutoff_local"], str)
    assert isinstance(data["substitution_allowed"], bool)
    assert data["flat_transfer_price"] > 0


def assert_cafe(data: dict):
    _assert_common(data, "Cafe")
    assert isinstance(data["name"], str) and data["name"]
    assert is_valid_uuid(data.get("facility_id", ""))
    assert data["ownership_type"] in ("COMPANY", "FRANCHISE")
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] > 0
    assert isinstance(data["credit_balance_cents"], int) and data["credit_balance_cents"] >= 0


def assert_demand_adjustment(data: dict):
    _assert_common(data, "DemandAdjustment")
    assert is_valid_uuid(data.get("cafe_id", ""))
    assert isinstance(data["production_date"], str)
    assert data["reason"] in ("WEATHER", "EVENT")
    assert isinstance(data["demand_delta_pct"], int) \
        and -80 <= data["demand_delta_pct"] <= 100
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "RESCINDED")


def assert_cafe_order(data: dict):
    _assert_common(data, "CafeOrder")
    assert is_valid_uuid(data.get("cafe_id", ""))
    assert is_valid_uuid(data.get("dough_type_id", ""))
    assert isinstance(data["production_date"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["adjusted_quantity"], int) and data["adjusted_quantity"] >= 0
    assert data["status"] in ("DRAFT", "SUBMITTED", "LOCKED", "PLANNED", "ROUTED",
                              "DELIVERED", "SHIPPED_SHORT", "CANCELLED")
    assert data["billing_status"] in ("UNBILLED", "INVOICED", "PAID", "CREDITED")


def assert_production_plan(data: dict):
    _assert_common(data, "ProductionPlan")
    assert is_valid_uuid(data.get("facility_id", ""))
    assert isinstance(data["production_date"], str)
    assert data["status"] in ("OPEN", "LOCKED", "RELEASED", "CLOSED")
    assert isinstance(data["total_effective_units"], int) \
        and data["total_effective_units"] >= 0
    assert isinstance(data["over_capacity"], bool)


def assert_delivery_route(data: dict):
    _assert_common(data, "DeliveryRoute")
    assert is_valid_uuid(data.get("facility_id", ""))
    assert isinstance(data["production_date"], str)
    assert data["status"] in ("DRAFT", "PUBLISHED", "IN_TRANSIT", "COMPLETED", "CANCELLED")
    assert isinstance(data["vehicle_capacity_units"], int) \
        and data["vehicle_capacity_units"] > 0


def assert_route_stop(data: dict):
    _assert_common(data, "RouteStop")
    assert is_valid_uuid(data.get("route_id", ""))
    assert isinstance(data["seq"], int) and data["seq"] >= 1
    assert is_valid_uuid(data.get("cafe_id", ""))
    assert isinstance(data["planned_arrival"], str)
    assert isinstance(data["window_start_local"], str)
    assert isinstance(data["window_end_local"], str)
    assert data["status"] in ("SCHEDULED", "ARRIVED", "ON_TIME", "LATE", "MISSED", "CANCELLED")
    assert isinstance(data["planned_units"], int) and data["planned_units"] > 0


def assert_cafe_schedule(data: dict):
    _assert_common(data, "CafeSchedule")
    assert is_valid_uuid(data.get("cafe_id", ""))
    assert isinstance(data["business_date"], str)
    assert data["status"] in ("PLANNED", "OPEN", "CLOSED")


def assert_bake_entry(data: dict):
    _assert_common(data, "BakeEntry")
    assert is_valid_uuid(data.get("schedule_id", ""))
    assert is_valid_uuid(data.get("cafe_order_id", ""))
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["proof_start_at"], str)
    assert isinstance(data["proof_minutes"], int) and data["proof_minutes"] > 0
    assert data["status"] in ("SCHEDULED", "PROOFING", "BAKING", "COMPLETED", "DISCARDED")


def assert_donation_pickup(data: dict):
    _assert_common(data, "DonationPickup")
    assert is_valid_uuid(data.get("cafe_id", ""))
    assert is_valid_uuid(data.get("schedule_id", ""))
    assert isinstance(data["partner_name"], str) and data["partner_name"]
    assert isinstance(data["unsold_conventional"], int) and data["unsold_conventional"] >= 0
    assert isinstance(data["unsold_artisan"], int) and data["unsold_artisan"] >= 0
    assert data["status"] in ("LOGGED", "CONFIRMED", "VOIDED")


def assert_billing_period(data: dict):
    _assert_common(data, "BillingPeriod")
    assert is_valid_uuid(data.get("facility_id", ""))
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert data["status"] in ("OPEN", "CLOSED", "SETTLED")
    assert isinstance(data["admin_pool_cents"], int)


def assert_settlement_line(data: dict):
    _assert_common(data, "SettlementLine")
    assert is_valid_uuid(data.get("billing_period_id", ""))
    assert is_valid_uuid(data.get("cafe_id", ""))
    assert isinstance(data["cafe_hours"], int) and data["cafe_hours"] >= 0


def assert_cafe_ledger_invariants(cafe: dict):
    """Domain invariant: the outstanding receivable never dips below zero."""
    assert cafe["credit_balance_cents"] >= 0, \
        f"credit_balance_cents must be >= 0, got {cafe['credit_balance_cents']}"
