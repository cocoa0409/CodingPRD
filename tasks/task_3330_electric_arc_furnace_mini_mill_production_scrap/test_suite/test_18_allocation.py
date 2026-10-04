"""Division allocation runs, order cancel compensating release, invoice ->
scorecard cascade (PRD §3.9, §3.11)."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, validate_success, validate_error,
    set_clock, make_mill, make_grade, make_account, make_order, publish_index,
    confirm_order, setup_supply_pool, setup_cast_heat, make_scorecard,
    get_order, get_scorecard,
)

AM = TEST_USERS["account_manager_headers"]
SCH = TEST_USERS["scheduler_headers"]


def test_allocation_run_empty_pool_is_noop():
    """PRD §3.9: "An empty pool produces a no-op run reporting zero
    `assigned_orders` and zero `assigned_tons`."

    Design: Corner/endpoints/allocation_run_empty_pool_is_noop
    """
    mill = make_mill(name="Crawfordsville Bar Mill", division="CONSTRUCTION")
    result = validate_success(api_client.run_allocation(mill["id"], SCH), 200)
    assert result["assigned_orders"] == 0
    assert result["assigned_tons"] == 0


def _setup_allocated_order(order_tons=8, heat_tons=8, heat_tap="2026-09-08T12:00:00Z"):
    """CONTRACT account, one CONFIRMED order, one CAST heat; allocation assigns."""
    set_clock("2026-09-10T00:00:00Z")
    mill = make_mill(name="Crawfordsville Bar Mill", division="CONSTRUCTION")
    publish_index(mill["id"], grade_category="SHREDDED", effective_month="2026-09",
                  price_per_ton_cents=38000)
    grade = make_grade(mill["id"], grade_code="GR40")
    acct = make_account(mill["id"], name="Contract Builders Inc",
                        market="CONSTRUCTION", pricing_mode="CONTRACT")
    order = make_order(mill["id"], acct["id"], grade["id"], tons=order_tons,
                       fulfillment_month="2026-09", base_price_cents_per_ton=25000)
    confirm_order(mill["id"], acct["id"], order)
    contract, lots = setup_supply_pool(
        mill["id"], price=30000, committed=50, supplier_name="Coastal Scrap Co",
        lots=[{"received_on": "2026-09-03", "tons_received": 25, "moisture_pct": 0.0}],
    )
    heat = setup_cast_heat(mill["id"], grade["id"], lots[0]["id"], heat_tons,
                           tap_at=heat_tap)
    return mill, acct, order, heat


def test_order_cancel_from_allocated_releases_allocation():
    """PRD §3.9: "From `CONFIRMED` or `ALLOCATED`, the cancel performs a
    compensating release: any allocated tonnage is returned and `allocated_tons`
    reset to 0. The order lands in `CANCELLED`, terminal, with `version`
    incremented."

    Design: Difficulty/compensating_invariant/order_cancel_releases_allocation
    """
    mill, acct, order, heat = _setup_allocated_order()
    run = validate_success(api_client.run_allocation(mill["id"], SCH), 200)
    assert run["assigned_orders"] == 1
    assert run["assigned_tons"] == 8
    allocated = get_order(mill["id"], order["id"])
    assert allocated["status"] == "ALLOCATED"
    assert allocated["allocated_tons"] == 8

    cancelled = validate_success(
        api_client.cancel_order(mill["id"], acct["id"], order["id"], AM), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["allocated_tons"] == 0


def test_allocation_after_cancel_is_noop_for_cancelled_order():
    """PRD §3.9: "an allocation run assigns tonnage from eligible heats — those
    `CAST` and not yet committed to any campaign line — to eligible orders — those
    `CONFIRMED` with `allocated_tons` below `tons` on accounts not `BLOCKED`."
    PRD §3.9: "An empty pool produces a no-op run reporting zero `assigned_orders`
    and zero `assigned_tons`."

    Design: Difficulty/compensating_invariant/order_cancel_releases_allocation
    """
    mill, acct, order, heat = _setup_allocated_order()
    validate_success(api_client.run_allocation(mill["id"], SCH), 200)
    validate_success(api_client.cancel_order(mill["id"], acct["id"], order["id"], AM), 200)

    rerun = validate_success(api_client.run_allocation(mill["id"], SCH), 200)
    # The CANCELLED order is out of the eligible pool and no other order exists.
    assert rerun["assigned_orders"] == 0
    assert rerun["assigned_tons"] == 0


def test_order_invoice_rescores_division_profit_share():
    """PRD §3.9: "The invoice also feeds the division's books: if the scorecard for
    the mill and the order's `fulfillment_month` is `OPEN`, the invoiced
    `computed_price_cents` is added to its `revenue_cents` and the profit fields
    recompute."
    PRD §3.11: "`profit_cents` is `revenue_cents` minus `material_cost_cents` minus
    `energy_cost_cents`."
    PRD §3.6: "if a division scorecard exists for the mill and the calendar month of
    the heat's `planned_tap_at`, and that scorecard is `OPEN`, the heat's frozen
    `charge_cost_cents` is added to the scorecard's `material_cost_cents`."

    Design: Difficulty/transitive_cascade/order_invoice_rescores_division_profit_share
    """
    set_clock("2026-09-10T00:00:00Z")
    mill = make_mill(name="Crawfordsville Bar Mill", division="CONSTRUCTION")
    publish_index(mill["id"], grade_category="SHREDDED", effective_month="2026-09",
                  price_per_ton_cents=38000)
    grade = make_grade(mill["id"], grade_code="GR40")
    acct = make_account(mill["id"], name="Contract Builders Inc",
                        market="CONSTRUCTION", pricing_mode="CONTRACT")
    order = make_order(mill["id"], acct["id"], grade["id"], tons=20,
                       fulfillment_month="2026-09", base_price_cents_per_ton=25000)
    confirm_order(mill["id"], acct["id"], order)
    contract, lots = setup_supply_pool(
        mill["id"], price=30000, committed=50, supplier_name="Coastal Scrap Co",
        lots=[{"received_on": "2026-09-03", "tons_received": 25, "moisture_pct": 0.0}],
    )
    scorecard = make_scorecard(mill["id"], period="2026-09", headcount=7)
    heat = setup_cast_heat(mill["id"], grade["id"], lots[0]["id"], 20,
                           tap_at="2026-09-08T12:00:00Z")
    validate_success(api_client.run_allocation(mill["id"], SCH), 200)

    invoiced = validate_success(
        api_client.invoice_order(mill["id"], acct["id"], order["id"], AM), 200)
    assert invoiced["status"] == "INVOICED"

    sc = get_scorecard(mill["id"], scorecard["id"])
    # CONTRACT account keeps the confirmed price: (25000 + 38000) * 20 = 1260000.
    assert sc["revenue_cents"] == 1_260_000
    # The CAST of the 20t heat at 30000/t posted its frozen charge_cost_cents.
    assert sc["material_cost_cents"] == 600_000
    assert sc["profit_cents"] == 660_000


def test_order_invoice_contract_account_keeps_confirmed_price():
    """PRD §3.9: "`CONTRACT` accounts keep the confirmed price untouched."
    PRD §3.9: "The order becomes `INVOICED`, a terminal state, with `version`
    bumped."

    Design: Difficulty/transitive_cascade/order_invoice_rescores_division_profit_share
    """
    set_clock("2026-09-10T00:00:00Z")
    mill = make_mill(name="Crawfordsville Bar Mill", division="CONSTRUCTION")
    publish_index(mill["id"], grade_category="SHREDDED", effective_month="2026-09",
                  price_per_ton_cents=38000)
    grade = make_grade(mill["id"], grade_code="GR40")
    acct = make_account(mill["id"], name="Contract Builders Inc",
                        market="CONSTRUCTION", pricing_mode="CONTRACT")
    order = make_order(mill["id"], acct["id"], grade["id"], tons=20,
                       fulfillment_month="2026-09", base_price_cents_per_ton=25000)
    confirmed = confirm_order(mill["id"], acct["id"], order)
    contract, lots = setup_supply_pool(
        mill["id"], price=30000, committed=50, supplier_name="Coastal Scrap Co",
        lots=[{"received_on": "2026-09-03", "tons_received": 25, "moisture_pct": 0.0}],
    )
    heat = setup_cast_heat(mill["id"], grade["id"], lots[0]["id"], 20,
                           tap_at="2026-09-08T12:00:00Z")
    run = validate_success(api_client.run_allocation(mill["id"], SCH), 200)
    assert run["assigned_tons"] == 20

    invoiced = validate_success(
        api_client.invoice_order(mill["id"], acct["id"], order["id"], AM), 200)
    assert invoiced["status"] == "INVOICED"
    assert invoiced["computed_price_cents"] == confirmed["computed_price_cents"]
    assert invoiced["computed_price_cents"] == 1_260_000
