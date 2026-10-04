"""Request-shape rejections: missing required fields and out-of-range values.

Every write endpoint runs the same request-shape check, so a body that omits a
field the PRD names as part of the write, or that carries an enum member or a
numeric value outside the declared band, is rejected before anything is
persisted.  Each test therefore asserts both the rejection and the absence of
the row it would have written.
"""

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    api_client,
    ApiErrorId,
    create_car_type_payload,
    create_component_payload,
    create_production_order_payload,
    get_success_data,
    set_clock,
    setup_catalogue,
    setup_retained_order_with_fleet_cars,
    setup_retrofit_program_with_car,
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


# ─── Catalogue and backlog ────────────────────────────

def test_car_type_with_unknown_car_class_is_rejected(api):
    """PRD §2.4: "its `car_class` is one of `BOXCAR`, `TANK`, `HOPPER`,
    `FLATCARS` or `GONDOLA`".
    PRD §2.11: "Seventeenth, request shape: required fields must be present,
    enum members must be legal, and numeric ranges must hold — `quantity` at
    least 1, `planned_shop_days` equal to the car type's `build_hours`
    multiplied by `quantity`, and `term_end_date` strictly after
    `term_start_date` — with a breach rejected as `ERR_INVALID_REQUEST`
    (HTTP 400) on every write endpoint."
    PRD §2.11: "The checks are evaluated in this fixed sequence, and the first
    failure short-circuits the rest of the evaluation."

    Because the rejected create short-circuits before any write, the identical
    model code can then be registered cleanly instead of tripping the
    catalogue's uniqueness rule.

    Design: Corner/entities/car_type_invalid_car_class_enum_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    rejected = api_client.create_car_type(
        create_car_type_payload(
            model_code="BOX-100",
            car_class="SUBMARINE",
            build_hours=10,
            regulatory_life_years=25,
            line_count_family="LINE-A",
        ),
        PLANNER,
    )
    validate_error(rejected, ApiErrorId.ERR_INVALID_REQUEST)
    assert rejected.status_code == 400

    retried = api_client.create_car_type(
        create_car_type_payload(
            model_code="BOX-100",
            car_class="BOXCAR",
            build_hours=10,
            regulatory_life_years=25,
            line_count_family="LINE-A",
        ),
        PLANNER,
    )
    assert retried.status_code == 201, (
        "the rejected row must never have been persisted: the same model_code "
        "must not trip the catalogue's uniqueness rule"
    )
    car_type = validate_success(retried, expected_status=201)

    stored = get_success_data(api_client.get_car_type(car_type["id"], ADMIN))
    assert stored["car_class"] == "BOXCAR"
    assert stored["status"] == "ACTIVE"


def test_component_without_lead_time_days_is_rejected(api):
    """PRD §3.1: "a `SupplyChainCoordinator` registers a component with its
    `part_number`, `component_class`, `unit_cost_cents` and `lead_time_days`".
    PRD §2.11: "Seventeenth, request shape: required fields must be present,
    enum members must be legal, and numeric ranges must hold — `quantity` at
    least 1, `planned_shop_days` equal to the car type's `build_hours`
    multiplied by `quantity`, and `term_end_date` strictly after
    `term_start_date` — with a breach rejected as `ERR_INVALID_REQUEST`
    (HTTP 400) on every write endpoint."

    The rejected create leaves no row behind, so the identical part number can
    then be registered cleanly.

    Design: Corner/entities/component_missing_lead_time_days_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    rejected = api_client.create_component(
        {
            "part_number": "WS-200",
            "component_class": "WHEELSET",
            "unit_cost_cents": 200000,
        },
        SUPPLY,
    )
    validate_error(rejected, ApiErrorId.ERR_INVALID_REQUEST)
    assert rejected.status_code == 400

    retried = api_client.create_component(
        create_component_payload(
            part_number="WS-200",
            component_class="WHEELSET",
            unit_cost_cents=200000,
            lead_time_days=10,
        ),
        SUPPLY,
    )
    assert retried.status_code == 201, (
        "the rejected row must never have been persisted: the same part_number "
        "must not trip the component catalogue's uniqueness rule"
    )
    component = validate_success(retried, expected_status=201)
    assert component["lead_time_days"] == 10


def test_production_order_with_zero_quantity_is_rejected(api):
    """PRD §3.1: "The request shape must hold — `quantity` at least 1,
    `priority_rank` at least 1, `planned_shop_days` at least 1 and equal to the
    car type's `build_hours` multiplied by `quantity` — or the request is
    rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §2.11: "Seventeenth, request shape: required fields must be present,
    enum members must be legal, and numeric ranges must hold — `quantity` at
    least 1, `planned_shop_days` equal to the car type's `build_hours`
    multiplied by `quantity`, and `term_end_date` strictly after
    `term_start_date` — with a breach rejected as `ERR_INVALID_REQUEST`
    (HTTP 400) on every write endpoint."

    Design: Corner/entities/production_order_quantity_zero_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(include_coating=False, include_bom=False)

    rejected = api_client.create_production_order(
        create_production_order_payload(
            car_type_id=catalogue["car_type"]["id"],
            quantity=0,
            planned_shop_days=10,
            disposition="SOLD",
            priority_rank=1,
            order_date="2026-09-01",
            required_delivery_date="2026-11-30",
        ),
        PLANNER,
    )
    validate_error(rejected, ApiErrorId.ERR_INVALID_REQUEST)
    assert rejected.status_code == 400

    rows, meta = validate_paginated(api_client.list_production_orders(ADMIN))
    assert meta["total_count"] == 0
    assert rows == []


def test_production_order_without_required_delivery_date_is_rejected(api):
    """PRD §3.1: "The planner supplies `car_type_id`, `quantity`,
    `planned_shop_days`, `disposition`, `priority_rank`, `order_date` and
    `required_delivery_date`".
    PRD §2.11: "Seventeenth, request shape: required fields must be present,
    enum members must be legal, and numeric ranges must hold — `quantity` at
    least 1, `planned_shop_days` equal to the car type's `build_hours`
    multiplied by `quantity`, and `term_end_date` strictly after
    `term_start_date` — with a breach rejected as `ERR_INVALID_REQUEST`
    (HTTP 400) on every write endpoint."

    Design: Corner/entities/production_order_missing_required_delivery_date_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(include_coating=False, include_bom=False)

    rejected = api_client.create_production_order(
        {
            "car_type_id": catalogue["car_type"]["id"],
            "quantity": 1,
            "planned_shop_days": 10,
            "disposition": "SOLD",
            "priority_rank": 1,
            "order_date": "2026-09-01",
        },
        PLANNER,
    )
    validate_error(rejected, ApiErrorId.ERR_INVALID_REQUEST)
    assert rejected.status_code == 400

    rows, meta = validate_paginated(api_client.list_production_orders(ADMIN))
    assert meta["total_count"] == 0


# ─── Placements, returns and shop work ────────────────

def test_car_assignment_without_mileage_allowance_is_rejected(api):
    """PRD §3.6: "The creating write names the `lease_fleet_car_id`, the
    `lease_contract_id` that will govern the placement, the `lessee_id` being
    served, the `start_date`, the `end_date` and the `mileage_allowance`."
    PRD §2.11: "Seventeenth, request shape: required fields must be present,
    enum members must be legal, and numeric ranges must hold — `quantity` at
    least 1, `planned_shop_days` equal to the car type's `build_hours`
    multiplied by `quantity`, and `term_end_date` strictly after
    `term_start_date` — with a breach rejected as `ERR_INVALID_REQUEST`
    (HTTP 400) on every write endpoint."

    The car stays free, so the rejected placement had no partial effect.

    Design: Corner/entities/car_assignment_missing_mileage_allowance_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    world = setup_retained_order_with_fleet_cars(
        catalogue=setup_catalogue(include_coating=False),
        completion_date="2026-09-15",
    )
    advance_clock_to("2026-10-01T00:00:00Z")

    rejected = api_client.create_car_assignment(
        {
            "lease_fleet_car_id": world["car"]["id"],
            "lease_contract_id": world["contract"]["id"],
            "lessee_id": world["lessee"]["id"],
            "start_date": "2026-10-01",
            "end_date": "2026-10-31",
        },
        LEASE,
    )
    validate_error(rejected, ApiErrorId.ERR_INVALID_REQUEST)
    assert rejected.status_code == 400

    rows, meta = validate_paginated(api_client.list_car_assignments(ADMIN))
    assert meta["total_count"] == 0

    car = get_success_data(api_client.get_lease_fleet_car(world["car"]["id"], ADMIN))
    assert car["status"] == "HELD"


def test_retrofit_work_order_without_component_qty_is_rejected(api):
    """PRD §3.8: "A `ProductionPlanner` or a `RegulatoryRetrofitist` raises a
    retrofit work order naming the `retrofit_program_id`, the
    `lease_fleet_car_id`, the `shop_line` the work occupies, the
    `scheduled_start_date` and `scheduled_end_date` of the window, and the
    `component_qty_consumed`."
    PRD §2.11: "Seventeenth, request shape: required fields must be present,
    enum members must be legal, and numeric ranges must hold — `quantity` at
    least 1, `planned_shop_days` equal to the car type's `build_hours`
    multiplied by `quantity`, and `term_end_date` strictly after
    `term_start_date` — with a breach rejected as `ERR_INVALID_REQUEST`
    (HTTP 400) on every write endpoint."

    The covered car is not dragged into the repair queue by the rejected write.

    Design: Corner/entities/retrofit_work_order_missing_component_qty_consumed_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue()
    world = setup_retrofit_program_with_car(
        catalogue=catalogue,
        required_shop_days_per_car=10,
        compliance_deadline_date="2026-12-31",
        completion_date="2026-09-15",
    )

    rejected = api_client.create_retrofit_work_order(
        {
            "retrofit_program_id": world["program"]["id"],
            "lease_fleet_car_id": world["car"]["id"],
            "shop_line": "SHOP-R8A",
            "scheduled_start_date": "2026-10-01",
            "scheduled_end_date": "2026-10-11",
        },
        PLANNER,
    )
    validate_error(rejected, ApiErrorId.ERR_INVALID_REQUEST)
    assert rejected.status_code == 400

    rows, meta = validate_paginated(api_client.list_retrofit_work_orders(ADMIN))
    assert meta["total_count"] == 0

    car = get_success_data(api_client.get_lease_fleet_car(world["car"]["id"], ADMIN))
    assert car["status"] == "HELD"


def test_retrofit_program_without_required_shop_days_is_rejected(api):
    """PRD §3.8: "A `RegulatoryRetrofitist` creates it with a unique
    `mandate_code`, a `description`, the `compliance_deadline_date` by which
    every enrolled car must be retrofitted, the `required_shop_days_per_car`
    the work consumes, and an optional `required_component_id` naming the
    coating or casting kit consumed per retrofit car".
    PRD §2.11: "Seventeenth, request shape: required fields must be present,
    enum members must be legal, and numeric ranges must hold — `quantity` at
    least 1, `planned_shop_days` equal to the car type's `build_hours`
    multiplied by `quantity`, and `term_end_date` strictly after
    `term_start_date` — with a breach rejected as `ERR_INVALID_REQUEST`
    (HTTP 400) on every write endpoint."

    Design: Corner/entities/retrofit_program_missing_required_shop_days_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    rejected = api_client.create_retrofit_program(
        {
            "mandate_code": "MAND-2026-01",
            "description": "Boxcar door retrofit mandate",
            "compliance_deadline_date": "2026-12-31",
        },
        RETROFIT,
    )
    validate_error(rejected, ApiErrorId.ERR_INVALID_REQUEST)
    assert rejected.status_code == 400

    rows, meta = validate_paginated(api_client.list_retrofit_programs(ADMIN))
    assert meta["total_count"] == 0


# ─── Disposal ─────────────────────────────────────────

def test_lease_fleet_sale_without_writeback_liability_is_rejected(api):
    """PRD §3.9: "A `PortfolioManager` sells a car by naming the
    `lease_fleet_car_id`, an optional `lease_contract_id` for the contract that
    had to be terminated first, the `buyer_name`, the `sale_price_cents`, an
    optional `net_book_value_cents`, the `writeback_liability_cents`, and the
    `sale_date`."
    PRD §2.11: "Seventeenth, request shape: required fields must be present,
    enum members must be legal, and numeric ranges must hold — `quantity` at
    least 1, `planned_shop_days` equal to the car type's `build_hours`
    multiplied by `quantity`, and `term_end_date` strictly after
    `term_start_date` — with a breach rejected as `ERR_INVALID_REQUEST`
    (HTTP 400) on every write endpoint."

    Only the two fields the PRD flags as optional may be omitted; the car stays
    held, so the rejected sale had no partial effect.

    Design: Corner/entities/lease_fleet_sale_missing_writeback_liability_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    world = setup_retained_order_with_fleet_cars(
        catalogue=setup_catalogue(include_coating=False),
        completion_date="2026-09-15",
    )
    advance_clock_to("2026-10-01T00:00:00Z")

    rejected = api_client.create_lease_fleet_sale(
        {
            "lease_fleet_car_id": world["car"]["id"],
            "buyer_name": "Rail Trust LLC",
            "sale_price_cents": 1500000,
            "sale_date": "2026-10-01",
        },
        PORTFOLIO,
    )
    validate_error(rejected, ApiErrorId.ERR_INVALID_REQUEST)
    assert rejected.status_code == 400

    rows, meta = validate_paginated(api_client.list_lease_fleet_sales(ADMIN))
    assert meta["total_count"] == 0

    car = get_success_data(api_client.get_lease_fleet_car(world["car"]["id"], ADMIN))
    assert car["status"] == "HELD"
