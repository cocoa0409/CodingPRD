"""Server-side defaults, computed fields and system-maintained fields.

Two families live here.  The first asserts the starting figures a freshly
created resource carries when the client says nothing about them.  The second
asserts that a client-supplied value for a field the server derives is ignored
and the server's own figure is what gets stored.
"""

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    api_client,
    assert_car_assignment,
    assert_car_return,
    assert_lease_contract,
    assert_lessee,
    assert_lessee_outstanding_balance,
    assert_retrofit_program,
    create_assignment,
    create_car_assignment_payload,
    create_car_type_payload,
    create_component_payload,
    create_lease_contract_payload,
    create_lessee_payload,
    create_production_order_payload,
    create_return,
    create_retrofit_program_payload,
    get_success_data,
    make_lessee_headers,
    set_clock,
    setup_catalogue,
    setup_retained_order_with_fleet_cars,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SUPPLY = TEST_USERS["supply_chain_coordinator_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
LEASE = TEST_USERS["lease_administrator_headers"]
RETROFIT = TEST_USERS["regulatory_retrofitist_headers"]


# ─── Commercial defaults ──────────────────────────────

def test_lease_contract_creation_defaults_status_sequence_and_capital(api):
    """PRD §3.5: "A drafted contract starts in `DRAFT` with an `amendment_seq`
    of 0 and a `capital_allocation_cents` of 0."
    PRD §2.9: "A contract's `capital_allocation_cents` records the capital that
    has moved into the lease fleet for `RETAINED` cars under that contract; it
    starts at 0 and is re-derived by the allocation rule of §3.4 rather than
    adjusted incrementally."
    PRD §2.4: "`version` starts at 1 for a newly created resource".

    Design: Corner/entities/lease_contract_creation_defaults_amendment_seq_and_capital_zero
    """
    set_clock("2026-09-01T00:00:00Z")
    lessee = validate_success(
        api_client.create_lessee(
            create_lessee_payload(
                legal_name="Acme Leasing LLC",
                credit_tier="A",
                utilization_threshold_pct=50,
                credit_ceiling_cents=50000000,
            ),
            LEASE,
        ),
        expected_status=201,
    )

    created = api_client.create_lease_contract(
        create_lease_contract_payload(
            lessee_id=lessee["id"],
            lease_type="FULL_SERVICE",
            per_diem_rate_cents=25000,
            liability_bearer="LESSOR",
            term_start_date="2026-09-01",
            term_end_date="2027-09-01",
            fleet_car_cap=10,
        ),
        LEASE,
    )
    contract = validate_success(created, expected_status=201)

    stored = get_success_data(api_client.get_lease_contract(contract["id"], ADMIN))
    assert stored["status"] == "DRAFT"
    assert stored["amendment_seq"] == 0
    assert stored["capital_allocation_cents"] == 0
    assert stored["per_diem_rate_cents"] == 25000
    assert stored["liability_bearer"] == "LESSOR"
    assert stored["lease_type"] == "FULL_SERVICE"
    assert stored["version"] == 1
    assert_lease_contract(stored)


def test_lessee_creation_defaults_active_status_and_zero_balance(api):
    """PRD §3.5: "The account starts `ACTIVE` with an
    `outstanding_balance_cents` of 0."
    PRD §3.9: "The outstanding-balance read exposes the components as well: it
    reports `outstanding_balance_cents`, `settled_charges_cents` and
    `credits_applied_cents`, and a lessee may read it only for its own `id`."
    PRD §2.1: "A `Lessee` may read its own contracts, placements, cars and
    ledger balance; the outstanding-balance read is available to a lessee only
    for its own `id`."

    Nothing has charged or credited the account, so every ledger component is
    still zero.

    Design: Corner/entities/lessee_creation_defaults_outstanding_balance_zero_and_active
    """
    set_clock("2026-09-01T00:00:00Z")
    created = api_client.create_lessee(
        create_lessee_payload(
            legal_name="Acme Leasing LLC",
            credit_tier="A",
            utilization_threshold_pct=50,
            credit_ceiling_cents=50000000,
        ),
        LEASE,
    )
    lessee = validate_success(created, expected_status=201)

    assert lessee["status"] == "ACTIVE"
    assert lessee["outstanding_balance_cents"] == 0
    assert lessee["credit_tier"] == "A"
    assert lessee["utilization_threshold_pct"] == 50
    assert_lessee(lessee)

    balance = get_success_data(
        api_client.get_lessee_outstanding_balance(
            lessee["id"], make_lessee_headers(lessee["id"])
        )
    )
    assert balance["outstanding_balance_cents"] == 0
    assert balance["settled_charges_cents"] == 0
    assert balance["credits_applied_cents"] == 0
    assert_lessee_outstanding_balance(balance)


def test_retrofit_program_creation_defaults_status_planned_and_zero_cost(api):
    """PRD §3.8: "The program starts in `PLANNED` with a `program_cost_cents`
    of 0."
    PRD §3.8: "Program cost is an aggregation over completed shop work, and it
    is derived on two bases. On the scheduled estimate used while the program
    is `PLANNED` or `IN_PROGRESS`, every work order of the program that is not
    in `CANCELLED` status contributes."

    The program exists before any work order, so the aggregation contributes
    nothing even though the mandate already declares its shop days and kit.

    Design: Corner/entities/retrofit_program_creation_defaults_planned_and_cost_zero
    """
    set_clock("2026-09-01T00:00:00Z")
    coating = validate_success(
        api_client.create_component(
            create_component_payload(
                part_number="CT-400",
                component_class="COATING",
                unit_cost_cents=50000,
                lead_time_days=90,
            ),
            SUPPLY,
        ),
        expected_status=201,
    )

    created = api_client.create_retrofit_program(
        create_retrofit_program_payload(
            mandate_code="MAND-2026-01",
            description="Tank car valve retrofit mandate",
            compliance_deadline_date="2026-12-31",
            required_shop_days_per_car=10,
            required_component_id=coating["id"],
        ),
        RETROFIT,
    )
    program = validate_success(created, expected_status=201)

    stored = get_success_data(api_client.get_retrofit_program(program["id"], ADMIN))
    assert stored["status"] == "PLANNED"
    assert stored["program_cost_cents"] == 0
    assert stored["required_shop_days_per_car"] == 10
    assert stored["mandate_code"] == "MAND-2026-01"
    assert stored["compliance_deadline_date"] == "2026-12-31"
    assert stored["required_component_id"] == coating["id"]
    assert stored["version"] == 1
    assert_retrofit_program(stored)


# ─── Placement and return defaults ────────────────────

def test_assignment_ignores_client_rate_and_snapshots_contract_rate(api):
    """PRD §3.6: "the placement's `per_diem_rate_cents` is snapshotted from the
    contract's rate at that moment. That snapshot matters: every later accrual
    reads the rate stored on the placement, never the contract's current rate".
    PRD §3.6: "The placement starts in `ACTIVE` with `mileage_used` at 0".
    PRD §3.6: "The accrual window ends at the placement's `end_date` when the
    placement is `COMPLETED` or `REASSIGNED`, and at the logical clock's
    current date otherwise."

    The create body claims a one-cent daily rate; the contract says 25000, and
    that is what is stored.  The placement opens on the clock date, so zero
    days have elapsed and the accrual is zero.

    Design: Corner/entities/car_assignment_per_diem_rate_input_ignored_snapshot_stored
    """
    set_clock("2026-09-01T00:00:00Z")
    world = setup_retained_order_with_fleet_cars(
        catalogue=setup_catalogue(include_coating=False),
        completion_date="2026-09-15",
        per_diem_rate_cents=25000,
    )
    advance_clock_to("2026-10-01T00:00:00Z")

    created = api_client.create_car_assignment(
        create_car_assignment_payload(
            lease_fleet_car_id=world["car"]["id"],
            lease_contract_id=world["contract"]["id"],
            lessee_id=world["lessee"]["id"],
            start_date="2026-10-01",
            end_date="2026-10-31",
            mileage_allowance=1000,
            per_diem_rate_cents=1,
        ),
        LEASE,
    )
    assignment = validate_success(created, expected_status=201)

    stored = get_success_data(api_client.get_car_assignment(assignment["id"], ADMIN))
    assert stored["per_diem_rate_cents"] == 25000
    assert stored["per_diem_rate_cents"] != 1
    assert stored["status"] == "ACTIVE"
    assert stored["mileage_allowance"] == 1000
    assert stored["mileage_used"] == 0
    assert stored["per_diem_accrued_cents"] == 0
    assert stored["mileage_charge_cents"] == 0
    assert stored["maintenance_cost_cents"] == 0
    assert_car_assignment(stored)

    car = get_success_data(api_client.get_lease_fleet_car(world["car"]["id"], ADMIN))
    assert car["status"] == "ASSIGNED"
    assert car["lease_contract_id"] == world["contract"]["id"]


def test_car_return_creation_defaults_pending_settlement_and_zero_overage(api):
    """PRD §3.7: "The return record itself starts with a `settlement_status` of
    `PENDING`."
    PRD §3.7: "The number of days in the placement is the placement's `end_date`
    minus its `start_date`. That figure is divided by thirty and rounded up to a
    whole number to give the number of allowance blocks; the included miles are
    those blocks multiplied by the placement's `mileage_allowance`."
    PRD §2.6: "an overage of exactly zero produces a charge of exactly zero".
    PRD §3.7: "grade `A` maps to 0 cents".
    PRD §3.7: "On success the placement becomes `COMPLETED`, the parent car
    moves to `UNDER_REPAIR`, and the car's `accumulated_mileage` is recomputed
    as the total miles recorded across every placement and return for that car."

    The placement runs the whole of October, one thirty-day block grants the
    full 1000-mile allowance, and the car ran exactly 1000 miles.

    Design: Corner/entities/car_return_creation_defaults_settlement_pending_and_zero_overage
    """
    set_clock("2026-09-01T00:00:00Z")
    world = setup_retained_order_with_fleet_cars(
        catalogue=setup_catalogue(include_coating=False),
        completion_date="2026-09-15",
        per_diem_rate_cents=25000,
    )
    advance_clock_to("2026-10-01T00:00:00Z")
    assignment = create_assignment(
        world["car"],
        world["contract"],
        world["lessee"],
        start_date="2026-10-01",
        end_date="2026-10-31",
        mileage_allowance=1000,
    )

    car_return = create_return(
        world["car"],
        assignment,
        return_date="2026-10-31",
        mileage_since_last=1000,
        condition_grade="A",
    )

    stored = get_success_data(api_client.get_car_return(car_return["id"], ADMIN))
    assert stored["settlement_status"] == "PENDING"
    assert stored["mileage_overage_cents"] == 0
    assert stored["maintenance_parts_cents"] == 0
    assert stored["condition_grade"] == "A"
    assert stored["mileage_since_last"] == 1000
    assert_car_return(stored)

    closed = get_success_data(api_client.get_car_assignment(assignment["id"], ADMIN))
    assert closed["status"] == "COMPLETED"
    assert closed["mileage_charge_cents"] == 0

    car = get_success_data(api_client.get_lease_fleet_car(world["car"]["id"], ADMIN))
    assert car["status"] == "UNDER_REPAIR"
    assert car["accumulated_mileage"] == 1000


# ─── Client-supplied values the server overrides ──────

def test_car_type_status_supplied_at_creation_is_ignored(api):
    """PRD §2.4: "A car type's `status` is `ACTIVE` while the type is offered
    and `RETIRED` once it is withdrawn; a newly created type starts `ACTIVE`."

    The create body smuggles a `RETIRED` status in; the stored row is `ACTIVE`,
    because the status a new type starts in is the server's own choice.

    Design: Corner/entities/car_type_status_input_ignored_stored_active
    """
    set_clock("2026-09-01T00:00:00Z")
    created = api_client.create_car_type(
        create_car_type_payload(
            model_code="BOX-100",
            car_class="BOXCAR",
            build_hours=10,
            regulatory_life_years=25,
            line_count_family="LINE-A",
            status="RETIRED",
        ),
        PLANNER,
    )
    car_type = validate_success(created, expected_status=201)

    stored = get_success_data(api_client.get_car_type(car_type["id"], ADMIN))
    assert stored["status"] == "ACTIVE"
    assert stored["status"] != "RETIRED"
    assert stored["model_code"] == "BOX-100"


def test_production_order_status_supplied_at_creation_is_ignored(api):
    """PRD §3.1: "The order starts in `DRAFT`."
    PRD §3.4: "It is legal only from `IN_PRODUCTION`, and it completes the
    remaining cars in one step: the `completed_qty` supplied on the request,
    plus the quantity already finished, must equal the order's `quantity`."
    PRD §2.4: "`version` starts at 1 for a newly created resource".

    The create body claims `COMPLETED` with five cars finished; the stored
    order is `DRAFT` with nothing completed, because completion is the only
    path that moves either field.

    Design: Corner/entities/production_order_status_input_ignored_stored_draft
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(include_coating=False, include_bom=False)

    created = api_client.create_production_order(
        create_production_order_payload(
            car_type_id=catalogue["car_type"]["id"],
            quantity=1,
            planned_shop_days=10,
            disposition="SOLD",
            priority_rank=1,
            order_date="2026-09-01",
            required_delivery_date="2026-11-30",
            status="COMPLETED",
            completed_qty=5,
        ),
        PLANNER,
    )
    order = validate_success(created, expected_status=201)

    stored = get_success_data(api_client.get_production_order(order["id"], ADMIN))
    assert stored["status"] == "DRAFT"
    assert stored["completed_qty"] == 0
    assert stored["quantity"] == 1
    assert stored["version"] == 1
