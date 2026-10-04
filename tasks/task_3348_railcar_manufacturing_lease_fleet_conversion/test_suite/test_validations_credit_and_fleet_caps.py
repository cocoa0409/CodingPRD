"""Validation precedence, bands 18-19: credit exposure and the fleet cap.

Four instances, one test per side of each boundary.  The ceiling tests build a
lessee whose settled balance already stands at 60000 cents and then record a
second return whose projected mileage charge is twelve cents over, or exactly
at, the registered ceiling.  The cap tests release a second retained order
against a contract one car short of, or exactly at, its cap.
"""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    complete_order,
    create_assignment,
    create_car_return_payload,
    create_lessee_and_contract,
    create_order,
    create_return,
    get_success_data,
    release_order,
    reserve_order,
    set_clock,
    settle_return,
    setup_catalogue,
    setup_retained_order_with_fleet_cars,
    start_production,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
LEASE = TEST_USERS["lease_administrator_headers"]


def _two_held_cars(*, model_code, line_family, part_number, changeover_line,
                   changeover_start, completion_date):
    """A catalogue plus a RETAINED order of two cars, completed into two HELD cars."""
    catalogue = setup_catalogue(
        model_code=model_code,
        car_class="BOXCAR",
        build_hours=1,
        regulatory_life_years=15,
        line_count_family=line_family,
        wheelset_part_number=part_number,
        wheelset_unit_cost_cents=1000,
        wheelset_qty_per_car=1,
        lead_time_days=5,
        include_coating=False,
        on_hand_qty=100,
    )
    world = setup_retained_order_with_fleet_cars(
        car_count=2,
        catalogue=catalogue,
        build_contract=False,
        line=changeover_line,
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-09-20",
        changeover_start=changeover_start,
        completion_date=completion_date,
    )
    assert len(world["cars"]) == 2
    assert world["cars"][0]["built_date"] == completion_date
    return world


def _first_return_settled_to(*, world, lessee, contract, ceiling_cents,
                             first_mileage, first_overage_cents):
    """Place both cars, return the first, settle it, and read the balance."""
    car_a, car_b = world["cars"][0], world["cars"][1]
    assignment_a = create_assignment(
        car_a, contract, lessee, start_date="2026-09-05",
        end_date="2026-10-05", mileage_allowance=0,
    )
    assignment_b = create_assignment(
        car_b, contract, lessee, start_date="2026-09-05",
        end_date="2026-10-05", mileage_allowance=0,
    )
    first_return = create_return(
        car_a, assignment_a, return_date="2026-10-05",
        mileage_since_last=first_mileage, condition_grade="A",
    )
    assert first_return["mileage_overage_cents"] == first_overage_cents
    settled = settle_return(first_return["id"])
    assert settled["settlement_status"] == "SETTLED"

    balance = get_success_data(
        api_client.get_lessee_outstanding_balance(lessee["id"], ADMIN)
    )
    assert balance["outstanding_balance_cents"] == first_overage_cents
    assert ceiling_cents > first_overage_cents
    return car_a, car_b, assignment_a, assignment_b


def test_return_pushing_the_balance_past_the_credit_ceiling_is_rejected(api):
    """PRD §2.9: "The credit ceiling is enforced before a charge is booked, not
    after. When a return would add a projected mileage charge to the balance, or
    when a placement is created, the lessee's current `outstanding_balance_cents`
    plus the projected charge must stay at or below `credit_ceiling_cents`; a
    balance exactly equal to the ceiling passes, and only an amount strictly
    above it is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."
    PRD §3.7: "The mileage true-up is charged at return, and it is computed from
    the placement's own allowance rather than the contract's."
    PRD §3.7: "Settlement moves the charge into the ledger. A `PortfolioManager`
    settles a return, which is legal only while its `settlement_status` is
    `PENDING`".

    The projected charge is 40008 against a balance of 60000 and a ceiling of
    99996 — twelve cents over — so the comparison is genuinely strict; the
    rejected call must leave the car, the balance and the mileage untouched.

    Design: Corner/validations/validation_p18_return_pushing_balance_past_credit_ceiling_returns_credit_limit_exceeded
    """
    set_clock("2026-09-01T00:00:00Z")
    world = _two_held_cars(
        model_code="CR-100",
        line_family="CR_LINE",
        part_number="WS-CR-1",
        changeover_line="CR_LINE",
        changeover_start="2026-09-02",
        completion_date="2026-09-04",
    )
    contract_world = create_lessee_and_contract(
        legal_name="Credit Ceiling Rail Co",
        credit_tier="A",
        utilization_threshold_pct=60,
        credit_ceiling_cents=99996,
        lease_type="NET",
        per_diem_rate_cents=2000,
        liability_bearer="LESSEE",
        term_start_date="2026-09-01",
        term_end_date="2027-09-01",
        fleet_car_cap=10,
    )
    lessee, contract = contract_world["lessee"], contract_world["contract"]

    car_a, car_b, _, assignment_b = _first_return_settled_to(
        world=world, lessee=lessee, contract=contract, ceiling_cents=99996,
        first_mileage=5000, first_overage_cents=60000,
    )

    # blocks = ceil(30 / 30) = 1, included miles = 1 * 0 = 0, so all 3334 miles
    # are overage at 12 cents: 3334 * 12 = 40008, and 60000 + 40008 = 100008.
    rejected = api.create_car_return(
        create_car_return_payload(
            lease_fleet_car_id=car_b["id"],
            car_assignment_id=assignment_b["id"],
            return_date="2026-10-05",
            mileage_since_last=3334,
            condition_grade="A",
        ),
        LEASE,
    )
    validate_error(rejected, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
    assert rejected.status_code == 402

    car_after = get_success_data(api.get_lease_fleet_car(car_b["id"], ADMIN))
    assert car_after["status"] == "ASSIGNED", "not UNDER_REPAIR: no partial mutation"
    assert car_after["accumulated_mileage"] == 0

    balance_after = get_success_data(
        api.get_lessee_outstanding_balance(lessee["id"], ADMIN)
    )
    assert balance_after["outstanding_balance_cents"] == 60000, (
        "the rejected return moved no ledger value"
    )
    assert car_a["id"] != car_b["id"]


def test_return_landing_exactly_on_the_credit_ceiling_is_accepted(api):
    """PRD §2.9: "the lessee's current `outstanding_balance_cents` plus the
    projected charge must stay at or below `credit_ceiling_cents`; a balance
    exactly equal to the ceiling passes, and only an amount strictly above it is
    rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."
    PRD §2.11: "Eighteenth, credit exposure: the lessee's
    `outstanding_balance_cents` plus the projected mileage charge must stay at or
    below the lessee's `credit_ceiling_cents`, with equality permitted, and an
    excess is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402) on return
    recording and placement creation."
    PRD §3.7: "On success the placement becomes `COMPLETED`, the parent car moves
    to `UNDER_REPAIR`, and the car's `accumulated_mileage` is recomputed as the
    total miles recorded across every placement and return for that car."

    The projected charge of 39996 brings the settled balance of 60000 to exactly
    99996, so the at-or-below comparison admits the call with zero slack.

    Design: Corner/validations/validation_p18_satisfaction_balance_plus_charge_exactly_at_ceiling_passes
    """
    set_clock("2026-09-01T00:00:00Z")
    world = _two_held_cars(
        model_code="S18-100",
        line_family="S18_LINE",
        part_number="WS-S18-1",
        changeover_line="S18_LINE",
        changeover_start="2026-09-02",
        completion_date="2026-09-04",
    )
    contract_world = create_lessee_and_contract(
        legal_name="Exact Ceiling Rail Co",
        credit_tier="A",
        utilization_threshold_pct=60,
        credit_ceiling_cents=99996,
        lease_type="NET",
        per_diem_rate_cents=2000,
        liability_bearer="LESSEE",
        term_start_date="2026-09-01",
        term_end_date="2027-09-01",
        fleet_car_cap=10,
    )
    lessee, contract = contract_world["lessee"], contract_world["contract"]

    _, car_b, _, assignment_b = _first_return_settled_to(
        world=world, lessee=lessee, contract=contract, ceiling_cents=99996,
        first_mileage=5000, first_overage_cents=60000,
    )

    accepted = api.create_car_return(
        create_car_return_payload(
            lease_fleet_car_id=car_b["id"],
            car_assignment_id=assignment_b["id"],
            return_date="2026-10-05",
            mileage_since_last=3333,
            condition_grade="A",
        ),
        LEASE,
    )
    returned = validate_success(accepted, expected_status=201)
    assert returned["mileage_overage_cents"] == 39996, (
        "3333 * 12; the projected sum is 60000 + 39996 == 99996"
    )
    assert returned["settlement_status"] == "PENDING", (
        "the ceiling test used the projected figure, not a settled one"
    )

    assignment_after = get_success_data(
        api.get_car_assignment(assignment_b["id"], ADMIN)
    )
    assert assignment_after["status"] == "COMPLETED"

    car_after = get_success_data(api.get_lease_fleet_car(car_b["id"], ADMIN))
    assert car_after["status"] == "UNDER_REPAIR"
    assert car_after["accumulated_mileage"] == 3333


def test_release_pushing_the_live_fleet_past_the_cap_is_rejected(api):
    """PRD §2.9: "Fleet size is capped per contract. A contract carries a
    `fleet_car_cap`, and the number of live cars in the fleet — those in `HELD`,
    `ASSIGNED` or `UNDER_REPAIR` — plus the cars an order would add must stay at
    or below that cap. The cap is checked when a retained order is released and
    again when it completes, and a breach is rejected with
    `ERR_FLEET_CAP_EXCEEDED` (HTTP 402)."
    PRD §2.11: "Nineteenth, fleet cap: the live car count plus the cars an order
    would add must stay at or below the contract's `fleet_car_cap`, and an excess
    is rejected with `ERR_FLEET_CAP_EXCEEDED` (HTTP 402) on release and
    completion."

    The first order's own release passed at 0 + 1 <= 1, so the cap admits a
    single hop; the second release is the one that would take the fleet to two.

    Design: Corner/validations/validation_p19_release_pushing_live_fleet_past_cap_returns_fleet_cap_exceeded
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(
        model_code="CAP-100",
        car_class="BOXCAR",
        build_hours=1,
        regulatory_life_years=15,
        line_count_family="CAP_LINE",
        wheelset_part_number="WS-CAP-1",
        wheelset_unit_cost_cents=1000,
        wheelset_qty_per_car=1,
        lead_time_days=5,
        include_coating=False,
        on_hand_qty=100,
    )
    contract_world = create_lessee_and_contract(
        legal_name="Fleet Cap Rail Co",
        credit_tier="A",
        utilization_threshold_pct=50,
        credit_ceiling_cents=100000000,
        lease_type="NET",
        per_diem_rate_cents=2000,
        liability_bearer="LESSOR",
        term_start_date="2026-09-01",
        term_end_date="2027-09-01",
        fleet_car_cap=1,
    )
    contract = contract_world["contract"]

    first_order = create_order(
        catalogue, quantity=1, planned_shop_days=1, disposition="RETAINED",
        priority_rank=1, order_date="2026-09-01",
        required_delivery_date="2026-09-20",
    )
    reserve_order(first_order["id"])
    released = release_order(first_order["id"], lease_contract_id=contract["id"])
    assert released["status"] == "RELEASED", "0 live + 1 added == cap 1 passes"
    start_production(first_order["id"], "CAP_LINE", window_start="2026-09-02",
                     window_days=1)
    complete_order(first_order["id"], completed_qty=1,
                   completion_date="2026-09-03")

    car_a = get_success_data(
        api.list_lease_fleet_cars(ADMIN, {"production_order_id": first_order["id"]})
    )[0]
    assert car_a["status"] == "HELD", "the live count is now 1"

    second_order = create_order(
        catalogue, quantity=1, planned_shop_days=1, disposition="RETAINED",
        priority_rank=2, order_date="2026-09-01",
        required_delivery_date="2026-09-20",
    )
    reserved = reserve_order(second_order["id"])
    assert reserved["status"] == "COMPONENT_RESERVED"

    rejected = api.release_production_order(
        second_order["id"], PLANNER, {"lease_contract_id": contract["id"]}
    )
    validate_error(rejected, ApiErrorId.ERR_FLEET_CAP_EXCEEDED)
    assert rejected.status_code == 402

    order_after = get_success_data(
        api.get_production_order(second_order["id"], ADMIN)
    )
    assert order_after["status"] == "COMPONENT_RESERVED", "never RELEASED"

    # The car is HELD and has never been placed, so its `lease_contract_id`
    # stamp is still null (PRD 3.6 stamps it at placement); the producing order
    # is what ties it to this scenario.
    fleet = validate_success(
        api.list_lease_fleet_cars(ADMIN, {"production_order_id": first_order["id"]})
    )
    assert len(fleet) == 1, "the fleet still holds exactly the one car"
    assert fleet[0]["id"] == car_a["id"]


def test_release_landing_exactly_on_the_fleet_cap_is_accepted(api):
    """PRD §2.9: "the number of live cars in the fleet — those in `HELD`,
    `ASSIGNED` or `UNDER_REPAIR` — plus the cars an order would add must stay at
    or below that cap."
    PRD §2.11: "Nineteenth, fleet cap: the live car count plus the cars an order
    would add must stay at or below the contract's `fleet_car_cap`, and an excess
    is rejected with `ERR_FLEET_CAP_EXCEEDED` (HTTP 402) on release and
    completion."
    PRD §2.4: "`version` starts at 1 for a newly created resource and is
    incremented by exactly 1 on every mutation that the state machines in §3
    prescribe, with `updated_at` refreshed in the same write."

    One live car plus the one car the second order would add equals the cap of
    two exactly, so the at-or-below comparison admits the release.

    Design: Corner/validations/validation_p19_satisfaction_live_count_plus_added_exactly_at_fleet_cap_passes
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(
        model_code="S19-100",
        car_class="BOXCAR",
        build_hours=1,
        regulatory_life_years=15,
        line_count_family="S19_LINE",
        wheelset_part_number="WS-S19-1",
        wheelset_unit_cost_cents=1000,
        wheelset_qty_per_car=1,
        lead_time_days=5,
        include_coating=False,
        on_hand_qty=100,
    )
    contract_world = create_lessee_and_contract(
        legal_name="Exact Cap Rail Co",
        credit_tier="A",
        utilization_threshold_pct=50,
        credit_ceiling_cents=100000000,
        lease_type="NET",
        per_diem_rate_cents=2000,
        liability_bearer="LESSOR",
        term_start_date="2026-09-01",
        term_end_date="2027-09-01",
        fleet_car_cap=2,
    )
    contract = contract_world["contract"]

    first_order = create_order(
        catalogue, quantity=1, planned_shop_days=1, disposition="RETAINED",
        priority_rank=1, order_date="2026-09-01",
        required_delivery_date="2026-09-20",
    )
    reserve_order(first_order["id"])
    release_order(first_order["id"], lease_contract_id=contract["id"])
    start_production(first_order["id"], "S19_LINE", window_start="2026-09-02",
                     window_days=1)
    complete_order(first_order["id"], completed_qty=1,
                   completion_date="2026-09-03")
    car_a = get_success_data(
        api.list_lease_fleet_cars(ADMIN, {"production_order_id": first_order["id"]})
    )[0]
    assert car_a["status"] == "HELD"

    second_order = create_order(
        catalogue, quantity=1, planned_shop_days=1, disposition="RETAINED",
        priority_rank=2, order_date="2026-09-01",
        required_delivery_date="2026-09-20",
    )
    reserve_order(second_order["id"])

    accepted = validate_success(
        api.release_production_order(
            second_order["id"], PLANNER, {"lease_contract_id": contract["id"]}
        )
    )
    assert accepted["status"] == "RELEASED", (
        "1 live + 1 added == cap 2, so the comparison admits the call"
    )
    assert accepted["version"] == 3, "1 at creation, 2 at reserve, 3 at release"
