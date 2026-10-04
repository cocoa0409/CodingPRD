"""Segregation of duties: two duties the PRD splits across operators or roles.

Two instances, one test each.  The endorsement test holds the acting role fixed
and varies only ``X-User-ID``; the return test holds the body fixed and varies
only the acting role.  In both, the paired success proves the refusal was keyed
on the identity dimension the rule names.
"""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    build_user_headers,
    create_assignment,
    create_component_payload,
    create_endorsement,
    create_lessee_and_contract,
    create_order,
    create_return,
    release_order,
    reserve_order,
    set_clock,
    setup_catalogue,
    start_production,
    complete_order,
    validate_error,
    validate_success,
)

SUPPLY = TEST_USERS["supply_chain_coordinator_headers"]
LEASE = TEST_USERS["lease_administrator_headers"]
PORTFOLIO = TEST_USERS["portfolio_manager_headers"]

MAKER = build_user_headers("user-sod-1", "ProductionPlanner")
SAME_OPERATOR_AS_APPROVER = build_user_headers("user-sod-1", "LeaseAdministrator")
SECOND_APPROVER = build_user_headers("user-sod-2", "LeaseAdministrator")


def test_endorsement_creator_cannot_approve_its_own_endorsement(api):
    """PRD §2.1: "Second, substitution endorsements are subject to a
    segregation-of-duties rule — the operator who created an endorsement may
    not be the operator who approves it, and an approval attempted by the
    creating `X-User-ID` is rejected with `ERR_SELF_APPROVAL_FORBIDDEN`
    (HTTP 403)."
    PRD §3.3: "Approval is a second-person action and belongs to a
    `LeaseAdministrator`.  It is legal only from `PENDING`, and it carries a
    segregation-of-duties precondition: the acting `X-User-ID` must not be the
    `X-User-ID` that created the endorsement, and an approval attempted by the
    creator is rejected with `ERR_SELF_APPROVAL_FORBIDDEN` (HTTP 403)."
    PRD §3.3: "A successful create starts the endorsement in `PENDING`,
    supersedes any earlier `PENDING` endorsement for the same original component
    on that order, and increments the production order's `version`."

    Design: Corner/rbac/rbac_segregation_of_duties_endorsement_creator_cannot_self_approve
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(
        model_code="CT-SOD-1",
        build_hours=1,
        regulatory_life_years=25,
        line_count_family="LINE-SOD",
        wheelset_part_number="WS-SOD-1",
        wheelset_unit_cost_cents=1000,
        wheelset_lead_time_days=5,
        include_bom=False,
        on_hand_qty=1000,
    )
    substitute = validate_success(
        api_client.create_component(
            create_component_payload(
                part_number="WS-SOD-2",
                component_class="WHEELSET",
                unit_cost_cents=1100,
                lead_time_days=4,
                on_hand_qty=1000,
            ),
            SUPPLY,
        ),
        expected_status=201,
    )
    order = create_order(
        catalogue,
        quantity=1,
        disposition="RETAINED",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-09-20",
    )

    endorsement = create_endorsement(
        order,
        catalogue["wheelset"],
        substitute,
        substitute_qty_per_car=1,
        decides_material=False,
        headers=MAKER,
    )
    assert endorsement["status"] == "PENDING"

    refused = api.approve_substitution_endorsement(
        endorsement["id"], SAME_OPERATOR_AS_APPROVER
    )
    validate_error(refused, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN)
    assert refused.status_code == 403

    untouched = validate_success(
        api.get_substitution_endorsement(endorsement["id"], LEASE)
    )
    assert untouched["status"] == "PENDING", (
        "the refused self-approval left the row exactly where it stood"
    )

    approved = validate_success(
        api.approve_substitution_endorsement(endorsement["id"], SECOND_APPROVER)
    )
    assert approved["status"] == "APPROVED", (
        "a different operator under the same role satisfies the second-person "
        "rule, so the gate is identity-keyed rather than role-keyed"
    )


def test_return_booker_cannot_settle_the_return_it_booked(api):
    """PRD §2.1: "`PortfolioManager` (who owns secondary-market sales,
    scrapping and return settlement)"
    PRD §3.7: "Settlement moves the charge into the ledger.  A
    `PortfolioManager` settles a return, which is legal only while its
    `settlement_status` is `PENDING`; the settlement sets the status to
    `SETTLED` and recomputes the lessee's `outstanding_balance_cents` by the
    reconciliation rule of §3.9, and it increments the return's `version`."
    PRD §3.7: "Until a return is settled, its mileage overage does not count
    toward the lessee's balance, because the reconciliation aggregates only
    settled returns."
    PRD §3.7: "The charge is the overage miles multiplied by the overage rate of
    12 cents per mile, and it is written to the return's `mileage_overage_cents`
    and to the placement's `mileage_charge_cents`."

    The placement runs 90 days from 2026-06-03 to 2026-09-01, so the allowance
    is re-granted for ceil(90 / 30) = 3 blocks of 1000 miles; 5200 miles used
    overruns by 2200 miles and the charge is 2200 * 12 = 26400 cents.

    Design: Corner/rbac/rbac_segregation_of_duties_return_booker_cannot_settle_own_return
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(
        model_code="CT-SOD2-1",
        build_hours=1,
        regulatory_life_years=25,
        line_count_family="LINE-SOD2",
        wheelset_part_number="WS-SOD2-1",
        wheelset_unit_cost_cents=1000,
        wheelset_lead_time_days=5,
        casting_part_number="CS-SOD2-1",
        casting_unit_cost_cents=2000,
        casting_lead_time_days=6,
        include_coating=False,
        on_hand_qty=10,
    )
    commercial = create_lessee_and_contract(
        legal_name="LESS-SOD2-1",
        per_diem_rate_cents=10000,
        liability_bearer="LESSOR",
        fleet_car_cap=10,
        credit_ceiling_cents=500_000_000,
    )

    # The retained order names neither a contract nor a lessee, so its value is
    # attributable to no lessee and cannot disturb the balance asserted below.
    order = create_order(
        catalogue,
        quantity=1,
        disposition="RETAINED",
        priority_rank=1,
        order_date="2026-06-01",
        required_delivery_date="2026-06-20",
    )
    reserve_order(order["id"])
    release_order(order["id"])
    start_production(order["id"], "LINE-SOD2", window_start="2026-06-01")
    complete_order(order["id"], completion_date="2026-06-03")

    cars = validate_success(
        api_client.list_lease_fleet_cars(
            LEASE, {"production_order_id": order["id"], "limit": 10}
        )
    )
    assert len(cars) == 1
    car = cars[0]
    assert car["status"] == "HELD"

    booker = build_user_headers("user-sod-9", "LeaseAdministrator")
    assignment = create_assignment(
        car,
        commercial["contract"],
        commercial["lessee"],
        start_date="2026-06-03",
        end_date="2026-09-01",
        mileage_allowance=1000,
        headers=booker,
    )
    car_return = create_return(
        car,
        assignment,
        return_date="2026-09-01",
        mileage_since_last=5200,
        condition_grade="B",
        headers=booker,
    )
    assert car_return["settlement_status"] == "PENDING"
    assert car_return["mileage_overage_cents"] == 26400, (
        "(5200 - 3 * 1000) overage miles * 12 cents"
    )

    refused = api_client.settle_car_return(car_return["id"], booker)
    validate_error(refused, ApiErrorId.ERR_FORBIDDEN)
    assert refused.status_code == 403

    pending_balance = validate_success(
        api_client.get_lessee_outstanding_balance(commercial["lessee"]["id"], LEASE)
    )
    assert pending_balance["outstanding_balance_cents"] == 0, (
        "an unsettled return has not reached the ledger"
    )

    settler = build_user_headers("user-sod-10", "PortfolioManager")
    settled = validate_success(
        api_client.settle_car_return(car_return["id"], settler)
    )
    assert settled["settlement_status"] == "SETTLED"

    final_balance = validate_success(
        api_client.get_lessee_outstanding_balance(commercial["lessee"]["id"], PORTFOLIO)
    )
    assert final_balance["outstanding_balance_cents"] == 26400, (
        "the settled mileage true-up is the only charge on the ledger"
    )
