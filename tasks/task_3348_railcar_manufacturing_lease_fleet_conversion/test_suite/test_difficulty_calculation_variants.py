"""Difficulty queue: calculation variants and pinned evaluation order.

Four instances, one test each:

* ``dual_variant_calc`` — the forecast quote variant lapses locked component
  prices once the order is older than the lock horizon, while the committed
  basis keeps them; and the retained/sold capital bases diverge on the same
  contract.
* ``combinatorial_formula`` — the per-line ceiling runs before the summation,
  and the fleet reconciliation reads committed capital before subtracting the
  settled disposal proceeds.

Every expected money figure is recomputed from the PRD's stated formulas.
"""

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    api_client,
    complete_order,
    create_lessee_and_contract,
    create_lessee_payload,
    create_order,
    create_sale,
    ensure_coating_supply,
    get_success_data,
    release_order,
    reserve_order,
    set_clock,
    settle_sale,
    setup_catalogue,
    start_production,
)

LEASE = TEST_USERS["lease_administrator_headers"]
PORTFOLIO = TEST_USERS["portfolio_manager_headers"]


def _create_lessee(legal_name: str, **overrides) -> dict:
    """Register a bare lessee account (no contract) for quote-only scenarios."""
    return get_success_data(
        api_client.create_lessee(
            create_lessee_payload(legal_name=legal_name, **overrides), LEASE
        )
    )


# ─── dual_variant_calc ────────────────────────────────

def test_forecast_quote_lapses_locked_component_prices_past_lock_horizon(api):
    """PRD §3.1: "The committed basis applies once the order has been
    component-reserved or released, at which point contract prices and the
    endorsed composition are locked."
    PRD §3.1: "The forecast basis differs from the committed basis in exactly
    two substitutions, both applied to the input costs before the line loop
    begins. First, for every row whose `component_class` is `WHEELSET` or
    `CASTING` and where the current date is more than 120 days past the order's
    `order_date`, the component's `unit_cost_cents` is replaced by that cost
    multiplied by 110 and divided by 100, rounded up to a whole cent — the
    locked contract price has lapsed."
    PRD §3.1: "The line amount for the row is then the effective quantity
    multiplied by the component's `unit_cost_cents`, plus a line surcharge of
    25,000 cents, divided by one hundred, rounded up to the next whole number,
    and multiplied back by one hundred — that is, each line is rounded up to
    the next whole dollar before it is summed."

    Two orders are quoted against the same locked catalogue on the same
    ``order_date``: one taken while the clock still reads that day, one taken
    153 days later.  Only the second is past the 120-day lock horizon, so only
    the second re-prices the WHEELSET and CASTING rows upward by the 110/100
    lapse factor.

    Design: Difficulty/dual_variant_calc/quote_variant_divergence_wheelset_lapse
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(
        model_code="BOX-100",
        car_class="BOXCAR",
        build_hours=40,
        regulatory_life_years=40,
        line_count_family="BOX_LINE",
        wheelset_part_number="WS-100",
        wheelset_unit_cost_cents=180000,
        wheelset_qty_per_car=4,
        wheelset_lead_time_days=30,
        casting_part_number="CT-100",
        casting_unit_cost_cents=90000,
        casting_qty_per_car=2,
        casting_lead_time_days=20,
        coating_part_number="CK-100",
        coating_unit_cost_cents=40000,
        coating_qty_per_car=1,
        coating_lead_time_days=60,
        on_hand_qty=100,
    )
    lessee = _create_lessee(
        "Variant Rail Co",
        credit_tier="A",
        utilization_threshold_pct=80,
        credit_ceiling_cents=50000000,
    )

    # Day 0: the lock horizon has not lapsed, so both rows keep their locked
    # costs.  Per-line ceilings: WS 4*180000+25000 -> 745000; CT
    # 2*90000+25000 -> 205000; CK 1*40000+25000 -> 65000.  Subtotal 1015000,
    # labour 40*45000 = 1800000, no change fee -> unit price 2815000.
    same_day = create_order(
        catalogue,
        quantity=10,
        planned_shop_days=400,
        disposition="SOLD",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-12-01",
        lessee_id=lessee["id"],
    )
    assert same_day["unit_price_cents"] == 2815000, (
        "a quote taken on the order date must keep the locked contract prices"
    )

    # Day 153: the horizon has lapsed, so WHEELSET and CASTING are re-priced at
    # ceil(cost * 110 / 100): 180000 -> 198000 and 90000 -> 99000.  Their lines
    # become 4*198000+25000 -> 817000 and 2*99000+25000 -> 223000, so the
    # subtotal rises to 1105000 and the unit price to 2905000.
    advance_clock_to("2027-02-01T00:00:00Z")
    lapsed = create_order(
        catalogue,
        quantity=10,
        planned_shop_days=400,
        disposition="SOLD",
        priority_rank=2,
        order_date="2026-09-01",
        required_delivery_date="2027-04-01",
        lessee_id=lessee["id"],
    )
    assert lapsed["unit_price_cents"] == 2905000, (
        "past the 120-day lock horizon the forecast variant must lapse the "
        "wheelset and casting prices"
    )

    assert lapsed["unit_price_cents"] - same_day["unit_price_cents"] == 90000, (
        "the divergence must equal the wheelset and casting lapse alone"
    )
    assert lapsed["unit_price_cents"] > same_day["unit_price_cents"]


def test_retained_capital_posts_but_sold_completion_does_not(api):
    """PRD §2.9: "A contract's `capital_allocation_cents` records the capital
    that has moved into the lease fleet for `RETAINED` cars under that
    contract; it starts at 0 and is re-derived by the allocation rule of §3.4
    rather than adjusted incrementally."
    PRD §3.4: "On the `SOLD` basis the capital never enters the fleet at all:
    `capital_allocation_cents` keeps whatever value it previously held, and the
    order's value is accrued against the lessee's `outstanding_balance_cents`
    instead."
    PRD §3.4: "The capital figure is the size of that set multiplied by the
    order's `unit_price_cents`."

    One contract carries a two-car RETAINED order and a one-car SOLD order on
    the same car type.  Both quote at 2815000 cents per car, so the retained
    completion must post 2 * 2815000 = 5630000 cents of fleet capital while the
    sold completion must leave that figure untouched.

    Design: Difficulty/dual_variant_calc/capital_allocation_retained_vs_sold_basis
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(
        model_code="BOX-100",
        car_class="BOXCAR",
        build_hours=40,
        regulatory_life_years=40,
        line_count_family="BOX_LINE",
        wheelset_part_number="WS-100",
        wheelset_unit_cost_cents=180000,
        wheelset_qty_per_car=4,
        wheelset_lead_time_days=30,
        casting_part_number="CT-100",
        casting_unit_cost_cents=90000,
        casting_qty_per_car=2,
        casting_lead_time_days=20,
        coating_part_number="CK-100",
        coating_unit_cost_cents=40000,
        coating_qty_per_car=1,
        coating_lead_time_days=60,
        on_hand_qty=200,
    )
    world = create_lessee_and_contract(
        legal_name="Basis Rail Co",
        credit_tier="A",
        utilization_threshold_pct=80,
        credit_ceiling_cents=50000000,
        lease_type="FULL_SERVICE",
        per_diem_rate_cents=20000,
        liability_bearer="LESSOR",
        term_start_date="2026-09-01",
        term_end_date="2028-09-01",
        fleet_car_cap=100,
    )
    lessee, contract = world["lessee"], world["contract"]

    # RETAINED leg: two cars released against the contract.
    retained = create_order(
        catalogue,
        quantity=2,
        planned_shop_days=80,
        disposition="RETAINED",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-12-01",
        lessee_id=lessee["id"],
    )
    assert retained["unit_price_cents"] == 2815000
    reserve_order(retained["id"])
    ensure_coating_supply(
        catalogue["coating"], 2, retained["required_delivery_date"],
        order_date=retained["order_date"],
    )
    release_order(retained["id"], lease_contract_id=contract["id"])
    start_production(retained["id"], "BOX_LINE", window_start="2026-09-05",
                     window_days=80)
    complete_order(retained["id"], completed_qty=2, completion_date="2026-11-24")

    after_retained = get_success_data(
        api_client.get_lease_contract(contract["id"], LEASE)
    )
    assert after_retained["capital_allocation_cents"] == 5630000, (
        "two retained cars at 2815000 cents each must post 5630000 of capital"
    )

    # SOLD leg: one car, released without naming a contract.
    sold = create_order(
        catalogue,
        quantity=1,
        planned_shop_days=40,
        disposition="SOLD",
        priority_rank=2,
        order_date="2026-09-01",
        required_delivery_date="2026-12-01",
        lessee_id=lessee["id"],
    )
    assert sold["unit_price_cents"] == 2815000
    reserve_order(sold["id"])
    ensure_coating_supply(
        catalogue["coating"], 1, sold["required_delivery_date"],
        order_date=sold["order_date"],
    )
    release_order(sold["id"])
    start_production(sold["id"], "BOX_LINE", window_start="2026-11-24",
                     window_days=40)
    complete_order(sold["id"], completed_qty=1, completion_date="2027-01-03",
                   lessee_id=lessee["id"])

    after_sold = get_success_data(
        api_client.get_lease_contract(contract["id"], LEASE)
    )
    assert after_sold["capital_allocation_cents"] == 5630000, (
        "a sold completion must leave the contract's capital at 5630000, "
        "not raise it to 8445000"
    )

    # The sold car's value lands on the lessee ledger instead.  The retained
    # credit (2 * 2815000) exceeds the sold debit (1 * 2815000), and the
    # aggregate is clamped at zero.
    balance = get_success_data(
        api_client.get_lessee_outstanding_balance(lessee["id"], LEASE)
    )
    assert balance["outstanding_balance_cents"] == 0, (
        "the retained credit of 5630000 exceeds the sold charge of 2815000, so "
        "the aggregated balance is floored at zero"
    )


# ─── combinatorial_formula ────────────────────────────

def test_order_quote_ceils_each_bom_line_before_summing(api):
    """PRD §3.1: "The line amount for the row is then the effective quantity
    multiplied by the component's `unit_cost_cents`, plus a line surcharge of
    25,000 cents, divided by one hundred, rounded up to the next whole number,
    and multiplied back by one hundred — that is, each line is rounded up to
    the next whole dollar before it is summed."
    PRD §3.1: "The labor charge is the car type's `build_hours` multiplied by
    the labor rate of 45,000 cents per build hour."
    PRD §3.1: "Evaluation order is pinned: per-line ceilings first, summation
    second, the cap and the fee third, and no further rounding after the final
    addition."

    Every component cost carries a cent residue, so the pinned per-line ceiling
    is what makes the quoted figure well defined.

    Design: Difficulty/combinatorial_formula/order_quote_line_rounding_order_pinned
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(
        model_code="GON-100",
        car_class="GONDOLA",
        build_hours=40,
        regulatory_life_years=40,
        line_count_family="GON_LINE",
        wheelset_part_number="WS-200",
        wheelset_unit_cost_cents=16500,
        wheelset_qty_per_car=4,
        wheelset_lead_time_days=10,
        casting_part_number="CT-200",
        casting_unit_cost_cents=51250,
        casting_qty_per_car=4,
        casting_lead_time_days=10,
        coating_part_number="CK-200",
        coating_unit_cost_cents=32145,
        coating_qty_per_car=2,
        coating_lead_time_days=10,
        on_hand_qty=100,
    )
    lessee = _create_lessee(
        "Rounding Rail Co",
        credit_tier="A",
        utilization_threshold_pct=80,
        credit_ceiling_cents=50000000,
    )

    order = create_order(
        catalogue,
        quantity=1,
        planned_shop_days=40,
        disposition="SOLD",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-12-01",
        lessee_id=lessee["id"],
    )

    # Ceiling each line to the next whole dollar before summing:
    #   WS-200  4 * 16500  + 25000 =  91000 ->   91000
    #   CT-200  4 * 51250  + 25000 = 230000 ->  230000
    #   CK-200  2 * 32145  + 25000 =  89290 ->   89300
    # Component subtotal 410300, labour 40 * 45000 = 1800000, change fee 0
    # (no APPROVED or APPLIED endorsement on the order).
    assert order["unit_price_cents"] == 2210300, (
        "the quote must ceiling each line to the next whole dollar and only "
        "then sum"
    )
    assert order["status"] == "DRAFT"
    assert order["planned_shop_days"] == 40


def test_fleet_reconciliation_subtracts_settled_proceeds_from_committed_capital(api):
    """PRD §3.9: "The committed basis is the ledger's `committed_capital_cents`
    minus those disposal proceeds — the historic cost basis, which charges the
    full proceeds against committed capital and applies no depreciation."
    PRD §3.9: "The newest basis is the live fleet's depreciated book value: for
    every car in `HELD`, `ASSIGNED` or `UNDER_REPAIR`, the car's
    `acquisition_cost_cents` minus the number of days from its `built_date` to
    the current clock date multiplied by the daily depreciation of 2,500 cents,
    floored at zero per car so a fully depreciated car contributes nothing,
    summed across the fleet and rounded up to a whole cent."
    PRD §3.9: "The disposal proceeds term is the sum of `sale_price_cents` over
    every sale in `SETTLED` status, floored at zero; sales that are `VOIDED` or
    still `PENDING_SETTLEMENT` contribute nothing."

    The retained completion writes committed capital first; the settled sale is
    then charged against it, so the two bases diverge by exactly the drift.

    Design: Difficulty/combinatorial_formula/fleet_reconciliation_circular_order_pinned
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(
        model_code="BOX-300",
        car_class="BOXCAR",
        build_hours=40,
        regulatory_life_years=40,
        line_count_family="BOX_LINE",
        wheelset_part_number="WS-300",
        wheelset_unit_cost_cents=180000,
        wheelset_qty_per_car=4,
        wheelset_lead_time_days=10,
        casting_part_number="CT-300",
        casting_unit_cost_cents=152500,
        casting_qty_per_car=2,
        casting_lead_time_days=10,
        include_coating=False,
        on_hand_qty=100,
    )
    world = create_lessee_and_contract(
        legal_name="Ledger Rail Co",
        credit_tier="A",
        utilization_threshold_pct=80,
        credit_ceiling_cents=50000000,
        lease_type="FULL_SERVICE",
        per_diem_rate_cents=20000,
        liability_bearer="LESSOR",
        term_start_date="2026-09-01",
        term_end_date="2028-09-01",
        fleet_car_cap=100,
    )
    lessee, contract = world["lessee"], world["contract"]

    # Committed quote: WS 4*180000+25000 -> 745000, CT 2*152500+25000 ->
    # 330000; subtotal 1075000, labour 40*45000 = 1800000, fee 0.
    order = create_order(
        catalogue,
        quantity=1,
        planned_shop_days=40,
        disposition="RETAINED",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-12-01",
        lessee_id=lessee["id"],
    )
    assert order["unit_price_cents"] == 2875000
    reserve_order(order["id"])
    release_order(order["id"], lease_contract_id=contract["id"])
    start_production(order["id"], "BOX_LINE", window_start="2026-09-05",
                     window_days=40)
    complete_order(order["id"], completed_qty=1, completion_date="2026-10-15")

    ledger = get_success_data(api_client.get_portfolio_ledger(PORTFOLIO))
    assert ledger["committed_capital_cents"] == 2875000, (
        "the retained completion writes committed capital before any disposal "
        "is subtracted"
    )

    cars = get_success_data(
        api_client.list_lease_fleet_cars(
            PORTFOLIO, {"production_order_id": order["id"]}
        )
    )
    assert len(cars) == 1
    car = cars[0]
    assert car["acquisition_cost_cents"] == 2875000
    assert car["status"] == "HELD"

    # 351 days of depreciation take the car's book value to
    # 2875000 - 351 * 2500 = 1997500, so a 2000000-cent sale settles (the zero
    # writeback does not exceed the 2500-cent gain over book).
    advance_clock_to("2027-10-01T00:00:00Z")
    sale = create_sale(
        car,
        sale_price_cents=2000000,
        sale_date="2027-10-01",
        writeback_liability_cents=0,
    )
    assert sale["gain_loss_cents"] == 2500
    settle_sale(sale["id"])

    reconciliation = get_success_data(
        api_client.get_portfolio_ledger_reconciliation(PORTFOLIO)
    )
    assert reconciliation["oldest_basis_cents"] == 875000, (
        "committed basis = committed capital 2875000 - settled proceeds 2000000"
    )
    assert reconciliation["newest_basis_cents"] == 0, (
        "the only car left the live set when it was sold, so the newest basis "
        "sums over zero cars"
    )
    assert reconciliation["drift_cents"] == 875000
    assert reconciliation["committed_capital_cents"] == 2875000
