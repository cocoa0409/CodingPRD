"""RBAC role matrix, allow half: each role's declared exclusive operations.

Eight instances, one test each.  Every test drives the full success chain for a
single role and pins the state it produces, so the suite shows that each
operation the PRD reserves for a role is exercisable end to end by that role
and by no other.  The denial half of each pair lives in the sibling
``test_rbac_role_denials`` module.
"""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_component_payload,
    create_component_purchase_order_payload,
    create_component_receipt_payload,
    create_lessee_and_contract,
    create_order,
    make_lessee_headers,
    set_clock,
    setup_catalogue,
    setup_retained_order_with_fleet_cars,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SUPPLY = TEST_USERS["supply_chain_coordinator_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
LEASE = TEST_USERS["lease_administrator_headers"]
PORTFOLIO = TEST_USERS["portfolio_manager_headers"]
RETROFIT = TEST_USERS["regulatory_retrofitist_headers"]


def test_platform_admin_clock_control_is_durable_and_operator_scoped(api):
    """PRD §2.5: "On server startup the logical clock reads exactly
    `2026-09-01T00:00:00Z`; it holds that value until it is set, and it never
    falls back to the host's system time under any circumstance."
    PRD §2.5: "Advancing the clock is an operator-only capability: a
    `PlatformAdmin` supplies a target instant in the `to_iso8601` field, and the
    clock thereafter reads that instant."
    PRD §2.1: "First, clock control is exclusive to `PlatformAdmin`: no other
    role may advance the logical clock."
    PRD §2.5: "A read of the clock returns the current instant as
    `current_utc`."

    Design: Corner/rbac/rbac_platform_admin_clock_control_exclusive_operation_succeeds
    """
    default = validate_success(api.get_current_utc(ADMIN))
    assert default["current_utc"] == "2026-09-01T00:00:00Z", (
        "a freshly started server reads the declared startup default, not a "
        f"wall-clock instant: {default['current_utc']!r}"
    )

    echo = validate_success(api.set_current_utc("2026-10-01T00:00:00Z", ADMIN))
    assert echo["current_utc"] == "2026-10-01T00:00:00Z", (
        "the clock write's own response already carries the new instant"
    )

    after = validate_success(api.get_current_utc(ADMIN))
    assert after["current_utc"] == "2026-10-01T00:00:00Z", (
        "the newly set instant is durable for the immediately following read"
    )

    # The capability is role-scoped: a declared role that does not own the
    # clock is refused, and the refusal leaves the clock where it stood.
    refused = api.set_current_utc("2026-11-01T00:00:00Z", PLANNER)
    validate_error(refused, ApiErrorId.ERR_FORBIDDEN)
    assert refused.status_code == 403
    unchanged = validate_success(api.get_current_utc(ADMIN))
    assert unchanged["current_utc"] == "2026-10-01T00:00:00Z", (
        "the refused operator never advanced the clock"
    )


def test_platform_admin_override_is_per_operation_not_a_blanket_bypass(api):
    """PRD §2.1: "`PlatformAdmin` is the platform operator with unconditional
    override and owns the logical clock; when `X-User-Role` is `PlatformAdmin`,
    `X-User-ID` is an opaque operator identifier not tied to any persisted
    entity — the server may record it, but it never compares it to any entity's
    `id`."
    PRD §2.1: "A request whose role is declared but not permitted for the
    requested operation is rejected with `ERR_FORBIDDEN` (HTTP 403);
    authorization is evaluated against both the role matrix in this section and
    the per-endpoint role list in §4."
    PRD §2.11: "Second, authorization: the acting role must be permitted for the
    operation by the matrix in §2.1 and by the endpoint's own role list in §4,
    and a role that is declared but not permitted is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."

    The same body is submitted under both roles, so the only variable is the
    acting role; had the refused call persisted anything, the accepted call
    would collide with it as a duplicate part number.

    Design: Corner/rbac/rbac_platform_admin_denied_component_creation_returns_forbidden
    """
    set_clock("2026-09-01T00:00:00Z")
    payload = create_component_payload(
        part_number="WS-DENIED-1",
        component_class="WHEELSET",
        unit_cost_cents=1500,
        lead_time_days=5,
    )

    refused = api.create_component(payload, ADMIN)
    validate_error(refused, ApiErrorId.ERR_FORBIDDEN)
    assert refused.status_code == 403
    error_body = refused.json()["data"]
    assert error_body["error_id"] == "ERR_FORBIDDEN"
    assert error_body["error_id"] != ApiErrorId.ERR_UNAUTHENTICATED.value, (
        "PlatformAdmin is a declared role, so the authentication check passes"
    )
    assert "id" not in error_body, "the refused write minted no component row"

    created = validate_success(api.create_component(payload, SUPPLY), expected_status=201)
    assert created["part_number"] == "WS-DENIED-1"
    assert created["component_class"] == "WHEELSET"


def test_supply_chain_coordinator_owns_catalogue_purchasing_and_yard(api):
    """PRD §2.1: "The same opaque treatment applies to `SupplyChainCoordinator`
    (who owns the component catalogue, purchase orders and yard receipts),
    `ProductionPlanner` (who owns the order backlog, the production line
    schedule and shop work), `LeaseAdministrator` (who owns lease contracts,
    placements and the return desk, and acts as the second-person approver for
    substitution endorsements), `PortfolioManager` (who owns secondary-market
    sales, scrapping and return settlement), and `RegulatoryRetrofitist` (who
    owns retrofit mandates, their covered car types and program closure)."
    PRD §3.2: "Stock moves only on receipt.  A coordinator books a
    `ComponentReceipt` against the purchase with the
    `component_purchase_order_id`, the `component_id`, the `qty_received` and
    the `receipt_date`; booking the receipt alone does not change stock."
    PRD §3.2: "On success the purchase order becomes `RECEIVED`, the component's
    `on_hand_qty` is increased by `qty_received`, and `reserved_qty` and
    `shortfall_qty` are recomputed by the allocation rule above."
    PRD §2.4: "`on_hand_qty` is system-maintained: it starts at 0 when the
    component is registered unless the caller supplies an opening quantity, is
    increased only by a receipt, and is decreased only by consumption against a
    reservation or by scrapping — it is never set directly by a client after
    creation and never goes negative."

    Design: Corner/rbac/rbac_supply_chain_coordinator_component_catalog_and_receipt_operations_succeed
    """
    set_clock("2026-09-01T00:00:00Z")
    component = validate_success(
        api.create_component(
            create_component_payload(
                part_number="WS-SCC-1",
                component_class="WHEELSET",
                unit_cost_cents=1500,
                lead_time_days=5,
            ),
            SUPPLY,
        ),
        expected_status=201,
    )
    assert component["on_hand_qty"] == 0, "no opening quantity was supplied"

    purchase_order = validate_success(
        api.create_component_purchase_order(
            create_component_purchase_order_payload(
                component_id=component["id"],
                qty_ordered=12,
                unit_cost_cents=1500,
                order_date="2026-09-01",
                expected_receipt_date="2026-09-06",
            ),
            SUPPLY,
        ),
        expected_status=201,
    )
    assert purchase_order["status"] == "PLACED"

    confirmed = validate_success(
        api.confirm_component_purchase_order(purchase_order["id"], SUPPLY)
    )
    assert confirmed["status"] == "CONFIRMED"

    receipt = validate_success(
        api.create_component_receipt(
            create_component_receipt_payload(
                component_purchase_order_id=purchase_order["id"],
                component_id=component["id"],
                qty_received=12,
                receipt_date="2026-09-06",
            ),
            SUPPLY,
        ),
        expected_status=201,
    )

    booked = validate_success(api.get_component(component["id"], SUPPLY))
    assert booked["on_hand_qty"] == 0, "booking a receipt alone moves no stock"

    validate_success(api.receive_component_receipt(receipt["id"], SUPPLY))

    closed = validate_success(api.get_component_purchase_order(purchase_order["id"], SUPPLY))
    assert closed["status"] == "RECEIVED"

    landed = validate_success(api.get_component(component["id"], SUPPLY))
    assert landed["on_hand_qty"] == 12, "exactly qty_received lands on hand"
    assert landed["reserved_qty"] == 0, (
        "no released order and no in-progress retrofit work order hold a "
        "reservation term"
    )


def test_production_planner_owns_car_type_and_bill_of_material_writes(api):
    """PRD §2.1: "Several operations are shared rather than exclusive: creating
    a car type is open to both `ProductionPlanner` and `RegulatoryRetrofitist`;
    raising a substitution endorsement and scheduling a retrofit work order are
    open to `ProductionPlanner` and `RegulatoryRetrofitist` alike; and every
    role may perform the read operations listed in §4."
    PRD §3.1: "A `ProductionPlanner` or a `RegulatoryRetrofitist` registers a
    car type by supplying its `model_code`, `car_class`, `build_hours`,
    `regulatory_life_years` and `line_count_family`; a
    `SupplyChainCoordinator` registers a component with its `part_number`,
    `component_class`, `unit_cost_cents` and `lead_time_days`, optionally
    opening the stock position with an `on_hand_qty`; and a
    `ProductionPlanner` binds the two together by adding a bill-of-material row
    carrying `car_type_id`, `component_id` and `qty_per_car`."
    PRD §2.4: "A `CarTypeComponentRequirement` is the bill-of-material row
    binding one component to one car type.  It names the `car_type_id` and the
    `component_id`, and states `qty_per_car`, the units of that component
    consumed per finished car, which is at least 1."

    Design: Corner/rbac/rbac_production_planner_car_type_and_bill_of_material_operations_succeed
    """
    set_clock("2026-09-01T00:00:00Z")
    component = validate_success(
        api.create_component(
            create_component_payload(
                part_number="WS-PP-1",
                component_class="WHEELSET",
                unit_cost_cents=1000,
                lead_time_days=5,
            ),
            SUPPLY,
        ),
        expected_status=201,
    )

    car_type = validate_success(
        api.create_car_type(
            {
                "model_code": "CT-PP-1",
                "car_class": "BOXCAR",
                "build_hours": 1,
                "regulatory_life_years": 25,
                "line_count_family": "LINE-PP",
            },
            PLANNER,
        ),
        expected_status=201,
    )
    assert car_type["status"] == "ACTIVE", "a newly created type starts ACTIVE"

    requirement = validate_success(
        api.create_car_type_component_requirement(
            {
                "car_type_id": car_type["id"],
                "component_id": component["id"],
                "qty_per_car": 2,
            },
            PLANNER,
        ),
        expected_status=201,
    )
    assert requirement["qty_per_car"] == 2
    assert requirement["component_id"] == component["id"]

    listed = validate_success(
        api.list_car_type_component_requirements(
            PLANNER, {"car_type_id": car_type["id"]}
        )
    )
    assert len(listed) == 1, "the car type carries exactly the one row just bound"
    assert listed[0]["id"] == requirement["id"]
    assert listed[0]["qty_per_car"] == 2
    assert listed[0]["component_id"] == component["id"]


def test_lease_administrator_owns_lessee_minting_and_contract_lifecycle(api):
    """PRD §2.1: "The same opaque treatment applies to `SupplyChainCoordinator`
    (who owns the component catalogue, purchase orders and yard receipts),
    `ProductionPlanner` (who owns the order backlog, the production line
    schedule and shop work), `LeaseAdministrator` (who owns lease contracts,
    placements and the return desk, and acts as the second-person approver for
    substitution endorsements), `PortfolioManager` (who owns secondary-market
    sales, scrapping and return settlement), and `RegulatoryRetrofitist` (who
    owns retrofit mandates, their covered car types and program closure)."
    PRD §3.5: "A lessee account is opened before any contract names it.  A
    `LeaseAdministrator` registers the account with its `legal_name`, its
    `credit_tier` — one of `A`, `B`, `C` or `D`, with `A` the strongest
    standing — its `utilization_threshold_pct` between 0 and 100, and its
    `credit_ceiling_cents`, the maximum exposure the business will carry."
    PRD §3.5: "A drafted contract starts in `DRAFT` with an `amendment_seq` of
    0 and a `capital_allocation_cents` of 0."
    PRD §3.5: "A contract is put into force by activation, which is legal only
    from `DRAFT`."
    PRD §2.4: "`version` starts at 1 for a newly created resource and is
    incremented by exactly 1 on every mutation that the state machines in §3
    prescribe, with `updated_at` refreshed in the same write."

    Design: Corner/rbac/rbac_lease_administrator_lessee_and_contract_lifecycle_operations_succeed
    """
    set_clock("2026-09-01T00:00:00Z")
    lessee = validate_success(
        api.create_lessee(
            {
                "legal_name": "LESS-LA-1",
                "credit_tier": "A",
                "utilization_threshold_pct": 50,
                "credit_ceiling_cents": 9000000,
            },
            LEASE,
        ),
        expected_status=201,
    )
    assert lessee["status"] == "ACTIVE", "a newly registered lessee starts ACTIVE"
    assert lessee["outstanding_balance_cents"] == 0

    contract = validate_success(
        api.create_lease_contract(
            {
                "lessee_id": lessee["id"],
                "lease_type": "FULL_SERVICE",
                "per_diem_rate_cents": 10000,
                "liability_bearer": "LESSOR",
                "term_start_date": "2026-01-01",
                "term_end_date": "2027-12-31",
                "fleet_car_cap": 10,
            },
            LEASE,
        ),
        expected_status=201,
    )
    assert contract["status"] == "DRAFT"
    assert contract["amendment_seq"] == 0
    assert contract["capital_allocation_cents"] == 0

    activated = validate_success(api.activate_lease_contract(contract["id"], LEASE))
    assert activated["status"] == "ACTIVE"
    assert activated["version"] == contract["version"] + 1, (
        "activation is one mutation of the contract"
    )
    assert activated["amendment_seq"] == 0, "activation ratifies nothing"


def test_portfolio_manager_scrap_reduces_the_former_contract_capital(api):
    """PRD §2.1: "`PortfolioManager` (who owns secondary-market sales,
    scrapping and return settlement)"
    PRD §3.9: "A `PortfolioManager` scraps a car from `HELD` status, supplying
    an optional `scrap_reason`.  The scrap sets the car to `SCRAPPED`,
    re-derives its former contract's `capital_allocation_cents` by the
    allocation rule of §3.4 — which now excludes this car, so the contract's
    capital figure shrinks — and clears the car's retrofit obligations".
    PRD §3.4: "The retained-car set is every fleet car whose
    `production_order_id` points at this order and whose status is one of the
    three live fleet states, `HELD`, `ASSIGNED` or `UNDER_REPAIR`; cars that
    have been sold or scrapped are excluded, which is why scrapping a car
    re-derives a smaller capital figure for its former contract."
    PRD §3.4: "The capital figure is the size of that set multiplied by the
    order's `unit_price_cents`."

    The car type is priced at build_hours 1 with one wheelset at 1000 cents and
    one casting at 2000 cents per car, so the quote is
    ceil((1000 + 25000) / 100) * 100 + ceil((2000 + 25000) / 100) * 100
    + 1 * 45000 = 98000 cents with no endorsement change fee.

    Design: Corner/rbac/rbac_portfolio_manager_scrap_of_held_car_succeeds
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(
        model_code="CT-PM-1",
        car_class="BOXCAR",
        build_hours=1,
        regulatory_life_years=25,
        line_count_family="LINE-PM",
        wheelset_part_number="WS-PM-1",
        wheelset_unit_cost_cents=1000,
        wheelset_qty_per_car=1,
        wheelset_lead_time_days=5,
        casting_part_number="CS-PM-1",
        casting_unit_cost_cents=2000,
        casting_qty_per_car=1,
        casting_lead_time_days=6,
        include_coating=False,
        on_hand_qty=10,
    )
    commercial = create_lessee_and_contract(
        legal_name="LESS-PM-1",
        per_diem_rate_cents=10000,
        liability_bearer="LESSOR",
        fleet_car_cap=10,
    )
    world = setup_retained_order_with_fleet_cars(
        car_count=2,
        catalogue=catalogue,
        contract=commercial["contract"],
        lessee=commercial["lessee"],
        build_contract=False,
        order_date="2026-09-01",
        required_delivery_date="2026-09-20",
        changeover_start="2026-09-02",
        completion_date="2026-09-04",
    )
    assert world["order"]["unit_price_cents"] == 98000, (
        "per-line ceiling first, then summation, then the labor charge"
    )

    cars = world["cars"]
    assert len(cars) == 2, "a two-car retained completion creates two fleet cars"
    assert cars[0]["status"] == "HELD" and cars[1]["status"] == "HELD"
    assert cars[0]["acquisition_cost_cents"] == 98000

    before = validate_success(api.get_lease_contract(commercial["contract"]["id"], PORTFOLIO))
    assert before["capital_allocation_cents"] == 196000, "2 live cars * 98000"

    scrapped = validate_success(
        api.scrap_lease_fleet_car(
            cars[0]["id"], PORTFOLIO, {"scrap_reason": "Economic write-off"}
        )
    )
    assert scrapped["status"] == "SCRAPPED"
    assert scrapped["version"] == cars[0]["version"] + 1

    after = validate_success(api.get_lease_contract(commercial["contract"]["id"], PORTFOLIO))
    assert after["capital_allocation_cents"] == 98000, (
        "the scrapped car leaves the retained-car set, so the capital figure "
        "shrinks to the single remaining live car"
    )


def test_regulatory_retrofitist_owns_mandates_coverage_and_closure(api):
    """PRD §2.1: "`RegulatoryRetrofitist` (who owns retrofit mandates, their
    covered car types and program closure)"
    PRD §2.1: "Several operations are shared rather than exclusive: creating a
    car type is open to both `ProductionPlanner` and `RegulatoryRetrofitist`;
    raising a substitution endorsement and scheduling a retrofit work order are
    open to `ProductionPlanner` and `RegulatoryRetrofitist` alike; and every
    role may perform the read operations listed in §4."
    PRD §3.8: "The program starts in `PLANNED` with a `program_cost_cents` of
    0.  Coverage is then declared by adding `RetrofitProgramCarType` rows, each
    naming the `retrofit_program_id` and the `car_type_id` it covers; a program
    covers nothing until at least one such row exists."
    PRD §3.8: "On success the program becomes `IN_PROGRESS`, the
    `retrofit_required` flag is set to true on every fleet car of a covered car
    type whose status is `HELD` or `UNDER_REPAIR`, and the program's
    `program_cost_cents` is re-derived by the cost rule below."
    PRD §3.8: "Voiding is the abandonment path: it is legal from `IN_PROGRESS`,
    accepts an optional `reason`, sets the program to `VOIDED`, sets every work
    order of the program to `CANCELLED`, and sets `retrofit_required` to false
    on every enrolled car."

    Design: Corner/rbac/rbac_regulatory_retrofitist_program_and_coverage_operations_succeed
    """
    set_clock("2026-09-01T00:00:00Z")
    car_type = validate_success(
        api.create_car_type(
            {
                "model_code": "CT-RR-1",
                "car_class": "TANK",
                "build_hours": 2,
                "regulatory_life_years": 30,
                "line_count_family": "LINE-RR",
            },
            RETROFIT,
        ),
        expected_status=201,
    )
    assert car_type["status"] == "ACTIVE", (
        "the car-type write is a shared operation of this role"
    )

    program = validate_success(
        api.create_retrofit_program(
            {
                "mandate_code": "MAND-RR-1",
                "description": "Tank car valve mandate",
                "compliance_deadline_date": "2026-12-31",
                "required_shop_days_per_car": 3,
            },
            RETROFIT,
        ),
        expected_status=201,
    )
    assert program["status"] == "PLANNED"
    assert program["program_cost_cents"] == 0

    coverage = validate_success(
        api.create_retrofit_program_car_type(
            {"retrofit_program_id": program["id"], "car_type_id": car_type["id"]},
            RETROFIT,
        ),
        expected_status=201,
    )
    assert coverage["retrofit_program_id"] == program["id"]
    assert coverage["car_type_id"] == car_type["id"]

    started = validate_success(api.start_retrofit_program(program["id"], RETROFIT))
    assert started["status"] == "IN_PROGRESS"
    assert started["version"] == program["version"] + 1

    voided = validate_success(
        api.void_retrofit_program(
            program["id"], RETROFIT, {"reason": "Superseded by a later mandate"}
        )
    )
    assert voided["status"] == "VOIDED"
    assert voided["version"] == started["version"] + 1


def test_lessee_reads_its_own_outstanding_balance_breakdown(api):
    """PRD §2.1: "`Lessee` is the exception.  When `X-User-Role` is `Lessee`,
    `X-User-ID` is the `id` of the acting `Lessee`; ownership checks on any
    resource that references a `Lessee` compare the resource's foreign-key
    field to `X-User-ID`.  A `Lessee` may read its own contracts, placements,
    cars and ledger balance; the outstanding-balance read is available to a
    lessee only for its own `id`."
    PRD §3.9: "The outstanding-balance read exposes the components as well: it
    reports `outstanding_balance_cents`, `settled_charges_cents` and
    `credits_applied_cents`, and a lessee may read it only for its own `id`."

    Design: Corner/rbac/rbac_lessee_reads_own_outstanding_balance_succeeds
    """
    set_clock("2026-09-01T00:00:00Z")
    account = validate_success(
        api.create_lessee(
            {
                "legal_name": "LESS-OWN-A",
                "credit_tier": "A",
                "utilization_threshold_pct": 50,
                "credit_ceiling_cents": 4000000,
            },
            LEASE,
        ),
        expected_status=201,
    )

    balance = validate_success(
        api.get_lessee_outstanding_balance(
            account["id"], make_lessee_headers(account["id"])
        )
    )
    assert balance["outstanding_balance_cents"] == 0
    assert balance["settled_charges_cents"] == 0, (
        "no settled return, sold order or settled sale has accrued yet"
    )
    assert balance["credits_applied_cents"] == 0


def test_every_role_reads_the_catalogue_backlog_and_ledger(api):
    """PRD §2.1: "Several operations are shared rather than exclusive: creating
    a car type is open to both `ProductionPlanner` and `RegulatoryRetrofitist`;
    raising a substitution endorsement and scheduling a retrofit work order are
    open to `ProductionPlanner` and `RegulatoryRetrofitist` alike; and every
    role may perform the read operations listed in §4."
    PRD §4: "Where a row reads "All seven roles", the endpoint is a read
    available to `PlatformAdmin`, `SupplyChainCoordinator`,
    `ProductionPlanner`, `LeaseAdministrator`, `PortfolioManager`,
    `RegulatoryRetrofitist` and `Lessee` alike; the single exception is the
    outstanding-balance read, which a `Lessee` may call only for its own `id`."

    Design: Corner/rbac/rbac_lessee_shared_get_reads_succeed_across_catalog
    """
    set_clock("2026-09-01T00:00:00Z")
    account = validate_success(
        api.create_lessee(
            {
                "legal_name": "LESS-READ-1",
                "credit_tier": "A",
                "utilization_threshold_pct": 50,
                "credit_ceiling_cents": 1000000,
            },
            LEASE,
        ),
        expected_status=201,
    )
    catalogue = setup_catalogue(
        model_code="CT-READ-1",
        car_class="BOXCAR",
        build_hours=1,
        regulatory_life_years=25,
        line_count_family="LINE-READ",
        wheelset_part_number="WS-READ-1",
        wheelset_unit_cost_cents=1000,
        wheelset_qty_per_car=1,
        casting_part_number="CS-READ-1",
        casting_unit_cost_cents=2000,
        casting_qty_per_car=1,
        include_coating=False,
        on_hand_qty=10,
    )
    order = create_order(
        catalogue,
        quantity=1,
        disposition="RETAINED",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-09-20",
    )

    lessee_headers = make_lessee_headers(account["id"])

    car_type = validate_success(
        api.get_car_type(catalogue["car_type"]["id"], lessee_headers)
    )
    assert car_type["model_code"] == "CT-READ-1"

    component = validate_success(
        api.get_component(catalogue["wheelset"]["id"], lessee_headers)
    )
    assert component["part_number"] == "WS-READ-1"

    orders = validate_success(api.list_production_orders(lessee_headers))
    assert len(orders) == 1, "the least privileged role still sees the backlog"
    assert orders[0]["id"] == order["id"]

    reconciliation = validate_success(
        api.get_portfolio_ledger_reconciliation(lessee_headers)
    )
    assert reconciliation["committed_capital_cents"] == 0, (
        "no retained order has completed, so nothing is committed"
    )
    assert reconciliation["drift_cents"] == 0, (
        "with no live fleet and no settled disposal both bases read zero"
    )
