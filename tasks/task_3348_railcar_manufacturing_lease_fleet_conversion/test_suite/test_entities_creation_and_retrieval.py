"""Creation and retrieval claims across the persisted resource types.

Every test drives the write that mints a resource — either directly, or through
the multi-step sequence that produces it as a side effect — and then reads the
persisted row back, so the assertions are made against stored state rather than
against the create response alone.
"""

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    api_client,
    assert_car_type,
    assert_car_type_component_requirement,
    assert_component_receipt,
    assert_lease_fleet_sale,
    assert_retrofit_work_order,
    assert_substitution_endorsement,
    create_car_type_component_requirement_payload,
    create_car_type_payload,
    create_component_payload,
    create_component_purchase_order_payload,
    create_component_receipt_payload,
    create_order,
    create_production_order_payload,
    create_retrofit_program_car_type_payload,
    create_retrofit_program_payload,
    create_retrofit_work_order_payload,
    create_sale,
    create_substitution_endorsement_payload,
    get_success_data,
    receive_component_stock,
    set_clock,
    setup_catalogue,
    setup_retained_order_with_fleet_cars,
    setup_retrofit_program_with_car,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SUPPLY = TEST_USERS["supply_chain_coordinator_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
RETROFIT = TEST_USERS["regulatory_retrofitist_headers"]

# The order quote for the two-row catalogue the shared preamble builds
# (CS-200 at 2 x 50000 and WS-200 at 4 x 200000, each line plus the 25000-cent
# surcharge and rounded up to whole dollars, then 10 build hours at 45000 with
# a zero change fee): 125000 + 825000 + 450000 = 1400000 cents.
FIXTURE_CATALOGUE_QUOTE_CENTS = 1400000


# ─── Catalogue ────────────────────────────────────────

def test_car_type_creation_returns_created_row_with_status_active(api):
    """PRD §3.1: "A `ProductionPlanner` or a `RegulatoryRetrofitist` registers a
    car type by supplying its `model_code`, `car_class`, `build_hours`,
    `regulatory_life_years` and `line_count_family`".
    PRD §2.4: "A car type's `status` is `ACTIVE` while the type is offered and
    `RETIRED` once it is withdrawn; a newly created type starts `ACTIVE`."
    PRD §4: "A request that creates a new resource answers with 201 Created".
    PRD §2.4: "`version` starts at 1 for a newly created resource".

    Design: Corner/entities/car_type_creation_returns_201_with_computed_status_active
    """
    set_clock("2026-09-01T00:00:00Z")
    created = api_client.create_car_type(
        create_car_type_payload(
            model_code="BOX-100",
            car_class="BOXCAR",
            build_hours=10,
            regulatory_life_years=25,
            line_count_family="LINE-A",
        ),
        PLANNER,
    )
    car_type = validate_success(created, expected_status=201)

    stored = get_success_data(api_client.get_car_type(car_type["id"], ADMIN))
    assert stored["model_code"] == "BOX-100"
    assert stored["car_class"] == "BOXCAR"
    assert stored["build_hours"] == 10
    assert stored["regulatory_life_years"] == 25
    assert stored["line_count_family"] == "LINE-A"
    assert stored["status"] == "ACTIVE"
    assert stored["version"] == 1
    assert_car_type(stored)


def test_car_type_component_requirement_binds_car_type_and_component(api):
    """PRD §2.4: "A `CarTypeComponentRequirement` is the bill-of-material row
    binding one component to one car type. It names the `car_type_id` and the
    `component_id`, and states `qty_per_car`, the units of that component
    consumed per finished car, which is at least 1."
    PRD §2.4: "`reserved_qty` is derived, not stored input: it starts at 0 and
    is recomputed from scratch by the component allocation rule of §3.2 on
    every event that changes commitments".

    Nothing is RELEASED against the new row, so the allocation rule re-derives
    an empty reservation set and the component's stock figures stay untouched.

    Design: Corner/entities/car_type_component_requirement_creation_binds_car_type_and_component
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(include_coating=False, include_bom=False, on_hand_qty=0)

    created = api_client.create_car_type_component_requirement(
        create_car_type_component_requirement_payload(
            car_type_id=catalogue["car_type"]["id"],
            component_id=catalogue["wheelset"]["id"],
            qty_per_car=4,
        ),
        PLANNER,
    )
    row = validate_success(created, expected_status=201)

    stored = get_success_data(
        api_client.get_car_type_component_requirement(row["id"], ADMIN)
    )
    assert stored["car_type_id"] == catalogue["car_type"]["id"]
    assert stored["component_id"] == catalogue["wheelset"]["id"]
    assert stored["qty_per_car"] == 4
    assert_car_type_component_requirement(stored)

    component = get_success_data(
        api_client.get_component(catalogue["wheelset"]["id"], ADMIN)
    )
    assert component["reserved_qty"] == 0
    assert component["on_hand_qty"] == 0


def test_component_creation_returns_created_row_with_zero_stock(api):
    """PRD §2.4: "`on_hand_qty` is system-maintained: it starts at 0 when the
    component is registered unless the caller supplies an opening quantity".
    PRD §2.4: "`reserved_qty` is derived, not stored input: it starts at 0 and
    is recomputed from scratch by the component allocation rule of §3.2 on
    every event that changes commitments, so it is never patched incrementally."
    PRD §4: "A request that creates a new resource answers with 201 Created".

    The create body carries no stock at all, so both quantities are the
    server's own starting figures.

    Design: Corner/entities/component_creation_defaults_on_hand_qty_and_reserved_qty_zero
    """
    set_clock("2026-09-01T00:00:00Z")
    created = api_client.create_component(
        create_component_payload(
            part_number="WS-200",
            component_class="WHEELSET",
            unit_cost_cents=200000,
            lead_time_days=10,
        ),
        SUPPLY,
    )
    component = validate_success(created, expected_status=201)

    stored = get_success_data(api_client.get_component(component["id"], ADMIN))
    assert stored["part_number"] == "WS-200"
    assert stored["component_class"] == "WHEELSET"
    assert stored["unit_cost_cents"] == 200000
    assert stored["lead_time_days"] == 10
    assert stored["on_hand_qty"] == 0
    assert stored["reserved_qty"] == 0


# ─── Backlog ──────────────────────────────────────────

def test_production_order_creation_starts_draft_with_server_quote(api):
    """PRD §3.1: "The order starts in `DRAFT`."
    PRD §3.1: "The component subtotal is the sum of those line amounts, in the
    row order established above. The labor charge is the car type's
    `build_hours` multiplied by the labor rate of 45,000 cents per build hour.
    The unrounded total is the component subtotal plus the labor charge."
    PRD §3.1: "the order's `unit_price_cents` is the unrounded total plus that
    change fee."
    PRD §2.4: "`version` starts at 1 for a newly created resource".

    The create body omits `unit_price_cents` entirely, so the stored figure is
    the server's quote: ceil((2 * 50000 + 25000) / 100) * 100 = 125000 for the
    casting row, ceil((4 * 200000 + 25000) / 100) * 100 = 825000 for the
    wheelset row, plus 10 * 45000 = 450000 of labor, and a zero change fee.

    Design: Corner/entities/production_order_creation_starts_draft_with_forecast_quote
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(include_coating=False)

    created = api_client.create_production_order(
        create_production_order_payload(
            car_type_id=catalogue["car_type"]["id"],
            quantity=1,
            planned_shop_days=10,
            disposition="RETAINED",
            priority_rank=1,
            order_date="2026-09-01",
            required_delivery_date="2026-11-30",
        ),
        PLANNER,
    )
    order = validate_success(created, expected_status=201)

    stored = get_success_data(api_client.get_production_order(order["id"], ADMIN))
    assert stored["status"] == "DRAFT"
    assert stored["unit_price_cents"] == FIXTURE_CATALOGUE_QUOTE_CENTS
    assert stored["quantity"] == 1
    assert stored["completed_qty"] == 0
    assert stored["planned_shop_days"] == 10
    assert stored["disposition"] == "RETAINED"
    assert stored["priority_rank"] == 1
    assert stored["version"] == 1


def test_substitution_endorsement_creation_starts_pending(api):
    """PRD §3.3: "A successful create starts the endorsement in `PENDING`,
    supersedes any earlier `PENDING` endorsement for the same original
    component on that order, and increments the production order's `version`."
    PRD §3.3: "The write must also carry `expected_production_order_version`
    holding the client's last observed `version` of the production order".
    PRD §3.3: "the `decides_material` flag, which is true when the substitution
    can change the material composition of a car because the substitute's
    component class differs from the original's."
    PRD §2.4: "`version` starts at 1 for a newly created resource".

    Design: Corner/entities/substitution_endorsement_creation_starts_pending
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(include_coating=False)
    order = create_order(
        catalogue,
        quantity=1,
        disposition="SOLD",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-11-30",
    )

    created = api_client.create_substitution_endorsement(
        create_substitution_endorsement_payload(
            production_order_id=order["id"],
            original_component_id=catalogue["wheelset"]["id"],
            substitute_component_id=catalogue["casting"]["id"],
            substitute_qty_per_car=2,
            decides_material=True,
            expected_production_order_version=order["version"],
        ),
        PLANNER,
    )
    endorsement = validate_success(created, expected_status=201)

    stored = get_success_data(
        api_client.get_substitution_endorsement(endorsement["id"], ADMIN)
    )
    assert stored["status"] == "PENDING"
    assert stored["decides_material"] is True
    assert stored["substitute_qty_per_car"] == 2
    assert stored["production_order_id"] == order["id"]
    assert stored["original_component_id"] == catalogue["wheelset"]["id"]
    assert stored["version"] == 1
    assert_substitution_endorsement(stored)

    parent = get_success_data(api_client.get_production_order(order["id"], ADMIN))
    assert parent["version"] == order["version"] + 1
    assert parent["status"] == "DRAFT"


# ─── Fleet cars and sales ─────────────────────────────

def test_retained_order_completion_creates_held_fleet_car(api):
    """PRD §3.4: "On the retained branch, completion creates one fleet car per
    car built, each starting in `HELD` with its `production_order_id` pointing
    at the producing order, its `acquisition_cost_cents` equal to the order's
    `unit_price_cents`, and its `built_date` set to the completion date".
    PRD §2.8: "A lease fleet car's `regulatory_life_end_date` is derived from
    its build date and its car type: it is the car's `built_date` advanced by
    the car type's `regulatory_life_years`."
    PRD §2.10: "A fleet car's `lease_contract_id` is stamped when a placement is
    created against a contract and cleared when the car returns to the fleet
    through the repair queue or is sold".

    Design: Corner/entities/lease_fleet_car_created_by_retained_order_completion_starts_held
    """
    set_clock("2026-09-01T00:00:00Z")
    world = setup_retained_order_with_fleet_cars(
        car_count=1,
        catalogue=setup_catalogue(include_coating=False),
        completion_date="2026-09-15",
    )

    order = get_success_data(api_client.get_production_order(world["order"]["id"], ADMIN))
    car = get_success_data(api_client.get_lease_fleet_car(world["car"]["id"], ADMIN))

    assert order["status"] == "COMPLETED"
    assert order["completed_qty"] == 1
    assert car["status"] == "HELD"
    assert car["production_order_id"] == order["id"]
    assert car["acquisition_cost_cents"] == order["unit_price_cents"]
    assert car["acquisition_cost_cents"] == FIXTURE_CATALOGUE_QUOTE_CENTS
    assert car["built_date"] == "2026-09-15"
    assert car["regulatory_life_end_date"] == "2051-09-15"
    assert car["accumulated_mileage"] == 0
    assert car["retrofit_required"] is False
    assert car["lease_contract_id"] is None


def test_lease_fleet_sale_creation_starts_pending_settlement_with_gain(api):
    """PRD §3.9: "The sale itself starts in `PENDING_SETTLEMENT`."
    PRD §3.9: "The book value is the car's `acquisition_cost_cents` minus that
    age multiplied by the daily depreciation of 2,500 cents. The sale's
    `gain_loss_cents` is the `sale_price_cents` minus that book value minus the
    sale's `writeback_liability_cents`".
    PRD §3.9: "On success the car moves to `SOLD`, its `lease_contract_id` is
    cleared, and the sale's `net_book_value_cents`, `writeback_liability_cents`
    and `gain_loss_cents` are computed by the rule below."

    The car was built on 2026-09-15 and sold on 2026-10-01, an age of 16 days,
    so its book value is 1400000 - 16 * 2500 = 1360000 and the gain on a
    1500000-cent sale with no writeback is 140000.

    Design: Corner/entities/lease_fleet_sale_creation_starts_pending_settlement_with_computed_gain
    """
    set_clock("2026-09-01T00:00:00Z")
    world = setup_retained_order_with_fleet_cars(
        car_count=1,
        catalogue=setup_catalogue(include_coating=False),
        completion_date="2026-09-15",
    )
    car = get_success_data(api_client.get_lease_fleet_car(world["car"]["id"], ADMIN))
    assert car["acquisition_cost_cents"] == FIXTURE_CATALOGUE_QUOTE_CENTS

    advance_clock_to("2026-10-01T00:00:00Z")
    sale = create_sale(
        car,
        sale_price_cents=1500000,
        sale_date="2026-10-01",
        writeback_liability_cents=0,
        buyer_name="Rail Trust LLC",
    )

    stored = get_success_data(api_client.get_lease_fleet_sale(sale["id"], ADMIN))
    assert stored["status"] == "PENDING_SETTLEMENT"
    assert stored["gain_loss_cents"] == 140000
    assert stored["net_book_value_cents"] == 1360000
    assert stored["sale_price_cents"] == 1500000
    assert stored["writeback_liability_cents"] == 0
    assert stored["lease_fleet_car_id"] == car["id"]
    assert_lease_fleet_sale(stored)

    sold = get_success_data(api_client.get_lease_fleet_car(car["id"], ADMIN))
    assert sold["status"] == "SOLD"
    assert sold["lease_contract_id"] is None


# ─── Retrofit ─────────────────────────────────────────

def test_retrofit_program_car_type_creation_covers_car_type(api):
    """PRD §3.8: "Coverage is then declared by adding `RetrofitProgramCarType`
    rows, each naming the `retrofit_program_id` and the `car_type_id` it
    covers; a program covers nothing until at least one such row exists."
    PRD §3.8: "The program starts in `PLANNED` with a `program_cost_cents` of
    0."  PRD §3.8: "On success the program becomes `IN_PROGRESS`, the
    `retrofit_required` flag is set to true on every fleet car of a covered car
    type whose status is `HELD` or `UNDER_REPAIR`".

    Design: Corner/entities/retrofit_program_car_type_creation_covers_car_type
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(
        model_code="TANK-700",
        car_class="TANK",
        build_hours=12,
        regulatory_life_years=30,
        line_count_family="LINE-B",
    )
    program = validate_success(
        api_client.create_retrofit_program(
            create_retrofit_program_payload(
                mandate_code="MAND-2026-01",
                description="Tank car valve retrofit mandate",
                compliance_deadline_date="2026-12-31",
                required_shop_days_per_car=10,
            ),
            RETROFIT,
        ),
        expected_status=201,
    )

    created = api_client.create_retrofit_program_car_type(
        create_retrofit_program_car_type_payload(
            retrofit_program_id=program["id"],
            car_type_id=catalogue["car_type"]["id"],
        ),
        RETROFIT,
    )
    coverage = validate_success(created, expected_status=201)

    stored = get_success_data(
        api_client.get_retrofit_program_car_type(coverage["id"], ADMIN)
    )
    assert stored["retrofit_program_id"] == program["id"]
    assert stored["car_type_id"] == catalogue["car_type"]["id"]

    after = get_success_data(api_client.get_retrofit_program(program["id"], ADMIN))
    assert after["status"] == "PLANNED"
    assert after["program_cost_cents"] == 0


def test_retrofit_work_order_creation_starts_scheduled_with_shop_days(api):
    """PRD §3.8: "A successful scheduling write moves the car to
    `UNDER_REPAIR`, sets its `retrofit_required` flag to true, and increments
    the car's `version`; the work order itself starts in `SCHEDULED`."
    PRD §2.8: "A work order's derived `shop_days` — the difference between its
    scheduled end and start — must equal the program's
    `required_shop_days_per_car`, so the shop occupancy a mandate demands and
    the occupancy a work order books cannot diverge."
    PRD §4: "A request that creates a new resource answers with 201 Created".

    The half-open window [2026-10-01, 2026-10-11) is ten days wide, which is
    the program's demanded occupancy.

    Design: Corner/entities/retrofit_work_order_creation_starts_scheduled_with_computed_shop_days
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue()
    world = setup_retrofit_program_with_car(
        catalogue=catalogue,
        required_shop_days_per_car=10,
        compliance_deadline_date="2026-12-31",
        required_component_id=catalogue["coating"]["id"],
        completion_date="2026-09-15",
    )

    created = api_client.create_retrofit_work_order(
        create_retrofit_work_order_payload(
            retrofit_program_id=world["program"]["id"],
            lease_fleet_car_id=world["car"]["id"],
            shop_line="SHOP-R8A",
            scheduled_start_date="2026-10-01",
            scheduled_end_date="2026-10-11",
            component_qty_consumed=2,
        ),
        PLANNER,
    )
    work_order = validate_success(created, expected_status=201)

    stored = get_success_data(api_client.get_retrofit_work_order(work_order["id"], ADMIN))
    assert stored["status"] == "SCHEDULED"
    assert stored["shop_days"] == 10
    assert stored["shop_line"] == "SHOP-R8A"
    assert stored["scheduled_start_date"] == "2026-10-01"
    assert stored["scheduled_end_date"] == "2026-10-11"
    assert stored["component_qty_consumed"] == 2
    assert stored["version"] == 1
    assert_retrofit_work_order(stored)

    car = get_success_data(api_client.get_lease_fleet_car(world["car"]["id"], ADMIN))
    assert car["status"] == "UNDER_REPAIR"


# ─── Purchasing ───────────────────────────────────────

def test_component_purchase_order_creation_starts_placed(api):
    """PRD §3.2: "A `SupplyChainCoordinator` raises a purchase order naming the
    `component_id`, the `qty_ordered`, the agreed `unit_cost_cents`, the
    `order_date` and the `expected_receipt_date`; the purchase starts in
    `PLACED`."
    PRD §3.2: "Stock moves only on receipt."
    PRD §2.4: "`on_hand_qty` is system-maintained: it starts at 0 when the
    component is registered unless the caller supplies an opening quantity, is
    increased only by a receipt".

    The receipt date is the order date plus the part's ten-day supplier lead
    time, and raising the purchase moves no stock.

    Design: Corner/entities/component_purchase_order_creation_starts_placed
    """
    set_clock("2026-09-01T00:00:00Z")
    component = validate_success(
        api_client.create_component(
            create_component_payload(
                part_number="WS-200",
                component_class="WHEELSET",
                unit_cost_cents=200000,
                lead_time_days=10,
            ),
            SUPPLY,
        ),
        expected_status=201,
    )

    created = api_client.create_component_purchase_order(
        create_component_purchase_order_payload(
            component_id=component["id"],
            qty_ordered=4,
            unit_cost_cents=200000,
            order_date="2026-09-01",
            expected_receipt_date="2026-09-11",
        ),
        SUPPLY,
    )
    purchase_order = validate_success(created, expected_status=201)

    stored = get_success_data(
        api_client.get_component_purchase_order(purchase_order["id"], ADMIN)
    )
    assert stored["status"] == "PLACED"
    assert stored["qty_ordered"] == 4
    assert stored["unit_cost_cents"] == 200000
    assert stored["order_date"] == "2026-09-01"
    assert stored["expected_receipt_date"] == "2026-09-11"
    assert stored["component_id"] == component["id"]
    assert stored["version"] == 1

    untouched = get_success_data(api_client.get_component(component["id"], ADMIN))
    assert untouched["on_hand_qty"] == 0


def test_component_receipt_booking_defers_stock_until_receive(api):
    """PRD §3.2: "booking the receipt alone does not change stock. Applying it
    — the receiving action on that receipt — is what moves the goods".
    PRD §3.2: "On success the purchase order becomes `RECEIVED`, the
    component's `on_hand_qty` is increased by `qty_received`, and
    `reserved_qty` and `shortfall_qty` are recomputed by the allocation rule
    above."
    PRD §2.4: "`reserved_qty` is derived, not stored input: it starts at 0".

    Design: Corner/entities/component_receipt_creation_books_without_moving_stock_until_receive
    """
    set_clock("2026-09-01T00:00:00Z")
    component = validate_success(
        api_client.create_component(
            create_component_payload(
                part_number="WS-200",
                component_class="WHEELSET",
                unit_cost_cents=200000,
                lead_time_days=10,
            ),
            SUPPLY,
        ),
        expected_status=201,
    )
    confirmed = receive_component_stock(component, 4, apply_receipt=False)
    purchase_order_id = confirmed["purchase_order"]["id"]
    assert confirmed["purchase_order"]["status"] == "CONFIRMED"

    created = api_client.create_component_receipt(
        create_component_receipt_payload(
            component_purchase_order_id=purchase_order_id,
            component_id=component["id"],
            qty_received=4,
            receipt_date="2026-09-11",
        ),
        SUPPLY,
    )
    receipt = validate_success(created, expected_status=201)
    stored_receipt = get_success_data(api_client.get_component_receipt(receipt["id"], ADMIN))
    assert stored_receipt["qty_received"] == 4
    assert stored_receipt["receipt_date"] == "2026-09-11"
    assert stored_receipt["component_id"] == component["id"]
    assert stored_receipt["component_purchase_order_id"] == purchase_order_id
    assert_component_receipt(stored_receipt)

    booked_only = get_success_data(api_client.get_component(component["id"], ADMIN))
    assert booked_only["on_hand_qty"] == 0
    assert booked_only["reserved_qty"] == 0

    applied = api_client.receive_component_receipt(receipt["id"], SUPPLY)
    validate_success(applied)

    after = get_success_data(api_client.get_component(component["id"], ADMIN))
    assert after["on_hand_qty"] == 4
    assert after["reserved_qty"] == 0
    parent = get_success_data(
        api_client.get_component_purchase_order(purchase_order_id, ADMIN)
    )
    assert parent["status"] == "RECEIVED"


def test_component_receipt_retrieval_returns_booked_fields(api):
    """PRD §3.2: "A coordinator books a `ComponentReceipt` against the purchase
    with the `component_purchase_order_id`, the `component_id`, the
    `qty_received` and the `receipt_date`".
    PRD §4: "a request that returns a single resource answers with 200 OK and
    the resource object in `data`."

    Design: Corner/entities/component_receipt_retrieval_returns_booked_fields
    """
    set_clock("2026-09-01T00:00:00Z")
    component = validate_success(
        api_client.create_component(
            create_component_payload(
                part_number="WS-200",
                component_class="WHEELSET",
                unit_cost_cents=200000,
                lead_time_days=10,
            ),
            SUPPLY,
        ),
        expected_status=201,
    )
    confirmed = receive_component_stock(component, 4, apply_receipt=False)
    purchase_order_id = confirmed["purchase_order"]["id"]

    receipt = validate_success(
        api_client.create_component_receipt(
            create_component_receipt_payload(
                component_purchase_order_id=purchase_order_id,
                component_id=component["id"],
                qty_received=4,
                receipt_date="2026-09-11",
            ),
            SUPPLY,
        ),
        expected_status=201,
    )

    fetched = get_success_data(api_client.get_component_receipt(receipt["id"], ADMIN))
    assert fetched["id"] == receipt["id"]
    assert fetched["qty_received"] == 4
    assert fetched["receipt_date"] == "2026-09-11"
    assert fetched["component_id"] == component["id"]
    assert fetched["component_purchase_order_id"] == purchase_order_id
    assert_component_receipt(fetched)
