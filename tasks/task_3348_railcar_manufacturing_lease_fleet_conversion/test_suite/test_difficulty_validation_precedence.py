"""Difficulty queue: validation-pair conflicts and the fixed precedence order.

Two instances, one test each.  Both build a request that genuinely violates two
checks at once and assert that the earliest failing check in the PRD's fixed
sequence is the one reported.

* ``state`` vs ``business_fiscal`` on a second return against a closed
  placement.
* ``business_safety`` vs ``business_referential`` on a second placement of a
  car that is both past its regulatory life and no longer free.
"""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock_to,
    api_client,
    complete_order,
    create_assignment,
    create_lessee_and_contract,
    create_order,
    create_return,
    get_success_data,
    release_order,
    reserve_order,
    set_clock,
    settle_return,
    setup_catalogue,
    start_production,
    validate_error,
)

LEASE = TEST_USERS["lease_administrator_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def _priority_catalogue(*, model_code: str, car_class: str, line_family: str,
                        part_number: str, regulatory_life_years: int):
    """A one-row catalogue whose single gated row keeps the order feasible."""
    return setup_catalogue(
        model_code=model_code,
        car_class=car_class,
        build_hours=1,
        regulatory_life_years=regulatory_life_years,
        line_count_family=line_family,
        wheelset_part_number=part_number,
        wheelset_unit_cost_cents=200000,
        wheelset_qty_per_car=1,
        wheelset_lead_time_days=10,
        include_coating=False,
        on_hand_qty=10,
    )


def _completed_retained_car(catalogue, *, order_date: str,
                            required_delivery_date: str, changeover_start: str,
                            changeover_end: str):
    """Reserve, release, schedule and complete a one-car RETAINED order."""
    order = create_order(
        catalogue,
        quantity=1,
        planned_shop_days=1,
        disposition="RETAINED",
        priority_rank=1,
        order_date=order_date,
        required_delivery_date=required_delivery_date,
    )
    reserve_order(order["id"])
    release_order(order["id"])
    start_production(
        order["id"],
        catalogue["car_type"]["line_count_family"],
        window_start=changeover_start,
        window_days=1,
    )
    complete_order(order["id"], completed_qty=1, completion_date=changeover_end)
    return get_success_data(
        api_client.list_lease_fleet_cars(
            ADMIN, {"production_order_id": order["id"]}
        )
    )[0]


# ─── priority_pair_validation_conflict ────────────────

def test_closed_placement_return_reports_state_legality_before_credit_ceiling(api):
    """PRD §2.11: "A request can fail more than one check at once, and the error
    a client receives must be the one that belongs to the earliest failing check
    in the order below — not an arbitrary member of the failing set. The checks
    are evaluated in this fixed sequence, and the first failure short-circuits
    the rest of the evaluation."
    PRD §2.11: "Fifth, state legality: the target resource must be in a state
    from which the requested action is legal per §3, and an illegal source state
    is rejected with `ERR_INVALID_STATE` (HTTP 409); this check applies to every
    action endpoint."
    PRD §2.11: "Eighteenth, credit exposure: the lessee's
    `outstanding_balance_cents` plus the projected mileage charge must stay at
    or below the lessee's `credit_ceiling_cents`, with equality permitted, and
    an excess is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402) on return
    recording and placement creation."
    PRD §3.7: "The placement being closed must be in `ACTIVE` or `SUSPENDED`
    status, the `return_date` must be strictly later than the placement's
    `start_date`, and no other placement of the same car may hold a date
    interval that would overlap the interval being closed — a conflict is
    rejected with `ERR_ASSIGNMENT_OVERLAP` (HTTP 409)."

    The lessee's balance sits exactly on its ceiling, so the credit check is
    live; the placement is already COMPLETED, so the state check is live too.
    Priority 5 must win over priority 18.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_return_conflict
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = _priority_catalogue(
        model_code="PRI-RET-100",
        car_class="GONDOLA",
        line_family="PRI_RET_LINE",
        part_number="PRI-RET-WS",
        regulatory_life_years=25,
    )
    car = _completed_retained_car(
        catalogue,
        order_date="2026-09-01",
        required_delivery_date="2026-09-20",
        changeover_start="2026-09-02",
        changeover_end="2026-09-03",
    )
    assert car["built_date"] == "2026-09-03"

    world = create_lessee_and_contract(
        legal_name="Priority Pair Rail Co",
        credit_tier="B",
        utilization_threshold_pct=50,
        credit_ceiling_cents=60000,
        lease_type="NET",
        per_diem_rate_cents=1000,
        liability_bearer="LESSEE",
        term_start_date="2026-09-01",
        term_end_date="2027-09-01",
        fleet_car_cap=10,
    )
    lessee, contract = world["lessee"], world["contract"]

    advance_clock_to("2026-09-05T00:00:00Z")
    assignment = create_assignment(
        car, contract, lessee, start_date="2026-09-05",
        end_date="2026-10-05", mileage_allowance=0,
    )

    # 30 days in placement grants exactly one block of 0 included miles, so all
    # 5000 miles run are overage: 5000 * 12 = 60000 cents, exactly the ceiling.
    first_return = create_return(
        car, assignment, return_date="2026-10-05",
        mileage_since_last=5000, condition_grade="A",
    )
    assert first_return["mileage_overage_cents"] == 60000
    settle_return(first_return["id"])

    balance = get_success_data(
        api_client.get_lessee_outstanding_balance(lessee["id"], LEASE)
    )
    assert balance["outstanding_balance_cents"] == 60000

    closed = get_success_data(
        api_client.get_car_assignment(assignment["id"], ADMIN)
    )
    assert closed["status"] == "COMPLETED"

    # Both checks are live on this request: the placement is COMPLETED
    # (priority 5) and 60000 plus any positive projected charge would breach
    # the 60000 ceiling (priority 18).  The lower priority number wins.
    second_return = api_client.create_car_return(
        {
            "lease_fleet_car_id": car["id"],
            "car_assignment_id": assignment["id"],
            "return_date": "2026-10-06",
            "mileage_since_last": 100,
            "condition_grade": "A",
        },
        LEASE,
    )
    validate_error(second_return, ApiErrorId.ERR_INVALID_STATE)
    assert second_return.status_code == 409
    body = second_return.json()["data"]
    assert body["error_id"] != ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value, (
        "the business_fiscal check must not pre-empt the state check"
    )

    unchanged_balance = get_success_data(
        api_client.get_lessee_outstanding_balance(lessee["id"], LEASE)
    )
    assert unchanged_balance["outstanding_balance_cents"] == 60000, (
        "the rejected return must not accrue any charge"
    )
    unchanged_assignment = get_success_data(
        api_client.get_car_assignment(assignment["id"], ADMIN)
    )
    assert unchanged_assignment["status"] == "COMPLETED"


def test_past_life_placement_reports_regulatory_life_before_car_availability(api):
    """PRD §2.11: "Eighth, regulatory life: the car's `regulatory_life_end_date`
    must be on or after the operation date, because a car at or past the end of
    its regulatory life may only be scrapped; a breach is rejected with
    `ERR_REGULATORY_LIFE_EXCEEDED` (HTTP 422), and it guards sale creation,
    placement creation and retrofit work-order creation."
    PRD §2.11: "Twenty-first, car availability: the car must be in `HELD` status
    for every operation that requires a free car, and a breach is rejected with
    `ERR_CAR_NOT_HELD` (HTTP 409) on sale creation, placement creation, retrofit
    work-order creation and scrapping."
    PRD §2.8: "A car whose `regulatory_life_end_date` is on or after the
    operation date remains eligible for the normal operations that need it —
    sale, placement, or retrofit scheduling — but a car at or past the end of
    its regulatory life may only be scrapped."
    PRD §3.6: "A car past the end of its regulatory life may not be placed
    either, and such an attempt is rejected with `ERR_REGULATORY_LIFE_EXCEEDED`
    (HTTP 422)."

    The car is still ASSIGNED, so the availability check is live; the clock has
    also moved one day past its derived life end, so the regulatory check is
    live.  Priority 8 must win over priority 21.

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_placement_conflict
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = _priority_catalogue(
        model_code="PRI-LIFE-100",
        car_class="TANK",
        line_family="PRI_LIFE_LINE",
        part_number="PRI-LIFE-WS",
        regulatory_life_years=10,
    )
    car = _completed_retained_car(
        catalogue,
        order_date="2026-09-01",
        required_delivery_date="2026-09-20",
        changeover_start="2026-09-02",
        changeover_end="2026-09-03",
    )
    assert car["built_date"] == "2026-09-03"
    assert car["regulatory_life_end_date"] == "2036-09-03"

    world = create_lessee_and_contract(
        legal_name="Regulatory Life Rail Co",
        credit_tier="A",
        utilization_threshold_pct=60,
        credit_ceiling_cents=50000000,
        lease_type="FULL_SERVICE",
        per_diem_rate_cents=2000,
        liability_bearer="LESSOR",
        term_start_date="2026-09-01",
        term_end_date="2037-09-01",
        fleet_car_cap=10,
    )
    lessee, contract = world["lessee"], world["contract"]

    advance_clock_to("2026-09-05T00:00:00Z")
    incumbent = create_assignment(
        car, contract, lessee, start_date="2026-09-05",
        end_date="2026-10-05", mileage_allowance=1000,
    )
    assert incumbent["status"] == "ACTIVE"

    # One day past the car's regulatory life end: it may only be scrapped.
    advance_clock_to("2036-09-04T00:00:00Z")

    second_placement = api_client.create_car_assignment(
        {
            "lease_fleet_car_id": car["id"],
            "lease_contract_id": contract["id"],
            "lessee_id": lessee["id"],
            "start_date": "2036-09-10",
            "end_date": "2036-10-10",
            "mileage_allowance": 1000,
        },
        LEASE,
    )
    validate_error(second_placement, ApiErrorId.ERR_REGULATORY_LIFE_EXCEEDED)
    assert second_placement.status_code == 422
    body = second_placement.json()["data"]
    assert body["error_id"] != ApiErrorId.ERR_CAR_NOT_HELD.value, (
        "the car-availability check must not pre-empt the regulatory-life check"
    )

    untouched = get_success_data(api_client.get_lease_fleet_car(car["id"], ADMIN))
    assert untouched["status"] == "ASSIGNED", (
        "the car-availability violation was genuinely live at call time"
    )
    assert untouched["regulatory_life_end_date"] == "2036-09-03", (
        "exactly one day before the clock date 2036-09-04"
    )

    placements = get_success_data(
        api_client.list_car_assignments(
            ADMIN, {"lease_fleet_car_id": car["id"]}
        )
    )
    assert len(placements) == 1, "no second placement may be written"
    assert placements[0]["id"] == incumbent["id"]
