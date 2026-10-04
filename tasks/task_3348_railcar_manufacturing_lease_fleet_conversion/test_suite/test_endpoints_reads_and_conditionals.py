"""Cross-reference links, computed reads, conditional actions and listing.

Each test pins the catalogue it builds, so every asserted figure is a function
of the PRD's formulas applied to that catalogue rather than of a default the
shared helper happens to carry.  The two ledger tests deliberately release their
retained order with no contract, which keeps the lessee attribution of that
order out of the asserted figure.
"""

from test_helpers import (
    CLOCK_START_ISO,
    ApiErrorId,
    TEST_USERS,
    advance_clock_to,
    api_client,
    create_assignment,
    create_car_type_payload,
    create_car_type_component_requirement_payload,
    create_component_payload,
    create_component_purchase_order_payload,
    create_endorsement,
    create_lease_fleet_sale_payload,
    create_lessee_and_contract,
    create_order,
    create_retrofit_program_car_type_payload,
    create_retrofit_program_payload,
    create_return,
    get_success_data,
    release_order,
    reserve_order,
    scrap_lease_fleet_car_payload,
    set_clock,
    setup_catalogue,
    setup_retained_order_with_fleet_cars,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SUPPLY = TEST_USERS["supply_chain_coordinator_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
LEASE = TEST_USERS["lease_administrator_headers"]
PORTFOLIO = TEST_USERS["portfolio_manager_headers"]
RETROFIT = TEST_USERS["regulatory_retrofitist_headers"]


def flat_catalogue(**overrides):
    """One BOXCAR type carrying a single wheelset bill-of-material row.

    The row is added here rather than by the shared catalogue helper, so the car
    type consumes exactly one component and a quote asserted against it is a
    function of that one row's numbers alone.
    """
    defaults = dict(
        model_code="CT-FLAT",
        car_class="BOXCAR",
        build_hours=1,
        regulatory_life_years=25,
        line_count_family="LINE-FLAT",
        wheelset_part_number="WS-FLAT",
        wheelset_unit_cost_cents=1000,
        wheelset_lead_time_days=5,
        wheelset_qty_per_car=1,
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


# ─── Cross-reference links ────────────────────────────

def test_bill_of_material_row_is_readable_from_both_sides(api):
    """PRD §2.4: "A `CarTypeComponentRequirement` is the bill-of-material row
    binding one component to one car type. It names the `car_type_id` and the
    `component_id`, and states `qty_per_car`, the units of that component
    consumed per finished car, which is at least 1."
    PRD §2.3: "List endpoints accept their documented filters alongside these two
    parameters; filters that name a status, a car type, a component, a contract,
    a car, a production order, a purchase order, a settlement status, a shop
    line, a program or a superseding order narrow the result set before
    pagination is applied."

    The two rows of one car type are reachable from the car-type side, and each
    row is reachable from its component's side, with the by-id read confirming
    the pair and the per-car quantity.

    Design: Corner/endpoints/endpoint_link_car_type_component_requirement_readable_from_both_sides
    """
    catalogue = setup_catalogue(
        model_code="CT-L1",
        car_class="BOXCAR",
        build_hours=1,
        regulatory_life_years=25,
        line_count_family="LINE-L1",
        wheelset_part_number="WS-L1",
        wheelset_unit_cost_cents=1000,
        wheelset_lead_time_days=5,
        wheelset_qty_per_car=4,
        casting_part_number="CS-L1",
        casting_unit_cost_cents=2000,
        casting_lead_time_days=6,
        casting_qty_per_car=2,
        include_coating=False,
        on_hand_qty=100,
    )
    wheelset_row, casting_row = catalogue["bom"]

    by_car_type, _ = validate_paginated(
        api_client.list_car_type_component_requirements(
            ADMIN, {"car_type_id": catalogue["car_type"]["id"]}
        )
    )
    assert len(by_car_type) == 2
    assert {row["id"] for row in by_car_type} == {wheelset_row["id"], casting_row["id"]}

    by_component, _ = validate_paginated(
        api_client.list_car_type_component_requirements(
            ADMIN, {"component_id": catalogue["wheelset"]["id"]}
        )
    )
    assert len(by_component) == 1
    assert by_component[0]["id"] == wheelset_row["id"], (
        "the component side returns the identical junction row"
    )

    row = get_success_data(
        api_client.get_car_type_component_requirement(by_component[0]["id"], ADMIN)
    )
    assert row["car_type_id"] == catalogue["car_type"]["id"]
    assert row["component_id"] == catalogue["wheelset"]["id"]
    assert row["qty_per_car"] == wheelset_row["qty_per_car"] == 4

    sibling, _ = validate_paginated(
        api_client.list_car_type_component_requirements(
            ADMIN, {"component_id": catalogue["casting"]["id"]}
        )
    )
    assert len(sibling) == 1
    assert sibling[0]["id"] == casting_row["id"]


def test_retrofit_program_car_type_row_is_readable_from_both_sides(api):
    """PRD §3.8: "Coverage is then declared by adding `RetrofitProgramCarType`
    rows, each naming the `retrofit_program_id` and the `car_type_id` it covers;
    a program covers nothing until at least one such row exists."
    PRD §2.3: "List endpoints accept their documented filters alongside these two
    parameters; filters that name a status, a car type, a component, a contract,
    a car, a production order, a purchase order, a settlement status, a shop
    line, a program or a superseding order narrow the result set before
    pagination is applied."

    With three coverage rows over two programs and two car types, the
    program-side filter lists both types the program covers and the car-type-side
    filter lists both programs covering that type.

    Design: Corner/endpoints/endpoint_link_retrofit_program_car_type_readable_from_both_sides
    """
    set_clock(CLOCK_START_ISO)
    first_type = get_success_data(
        api_client.create_car_type(
            create_car_type_payload(
                model_code="CT-L2",
                car_class="BOXCAR",
                build_hours=1,
                regulatory_life_years=25,
                line_count_family="LINE-L2",
            ),
            PLANNER,
        )
    )
    second_type = get_success_data(
        api_client.create_car_type(
            create_car_type_payload(
                model_code="CT-L3",
                car_class="BOXCAR",
                build_hours=1,
                regulatory_life_years=25,
                line_count_family="LINE-L3",
            ),
            PLANNER,
        )
    )
    first_program = get_success_data(
        api_client.create_retrofit_program(
            create_retrofit_program_payload(
                mandate_code="MAND-L2",
                description="First mandate",
                compliance_deadline_date="2026-12-31",
                required_shop_days_per_car=3,
            ),
            RETROFIT,
        )
    )
    second_program = get_success_data(
        api_client.create_retrofit_program(
            create_retrofit_program_payload(
                mandate_code="MAND-L3",
                description="Second mandate",
                compliance_deadline_date="2026-12-31",
                required_shop_days_per_car=3,
            ),
            RETROFIT,
        )
    )

    def cover(program, car_type):
        return get_success_data(
            api_client.create_retrofit_program_car_type(
                create_retrofit_program_car_type_payload(
                    retrofit_program_id=program["id"], car_type_id=car_type["id"]
                ),
                RETROFIT,
            )
        )

    link_a = cover(first_program, first_type)
    link_b = cover(first_program, second_type)
    link_c = cover(second_program, first_type)

    program_side, _ = validate_paginated(
        api_client.list_retrofit_program_car_types(
            ADMIN, {"retrofit_program_id": first_program["id"]}
        )
    )
    assert len(program_side) == 2
    assert {row["id"] for row in program_side} == {link_a["id"], link_b["id"]}

    type_side, _ = validate_paginated(
        api_client.list_retrofit_program_car_types(
            ADMIN, {"car_type_id": first_type["id"]}
        )
    )
    assert len(type_side) == 2
    assert {row["id"] for row in type_side} == {link_a["id"], link_c["id"]}, (
        "both covering programs list the same junction row"
    )

    row = get_success_data(
        api_client.get_retrofit_program_car_type(link_a["id"], ADMIN)
    )
    assert row["retrofit_program_id"] == first_program["id"]
    assert row["car_type_id"] == first_type["id"]

    reverse, _ = validate_paginated(
        api_client.list_retrofit_program_car_types(
            ADMIN, {"car_type_id": second_type["id"]}
        )
    )
    assert len(reverse) == 1
    assert reverse[0]["id"] == link_b["id"]


def test_substitution_endorsement_is_readable_from_every_side(api):
    """PRD §3.3: "The creating write names the `production_order_id` awaiting the
    endorsement, the `original_component_id` the order is short of, the
    `substitute_component_id` being offered, the `substitute_qty_per_car` that
    will override the junction row's quantity while the endorsement is
    `APPROVED`, and the `decides_material` flag, which is true when the
    substitution can change the material composition of a car because the
    substitute's component class differs from the original's."

    The one junction row is reachable from the order side, the original-component
    side and the substitute-component side, and the by-id read confirms all three
    foreign keys.

    Design: Corner/endpoints/endpoint_link_substitution_endorsement_readable_from_both_sides
    """
    catalogue = flat_catalogue(
        model_code="CT-L4",
        line_count_family="LINE-L4",
        wheelset_part_number="WS-L4",
        wheelset_qty_per_car=2,
    )
    substitute = get_success_data(
        api_client.create_component(
            create_component_payload(
                part_number="WS-L5",
                component_class="WHEELSET",
                unit_cost_cents=1100,
                lead_time_days=4,
                on_hand_qty=100,
            ),
            SUPPLY,
        )
    )
    order = create_order(
        catalogue,
        quantity=1,
        planned_shop_days=1,
        disposition="SOLD",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-12-01",
    )
    endorsement = create_endorsement(
        order,
        catalogue["wheelset"],
        substitute,
        substitute_qty_per_car=2,
        decides_material=False,
    )
    assert endorsement["status"] == "PENDING"

    from_order, _ = validate_paginated(
        api_client.list_substitution_endorsements(
            ADMIN, {"production_order_id": order["id"]}
        )
    )
    assert len(from_order) == 1
    assert from_order[0]["id"] == endorsement["id"]

    from_original, _ = validate_paginated(
        api_client.list_substitution_endorsements(
            ADMIN, {"original_component_id": catalogue["wheelset"]["id"]}
        )
    )
    assert len(from_original) == 1
    assert from_original[0]["id"] == endorsement["id"]

    from_substitute, _ = validate_paginated(
        api_client.list_substitution_endorsements(
            ADMIN, {"substitute_component_id": substitute["id"]}
        )
    )
    assert len(from_substitute) == 1
    assert from_substitute[0]["id"] == endorsement["id"]

    row = get_success_data(
        api_client.get_substitution_endorsement(endorsement["id"], ADMIN)
    )
    assert row["production_order_id"] == order["id"]
    assert row["original_component_id"] == catalogue["wheelset"]["id"]
    assert row["substitute_component_id"] == substitute["id"]
    assert row["status"] == "PENDING"


# ─── Computed reads ───────────────────────────────────

def test_component_read_surfaces_reserved_qty_after_release(api):
    """PRD §3.2: "The component's `reserved_qty` is the reservation term plus the
    retrofit term, and its `shortfall_qty` is the amount by which that reserved
    figure exceeds `on_hand_qty`, or zero when it does not."
    PRD §3.2: "orders in `DRAFT`, `COMPONENT_RESERVED`, `COMPLETED` or
    `CANCELLED` contribute nothing"

    The derived figure is 0 while the order is COMPONENT_RESERVED and 10 ==
    qty_per_car 2 * quantity 5 the moment the same order is RELEASED, with
    `on_hand_qty` untouched by the release.

    Design: Corner/endpoints/endpoint_computed_read_component_reserved_qty_after_release
    """
    catalogue = flat_catalogue(
        model_code="CT-E",
        line_count_family="LINE-E",
        wheelset_part_number="WS-E",
        wheelset_qty_per_car=2,
    )
    order = create_order(
        catalogue,
        quantity=5,
        planned_shop_days=5,
        disposition="SOLD",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-12-01",
    )
    reserved = reserve_order(order["id"])
    assert reserved["status"] == "COMPONENT_RESERVED"

    before = get_success_data(api_client.get_component(catalogue["wheelset"]["id"], ADMIN))
    assert before["on_hand_qty"] == 90, "100 less qty_per_car 2 * quantity 5"
    assert before["reserved_qty"] == 0, (
        "the reservation term counts only RELEASED production orders"
    )

    released = release_order(order["id"])
    assert released["status"] == "RELEASED"

    after = get_success_data(api_client.get_component(catalogue["wheelset"]["id"], ADMIN))
    assert after["reserved_qty"] == 10, "qty_per_car 2 * quantity 5"
    assert after["on_hand_qty"] == 90, (
        "the release re-derives reserved_qty from order state rather than patching "
        "the committed stock"
    )
    assert after["shortfall_qty"] == 0, "10 reserved against 90 on hand"


def test_lessee_balance_read_reports_only_settled_charges(api):
    """PRD §3.9: "A lessee's `outstanding_balance_cents` is the sum of the
    `mileage_overage_cents` of its returns whose `settlement_status` is
    `SETTLED`"
    PRD §3.9: "The outstanding-balance read exposes the components as well: it
    reports `outstanding_balance_cents`, `settled_charges_cents` and
    `credits_applied_cents`, and a lessee may read it only for its own `id`."

    One settled return of 18000 and one pending return of 42000 leave the read at
    exactly 18000 with no credit applied, because the pending return is outside
    the input set.

    Design: Corner/endpoints/endpoint_computed_read_lessee_outstanding_balance_breakdown
    """
    catalogue = flat_catalogue(
        model_code="CT-C2b",
        line_count_family="LINE-C2B",
        wheelset_part_number="WS-C2b",
    )
    world = setup_retained_order_with_fleet_cars(
        car_count=1,
        catalogue=catalogue,
        build_contract=False,
        changeover_start="2026-09-11",
        completion_date="2026-09-12",
    )
    pair = create_lessee_and_contract(
        legal_name="Breakdown Rail Co",
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
    car = world["car"]

    first_assignment = create_assignment(
        car,
        pair["contract"],
        pair["lessee"],
        start_date="2026-09-12",
        end_date="2026-10-12",
        mileage_allowance=1000,
    )
    first_return = create_return(
        car,
        first_assignment,
        return_date="2026-10-12",
        mileage_since_last=2500,
        condition_grade="A",
    )
    assert first_return["mileage_overage_cents"] == 18000
    settled = validate_success(api_client.settle_car_return(first_return["id"], PORTFOLIO))
    assert settled["settlement_status"] == "SETTLED"
    back_in_fleet = validate_success(
        api_client.settle_fleet_car_returns(car["id"], PLANNER)
    )
    assert back_in_fleet["status"] == "HELD"

    second_assignment = create_assignment(
        car,
        pair["contract"],
        pair["lessee"],
        start_date="2026-10-14",
        end_date="2026-11-13",
        mileage_allowance=1000,
    )
    second_return = create_return(
        car,
        second_assignment,
        return_date="2026-11-13",
        mileage_since_last=4500,
        condition_grade="A",
    )
    assert second_return["mileage_overage_cents"] == 42000, "max(0, 4500 - 1000) * 12"
    assert second_return["settlement_status"] == "PENDING"

    balance = get_success_data(
        api_client.get_lessee_outstanding_balance(pair["lessee"]["id"], ADMIN)
    )
    assert balance["outstanding_balance_cents"] == 18000, (
        "the PENDING return's 42000 is excluded from the settled-return sum"
    )
    assert balance["settled_charges_cents"] == 18000
    assert balance["credits_applied_cents"] == 0, (
        "no sale writeback and no retained-order credit has landed on this lessee"
    )


def test_portfolio_reconciliation_reports_both_bases_and_their_drift(api):
    """PRD §3.9: "The committed basis is the ledger's `committed_capital_cents`
    minus those disposal proceeds — the historic cost basis, which charges the
    full proceeds against committed capital and applies no depreciation."
    PRD §3.9: "The newest basis is the live fleet's depreciated book value: for
    every car in `HELD`, `ASSIGNED` or `UNDER_REPAIR`, the car's
    `acquisition_cost_cents` minus the number of days from its `built_date` to
    the current clock date multiplied by the daily depreciation of 2,500 cents,
    floored at zero per car so a fully depreciated car contributes nothing,
    summed across the fleet and rounded up to a whole cent."

    Two retained cars quoted at 71000 each, ten days old at the 2026-09-30 clock,
    read as 142000 on the committed basis and 92000 on the newest basis, so the
    drift is exactly 50000.

    Design: Corner/endpoints/endpoint_computed_read_portfolio_ledger_reconciliation_two_bases
    """
    catalogue = flat_catalogue(
        model_code="CT-B2",
        line_count_family="LINE-B2",
        wheelset_part_number="WS-B2",
    )
    world = setup_retained_order_with_fleet_cars(
        car_count=2,
        catalogue=catalogue,
        build_contract=False,
        changeover_start="2026-09-18",
        completion_date="2026-09-20",
    )
    cars = get_success_data(
        api_client.list_lease_fleet_cars(
            ADMIN, {"production_order_id": world["order"]["id"]}
        )
    )
    assert len(cars) == 2
    assert cars[0]["acquisition_cost_cents"] == 71000, (
        "ceil((1 * 1000 + 25000) / 100) * 100 + 1 * 45000"
    )
    assert cars[0]["built_date"] == "2026-09-20"

    advance_clock_to("2026-09-30T00:00:00Z")
    reconciliation = validate_success(
        api_client.get_portfolio_ledger_reconciliation(ADMIN)
    )
    assert reconciliation["committed_capital_cents"] == 142000, "2 * 71000"
    assert reconciliation["realized_gain_cents"] == 0
    assert reconciliation["oldest_basis_cents"] == 142000, (
        "the committed basis with no SETTLED sale to net off"
    )
    assert reconciliation["newest_basis_cents"] == 92000, (
        "ceil(2 * max(0, 71000 - 10 * 2500)) with ten days from built_date to clock"
    )
    assert reconciliation["drift_cents"] == 50000, "142000 - 92000"

    ledger = validate_success(api_client.get_portfolio_ledger(ADMIN))
    assert ledger["committed_capital_cents"] == 142000
    assert ledger["fleet_nbv_cents"] == 92000


# ─── Conditional actions ──────────────────────────────

def test_scrap_is_allowed_from_held_and_refused_from_assigned(api):
    """PRD §2.11: "Twenty-first, car availability: the car must be in `HELD`
    status for every operation that requires a free car, and a breach is rejected
    with `ERR_CAR_NOT_HELD` (HTTP 409) on sale creation, placement creation,
    retrofit work-order creation and scrapping."
    PRD §3.9: "A `PortfolioManager` scraps a car from `HELD` status, supplying an
    optional `scrap_reason`."

    The placed car is refused and stays ASSIGNED; its HELD sibling on the same
    order lands SCRAPPED and is the only row the status filter returns.

    Design: Corner/endpoints/endpoint_conditional_scrap_allowed_from_held_rejected_from_assigned
    """
    catalogue = flat_catalogue(
        model_code="CT-F",
        line_count_family="LINE-F",
        wheelset_part_number="WS-F",
    )
    world = setup_retained_order_with_fleet_cars(
        car_count=2,
        catalogue=catalogue,
        build_contract=False,
        changeover_start="2026-09-10",
        completion_date="2026-09-12",
    )
    pair = create_lessee_and_contract(
        legal_name="Conditional Scrap Rail Co",
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
    placed, free = world["cars"][0], world["cars"][1]
    create_assignment(
        placed,
        pair["contract"],
        pair["lessee"],
        start_date="2026-09-12",
        end_date="2026-10-12",
        mileage_allowance=1000,
    )
    assert get_success_data(api_client.get_lease_fleet_car(placed["id"], ADMIN))[
        "status"
    ] == "ASSIGNED"
    assert get_success_data(api_client.get_lease_fleet_car(free["id"], ADMIN))[
        "regulatory_life_end_date"
    ] == "2051-09-12", "both cars are inside their life, so only availability bites"

    refused = api_client.scrap_lease_fleet_car(
        placed["id"], PORTFOLIO, scrap_lease_fleet_car_payload("Attempt while placed")
    )
    validate_error(refused, ApiErrorId.ERR_CAR_NOT_HELD)
    untouched = get_success_data(api_client.get_lease_fleet_car(placed["id"], ADMIN))
    assert untouched["status"] == "ASSIGNED", "the rejection left the car untouched"

    scrapped = validate_success(
        api_client.scrap_lease_fleet_car(
            free["id"], PORTFOLIO, scrap_lease_fleet_car_payload("End of economic life")
        )
    )
    assert scrapped["status"] == "SCRAPPED"
    assert scrapped["version"] == 2, "creation version 1 plus the transition's own"

    rows, _ = validate_paginated(
        api_client.list_lease_fleet_cars(ADMIN, {"status": "SCRAPPED"})
    )
    assert len(rows) == 1
    assert rows[0]["id"] == free["id"]


def test_sale_requires_regulatory_life_remaining(api):
    """PRD §3.9: "The car must be in `HELD` status — otherwise `ERR_CAR_NOT_HELD`
    (HTTP 409) applies — and the car's `regulatory_life_end_date` must be
    strictly later than the sale date, or the sale is rejected with
    `ERR_REGULATORY_LIFE_EXCEEDED` (HTTP 422)."
    PRD §2.8: "An attempt to sell, place or schedule retrofit work on a car that
    has passed its life end is rejected with `ERR_REGULATORY_LIFE_EXCEEDED`
    (HTTP 422)"

    Two cars built 2026-09-20 carry a life end of 2051-09-20; at the same
    2051-09-19 clock the sale dated 2051-09-19 is accepted while the one dated
    2051-09-21 is refused and leaves its car HELD.

    Design: Corner/endpoints/endpoint_conditional_sale_requires_life_remaining
    """
    catalogue = flat_catalogue(
        model_code="CT-G",
        line_count_family="LINE-G",
        wheelset_part_number="WS-G",
    )
    world = setup_retained_order_with_fleet_cars(
        car_count=2,
        catalogue=catalogue,
        build_contract=False,
        changeover_start="2026-09-18",
        completion_date="2026-09-20",
    )
    inside, outside = world["cars"][0], world["cars"][1]
    assert get_success_data(api_client.get_lease_fleet_car(inside["id"], ADMIN))[
        "regulatory_life_end_date"
    ] == "2051-09-20", "built_date 2026-09-20 plus regulatory_life_years 25"

    advance_clock_to("2051-09-19T00:00:00Z")

    accepted = validate_success(
        api_client.create_lease_fleet_sale(
            create_lease_fleet_sale_payload(
                lease_fleet_car_id=inside["id"],
                buyer_name="Life Inside Buyer",
                sale_price_cents=80000,
                writeback_liability_cents=0,
                sale_date="2051-09-19",
            ),
            PORTFOLIO,
        ),
        expected_status=201,
    )
    assert accepted["status"] == "PENDING_SETTLEMENT"

    refused = api_client.create_lease_fleet_sale(
        create_lease_fleet_sale_payload(
            lease_fleet_car_id=outside["id"],
            buyer_name="Life Passed Buyer",
            sale_price_cents=80000,
            writeback_liability_cents=0,
            sale_date="2051-09-21",
        ),
        PORTFOLIO,
    )
    validate_error(refused, ApiErrorId.ERR_REGULATORY_LIFE_EXCEEDED)
    untouched = get_success_data(api_client.get_lease_fleet_car(outside["id"], ADMIN))
    assert untouched["status"] == "HELD", "no partial mutation on the rejected sale"


# ─── Listing and pagination ───────────────────────────

def test_list_pagination_default_limit_and_max_bound(api):
    """PRD §2.3: "`limit` defaults to 10, and its smallest permitted value is 1
    and its largest is 100; a value outside that band is a request-shape
    failure."
    PRD §2.3: "`has_more` is true exactly when `offset` plus the number of records
    returned is less than `total_count`."

    Twelve programs page as ten rows with total_count 12 and has_more true; the
    declared maximum limit returns all twelve with has_more false; a limit above
    the band is a request-shape failure.

    Design: Corner/endpoints/endpoint_list_pagination_default_limit_and_max_bound
    """
    set_clock(CLOCK_START_ISO)
    for index in range(1, 13):
        get_success_data(
            api_client.create_retrofit_program(
                create_retrofit_program_payload(
                    mandate_code=f"MAND-P{index:02d}",
                    description=f"Pagination row {index}",
                    compliance_deadline_date="2026-12-31",
                    required_shop_days_per_car=3,
                ),
                RETROFIT,
            )
        )

    response = api_client.list_retrofit_programs(ADMIN)
    rows, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array"
    assert isinstance(meta["api_request_id"], str) and meta["api_request_id"]
    assert len(rows) == 10, "the declared default limit of 10"
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 12
    assert meta["has_more"] is True, "offset 0 plus 10 returned rows is less than 12"

    full_response = api_client.list_retrofit_programs(ADMIN, {"limit": 100, "offset": 0})
    full_rows, full_meta = validate_paginated(full_response)
    assert len(full_rows) == 12, "the declared maximum limit is accepted"
    assert full_meta["total_count"] == 12
    assert full_meta["has_more"] is False, "offset 0 plus 100 returned rows is not less"
    assert {row["id"] for row in rows} <= {row["id"] for row in full_rows}

    over_max = api_client.list_retrofit_programs(ADMIN, {"limit": 101})
    validate_error(over_max, ApiErrorId.ERR_INVALID_REQUEST)


def test_list_offset_pagination_and_array_envelope(api):
    """PRD §2.3: "`offset` defaults to 0 and counts the number of matching
    records to skip before the first returned record."
    PRD §2.3: "The `meta` object of a list response carries all four pagination
    fields: `limit`, `offset`, `total_count` and `has_more`."
    PRD §2.3: "Results are ordered by `created_at` ascending."

    Twelve purchase orders page as ten rows at the default offset and the
    remaining two at offset 10 with has_more false, while the status filter still
    reports the whole twelve-row total.

    Design: Corner/endpoints/endpoint_list_offset_pagination_and_array_envelope
    """
    set_clock(CLOCK_START_ISO)
    component = get_success_data(
        api_client.create_component(
            create_component_payload(
                part_number="WS-Q1",
                component_class="WHEELSET",
                unit_cost_cents=1000,
                lead_time_days=20,
            ),
            SUPPLY,
        )
    )
    for _ in range(12):
        get_success_data(
            api_client.create_component_purchase_order(
                create_component_purchase_order_payload(
                    component_id=component["id"],
                    qty_ordered=10,
                    unit_cost_cents=1000,
                    order_date="2026-09-01",
                    expected_receipt_date="2026-09-21",
                ),
                SUPPLY,
            )
        )

    first_response = api_client.list_component_purchase_orders(ADMIN)
    first_page, first_meta = validate_paginated(first_response)
    assert first_response.json()["response_type"] == "array"
    assert len(first_page) == 10
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 12
    assert first_meta["has_more"] is True

    second_page, second_meta = validate_paginated(
        api_client.list_component_purchase_orders(ADMIN, {"offset": 10})
    )
    assert len(second_page) == 2, "the remaining rows after skipping ten"
    assert second_meta["offset"] == 10
    assert second_meta["total_count"] == 12
    assert second_meta["has_more"] is False
    assert {row["id"] for row in second_page}.isdisjoint(
        {row["id"] for row in first_page}
    ), "offset advances the window without repeating rows"

    filtered, filtered_meta = validate_paginated(
        api_client.list_component_purchase_orders(ADMIN, {"status": "PLACED"})
    )
    assert filtered_meta["total_count"] == 12, (
        "the filter narrows the result set before pagination is applied"
    )
    assert len(filtered) == 10
    assert filtered[0]["id"] == first_page[0]["id"]
    assert all(row["status"] == "PLACED" for row in filtered), (
        "the creation state of every purchase order is PLACED"
    )
