"""Action endpoints: the writes that move an aggregate and cascade.

Each test drives one action endpoint and asserts the transition together with
every declared side effect on the re-read entities.  The production catalogue is
pinned in every test, so each quoted price is a function of the PRD's formulas
and of the fixture's own numbers rather than of a default the shared catalogue
helper happens to carry.
"""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_endorsement,
    changeover_payload,
    complete_production_order_payload,
    create_assignment,
    create_car_type_component_requirement_payload,
    create_component_payload,
    create_component_purchase_order_payload,
    create_component_receipt_payload,
    create_endorsement,
    create_lessee_and_contract,
    create_lessee_payload,
    create_order,
    create_return,
    create_retrofit_program_car_type_payload,
    create_retrofit_program_payload,
    get_success_data,
    release_order,
    reserve_order,
    setup_catalogue,
    setup_retained_order_with_fleet_cars,
    start_production,
    terminate_lease_contract_payload,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SUPPLY = TEST_USERS["supply_chain_coordinator_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
LEASE = TEST_USERS["lease_administrator_headers"]
PORTFOLIO = TEST_USERS["portfolio_manager_headers"]
RETROFIT = TEST_USERS["regulatory_retrofitist_headers"]


# ─── Catalogue builders (every value pinned by the test) ───

def two_row_catalogue(**overrides):
    """One BOXCAR type carrying a wheelset row and a casting row, no coating.

    ``CT-A`` builds in 2 hours, so a five-car order quotes
    ceil((4 * 120000 + 25000) / 100) * 100 + ceil((2 * 80000 + 25000) / 100) * 100
    + 2 * 45000 == 780000.
    """
    defaults = dict(
        model_code="CT-A",
        car_class="BOXCAR",
        build_hours=2,
        regulatory_life_years=25,
        line_count_family="LINE-A",
        wheelset_part_number="WS-A1",
        wheelset_unit_cost_cents=120000,
        wheelset_lead_time_days=20,
        wheelset_qty_per_car=4,
        casting_part_number="CS-A1",
        casting_unit_cost_cents=80000,
        casting_lead_time_days=15,
        casting_qty_per_car=2,
        include_coating=False,
        on_hand_qty=100,
    )
    defaults.update(overrides)
    return setup_catalogue(**defaults)


def single_row_catalogue(**overrides):
    """A car type whose bill of materials is exactly one wheelset row."""
    defaults = dict(
        model_code="CT-C",
        car_class="BOXCAR",
        build_hours=2,
        regulatory_life_years=25,
        line_count_family="LINE-C",
        wheelset_part_number="WS-C1",
        wheelset_unit_cost_cents=1000,
        wheelset_lead_time_days=5,
        wheelset_qty_per_car=4,
        include_bom=False,
        include_coating=False,
        on_hand_qty=100,
    )
    defaults.update(overrides)
    catalogue = setup_catalogue(**defaults)
    catalogue["bom"] = [
        get_success_data(
            api_client.create_car_type_component_requirement(
                create_car_type_component_requirement_payload(
                    car_type_id=catalogue["car_type"]["id"],
                    component_id=catalogue["wheelset"]["id"],
                    qty_per_car=defaults["wheelset_qty_per_car"],
                ),
                PLANNER,
            )
        )
    ]
    return catalogue


# ─── Action endpoints ─────────────────────────────────

def test_reserve_components_commits_stock_and_requotes(api):
    """PRD §3.2: "A successful reservation commits the wheelset and casting
    stock: for each covered row, the component's `on_hand_qty` is decremented by
    the effective per-car quantity multiplied by the order quantity, and the
    component's `reserved_qty` is recomputed by the allocation rule below."
    PRD §3.2: "For a given component, the reservation term is the sum, over every
    bill-of-material row that names that component, of the row's `qty_per_car`
    multiplied by the total quantity of production orders that build that row's
    car type and are in `RELEASED` status; orders in `DRAFT`,
    `COMPONENT_RESERVED`, `COMPLETED` or `CANCELLED` contribute nothing."
    PRD §3.1: "The labor charge is the car type's `build_hours` multiplied by the
    labor rate of 45,000 cents per build hour."

    Reserving a five-car order takes 20 wheelsets and 10 castings off the shelf
    and re-quotes it at the committed 780000, while the derived `reserved_qty`
    stays 0 until the order is released.

    Design: Corner/endpoints/endpoint_action_reserve_components_commits_stock_and_requotes
    """
    catalogue = two_row_catalogue()
    order = create_order(
        catalogue,
        quantity=5,
        planned_shop_days=10,
        disposition="SOLD",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-12-01",
    )
    assert order["unit_price_cents"] == 780000, (
        "the same-day clock leaves the forecast basis equal to the committed "
        "basis: 505000 + 185000 + 2 * 45000"
    )

    reserved = validate_success(api_client.reserve_components(order["id"], PLANNER))
    assert reserved["status"] == "COMPONENT_RESERVED"
    assert reserved["version"] == 2, "creation version 1 plus the transition's own"
    assert reserved["unit_price_cents"] == 780000

    wheelset = get_success_data(api_client.get_component(catalogue["wheelset"]["id"], ADMIN))
    casting = get_success_data(api_client.get_component(catalogue["casting"]["id"], ADMIN))
    assert wheelset["on_hand_qty"] == 80, "100 less qty_per_car 4 * quantity 5"
    assert casting["on_hand_qty"] == 90, "100 less qty_per_car 2 * quantity 5"
    assert wheelset["reserved_qty"] == 0
    assert casting["reserved_qty"] == 0, (
        "the reservation term counts only RELEASED orders and this one is still "
        "COMPONENT_RESERVED"
    )


def test_release_applies_the_approved_endorsement_and_requotes(api):
    """PRD §3.3: "Releasing a component-reserved order applies every `APPROVED`
    endorsement on it, moving each to `APPLIED`."
    PRD §3.3: "Applying an endorsement replaces the original component's
    committed stock with the substitute's for the endorsed requirement row and
    recomputes `reserved_qty` for both components by the allocation rule of §3.2,
    and it re-quotes the order on the committed basis."
    PRD §3.1: "The change fee actually charged is the smaller of the raw fee and
    the cap, and the order's `unit_price_cents` is the unrounded total plus that
    change fee."

    The endorsed quote is 425000 + 185000 + 90000 + min(15000, 56000) == 715000;
    the substitute absorbs the 20 committed units and the original's stock is
    restored.

    Design: Corner/endpoints/endpoint_action_release_applies_approved_endorsement_and_requotes
    """
    catalogue = two_row_catalogue()
    substitute = get_success_data(
        api_client.create_component(
            create_component_payload(
                part_number="WS-A2",
                component_class="WHEELSET",
                unit_cost_cents=100000,
                lead_time_days=10,
                on_hand_qty=100,
            ),
            SUPPLY,
        )
    )
    order = create_order(
        catalogue,
        quantity=5,
        planned_shop_days=10,
        disposition="SOLD",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-12-01",
    )
    reserved = reserve_order(order["id"])

    endorsement = create_endorsement(
        order,
        catalogue["wheelset"],
        substitute,
        substitute_qty_per_car=4,
        decides_material=False,
        expected_production_order_version=reserved["version"],
    )
    approved = approve_endorsement(endorsement["id"])
    assert approved["status"] == "APPROVED"
    requoted = get_success_data(api_client.get_production_order(order["id"], ADMIN))
    assert requoted["unit_price_cents"] == 715000, (
        "approval alone re-quotes the order with the substitute standing in"
    )

    released = validate_success(api_client.release_production_order(order["id"], PLANNER))
    assert released["status"] == "RELEASED"
    assert released["version"] == 4, "create 1 -> reserve 2 -> endorsement 3 -> release 4"
    assert released["unit_price_cents"] == 715000

    applied = get_success_data(
        api_client.get_substitution_endorsement(endorsement["id"], ADMIN)
    )
    assert applied["status"] == "APPLIED"

    substitute_after = get_success_data(api_client.get_component(substitute["id"], ADMIN))
    original_after = get_success_data(
        api_client.get_component(catalogue["wheelset"]["id"], ADMIN)
    )
    assert substitute_after["on_hand_qty"] == 80, "the substitute absorbed 4 * 5 units"
    assert original_after["on_hand_qty"] == 100, (
        "the original's committed stock was replaced and fully restored"
    )


def test_changeover_starts_the_head_of_backlog_and_sets_the_window_width(api):
    """PRD §3.4: "On success the order moves to `IN_PRODUCTION`, its
    `planned_shop_days` is set to the width of the changeover window — which must
    still equal the car type's `build_hours` multiplied by the order's `quantity`
    — and its `version` and `updated_at` move."

    The sole order on its line family is the head of the backlog by
    `priority_rank`, and its `planned_shop_days` is re-stamped to the width of
    the half-open window [2026-09-10, 2026-09-20) == 2 * 5.

    Design: Corner/endpoints/endpoint_action_changeover_starts_head_of_backlog_and_sets_window_width
    """
    catalogue = single_row_catalogue(
        model_code="CT-C",
        line_count_family="LINE-C",
        wheelset_part_number="WS-C1",
        wheelset_unit_cost_cents=1000,
        wheelset_lead_time_days=5,
        wheelset_qty_per_car=4,
    )
    order = create_order(
        catalogue,
        quantity=5,
        planned_shop_days=10,
        disposition="SOLD",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-12-01",
    )
    reserve_order(order["id"])
    released = release_order(order["id"])
    assert released["status"] == "RELEASED"
    assert released["planned_shop_days"] == 10

    in_production = validate_success(
        api_client.changeover_production_line(
            "LINE-C",
            changeover_payload(
                production_order_id=order["id"],
                scheduled_start_date="2026-09-10",
                scheduled_end_date="2026-09-20",
            ),
            PLANNER,
        )
    )
    assert in_production["status"] == "IN_PRODUCTION"
    assert in_production["planned_shop_days"] == 10, (
        "the width of [2026-09-10, 2026-09-20) is exactly build_hours 2 * quantity 5"
    )
    assert in_production["version"] == 4, (
        "create 1 -> reserve 2 -> release 3 -> changeover 4"
    )


def test_complete_sold_debits_the_lessee_balance(api):
    """PRD §3.4: "On the sold branch, the lessee named on the request — or, when
    the body omits `lessee_id`, the lessee of the only `LESSOR`-liable contract
    in `ACTIVE` status — has its `outstanding_balance_cents` debited by the
    order's `unit_price_cents` multiplied by the order's `quantity`."
    PRD §3.9: "plus the sum of `unit_price_cents` multiplied by `quantity` over
    its production orders that are `COMPLETED` with disposition `SOLD`"

    Completing the five-car sold order debits 780000 * 5 == 3900000 and mints no
    fleet car, because the retained branch never ran.

    Design: Corner/endpoints/endpoint_action_complete_sold_debits_lessee_balance
    """
    catalogue = two_row_catalogue()
    lessee = get_success_data(
        api_client.create_lessee(
            create_lessee_payload(
                legal_name="Complete Debit Rail Co",
                credit_tier="A",
                utilization_threshold_pct=0,
                credit_ceiling_cents=50000000,
            ),
            LEASE,
        )
    )
    assert lessee["outstanding_balance_cents"] == 0

    order = create_order(
        catalogue,
        quantity=5,
        planned_shop_days=10,
        disposition="SOLD",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-12-01",
    )
    reserve_order(order["id"])
    release_order(order["id"])
    in_production = start_production(order["id"], "LINE-A", window_start="2026-09-10")
    assert in_production["status"] == "IN_PRODUCTION"

    completed = validate_success(
        api_client.complete_production_order(
            order["id"],
            complete_production_order_payload(
                completed_qty=5,
                lessee_id=lessee["id"],
                completion_date="2026-09-20",
            ),
            PLANNER,
        )
    )
    assert completed["status"] == "COMPLETED"
    assert completed["completed_qty"] == 5
    assert completed["unit_price_cents"] == 780000, (
        "the debit base is the committed quote"
    )
    assert completed["version"] == 5, (
        "create 1 -> reserve 2 -> release 3 -> changeover 4 -> complete 5"
    )

    balance = get_success_data(
        api_client.get_lessee_outstanding_balance(lessee["id"], ADMIN)
    )
    assert balance["outstanding_balance_cents"] == 3900000, "780000 * 5"
    assert balance["settled_charges_cents"] == 3900000

    cars = get_success_data(
        api_client.list_lease_fleet_cars(ADMIN, {"production_order_id": order["id"]})
    )
    assert cars == [], "the retained branch did not fire, so no fleet car exists"


def test_retrofit_program_start_enrolls_every_covered_car(api):
    """PRD §3.8: "On success the program becomes `IN_PROGRESS`, the
    `retrofit_required` flag is set to true on every fleet car of a covered car
    type whose status is `HELD` or `UNDER_REPAIR`, and the program's
    `program_cost_cents` is re-derived by the cost rule below."
    PRD §2.8: "A car's `retrofit_required` flag is derived too: it is true while
    the car is enrolled in a retrofit program whose status is `IN_PROGRESS` and
    whose `compliance_deadline_date` has not yet passed, and false otherwise."

    Both HELD cars of the covered car type flip to `retrofit_required` true while
    their lifecycle status stays HELD and the program cost stays 0, since no work
    order has completed.

    Design: Corner/endpoints/endpoint_action_retrofit_program_start_enrolls_covered_cars
    """
    catalogue = single_row_catalogue(
        model_code="CT-B",
        build_hours=1,
        line_count_family="LINE-B",
        wheelset_part_number="WS-B1",
        wheelset_unit_cost_cents=1000,
        wheelset_lead_time_days=5,
        wheelset_qty_per_car=1,
    )
    world = setup_retained_order_with_fleet_cars(
        car_count=2,
        catalogue=catalogue,
        build_contract=False,
        changeover_start="2026-09-10",
        completion_date="2026-09-12",
    )
    cars = get_success_data(
        api_client.list_lease_fleet_cars(
            ADMIN, {"production_order_id": world["order"]["id"]}
        )
    )
    assert len(cars) == 2
    assert cars[0]["retrofit_required"] is False
    assert cars[0]["regulatory_life_end_date"] == "2051-09-12", (
        "built_date 2026-09-12 plus regulatory_life_years 25"
    )

    program = get_success_data(
        api_client.create_retrofit_program(
            create_retrofit_program_payload(
                mandate_code="MAND-EP5",
                description="Enrol every covered car at program start",
                compliance_deadline_date="2026-12-31",
                required_shop_days_per_car=3,
            ),
            RETROFIT,
        )
    )
    assert program["status"] == "PLANNED"
    assert program["program_cost_cents"] == 0
    get_success_data(
        api_client.create_retrofit_program_car_type(
            create_retrofit_program_car_type_payload(
                retrofit_program_id=program["id"],
                car_type_id=catalogue["car_type"]["id"],
            ),
            RETROFIT,
        )
    )

    started = validate_success(api_client.start_retrofit_program(program["id"], RETROFIT))
    assert started["status"] == "IN_PROGRESS"
    assert started["version"] == 2
    assert started["program_cost_cents"] == 0, (
        "no work order exists yet, so the cost aggregation has nothing to sum"
    )

    for car in cars:
        after = get_success_data(api_client.get_lease_fleet_car(car["id"], ADMIN))
        assert after["retrofit_required"] is True
        assert after["status"] == "HELD", (
            "only scheduling a work order moves a car to UNDER_REPAIR"
        )


def test_settling_a_car_return_moves_its_charge_into_the_ledger(api):
    """PRD §3.7: "Until a return is settled, its mileage overage does not count
    toward the lessee's balance, because the reconciliation aggregates only
    settled returns."
    PRD §3.7: "the settlement sets the status to `SETTLED` and recomputes the
    lessee's `outstanding_balance_cents` by the reconciliation rule of §3.9, and
    it increments the return's `version`."
    PRD §3.7: "The charge is the overage miles multiplied by the overage rate of
    12 cents per mile, and it is written to the return's `mileage_overage_cents`
    and to the placement's `mileage_charge_cents`."

    A thirty-day placement granting one 1000-mile block against 2500 miles run
    books an 18000-cent true-up: the balance reads 0 while the return is PENDING
    and exactly 18000 once it settles.

    Design: Corner/endpoints/endpoint_action_car_return_settle_moves_charge_into_ledger
    """
    catalogue = single_row_catalogue(
        model_code="CT-C2",
        build_hours=1,
        line_count_family="LINE-C2",
        wheelset_part_number="WS-C2",
        wheelset_unit_cost_cents=1000,
        wheelset_lead_time_days=5,
        wheelset_qty_per_car=1,
    )
    world = setup_retained_order_with_fleet_cars(
        car_count=1,
        catalogue=catalogue,
        build_contract=False,
        changeover_start="2026-09-11",
        completion_date="2026-09-12",
    )
    pair = create_lessee_and_contract(
        legal_name="Settle Rail Co",
        credit_tier="B",
        utilization_threshold_pct=0,
        credit_ceiling_cents=1000000,
        lease_type="FULL_SERVICE",
        per_diem_rate_cents=1000,
        liability_bearer="LESSOR",
        term_start_date="2026-09-01",
        term_end_date="2027-09-01",
        fleet_car_cap=5,
        activate=True,
    )
    assignment = create_assignment(
        world["car"],
        pair["contract"],
        pair["lessee"],
        start_date="2026-09-12",
        end_date="2026-10-12",
        mileage_allowance=1000,
    )
    car_return = create_return(
        world["car"],
        assignment,
        return_date="2026-10-12",
        mileage_since_last=2500,
        condition_grade="A",
    )
    assert car_return["settlement_status"] == "PENDING"
    assert car_return["mileage_overage_cents"] == 18000, (
        "ceil(30 / 30) * 1000 == 1000 included miles, 2500 - 1000 == 1500 "
        "overage miles at 12 cents"
    )

    pending = get_success_data(
        api_client.get_lessee_outstanding_balance(pair["lessee"]["id"], ADMIN)
    )
    assert pending["outstanding_balance_cents"] == 0, (
        "a PENDING return is excluded from the settled-return sum"
    )

    settled = validate_success(api_client.settle_car_return(car_return["id"], PORTFOLIO))
    assert settled["settlement_status"] == "SETTLED"
    assert settled["version"] == 2

    balance = get_success_data(
        api_client.get_lessee_outstanding_balance(pair["lessee"]["id"], ADMIN)
    )
    assert balance["outstanding_balance_cents"] == 18000
    assert balance["settled_charges_cents"] == 18000


def test_terminate_contract_cascades_the_enumerated_placement(api):
    """PRD §3.5: "The request accepts an optional `cascade_assignment_ids` list,
    and the precondition is that no placement referencing this contract may be in
    `ACTIVE` or `SUSPENDED` status unless the body enumerates every such
    placement in that list."
    PRD §3.5: "On success the contract becomes `TERMINATED`, and for each
    placement of this contract in `ACTIVE` or `SUSPENDED` status the placement is
    set to `COMPLETED` and its parent car is returned to `HELD`"

    The same call without the enumeration is refused with `ERR_INVALID_STATE` and
    leaves the contract ACTIVE; with the placement named it terminates and closes
    both the placement and the car.

    Design: Corner/endpoints/endpoint_action_terminate_contract_cascades_listed_assignments
    """
    catalogue = single_row_catalogue(
        model_code="CT-C3",
        build_hours=1,
        line_count_family="LINE-C3",
        wheelset_part_number="WS-C3",
        wheelset_unit_cost_cents=1000,
        wheelset_lead_time_days=5,
        wheelset_qty_per_car=1,
    )
    world = setup_retained_order_with_fleet_cars(
        car_count=1,
        catalogue=catalogue,
        build_contract=False,
        changeover_start="2026-09-11",
        completion_date="2026-09-12",
    )
    pair = create_lessee_and_contract(
        legal_name="Cascade Rail Co",
        credit_tier="B",
        utilization_threshold_pct=0,
        credit_ceiling_cents=1000000,
        lease_type="FULL_SERVICE",
        per_diem_rate_cents=1000,
        liability_bearer="LESSOR",
        term_start_date="2026-09-01",
        term_end_date="2027-09-01",
        fleet_car_cap=5,
        activate=True,
    )
    contract = pair["contract"]
    assert contract["status"] == "ACTIVE"

    assignment = create_assignment(
        world["car"],
        contract,
        pair["lessee"],
        start_date="2026-09-12",
        end_date="2026-10-12",
        mileage_allowance=1000,
    )
    assert assignment["status"] == "ACTIVE"
    car = get_success_data(api_client.get_lease_fleet_car(world["car"]["id"], ADMIN))
    assert car["status"] == "ASSIGNED"

    blocked = api_client.terminate_lease_contract(contract["id"], LEASE)
    validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)
    still_active = get_success_data(api_client.get_lease_contract(contract["id"], ADMIN))
    assert still_active["status"] == "ACTIVE", "the rejection is atomic"

    terminated = validate_success(
        api_client.terminate_lease_contract(
            contract["id"],
            LEASE,
            terminate_lease_contract_payload(cascade_assignment_ids=[assignment["id"]]),
        )
    )
    assert terminated["status"] == "TERMINATED"
    assert terminated["version"] == 3, "create 1 -> activate 2 -> terminate 3"

    closed = get_success_data(api_client.get_car_assignment(assignment["id"], ADMIN))
    assert closed["status"] == "COMPLETED"
    returned = get_success_data(api_client.get_lease_fleet_car(world["car"]["id"], ADMIN))
    assert returned["status"] == "HELD", "the car was returned to the fleet"


def test_applying_a_receipt_books_stock_and_closes_the_purchase_order(api):
    """PRD §3.2: "booking the receipt alone does not change stock"
    PRD §3.2: "Applying it — the receiving action on that receipt — is what moves
    the goods: the parent purchase order must be `CONFIRMED`, and the receipt's
    `receipt_date` must not be before the purchase order's `order_date`, or the
    write is rejected."
    PRD §3.2: "On success the purchase order becomes `RECEIVED`, the component's
    `on_hand_qty` is increased by `qty_received`, and `reserved_qty` and
    `shortfall_qty` are recomputed by the allocation rule above."

    A 500-unit purchase confirmed and booked leaves `on_hand_qty` at 0 until the
    receipt is applied, at which point stock reads 500 and the purchase order
    lands RECEIVED at version 3.

    Design: Corner/endpoints/endpoint_action_receive_books_stock_and_closes_purchase_order
    """
    component = get_success_data(
        api_client.create_component(
            create_component_payload(
                part_number="WS-R1",
                component_class="WHEELSET",
                unit_cost_cents=100000,
                lead_time_days=20,
            ),
            SUPPLY,
        )
    )
    assert component["on_hand_qty"] == 0, "no opening quantity was supplied"

    purchase_order = get_success_data(
        api_client.create_component_purchase_order(
            create_component_purchase_order_payload(
                component_id=component["id"],
                qty_ordered=500,
                unit_cost_cents=100000,
                order_date="2026-09-01",
                expected_receipt_date="2026-09-21",
            ),
            SUPPLY,
        )
    )
    assert purchase_order["status"] == "PLACED"
    assert purchase_order["version"] == 1
    confirmed = get_success_data(
        api_client.confirm_component_purchase_order(purchase_order["id"], SUPPLY)
    )
    assert confirmed["status"] == "CONFIRMED"

    receipt = get_success_data(
        api_client.create_component_receipt(
            create_component_receipt_payload(
                component_purchase_order_id=purchase_order["id"],
                component_id=component["id"],
                qty_received=500,
                receipt_date="2026-09-21",
            ),
            SUPPLY,
        )
    )
    booked = get_success_data(api_client.get_component(component["id"], ADMIN))
    assert booked["on_hand_qty"] == 0, "booking the receipt alone moves no stock"

    applied = validate_success(api_client.receive_component_receipt(receipt["id"], SUPPLY))
    assert applied["qty_received"] == 500

    after = get_success_data(api_client.get_component(component["id"], ADMIN))
    assert after["on_hand_qty"] == 500, "exactly qty_received"
    assert after["reserved_qty"] == 0, (
        "no RELEASED order references this component, so the reservation term is 0"
    )
    purchase_after = get_success_data(
        api_client.get_component_purchase_order(purchase_order["id"], ADMIN)
    )
    assert purchase_after["status"] == "RECEIVED"
    assert purchase_after["version"] == 3, "create 1 -> confirm 2 -> receive 3"
