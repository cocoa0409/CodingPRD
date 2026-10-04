"""RBAC role matrix, denial half: a declared role is refused a foreign operation.

Seven instances, one test each.  Every test holds the request body fixed and
varies only the acting role, so the rejection is provably keyed on the role
rather than on the payload: the same body is accepted (or at least admitted past
the role gate) under the role the PRD names for that endpoint.
"""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_car_return_payload,
    create_lessee_and_contract,
    make_lessee_headers,
    set_clock,
    setup_catalogue,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

SUPPLY = TEST_USERS["supply_chain_coordinator_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
LEASE = TEST_USERS["lease_administrator_headers"]
PORTFOLIO = TEST_USERS["portfolio_manager_headers"]
RETROFIT = TEST_USERS["regulatory_retrofitist_headers"]

# Well-formed UUIDs that name nothing in a freshly started store, so the body
# passes request-shape validation and fails only on referential resolution.
MISSING_CAR_ID = "00000000-0000-0000-0000-0000000000c1"
MISSING_ASSIGNMENT_ID = "00000000-0000-0000-0000-0000000000c2"


def test_supply_chain_coordinator_is_refused_production_order_creation(api):
    """PRD §2.1: "`ProductionPlanner` (who owns the order backlog, the
    production line schedule and shop work)"
    PRD §2.1: "A request whose role is declared but not permitted for the
    requested operation is rejected with `ERR_FORBIDDEN` (HTTP 403);
    authorization is evaluated against both the role matrix in this section and
    the per-endpoint role list in §4."
    PRD §2.11: "Second, authorization: the acting role must be permitted for the
    operation by the matrix in §2.1 and by the endpoint's own role list in §4,
    and a role that is declared but not permitted is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: "| POST | `/api/v1/production-orders` | Take a customer order for
    cars of one type, evaluated for lead-time feasibility and quoted per §3.1.
    | `ProductionPlanner` |"

    The identical body is submitted under both roles, so a payload-shaped
    rejection is ruled out; the refused role keeps its shared list read.

    Design: Corner/rbac/rbac_supply_chain_coordinator_denied_production_order_creation_returns_forbidden
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(
        model_code="CT-SCC-1",
        build_hours=1,
        regulatory_life_years=25,
        line_count_family="LINE-SCC",
        include_coating=False,
        on_hand_qty=10,
    )
    payload = {
        "car_type_id": catalogue["car_type"]["id"],
        "quantity": 2,
        "planned_shop_days": 2,
        "disposition": "RETAINED",
        "priority_rank": 1,
        "order_date": "2026-09-01",
        "required_delivery_date": "2026-09-20",
    }

    refused = api.create_production_order(payload, SUPPLY)
    validate_error(refused, ApiErrorId.ERR_FORBIDDEN)
    assert refused.status_code == 403
    assert refused.json()["data"]["error_id"] != ApiErrorId.ERR_UNAUTHENTICATED.value, (
        "the role is declared, so only the authorization check can report"
    )

    shared_read = validate_success(api.list_production_orders(SUPPLY))
    assert shared_read == [], "the refusal is per-operation, not a read ban"

    accepted = validate_success(
        api.create_production_order(payload, PLANNER), expected_status=201
    )
    assert accepted["status"] == "DRAFT"

    after = validate_success(api.list_production_orders(SUPPLY))
    assert len(after) == 1, "the refused write minted no row"
    assert after[0]["id"] == accepted["id"]


def test_production_planner_is_refused_lessee_account_creation(api):
    """PRD §2.1: "`LeaseAdministrator` (who owns lease contracts, placements and
    the return desk, and acts as the second-person approver for substitution
    endorsements)"
    PRD §3.5: "A lessee account is opened before any contract names it.  A
    `LeaseAdministrator` registers the account with its `legal_name`, its
    `credit_tier` — one of `A`, `B`, `C` or `D`, with `A` the strongest
    standing — its `utilization_threshold_pct` between 0 and 100, and its
    `credit_ceiling_cents`, the maximum exposure the business will carry."
    PRD §2.11: "Second, authorization: the acting role must be permitted for the
    operation by the matrix in §2.1 and by the endpoint's own role list in §4,
    and a role that is declared but not permitted is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "and every role may perform the read operations listed in §4."

    Design: Corner/rbac/rbac_production_planner_denied_lessee_creation_returns_forbidden
    """
    set_clock("2026-09-01T00:00:00Z")
    payload = {
        "legal_name": "LESS-PP-DENIED",
        "credit_tier": "A",
        "utilization_threshold_pct": 50,
        "credit_ceiling_cents": 5000000,
    }

    refused = api.create_lessee(payload, PLANNER)
    validate_error(refused, ApiErrorId.ERR_FORBIDDEN)
    assert refused.status_code == 403
    assert "id" not in refused.json()["data"], "the refused write minted no row"

    accepted = validate_success(api.create_lessee(payload, LEASE), expected_status=201)
    assert accepted["status"] == "ACTIVE"
    assert accepted["outstanding_balance_cents"] == 0

    # The denied role still holds its shared read of the account it could not
    # create.
    balance = validate_success(
        api.get_lessee_outstanding_balance(accepted["id"], PLANNER)
    )
    assert balance["outstanding_balance_cents"] == 0


def test_lease_administrator_is_refused_retrofit_program_creation(api):
    """PRD §2.1: "`RegulatoryRetrofitist` (who owns retrofit mandates, their
    covered car types and program closure)"
    PRD §3.8: "A regulatory mandate is opened as a program.  A
    `RegulatoryRetrofitist` creates it with a unique `mandate_code`, a
    `description`, the `compliance_deadline_date` by which every enrolled car
    must be retrofitted, the `required_shop_days_per_car` the work consumes, and
    an optional `required_component_id` naming the coating or casting kit
    consumed per retrofit car — null when the mandate consumes no component."
    PRD §2.11: "Second, authorization: the acting role must be permitted for the
    operation by the matrix in §2.1 and by the endpoint's own role list in §4,
    and a role that is declared but not permitted is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "and every role may perform the read operations listed in §4."

    The same mandate code is used for both calls, so a persisted row from the
    refused write would surface as a duplicate on the accepted one.

    Design: Corner/rbac/rbac_lease_administrator_denied_retrofit_program_creation_returns_forbidden
    """
    set_clock("2026-09-01T00:00:00Z")
    payload = {
        "mandate_code": "MAND-LA-DENIED",
        "description": "Denied mandate",
        "compliance_deadline_date": "2026-12-31",
        "required_shop_days_per_car": 3,
    }

    refused = api.create_retrofit_program(payload, LEASE)
    validate_error(refused, ApiErrorId.ERR_FORBIDDEN)
    assert refused.status_code == 403

    shared_read = validate_success(api.list_retrofit_programs(LEASE))
    assert shared_read == [], "the refusal is per-operation, not a read ban"

    accepted = validate_success(
        api.create_retrofit_program(payload, RETROFIT), expected_status=201
    )
    assert accepted["status"] == "PLANNED"

    after = validate_success(api.list_retrofit_programs(LEASE))
    assert len(after) == 1, "the refused write minted no mandate"
    assert after[0]["id"] == accepted["id"]


def test_portfolio_manager_is_refused_placement_creation(api):
    """PRD §2.1: "`LeaseAdministrator` (who owns lease contracts, placements and
    the return desk, and acts as the second-person approver for substitution
    endorsements)"
    PRD §2.11: "Second, authorization: the acting role must be permitted for the
    operation by the matrix in §2.1 and by the endpoint's own role list in §4,
    and a role that is declared but not permitted is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.11: "Fourth, body referential integrity: every foreign key named in
    the request body must resolve to a persisted row, and a failure is rejected
    with `ERR_COMPONENT_NOT_FOUND` (HTTP 404).  This fourth check is not limited
    to component references despite its name — it covers `lease_fleet_car_id`,
    `lease_contract_id`, `lessee_id`, `component_id`, `car_type_id`,
    `production_order_id` and `retrofit_program_id` alike — and it guards the
    creation of production orders, car assignments, lease contracts,
    substitution endorsements, retrofit work orders and component purchase
    orders."

    The body clears the role gate for the owning role and then fails on the
    deliberately unresolvable car reference, which is what shows the 403 was
    role-keyed rather than payload-keyed.

    Design: Corner/rbac/rbac_portfolio_manager_denied_car_assignment_creation_returns_forbidden
    """
    set_clock("2026-09-01T00:00:00Z")
    commercial = create_lessee_and_contract(
        legal_name="LESS-PM-DENY",
        credit_ceiling_cents=9000000,
        per_diem_rate_cents=10000,
        liability_bearer="LESSOR",
        fleet_car_cap=10,
    )
    payload = {
        "lease_fleet_car_id": MISSING_CAR_ID,
        "lease_contract_id": commercial["contract"]["id"],
        "lessee_id": commercial["lessee"]["id"],
        "start_date": "2026-09-01",
        "end_date": "2026-12-01",
        "mileage_allowance": 1000,
    }

    refused = api.create_car_assignment(payload, PORTFOLIO)
    validate_error(refused, ApiErrorId.ERR_FORBIDDEN)
    assert refused.status_code == 403
    assert refused.json()["data"]["error_id"] != ApiErrorId.ERR_NOT_FOUND.value, (
        "the authorization check precedes body referential resolution"
    )

    shared_read = validate_success(api.list_car_assignments(PORTFOLIO))
    assert shared_read == []

    admitted = api.create_car_assignment(payload, LEASE)
    validate_error(admitted, ApiErrorId.ERR_COMPONENT_NOT_FOUND)
    assert admitted.status_code == 404, (
        "the identical body passes the role gate and fails only on the "
        "unresolvable car reference"
    )

    after = validate_success(api.list_car_assignments(PORTFOLIO))
    assert after == [], "neither rejected call created a placement"


def test_regulatory_retrofitist_is_refused_secondary_market_sale_creation(api):
    """PRD §2.1: "`PortfolioManager` (who owns secondary-market sales,
    scrapping and return settlement)"
    PRD §2.11: "Second, authorization: the acting role must be permitted for the
    operation by the matrix in §2.1 and by the endpoint's own role list in §4,
    and a role that is declared but not permitted is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.9: "A `PortfolioManager` sells a car by naming the
    `lease_fleet_car_id`, an optional `lease_contract_id` for the contract that
    had to be terminated first, the `buyer_name`, the `sale_price_cents`, an
    optional `net_book_value_cents`, the `writeback_liability_cents`, and the
    `sale_date`."
    PRD §2.1: "and every role may perform the read operations listed in §4."

    Design: Corner/rbac/rbac_regulatory_retrofitist_denied_lease_fleet_sale_creation_returns_forbidden
    """
    set_clock("2026-09-01T00:00:00Z")
    payload = {
        "lease_fleet_car_id": MISSING_CAR_ID,
        "buyer_name": "Delta Short Line",
        "sale_price_cents": 5000000,
        "writeback_liability_cents": 0,
        "sale_date": "2026-09-10",
    }

    refused = api.create_lease_fleet_sale(payload, RETROFIT)
    validate_error(refused, ApiErrorId.ERR_FORBIDDEN)
    assert refused.status_code == 403

    shared_read = validate_success(api.list_lease_fleet_sales(RETROFIT))
    assert shared_read == [], "the refusal is per-operation, not a read ban"

    admitted = api.create_lease_fleet_sale(payload, PORTFOLIO)
    admitted_error = validate_error_is_one_of(
        admitted, [ApiErrorId.ERR_COMPONENT_NOT_FOUND, ApiErrorId.ERR_NOT_FOUND]
    )
    assert admitted.status_code == 404, (
        "the identical body clears the role gate and fails only on the "
        f"unresolvable car reference ({admitted_error})"
    )

    after = validate_success(api.list_lease_fleet_sales(RETROFIT))
    assert after == [], "neither rejected call created a sale"


def test_lessee_cannot_read_another_accounts_outstanding_balance(api):
    """PRD §2.1: "`Lessee` is the exception.  When `X-User-Role` is `Lessee`,
    `X-User-ID` is the `id` of the acting `Lessee`; ownership checks on any
    resource that references a `Lessee` compare the resource's foreign-key
    field to `X-User-ID`.  A `Lessee` may read its own contracts, placements,
    cars and ledger balance; the outstanding-balance read is available to a
    lessee only for its own `id`."
    PRD §2.11: "Second, authorization: the acting role must be permitted for the
    operation by the matrix in §2.1 and by the endpoint's own role list in §4,
    and a role that is declared but not permitted is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.9: "The outstanding-balance read exposes the components as well: it
    reports `outstanding_balance_cents`, `settled_charges_cents` and
    `credits_applied_cents`, and a lessee may read it only for its own `id`."

    Design: Corner/rbac/rbac_lessee_denied_another_lessees_balance_returns_forbidden
    """
    set_clock("2026-09-01T00:00:00Z")
    account_a = validate_success(
        api.create_lessee(
            {
                "legal_name": "LESS-XS-A",
                "credit_tier": "A",
                "utilization_threshold_pct": 50,
                "credit_ceiling_cents": 4000000,
            },
            LEASE,
        ),
        expected_status=201,
    )
    account_b = validate_success(
        api.create_lessee(
            {
                "legal_name": "LESS-XS-B",
                "credit_tier": "B",
                "utilization_threshold_pct": 60,
                "credit_ceiling_cents": 4000000,
            },
            LEASE,
        ),
        expected_status=201,
    )

    refused = api.get_lessee_outstanding_balance(
        account_b["id"], make_lessee_headers(account_a["id"])
    )
    validate_error(refused, ApiErrorId.ERR_FORBIDDEN)
    assert refused.status_code == 403
    error_body = refused.json()["data"]
    assert error_body["error_id"] != ApiErrorId.ERR_UNAUTHENTICATED.value, (
        "Lessee is a declared role and this endpoint is open to it for its own id"
    )
    assert "outstanding_balance_cents" not in error_body, (
        "the error envelope discloses no field of the foreign ledger"
    )

    # Holding the path fixed and changing only X-User-ID flips the outcome.
    own = validate_success(
        api.get_lessee_outstanding_balance(
            account_b["id"], make_lessee_headers(account_b["id"])
        )
    )
    assert own["outstanding_balance_cents"] == 0


def test_lessee_cannot_book_a_car_return(api):
    """PRD §2.1: "`LeaseAdministrator` (who owns lease contracts, placements and
    the return desk, and acts as the second-person approver for substitution
    endorsements)"
    PRD §3.7: "A return is the mirror of a placement: it closes the commercial
    interval and starts the physical one.  A `LeaseAdministrator` records the
    return with the `lease_fleet_car_id`, the `car_assignment_id` being closed,
    the `return_date`, the `mileage_since_last` the car ran on this placement,
    and a `condition_grade` of `A`, `B`, `C` or `D`."
    PRD §2.11: "Second, authorization: the acting role must be permitted for the
    operation by the matrix in §2.1 and by the endpoint's own role list in §4,
    and a role that is declared but not permitted is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "A `Lessee` may read its own contracts, placements, cars and
    ledger balance; the outstanding-balance read is available to a lessee only
    for its own `id`."

    Design: Corner/rbac/rbac_lessee_denied_car_return_booking_returns_forbidden
    """
    set_clock("2026-09-01T00:00:00Z")
    account = validate_success(
        api.create_lessee(
            {
                "legal_name": "LESS-RET-DENY",
                "credit_tier": "A",
                "utilization_threshold_pct": 50,
                "credit_ceiling_cents": 4000000,
            },
            LEASE,
        ),
        expected_status=201,
    )
    lessee_headers = make_lessee_headers(account["id"])
    payload = create_car_return_payload(
        lease_fleet_car_id=MISSING_CAR_ID,
        car_assignment_id=MISSING_ASSIGNMENT_ID,
        return_date="2026-09-01",
        mileage_since_last=100,
        condition_grade="B",
    )

    refused = api.create_car_return(payload, lessee_headers)
    validate_error(refused, ApiErrorId.ERR_FORBIDDEN)
    assert refused.status_code == 403

    shared_read = validate_success(api.list_car_returns(lessee_headers))
    assert shared_read == [], "a lessee may observe returns but never book one"

    admitted = api.create_car_return(payload, LEASE)
    admitted_error = validate_error_is_one_of(
        admitted, [ApiErrorId.ERR_COMPONENT_NOT_FOUND, ApiErrorId.ERR_NOT_FOUND]
    )
    assert admitted.status_code == 404, (
        "the identical body passes the role gate and fails only on the "
        f"unresolvable references ({admitted_error})"
    )

    after = validate_success(api.list_car_returns(lessee_headers))
    assert after == [], "neither rejected call created a return"
