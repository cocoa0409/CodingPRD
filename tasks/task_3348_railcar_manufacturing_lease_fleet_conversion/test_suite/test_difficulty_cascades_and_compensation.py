"""Difficulty queue: transitive cascades and compensating invariants.

Four instances, one test each:

* ``transitive_cascade`` — a retained completion walks order -> fleet cars ->
  contract capital -> portfolio ledger, and settling a sale walks sale ->
  ledger realized gain -> fleet net book value.
* ``compensating_invariant`` — voiding a sale restores the ledger's realized
  gain, and cancelling a reservation restores every covered component's
  on-hand quantity.
"""

from test_helpers import (
    TEST_USERS,
    api_client,
    complete_order,
    create_lessee_and_contract,
    create_order,
    create_sale,
    get_success_data,
    release_order,
    reserve_order,
    set_clock,
    settle_sale,
    setup_catalogue,
    start_production,
    validate_success,
    void_sale,
)

LEASE = TEST_USERS["lease_administrator_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
PORTFOLIO = TEST_USERS["portfolio_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def _small_catalogue(*, on_hand_qty: int = 4, lead_time_days: int = 40):
    """A two-row BOXCAR catalogue whose committed quote is 660000 cents.

    WHEELSET 250000 at 1 per car, CASTING 180000 at 1 per car, build_hours 4:
    lines 275000 and 205000, labour 4 * 45000 = 180000, no change fee.
    """
    return setup_catalogue(
        model_code="BOX-100",
        car_class="BOXCAR",
        build_hours=4,
        regulatory_life_years=25,
        line_count_family="BOX_LINE",
        wheelset_part_number="WS-1000",
        wheelset_unit_cost_cents=250000,
        wheelset_qty_per_car=1,
        wheelset_lead_time_days=lead_time_days,
        casting_part_number="CS-2000",
        casting_unit_cost_cents=180000,
        casting_qty_per_car=1,
        casting_lead_time_days=20,
        include_coating=False,
        on_hand_qty=on_hand_qty,
    )


# ─── transitive_cascade ───────────────────────────────

def test_retained_completion_cascades_capital_into_contract_and_ledger(api):
    """PRD §3.4: "On the retained branch, completion creates one fleet car per
    car built, each starting in `HELD` with its `production_order_id` pointing
    at the producing order, its `acquisition_cost_cents` equal to the order's
    `unit_price_cents`, and its `built_date` set to the completion date".
    PRD §3.4: "The capital figure is the size of that set multiplied by the
    order's `unit_price_cents`."
    PRD §3.4: "The completion also advances the portfolio ledger: its
    `committed_capital_cents` is increased by the order's `unit_price_cents`
    multiplied by the number of cars completed, and its `fleet_nbv_cents` is
    re-derived by the reconciliation rule of §3.9."

    Each hop is caused by the previous one: the cars must exist before the
    contract's capital can count them, and the ledger's net book value is taken
    over the very same live-car set.

    Design: Difficulty/transitive_cascade/retained_completion_fleet_capital_cascade
    """
    # The catalogue helper pins the clock to the startup default, so the
    # scenario's own instant is pinned after it — the ledger's net book value
    # is read at the completion date, where no depreciation has elapsed.
    catalogue = _small_catalogue()
    set_clock("2026-06-01T00:00:00Z")
    world = create_lessee_and_contract(
        legal_name="Capital Cascade Lessee",
        credit_tier="A",
        utilization_threshold_pct=60,
        credit_ceiling_cents=50000000,
        lease_type="FULL_SERVICE",
        per_diem_rate_cents=45000,
        liability_bearer="LESSOR",
        term_start_date="2026-01-01",
        term_end_date="2027-12-31",
        fleet_car_cap=2,
    )
    lessee, contract = world["lessee"], world["contract"]

    order = create_order(
        catalogue,
        quantity=2,
        planned_shop_days=8,
        disposition="RETAINED",
        priority_rank=1,
        order_date="2026-05-30",
        required_delivery_date="2026-08-31",
        lessee_id=lessee["id"],
    )
    assert order["unit_price_cents"] == 660000
    reserve_order(order["id"])
    release_order(order["id"], lease_contract_id=contract["id"])
    start_production(order["id"], "BOX_LINE", window_start="2026-06-01",
                     window_days=8)

    completed = complete_order(
        order["id"], completed_qty=2, completion_date="2026-06-01"
    )

    # Hop 1: the order closes.
    assert completed["status"] == "COMPLETED"
    assert completed["completed_qty"] == 2

    # Hop 2: the completion minted the fleet cars.
    cars = get_success_data(
        api_client.list_lease_fleet_cars(
            ADMIN, {"production_order_id": order["id"]}
        )
    )
    assert len(cars) == 2
    for car in cars:
        assert car["status"] == "HELD"
        assert car["production_order_id"] == order["id"]
        assert car["acquisition_cost_cents"] == 660000

    # Hop 3: only now can the contract's capital count those two cars.
    refreshed = get_success_data(
        api_client.get_lease_contract(contract["id"], LEASE)
    )
    assert refreshed["capital_allocation_cents"] == 1320000, (
        "capital = 2 live cars of the order * 660000 cents"
    )

    # Terminal hop: the ledger is re-derived over the same live-car set, with
    # zero elapsed depreciation on the completion date.
    ledger = get_success_data(api_client.get_portfolio_ledger(PORTFOLIO))
    assert ledger["committed_capital_cents"] == 1320000
    assert ledger["fleet_nbv_cents"] == 1320000
    assert ledger["realized_gain_cents"] == 0


def test_settled_sale_moves_ledger_realized_gain_and_recomputes_nbv(api):
    """PRD §3.9: "On success the sale becomes `SETTLED`, the portfolio ledger's
    `realized_gain_cents` is adjusted by the sale's `gain_loss_cents`, and —
    when the terminated contract's `liability_bearer` was `LESSEE` — the
    lessee's `outstanding_balance_cents` is credited by the
    `writeback_liability_cents`."
    PRD §3.9: "The ledger's `fleet_nbv_cents` is re-derived by the
    reconciliation rule below, and the sale's and the ledger's versions both
    move."
    PRD §3.9: "The sale's `gain_loss_cents` is the `sale_price_cents` minus that
    book value minus the sale's `writeback_liability_cents`, and the associated
    balance delta is the gain or loss minus the writeback liability again."

    The ledger hop is caused by the settlement, not by the sale's creation: the
    car was already SOLD when the gain landed.

    Design: Difficulty/transitive_cascade/sale_settlement_realized_gain_cascade
    """
    set_clock("2026-06-01T00:00:00Z")
    catalogue = _small_catalogue(on_hand_qty=2)
    world = create_lessee_and_contract(
        legal_name="Settlement Cascade Lessee",
        credit_tier="A",
        utilization_threshold_pct=60,
        credit_ceiling_cents=50000000,
        lease_type="FULL_SERVICE",
        per_diem_rate_cents=45000,
        liability_bearer="LESSOR",
        term_start_date="2026-01-01",
        term_end_date="2027-12-31",
        fleet_car_cap=1,
    )
    lessee, contract = world["lessee"], world["contract"]

    order = create_order(
        catalogue,
        quantity=1,
        planned_shop_days=4,
        disposition="RETAINED",
        priority_rank=1,
        order_date="2026-05-30",
        required_delivery_date="2026-08-31",
        lessee_id=lessee["id"],
    )
    reserve_order(order["id"])
    release_order(order["id"], lease_contract_id=contract["id"])
    start_production(order["id"], "BOX_LINE", window_start="2026-06-01",
                     window_days=4)
    complete_order(order["id"], completed_qty=1, completion_date="2026-06-01")

    # No placement ever referenced the contract, so termination closes nothing
    # and the car keeps its HELD status with no contract stamp.
    terminated = validate_success(
        api_client.terminate_lease_contract(contract["id"], LEASE, {})
    )
    assert terminated["status"] == "TERMINATED"

    car = get_success_data(
        api_client.list_lease_fleet_cars(
            ADMIN, {"production_order_id": order["id"]}
        )
    )[0]
    assert car["acquisition_cost_cents"] == 660000
    assert car["built_date"] == "2026-06-01"

    ledger_before = get_success_data(api_client.get_portfolio_ledger(PORTFOLIO))
    assert ledger_before["committed_capital_cents"] == 660000

    # Sold on its build date, so no depreciation has accrued: the gain is
    # 700000 - 660000 - 0 = 40000 cents.
    sale = create_sale(
        car, sale_price_cents=700000, sale_date="2026-06-01",
        writeback_liability_cents=0, buyer_name="Great Lakes Freight",
    )
    assert sale["gain_loss_cents"] == 40000

    pending_ledger = get_success_data(api_client.get_portfolio_ledger(PORTFOLIO))
    assert pending_ledger["realized_gain_cents"] == 0, (
        "creating a sale must not move the ledger; only settlement does"
    )

    # Hop 1: the settlement lands.
    settled = settle_sale(sale["id"])
    assert settled["status"] == "SETTLED"

    # Hop 2: the ledger absorbs exactly the sale's recorded gain.
    ledger = get_success_data(api_client.get_portfolio_ledger(PORTFOLIO))
    assert ledger["realized_gain_cents"] == 40000, (
        "the ledger's realized gain must move by the settled sale's own "
        "gain_loss_cents"
    )

    # The same hop re-derives the live-fleet net book value; the car left the
    # live set when it was sold, so the sum is over zero cars.
    assert ledger["fleet_nbv_cents"] == 0

    # Boundary of the chain: the settlement mutated nothing else on the car.
    after = get_success_data(api_client.get_lease_fleet_car(car["id"], ADMIN))
    assert after["status"] == "SOLD"


# ─── compensating_invariant ───────────────────────────

def test_voiding_a_sale_restores_realized_gain_and_live_fleet_nbv(api):
    """PRD §2.9: "The ledger's `version` increments on every write that touches
    it, and `realized_gain_cents` moves only on settlement — voiding a sale
    must leave it exactly where it stood before that sale was created."
    PRD §2.10: "Where an operation is a compensating action — voiding a sale,
    cancelling a reservation, returning an endorsement to pending — it must
    restore the affected derived fields to the values they would hold had the
    original write never occurred."
    PRD §3.9: "The disposal proceeds term is the sum of `sale_price_cents` over
    every sale in `SETTLED` status, floored at zero; sales that are `VOIDED` or
    still `PENDING_SETTLEMENT` contribute nothing."

    The conserved quantity is the ledger's realized gain: 97500 cents stand
    from the first, settled sale and the forward-then-voided second sale must
    not disturb it, while the voided row survives as VOIDED and drops out of
    the settled-proceeds aggregate.

    Design: Difficulty/compensating_invariant/sale_void_conserves_realized_gain
    """
    # The catalogue helper pins the clock to the startup default, so the
    # scenario's own instant is pinned after it; the reconciliation reads below
    # depreciate the live cars against this clock date.
    catalogue = setup_catalogue(
        model_code="TC-4700",
        car_class="TANK",
        build_hours=6,
        regulatory_life_years=40,
        line_count_family="FAM-A",
        wheelset_part_number="WS-1001",
        wheelset_unit_cost_cents=180000,
        wheelset_qty_per_car=4,
        wheelset_lead_time_days=30,
        include_casting=False,
        include_coating=False,
        on_hand_qty=200,
    )
    set_clock("2026-10-01T00:00:00Z")

    def _retained_order(priority_rank: int):
        order = create_order(
            catalogue,
            quantity=1,
            planned_shop_days=6,
            disposition="RETAINED",
            priority_rank=priority_rank,
            order_date="2026-09-01",
            required_delivery_date="2027-03-01",
        )
        assert order["unit_price_cents"] == 1015000
        reserve_order(order["id"])
        release_order(order["id"])
        return order

    # Baseline leg: order A completes, its car sells at 1100000 on day 5 of its
    # life (book 1015000 - 5 * 2500 = 1002500) and settles for a 97500 gain.
    order_a = _retained_order(priority_rank=1)
    start_production(order_a["id"], "FAM-A", window_start="2026-09-14",
                     window_days=6)
    complete_order(order_a["id"], completed_qty=1, completion_date="2026-09-20")
    car_a = get_success_data(
        api_client.list_lease_fleet_cars(
            ADMIN, {"production_order_id": order_a["id"]}
        )
    )[0]
    assert car_a["acquisition_cost_cents"] == 1015000

    sale_a = create_sale(
        car_a, sale_price_cents=1100000, sale_date="2026-09-25",
        writeback_liability_cents=0, buyer_name="Steel Wheel Partners",
    )
    assert sale_a["gain_loss_cents"] == 97500
    settle_sale(sale_a["id"])

    # Second leg: order B completes so a live car exists again.
    order_b = _retained_order(priority_rank=2)
    start_production(order_b["id"], "FAM-A", window_start="2026-09-21",
                     window_days=6)
    complete_order(order_b["id"], completed_qty=1, completion_date="2026-09-27")
    car_b = get_success_data(
        api_client.list_lease_fleet_cars(
            ADMIN, {"production_order_id": order_b["id"]}
        )
    )[0]
    assert car_b["acquisition_cost_cents"] == 1015000

    snapshot = get_success_data(
        api_client.get_portfolio_ledger_reconciliation(PORTFOLIO)
    )
    assert snapshot["realized_gain_cents"] == 97500
    assert snapshot["committed_capital_cents"] == 2030000

    # Forward action: car B sells on day 4 of its life (book
    # 1015000 - 4 * 2500 = 1005000) for a 195000 gain, still pending.
    sale_b = create_sale(
        car_b, sale_price_cents=1200000, sale_date="2026-10-01",
        writeback_liability_cents=0, buyer_name="Great Lakes Rail Leasing",
    )
    assert sale_b["gain_loss_cents"] == 195000

    midflight = get_success_data(
        api_client.get_portfolio_ledger_reconciliation(PORTFOLIO)
    )
    assert midflight["realized_gain_cents"] == 97500, (
        "an unsettled sale contributes nothing to the realized gain"
    )
    assert midflight["newest_basis_cents"] == 0, (
        "both cars are SOLD, so no car remains in the live-fleet basis"
    )

    # Compensating action: the void must erase the forward write exactly.
    voided = void_sale(sale_b["id"], reason="buyer financing fell through")
    assert voided["status"] == "VOIDED"
    assert voided["gain_loss_cents"] == 195000, (
        "the voided row keeps its recorded gain while contributing nothing"
    )

    post = get_success_data(
        api_client.get_portfolio_ledger_reconciliation(PORTFOLIO)
    )
    assert post["realized_gain_cents"] == 97500
    assert post["realized_gain_cents"] == snapshot["realized_gain_cents"], (
        "the pair must be exactly compensating on the ledger scalar"
    )
    assert post["newest_basis_cents"] == 1005000, (
        "the void puts car B back into the live-fleet basis at its "
        "depreciated book value"
    )
    assert post["oldest_basis_cents"] == 930000, (
        "committed capital 2030000 less the only settled proceeds 1100000; the "
        "voided sale's 1200000 price is excluded"
    )
    assert post["drift_cents"] == -75000
    assert post["committed_capital_cents"] == 2030000

    restored_car = get_success_data(
        api_client.get_lease_fleet_car(car_b["id"], ADMIN)
    )
    assert restored_car["status"] == "HELD"
    standing_car = get_success_data(
        api_client.get_lease_fleet_car(car_a["id"], ADMIN)
    )
    assert standing_car["status"] == "SOLD", (
        "the first sale was settled and never compensated, so it stands"
    )


def test_cancelling_a_reserved_order_restores_every_covered_component(api):
    """PRD §3.4: "Cancelling a component-reserved order restores the
    `on_hand_qty` of every covered bill-of-material row and leaves each
    component's `reserved_qty` unchanged, and it supersedes every endorsement of
    that order that is still in `PENDING`, `APPROVED` or `APPLIED` status — a
    cancelled order can never ship a substitution."
    PRD §3.2: "A successful reservation commits the wheelset and casting stock:
    for each covered row, the component's `on_hand_qty` is decremented by the
    effective per-car quantity multiplied by the order quantity, and the
    component's `reserved_qty` is recomputed by the allocation rule below."
    PRD §3.2: "`COATING` rows are exempt from the on-hand test — they are
    procured to contract and commit through the purchase-receipt path instead".

    The conserved quantity is the physical inventory count: every covered
    component must land back on its pre-reservation figure.

    Design: Difficulty/compensating_invariant/reserve_cancel_conserves_component_on_hand
    """
    set_clock("2026-10-01T00:00:00Z")
    catalogue = setup_catalogue(
        model_code="TC-5100",
        car_class="BOXCAR",
        build_hours=5,
        regulatory_life_years=30,
        line_count_family="FAM-B",
        wheelset_part_number="WS-2001",
        wheelset_unit_cost_cents=150000,
        wheelset_qty_per_car=4,
        wheelset_lead_time_days=20,
        casting_part_number="CS-2002",
        casting_unit_cost_cents=90000,
        casting_qty_per_car=2,
        casting_lead_time_days=45,
        coating_part_number="CT-2003",
        coating_unit_cost_cents=30000,
        coating_qty_per_car=6,
        coating_lead_time_days=90,
        on_hand_qty=500,
    )
    wheelset, casting, coating = (
        catalogue["wheelset"], catalogue["casting"], catalogue["coating"]
    )

    order = create_order(
        catalogue,
        quantity=5,
        planned_shop_days=25,
        disposition="SOLD",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2027-03-01",
    )

    def _on_hand(component_id: str) -> dict:
        return get_success_data(api_client.get_component(component_id, ADMIN))

    snapshots = {
        "wheelset": _on_hand(wheelset["id"]),
        "casting": _on_hand(casting["id"]),
        "coating": _on_hand(coating["id"]),
    }
    assert snapshots["wheelset"]["on_hand_qty"] == 500
    assert snapshots["casting"]["on_hand_qty"] == 500
    assert snapshots["coating"]["on_hand_qty"] == 500

    # Forward leg: wheelsets drop by 4 * 5 = 20 and castings by 2 * 5 = 10.
    reserved_order = reserve_order(order["id"])
    assert reserved_order["status"] == "COMPONENT_RESERVED"
    assert _on_hand(wheelset["id"])["on_hand_qty"] == 480
    assert _on_hand(casting["id"])["on_hand_qty"] == 490
    assert _on_hand(coating["id"])["on_hand_qty"] == 500, (
        "the COATING row is exempt from the stock-commit path"
    )

    # Compensating leg.
    cancelled = validate_success(
        api_client.cancel_production_order(
            order["id"], PLANNER, {"reason": "customer withdrew the order"}
        )
    )
    assert cancelled["status"] == "CANCELLED"

    final_wheelset = _on_hand(wheelset["id"])
    final_casting = _on_hand(casting["id"])
    final_coating = _on_hand(coating["id"])
    assert final_wheelset["on_hand_qty"] == 500
    assert final_casting["on_hand_qty"] == 500
    assert final_coating["on_hand_qty"] == 500
    assert final_wheelset["on_hand_qty"] == snapshots["wheelset"]["on_hand_qty"]
    assert final_casting["on_hand_qty"] == snapshots["casting"]["on_hand_qty"]

    # Reserved quantity is derived, not restored: the allocation rule counts
    # only RELEASED orders and this one never left COMPONENT_RESERVED.
    assert final_wheelset["reserved_qty"] == 0
    assert final_casting["reserved_qty"] == 0

    persisted = get_success_data(
        api_client.get_production_order(order["id"], ADMIN)
    )
    assert persisted["status"] == "CANCELLED"
