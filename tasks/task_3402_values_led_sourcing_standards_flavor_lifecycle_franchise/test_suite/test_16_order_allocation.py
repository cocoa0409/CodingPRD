"""Order allocation: plant-day pint pool, conservation under cancel (PRD §3.8, §2.10)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, api_client,
    make_limited_run_flavor, make_operating_shop,
    make_confirmed_order, make_allocated_order,
    make_shop_operator_headers,
)

FA = TEST_USERS["franchise_admin_headers"]
PS = TEST_USERS["plant_scheduler_headers"]



def _setup_shop_and_flavor(api):
    shop = make_operating_shop(name="Bulk Buyer", credit_limit_cents=10_000_000)
    flavor = make_limited_run_flavor(name="Bulk Vanilla", pint_price_cents=100)
    return shop, flavor


def test_plant_date_aggregate_capacity(api):
    """PRD §3.8: "the server checks the plant-day pint pool of §2.10 — the pints already reserved for that plant and `production_date` plus the order's `total_pints` must stay within the plant's daily budget, failing with `ERR_ORDER_CAPACITY_EXCEEDED` (HTTP 422)"
    PRD §2.10: "Each plant can supply at most 12000 pints per production date at `VT_WATERBURY`, 9000 at `VT_ST_ALBANS`, and 7000 at `NL_HELLENDOORN`."

    Design: Difficulty/resource_temporal_overlap/plant_date_aggregate_capacity
    """
    shop, flavor = _setup_shop_and_flavor(api)
    order_a = make_allocated_order(
        shop["id"], [{"flavor_id": flavor["id"], "quantity_pints": 6000}],
        plant_code="VT_ST_ALBANS", production_date="2026-10-05")
    assert order_a["status"] == "ALLOCATED"

    order_b = make_confirmed_order(
        shop["id"], [{"flavor_id": flavor["id"], "quantity_pints": 4000}])
    resp = api.allocate_supply_order(order_b["id"], {"plant_code": "VT_ST_ALBANS"}, PS)
    validate_error(resp, ApiErrorId.ERR_ORDER_CAPACITY_EXCEEDED)
    # 6000 + 4000 = 10000 > 9000 (VT_ST_ALBANS daily budget)
    after = get_success_data(api.get_supply_order(order_b["id"], FA))
    assert after["status"] == "CONFIRMED"


def test_plant_date_buckets_are_independent(api):
    """PRD §3.8: "the server checks the plant-day pint pool of §2.10 — the pints already reserved for that plant and `production_date` plus the order's `total_pints` must stay within the plant's daily budget, failing with `ERR_ORDER_CAPACITY_EXCEEDED` (HTTP 422)"
    PRD §2.10: "Each plant can supply at most 12000 pints per production date at `VT_WATERBURY`, 9000 at `VT_ST_ALBANS`, and 7000 at `NL_HELLENDOORN`."
    PRD §2.10: "Allocating an order reserves its `total_pints` against the
    bucket keyed by plant and production date".

    Design: Difficulty/resource_temporal_overlap/plant_date_aggregate_capacity
    """
    shop, flavor = _setup_shop_and_flavor(api)
    make_allocated_order(
        shop["id"], [{"flavor_id": flavor["id"], "quantity_pints": 6000}],
        plant_code="VT_ST_ALBANS", production_date="2026-10-05")

    # Same plant but a different production date is a different bucket.
    order_b = make_confirmed_order(
        shop["id"], [{"flavor_id": flavor["id"], "quantity_pints": 4000}],
        production_date="2026-10-06")
    allocated = validate_success(api.allocate_supply_order(
        order_b["id"], {"plant_code": "VT_ST_ALBANS"}, PS))
    assert allocated["status"] == "ALLOCATED"
    assert allocated["allocated_plant_code"] == "VT_ST_ALBANS"


def test_order_allocate_cancel_capacity_conservation(api):
    """PRD §3.8: "the server checks the plant-day pint pool of §2.10 — the pints already reserved for that plant and `production_date` plus the order's `total_pints` must stay within the plant's daily budget, failing with `ERR_ORDER_CAPACITY_EXCEEDED` (HTTP 422)"
    PRD §3.8: "cancelling an `ALLOCATED` order releases its `total_pints` from the plant-day pool as a compensating reversal."

    Design: Difficulty/compensating_invariant/order_allocate_cancel_capacity_conservation
    """
    shop = make_operating_shop(name="Conserve Shop", credit_limit_cents=10_000_000)
    flavor = make_limited_run_flavor(name="Conserve Cocoa", pint_price_cents=100)
    order_a = make_allocated_order(
        shop["id"], [{"flavor_id": flavor["id"], "quantity_pints": 6000}],
        plant_code="VT_ST_ALBANS", production_date="2026-10-05")

    order_b = make_confirmed_order(
        shop["id"], [{"flavor_id": flavor["id"], "quantity_pints": 4000}])
    blocked = api.allocate_supply_order(order_b["id"], {"plant_code": "VT_ST_ALBANS"}, PS)
    validate_error(blocked, ApiErrorId.ERR_ORDER_CAPACITY_EXCEEDED)

    # Compensating reversal: cancelling A releases its 6000 pints.
    validate_success(api.cancel_supply_order(
        order_a["id"], make_shop_operator_headers(shop["id"])))
    allocated = validate_success(api.allocate_supply_order(
        order_b["id"], {"plant_code": "VT_ST_ALBANS"}, PS))
    assert allocated["status"] == "ALLOCATED", \
        "allocate+cancel on A left the pool exactly as before"

    data, _ = validate_paginated(api.list_supply_orders(
        shop["id"], FA, params={"status": "ALLOCATED"}))
    assert [o["id"] for o in data] == [order_b["id"]]
    assert data[0]["total_pints"] == 4000


def test_capacity_pools_are_per_plant(api):
    """PRD §3.8: "the server checks the plant-day pint pool of §2.10 — the pints already reserved for that plant and `production_date` plus the order's `total_pints` must stay within the plant's daily budget, failing with `ERR_ORDER_CAPACITY_EXCEEDED` (HTTP 422)"
    PRD §2.10: "Each plant can supply at most 12000 pints per production date at `VT_WATERBURY`, 9000 at `VT_ST_ALBANS`, and 7000 at `NL_HELLENDOORN`."
    PRD §3.8: "cancelling an `ALLOCATED` order releases its `total_pints` from the plant-day pool as a compensating reversal."

    Design: Difficulty/compensating_invariant/order_allocate_cancel_capacity_conservation
    """
    shop, flavor = _setup_shop_and_flavor(api)
    order_a = make_allocated_order(
        shop["id"], [{"flavor_id": flavor["id"], "quantity_pints": 6000}],
        plant_code="VT_ST_ALBANS", production_date="2026-10-05")

    # While A holds the ST_ALBANS pool, a different plant bucket is untouched.
    order_c = make_confirmed_order(
        shop["id"], [{"flavor_id": flavor["id"], "quantity_pints": 4000}])
    allocated = validate_success(api.allocate_supply_order(
        order_c["id"], {"plant_code": "NL_HELLENDOORN"}, PS))
    assert allocated["status"] == "ALLOCATED"  # 4000 <= 7000

    # Releasing A then lets the previously-blocked size into ST_ALBANS.
    validate_success(api.cancel_supply_order(
        order_a["id"], make_shop_operator_headers(shop["id"])))
    order_b = make_confirmed_order(
        shop["id"], [{"flavor_id": flavor["id"], "quantity_pints": 4000}])
    freed = validate_success(api.allocate_supply_order(
        order_b["id"], {"plant_code": "VT_ST_ALBANS"}, PS))
    assert freed["status"] == "ALLOCATED"
