"""Fleet capital allocation and the two reconciliations that read it back.

Capital is an aggregation over the cars an order has actually delivered into
the live fleet, re-derived from scratch on every event; the portfolio
reconciliation reports the historic cost basis beside the live fleet's
depreciated book value; the lessee reconciliation nets a retained completion
back off the balance it would otherwise carry. All three read the same
committed quote, which is why the provisional forecast figure never reaches the
fleet.

Every expected figure below is recomputed from the PRD's stated formulas.
"""

from test_helpers import (
    CLOCK_START_ISO,
    advance_clock_to,
    api_client,
    complete_order,
    create_order,
    create_sale,
    ensure_coating_supply,
    get_success_data,
    release_order,
    reserve_order,
    set_clock,
    settle_sale,
    setup_order_in_state,
    start_production,
)

from test_calculations_support import (
    ADMIN,
    LEASE,
    PLANNER,
    box_car_catalogue,
    commercial,
    flat_car_catalogue,
    held_cars,
)


def test_retained_completion_capitalises_the_committed_quote_per_live_car(api):
    """PRD §3.4: "The retained-car set is every fleet car whose
    `production_order_id` points at this order and whose status is one of the
    three live fleet states, `HELD`, `ASSIGNED` or `UNDER_REPAIR`; cars that have
    been sold or scrapped are excluded, which is why scrapping a car re-derives a
    smaller capital figure for its former contract. The capital figure is the
    size of that set multiplied by the order's `unit_price_cents`."
    PRD §3.4: "completion creates one fleet car per car built, each starting in
    `HELD` with its `production_order_id` pointing at the producing order, its
    `acquisition_cost_cents` equal to the order's `unit_price_cents`, and its
    `built_date` set to the completion date"

    Two cars complete against a committed quote of 1614500, so the contract's
    capital reads 3229000 — the re-derived aggregation, not an increment. The
    separate lessor-equity figure the same rule derives,
    floor(3229000 * min(700, 900) / 10000) == 226030, has no field of its own and
    is not what `capital_allocation_cents` holds.

    Design: Corner/calculations/lease_fleet_capital_allocation_correct_result_retained_completion
    """
    set_clock(CLOCK_START_ISO)
    catalogue = box_car_catalogue()
    pair = commercial(
        "Capital Rail Co",
        utilization_threshold_pct=70,
        per_diem_rate_cents=5000,
        liability_bearer="LESSOR",
        fleet_car_cap=10,
    )
    world = held_cars(
        catalogue,
        car_count=2,
        commercial_pair=pair,
        changeover_start="2026-09-05",
        completion_date="2026-11-04",
        required_delivery_date="2026-12-01",
    )

    contract = get_success_data(
        api_client.get_lease_contract(pair["contract"]["id"], LEASE)
    )
    assert contract["capital_allocation_cents"] == 3229000, (
        "two live cars of this order at the committed 1614500-cent quote"
    )
    assert len(world["cars"]) == 2
    for car in world["cars"]:
        assert car["acquisition_cost_cents"] == 1614500
        assert car["status"] == "HELD"
        assert car["built_date"] == "2026-11-04"
        assert car["regulatory_life_end_date"] == "2051-11-04"


def test_fleet_reconciliation_reports_both_bases_and_their_drift(api):
    """PRD §3.9: "The committed basis is the ledger's `committed_capital_cents`
    minus those disposal proceeds — the historic cost basis, which charges the
    full proceeds against committed capital and applies no depreciation. The
    newest basis is the live fleet's depreciated book value: for every car in
    `HELD`, `ASSIGNED` or `UNDER_REPAIR`, the car's `acquisition_cost_cents`
    minus the number of days from its `built_date` to the current clock date
    multiplied by the daily depreciation of 2,500 cents, floored at zero per car
    so a fully depreciated car contributes nothing, summed across the fleet and
    rounded up to a whole cent. The drift is the committed basis minus the newest
    basis."

    Two cars acquired at 71000 cents and read twenty days later give an oldest
    basis of 142000 with no settled disposal to charge, a newest basis of
    2 * (71000 - 20 * 2500) == 42000, and a drift of 100000.

    Design: Corner/calculations/fleet_capital_reconciliation_correct_result_oldest_basis_drift
    """
    set_clock(CLOCK_START_ISO)
    catalogue = flat_car_catalogue()
    world = held_cars(
        catalogue,
        car_count=2,
        changeover_start="2026-09-02",
        completion_date="2026-09-04",
        required_delivery_date="2026-09-20",
    )
    assert world["order"]["unit_price_cents"] == 71000, (
        "one 26000-cent ceiled line plus one 45000-cent build hour"
    )
    assert [car["built_date"] for car in world["cars"]] == ["2026-09-04", "2026-09-04"]

    advance_clock_to("2026-09-24T00:00:00Z")
    reconciliation = get_success_data(
        api_client.get_portfolio_ledger_reconciliation(ADMIN)
    )
    assert reconciliation["oldest_basis_cents"] == 142000
    assert reconciliation["newest_basis_cents"] == 42000, (
        "each car contributes max(0, 71000 - 20 * 2500) == 21000"
    )
    assert reconciliation["drift_cents"] == 100000
    assert reconciliation["committed_capital_cents"] == 142000
    assert reconciliation["realized_gain_cents"] == 0


def test_committed_quote_not_the_provisional_forecast_reaches_the_fleet(api):
    """PRD §3.1: "The forecast basis applies while the order is still `DRAFT` and
    the current date is more than the lock horizon of 120 days past
    `order_date`."
    PRD §3.1: "The committed basis applies once the order has been
    component-reserved or released, at which point contract prices and the
    endorsed composition are locked."
    PRD §3.4: "The capital figure is the size of that set multiplied by the
    order's `unit_price_cents`."

    The order is taken 153 days after its order date, so its draft quote is the
    lapsed 1629700; reserving it re-quotes to the locked 1614500, and it is the
    locked figure that the completed cars carry as their acquisition cost and
    that the contract capitalises. The 15200-cent provisional-to-final delta per
    car is therefore 30400 cents over the two-car order.

    Design: Corner/calculations/order_price_quote_reconciliation_committed_basis_carries_to_fleet
    """
    set_clock("2027-02-01T00:00:00Z")
    catalogue = box_car_catalogue(set_clock_first=False)
    pair = commercial(
        "Reconcile Rail Co",
        utilization_threshold_pct=70,
        per_diem_rate_cents=5000,
        liability_bearer="LESSOR",
        fleet_car_cap=10,
    )
    order = create_order(
        catalogue,
        quantity=2,
        planned_shop_days=60,
        disposition="RETAINED",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2027-04-10",
    )
    assert order["unit_price_cents"] == 1629700, (
        "the draft order is quoted on the lapsed forecast basis"
    )

    reserved = reserve_order(order["id"])
    assert reserved["unit_price_cents"] == 1614500
    ensure_coating_supply(
        catalogue["coating"],
        reserved["quantity"],
        reserved["required_delivery_date"],
        order_date=reserved["order_date"],
    )
    release_order(order["id"], lease_contract_id=pair["contract"]["id"])
    start_production(
        order["id"],
        catalogue["car_type"]["line_count_family"],
        window_start="2027-02-02",
        headers=PLANNER,
    )
    complete_order(order["id"], completion_date="2027-04-03")

    cars = get_success_data(
        api_client.list_lease_fleet_cars(
            ADMIN, {"production_order_id": order["id"], "limit": 10}
        )
    )
    assert len(cars) == 2
    for car in cars:
        assert car["acquisition_cost_cents"] == 1614500, (
            "the committed basis, never the 1629700 forecast figure"
        )
        assert car["built_date"] == "2027-04-03"
        assert car["status"] == "HELD"

    contract = get_success_data(
        api_client.get_lease_contract(pair["contract"]["id"], LEASE)
    )
    assert contract["capital_allocation_cents"] == 3229000
    assert 2 * 1629700 - contract["capital_allocation_cents"] == 30400


def test_sold_completion_leaves_contract_capital_untouched_and_debits_the_lessee(api):
    """PRD §3.4: "On the `SOLD` basis the capital never enters the fleet at all:
    `capital_allocation_cents` keeps whatever value it previously held, and the
    order's value is accrued against the lessee's `outstanding_balance_cents`
    instead."
    PRD §3.4: "On the sold branch, the lessee named on the request — or, when the
    body omits `lessee_id`, the lessee of the only `LESSOR`-liable contract in
    `ACTIVE` status — has its `outstanding_balance_cents` debited by the order's
    `unit_price_cents` multiplied by the order's `quantity`."

    Two sold cars at the 1614500-cent quote leave the contract's capital at the
    zero it already held and put 3229000 on the lessee instead, and no fleet car
    is minted at all, so the two figures are a partition rather than a double
    count.

    Design: Corner/calculations/lease_fleet_capital_allocation_variant_selection_sold_basis_defers_to_lessee
    """
    set_clock(CLOCK_START_ISO)
    catalogue = box_car_catalogue()
    pair = commercial(
        "Sold Basis Rail Co",
        utilization_threshold_pct=70,
        per_diem_rate_cents=5000,
        liability_bearer="LESSOR",
        fleet_car_cap=10,
    )
    world = setup_order_in_state(
        "COMPLETED",
        catalogue=catalogue,
        quantity=2,
        disposition="SOLD",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-12-01",
        lessee_id=pair["lessee"]["id"],
        lease_contract_id=pair["contract"]["id"],
        changeover_start="2026-09-05",
        completion_date="2026-11-04",
    )
    assert world["order"]["unit_price_cents"] == 1614500

    contract = get_success_data(
        api_client.get_lease_contract(pair["contract"]["id"], LEASE)
    )
    assert contract["capital_allocation_cents"] == 0, (
        "the sold basis never moves capital into the fleet"
    )

    balance = get_success_data(
        api_client.get_lessee_outstanding_balance(pair["lessee"]["id"], LEASE)
    )
    assert balance["outstanding_balance_cents"] == 3229000, (
        "1614500 per car over two completed SOLD cars"
    )

    cars = get_success_data(
        api_client.list_lease_fleet_cars(
            ADMIN, {"production_order_id": world["order"]["id"], "limit": 10}
        )
    )
    assert cars == [], "a sold completion mints no fleet car"


def test_retained_credit_nets_the_fleet_basis_out_of_the_lessee_balance(api):
    """PRD §3.9: "A lessee's `outstanding_balance_cents` is the sum of the
    `mileage_overage_cents` of its returns whose `settlement_status` is
    `SETTLED`, plus the sum of `unit_price_cents` multiplied by `quantity` over
    its production orders that are `COMPLETED` with disposition `SOLD`, plus the
    sum of `writeback_liability_cents` over its sales that are `SETTLED`, minus
    the sum of `unit_price_cents` multiplied by the retained car count over its
    orders with disposition `RETAINED`. The whole figure is then clamped at
    zero."
    PRD §3.4: "The capital figure is the size of that set multiplied by the
    order's `unit_price_cents`."

    One retained car and two sold cars of the same 1614500-cent order partition
    the value: the fleet basis holds 1 * 1614500 and the lessee balance holds
    2 * 1614500 - 1 * 1614500 == 1614500, so the two figures re-sum to the sold
    order's value rather than to the gross value of all three cars.

    Design: Corner/calculations/lease_fleet_capital_allocation_reconciliation_retained_and_sold_partition
    """
    set_clock(CLOCK_START_ISO)
    catalogue = box_car_catalogue()
    pair = commercial(
        "Partition Rail Co",
        utilization_threshold_pct=70,
        per_diem_rate_cents=5000,
        liability_bearer="LESSOR",
        fleet_car_cap=10,
    )
    retained = setup_order_in_state(
        "COMPLETED",
        catalogue=catalogue,
        quantity=1,
        disposition="RETAINED",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-12-01",
        lease_contract_id=pair["contract"]["id"],
        changeover_start="2026-09-05",
        completion_date="2026-10-05",
    )
    sold = setup_order_in_state(
        "COMPLETED",
        catalogue=catalogue,
        quantity=2,
        disposition="SOLD",
        priority_rank=2,
        order_date="2026-09-01",
        required_delivery_date="2026-12-01",
        lessee_id=pair["lessee"]["id"],
        lease_contract_id=pair["contract"]["id"],
        changeover_start="2026-10-05",
        completion_date="2026-12-04",
    )
    assert retained["order"]["unit_price_cents"] == 1614500
    assert sold["order"]["unit_price_cents"] == 1614500

    contract = get_success_data(
        api_client.get_lease_contract(pair["contract"]["id"], LEASE)
    )
    assert contract["capital_allocation_cents"] == 1614500, (
        "only the one retained car counts toward the fleet basis"
    )

    balance = get_success_data(
        api_client.get_lessee_outstanding_balance(pair["lessee"]["id"], LEASE)
    )
    assert balance["outstanding_balance_cents"] == 1614500
    assert (
        contract["capital_allocation_cents"] + balance["outstanding_balance_cents"]
        == 3229000
    ), "the two figures reconcile to the two sold cars' value"


def test_settled_disposal_moves_the_oldest_basis_and_not_the_newest(api):
    """PRD §3.9: "The disposal proceeds term is the sum of `sale_price_cents`
    over every sale in `SETTLED` status, floored at zero; sales that are `VOIDED`
    or still `PENDING_SETTLEMENT` contribute nothing."
    PRD §3.9: "The sale's `gain_loss_cents` is the `sale_price_cents` minus that
    book value minus the sale's `writeback_liability_cents`"
    PRD §3.9: "the portfolio ledger's `realized_gain_cents` is adjusted by the
    sale's `gain_loss_cents`"

    One of two 71000-cent cars is sold for 30000 cents and settled at age twenty
    days, so the historic basis charges the whole 30000 against the 142000 of
    committed capital while the newest basis depreciates the surviving car by
    20 * 2500: 112000 against 21000, a drift of 91000.

    Design: Corner/calculations/fleet_capital_reconciliation_variant_divergence_oldest_vs_newest
    """
    set_clock(CLOCK_START_ISO)
    catalogue = flat_car_catalogue()
    world = held_cars(
        catalogue,
        car_count=2,
        changeover_start="2026-09-02",
        completion_date="2026-09-04",
        required_delivery_date="2026-09-20",
    )
    advance_clock_to("2026-09-24T00:00:00Z")

    sale = create_sale(
        world["cars"][0],
        sale_price_cents=30000,
        sale_date="2026-09-24",
        writeback_liability_cents=0,
    )
    assert sale["gain_loss_cents"] == 9000, (
        "30000 price less the 21000-cent book value at age twenty days"
    )
    assert settle_sale(sale["id"])["status"] == "SETTLED"

    reconciliation = get_success_data(
        api_client.get_portfolio_ledger_reconciliation(ADMIN)
    )
    assert reconciliation["oldest_basis_cents"] == 112000, (
        "142000 of committed capital less the 30000 of settled proceeds"
    )
    assert reconciliation["newest_basis_cents"] == 21000, (
        "only the surviving car is live, at 71000 - 20 * 2500"
    )
    assert reconciliation["drift_cents"] == 91000
    assert reconciliation["realized_gain_cents"] == 9000
