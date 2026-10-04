"""Validation precedence, bands 20-22: settlement balance, car availability and lessee correspondence.

Four instances, one test each.  The two sale instances straddle the exact point
where the writeback liability equals the gain over book value; the last two
exercise the free-car precondition across three different endpoints and the
contract-lessee correspondence on a placement.
"""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    complete_order,
    create_assignment,
    create_car_assignment_payload,
    create_car_type_component_requirement_payload,
    create_car_type_payload,
    create_component_payload,
    create_lease_contract_payload,
    create_lease_fleet_sale_payload,
    create_lessee_and_contract,
    create_lessee_payload,
    create_order,
    create_production_order_payload,
    get_success_data,
    release_order,
    reserve_order,
    scrap_lease_fleet_car_payload,
    set_clock,
    start_production,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SUPPLY = TEST_USERS["supply_chain_coordinator_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
LEASE = TEST_USERS["lease_administrator_headers"]
PORTFOLIO = TEST_USERS["portfolio_manager_headers"]


def _catalogue_one_shop_hour(*, model_code, line_family, part_number):
    """A car type built in one shop hour from a single bill-of-material row."""
    car_type = validate_success(
        api_client.create_car_type(
            create_car_type_payload(
                model_code=model_code,
                car_class="BOXCAR",
                build_hours=1,
                regulatory_life_years=15,
                line_count_family=line_family,
            ),
            PLANNER,
        ),
        expected_status=201,
    )
    component = validate_success(
        api_client.create_component(
            create_component_payload(
                part_number=part_number,
                component_class="WHEELSET",
                unit_cost_cents=1000,
                lead_time_days=5,
                on_hand_qty=100,
            ),
            SUPPLY,
        ),
        expected_status=201,
    )
    bom_row = validate_success(
        api_client.create_car_type_component_requirement(
            create_car_type_component_requirement_payload(
                car_type_id=car_type["id"],
                component_id=component["id"],
                qty_per_car=1,
            ),
            PLANNER,
        ),
        expected_status=201,
    )
    return {
        "car_type": car_type,
        "wheelset": component,
        "casting": None,
        "coating": None,
        "components": [component],
        "bom": [bom_row],
    }


def _one_retained_car(*, catalogue, line_segment, completion_date):
    """Reserve, release, schedule and complete a one-car RETAINED order."""
    order = create_order(
        catalogue,
        quantity=1,
        planned_shop_days=1,
        disposition="RETAINED",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-09-20",
    )
    reserve_order(order["id"])
    release_order(order["id"])
    start_production(order["id"], line_segment, window_start="2026-09-02",
                     window_days=1)
    complete_order(order["id"], completed_qty=1, completion_date=completion_date)
    car = get_success_data(
        api_client.list_lease_fleet_cars(
            ADMIN, {"production_order_id": order["id"]}
        )
    )[0]
    return order, car


def test_settlement_refused_when_the_writeback_exceeds_the_gain_over_book(api):
    """PRD §2.9: "A sale settles only if it is internally balanced: when a sale's
    `writeback_liability_cents` exceeds its gain over book value, the settlement
    cannot balance and is rejected with `ERR_SETTLEMENT_UNBALANCED` (HTTP 409)."
    PRD §3.9: "The book value is the car's `acquisition_cost_cents` minus that
    age multiplied by the daily depreciation of 2,500 cents. The sale's
    `gain_loss_cents` is the `sale_price_cents` minus that book value minus the
    sale's `writeback_liability_cents`".
    PRD §3.9: "The disposal proceeds term is the sum of `sale_price_cents` over
    every sale in `SETTLED` status, floored at zero; sales that are `VOIDED` or
    still `PENDING_SETTLEMENT` contribute nothing."

    The car was built on the sale date, so its book value is its full acquisition
    cost and the writeback exceeds the gain by exactly 1000 cents; the refusal
    must leave both the sale and the ledger where they stood.

    Design: Corner/validations/validation_p20_writeback_exceeding_gain_over_book_returns_settlement_unbalanced
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = _catalogue_one_shop_hour(
        model_code="SL-100", line_family="SL_LINE", part_number="WS-SL-1"
    )
    order = validate_success(
        api.create_production_order(
            create_production_order_payload(
                car_type_id=catalogue["car_type"]["id"],
                quantity=1,
                planned_shop_days=1,
                disposition="RETAINED",
                priority_rank=1,
                order_date="2026-09-01",
                required_delivery_date="2026-09-20",
            ),
            PLANNER,
        ),
        expected_status=201,
    )
    # ceil((1 * 1000 + 25000) / 100) * 100 = 26000, plus labor 1 * 45000 = 45000.
    assert order["unit_price_cents"] == 71000

    reserve_order(order["id"])
    release_order(order["id"])
    start_production(order["id"], "SL_LINE", window_start="2026-09-02",
                     window_days=1)
    complete_order(order["id"], completed_qty=1, completion_date="2026-09-03")

    car = get_success_data(
        api.list_lease_fleet_cars(ADMIN, {"production_order_id": order["id"]})
    )[0]
    assert car["acquisition_cost_cents"] == 71000
    assert car["built_date"] == "2026-09-03"

    sale = validate_success(
        api.create_lease_fleet_sale(
            create_lease_fleet_sale_payload(
                lease_fleet_car_id=car["id"],
                buyer_name="Secondary Market Buyer",
                sale_price_cents=100000,
                net_book_value_cents=71000,
                writeback_liability_cents=30000,
                sale_date="2026-09-03",
            ),
            PORTFOLIO,
        ),
        expected_status=201,
    )
    assert sale["status"] == "PENDING_SETTLEMENT"
    assert sale["lease_fleet_car_id"] == car["id"]
    assert sale["gain_loss_cents"] == -1000, "100000 - 71000 - 30000"

    rejected = api.settle_lease_fleet_sale(sale["id"], PORTFOLIO)
    validate_error(rejected, ApiErrorId.ERR_SETTLEMENT_UNBALANCED)
    assert rejected.status_code == 409

    sale_after = get_success_data(api.get_lease_fleet_sale(sale["id"], ADMIN))
    assert sale_after["status"] == "PENDING_SETTLEMENT"
    assert sale_after["gain_loss_cents"] == -1000
    assert sale_after["writeback_liability_cents"] == 30000

    ledger = get_success_data(api.get_portfolio_ledger_reconciliation(ADMIN))
    assert ledger["realized_gain_cents"] == 0, (
        "the refused settlement moved no ledger value"
    )


def test_settlement_accepted_when_the_writeback_equals_the_gain_over_book(api):
    """PRD §2.9: "when a sale's `writeback_liability_cents` exceeds its gain over
    book value, the settlement cannot balance and is rejected with
    `ERR_SETTLEMENT_UNBALANCED` (HTTP 409)."
    PRD §3.9: "The settlement must also be internally balanced: a sale whose
    `writeback_liability_cents` exceeds its gain over book value cannot settle
    and is rejected with `ERR_SETTLEMENT_UNBALANCED` (HTTP 409)."
    PRD §3.9: "On success the sale becomes `SETTLED`, the portfolio ledger's
    `realized_gain_cents` is adjusted by the sale's `gain_loss_cents`".

    The gain over book is exactly the writeback liability, so the comparison
    admits the settlement with zero slack and the realized gain is exactly zero.

    Design: Corner/validations/validation_p20_satisfaction_writeback_exactly_equal_to_gain_over_book_settles
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = _catalogue_one_shop_hour(
        model_code="S20-100", line_family="S20_LINE", part_number="WS-S20-1"
    )
    order, car = _one_retained_car(
        catalogue=catalogue, line_segment="S20_LINE", completion_date="2026-09-03"
    )
    assert car["acquisition_cost_cents"] == 71000, (
        "so book_cents at age_days 0 is 71000"
    )

    sale = validate_success(
        api.create_lease_fleet_sale(
            create_lease_fleet_sale_payload(
                lease_fleet_car_id=car["id"],
                buyer_name="Boundary Buyer",
                sale_price_cents=101000,
                net_book_value_cents=71000,
                writeback_liability_cents=30000,
                sale_date="2026-09-03",
            ),
            PORTFOLIO,
        ),
        expected_status=201,
    )
    assert sale["gain_loss_cents"] == 0, "101000 - 71000 - 30000"

    settled = validate_success(api.settle_lease_fleet_sale(sale["id"], PORTFOLIO))
    assert settled["status"] == "SETTLED"
    assert settled["gain_loss_cents"] == 0

    car_after = get_success_data(api.get_lease_fleet_car(car["id"], ADMIN))
    assert car_after["status"] == "SOLD"

    ledger = get_success_data(api.get_portfolio_ledger_reconciliation(ADMIN))
    assert ledger["realized_gain_cents"] == 0, "the ledger increment is the zero gain"
    assert order["unit_price_cents"] == 71000


def test_assigned_car_is_not_held_for_sale_placement_or_scrap(api):
    """PRD §3.6: "The car must be in `HELD` status — an operation that requires a
    free car and finds one that is not held is rejected with `ERR_CAR_NOT_HELD`
    (HTTP 409)."
    PRD §2.11: "Twenty-first, car availability: the car must be in `HELD` status
    for every operation that requires a free car, and a breach is rejected with
    `ERR_CAR_NOT_HELD` (HTTP 409) on sale creation, placement creation, retrofit
    work-order creation and scrapping."
    PRD §3.9: "The car must be in `HELD` status — otherwise `ERR_CAR_NOT_HELD`
    (HTTP 409) applies".

    All three calls satisfy every other precondition — the second placement's
    window is disjoint from the incumbent's, so the buffering rule passes — and
    all three must report the availability failure.

    Design: Corner/validations/validation_p21_assigned_car_rejected_by_sale_assignment_and_scrap_returns_car_not_held
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = _catalogue_one_shop_hour(
        model_code="NC-100", line_family="NC_LINE", part_number="WS-NC-1"
    )
    contract_world = create_lessee_and_contract(
        legal_name="Not Held Rail Co",
        credit_tier="A",
        utilization_threshold_pct=50,
        credit_ceiling_cents=100000000,
        lease_type="NET",
        per_diem_rate_cents=2000,
        liability_bearer="LESSEE",
        term_start_date="2026-09-01",
        term_end_date="2027-09-01",
        fleet_car_cap=10,
    )
    lessee, contract = contract_world["lessee"], contract_world["contract"]

    _, car = _one_retained_car(
        catalogue=catalogue, line_segment="NC_LINE", completion_date="2026-09-03"
    )
    assignment = create_assignment(
        car, contract, lessee, start_date="2026-09-05",
        end_date="2026-10-05", mileage_allowance=1000,
    )
    placed = get_success_data(api.get_lease_fleet_car(car["id"], ADMIN))
    assert placed["status"] == "ASSIGNED"

    rejected_sale = api.create_lease_fleet_sale(
        create_lease_fleet_sale_payload(
            lease_fleet_car_id=car["id"],
            buyer_name="Not Held Buyer",
            sale_price_cents=100000,
            net_book_value_cents=71000,
            writeback_liability_cents=0,
            sale_date="2026-09-10",
        ),
        PORTFOLIO,
    )
    validate_error(rejected_sale, ApiErrorId.ERR_CAR_NOT_HELD)
    assert rejected_sale.status_code == 409

    rejected_assignment = api.create_car_assignment(
        create_car_assignment_payload(
            lease_fleet_car_id=car["id"],
            lease_contract_id=contract["id"],
            lessee_id=lessee["id"],
            start_date="2026-11-01",
            end_date="2026-12-01",
            mileage_allowance=1000,
        ),
        LEASE,
    )
    validate_error(rejected_assignment, ApiErrorId.ERR_CAR_NOT_HELD)
    assert rejected_assignment.status_code == 409
    assert rejected_assignment.json()["data"]["error_id"] != (
        ApiErrorId.ERR_ASSIGNMENT_OVERLAP.value
    ), "the windows are disjoint, so the buffering rule passes"

    rejected_scrap = api.scrap_lease_fleet_car(
        car["id"], PORTFOLIO,
        scrap_lease_fleet_car_payload(scrap_reason="Portfolio retirement review"),
    )
    validate_error(rejected_scrap, ApiErrorId.ERR_CAR_NOT_HELD)
    assert rejected_scrap.status_code == 409

    car_after = get_success_data(api.get_lease_fleet_car(car["id"], ADMIN))
    assert car_after["status"] == "ASSIGNED", "untouched by all three rejections"

    placements = validate_success(
        api.list_car_assignments(ADMIN, {"lease_fleet_car_id": car["id"]})
    )
    assert len(placements) == 1, "no second placement was written"
    assert placements[0]["id"] == assignment["id"]


def test_placement_naming_another_lessee_is_rejected(api):
    """PRD §2.11: "Twenty-second, lessee correspondence: the lessee named in the
    request must be the lessee of the referenced contract, or of the sold car's
    terminated contract, and a mismatch is rejected with `ERR_LESSEE_MISMATCH`
    (HTTP 409) on placement creation and sale creation."
    PRD §3.6: "The lessee named on the request must be the lessee of the
    referenced contract, or the write is rejected with `ERR_LESSEE_MISMATCH`
    (HTTP 409)."
    PRD §3.6: "On success the car moves to `ASSIGNED`, the car's
    `lease_contract_id` is stamped with the governing contract, and the
    placement's `per_diem_rate_cents` is snapshotted from the contract's rate at
    that moment."

    Both calls carry the identical window and allowance and differ only in the
    lessee they name, so the correspondence check is the sole discriminator.

    Design: Corner/validations/validation_p22_lessee_not_on_referenced_contract_returns_lessee_mismatch
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = _catalogue_one_shop_hour(
        model_code="LM-100", line_family="LM_LINE", part_number="WS-LM-1"
    )
    _, car = _one_retained_car(
        catalogue=catalogue, line_segment="LM_LINE", completion_date="2026-09-03"
    )

    contract_lessee = validate_success(
        api.create_lessee(
            create_lessee_payload(
                legal_name="Contract Holder Rail Co",
                credit_tier="A",
                utilization_threshold_pct=50,
                credit_ceiling_cents=100000000,
            ),
            LEASE,
        ),
        expected_status=201,
    )
    other_lessee = validate_success(
        api.create_lessee(
            create_lessee_payload(
                legal_name="Other Lessee Rail Co",
                credit_tier="B",
                utilization_threshold_pct=50,
                credit_ceiling_cents=100000000,
            ),
            LEASE,
        ),
        expected_status=201,
    )
    contract = validate_success(
        api.create_lease_contract(
            create_lease_contract_payload(
                lessee_id=contract_lessee["id"],
                lease_type="NET",
                per_diem_rate_cents=2000,
                liability_bearer="LESSEE",
                term_start_date="2026-09-01",
                term_end_date="2027-09-01",
                fleet_car_cap=10,
            ),
            LEASE,
        ),
        expected_status=201,
    )
    assert contract["lessee_id"] == contract_lessee["id"]
    validate_success(api.activate_lease_contract(contract["id"], LEASE))

    mismatched = api.create_car_assignment(
        create_car_assignment_payload(
            lease_fleet_car_id=car["id"],
            lease_contract_id=contract["id"],
            lessee_id=other_lessee["id"],
            start_date="2026-09-05",
            end_date="2026-10-05",
            mileage_allowance=1000,
        ),
        LEASE,
    )
    validate_error(mismatched, ApiErrorId.ERR_LESSEE_MISMATCH)
    assert mismatched.status_code == 409

    accepted = validate_success(
        api.create_car_assignment(
            create_car_assignment_payload(
                lease_fleet_car_id=car["id"],
                lease_contract_id=contract["id"],
                lessee_id=contract_lessee["id"],
                start_date="2026-09-05",
                end_date="2026-10-05",
                mileage_allowance=1000,
            ),
            LEASE,
        ),
        expected_status=201,
    )
    assert accepted["status"] == "ACTIVE"
    assert accepted["per_diem_rate_cents"] == 2000, (
        "the rate is snapshotted from the contract"
    )

    car_after = get_success_data(api.get_lease_fleet_car(car["id"], ADMIN))
    assert car_after["status"] == "ASSIGNED"
    assert car_after["lease_contract_id"] == contract["id"]
