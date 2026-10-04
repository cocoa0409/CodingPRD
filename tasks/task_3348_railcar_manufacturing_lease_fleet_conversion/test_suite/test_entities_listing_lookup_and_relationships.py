"""Listing, missing-resource lookup and body foreign-key resolution.

Three concerns share one shape: the server must resolve every identifier it is
handed — a path segment or a body foreign key — and must account for the rows a
list actually matched rather than the page it happens to be returning.
"""

from test_helpers import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    ApiErrorId,
    create_car_assignment_payload,
    create_component_payload,
    create_component_purchase_order_payload,
    create_lessee_and_contract,
    create_many_orders,
    create_order,
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


# ─── Missing resources ────────────────────────────────

def test_missing_production_order_read_returns_not_found(api):
    """PRD §2.4: "The server resolves each templated identifier in the order it
    appears in the path and stops at the first one that does not correspond to
    a persisted row, returning `ERR_NOT_FOUND` (HTTP 404)."
    PRD §2.11: "Third, path resolution: every templated resource identifier in
    the path must resolve to a persisted row, validated from left to right, and
    a failure is rejected with `ERR_NOT_FOUND` (HTTP 404)".

    A real order is read in the same database, so the miss is the identifier
    and not the route.

    Design: Corner/entities/production_order_not_found_returns_404
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(include_coating=False, include_bom=False)
    order = create_order(
        catalogue,
        quantity=1,
        disposition="SOLD",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-11-30",
    )

    missing = api_client.get_production_order(NON_EXISTENT_UUID, ADMIN)
    validate_error(missing, ApiErrorId.ERR_NOT_FOUND)
    assert missing.status_code == 404

    found = api_client.get_production_order(order["id"], ADMIN)
    assert found.status_code == 200
    stored = validate_success(found)
    assert stored["id"] == order["id"]
    assert stored["status"] == "DRAFT"


def test_missing_lease_fleet_car_read_returns_not_found(api):
    """PRD §2.4: "The server resolves each templated identifier in the order it
    appears in the path and stops at the first one that does not correspond to
    a persisted row, returning `ERR_NOT_FOUND` (HTTP 404)."
    PRD §2.11: "Third, path resolution: every templated resource identifier in
    the path must resolve to a persisted row, validated from left to right, and
    a failure is rejected with `ERR_NOT_FOUND` (HTTP 404)".

    Design: Corner/entities/lease_fleet_car_not_found_returns_404
    """
    set_clock("2026-09-01T00:00:00Z")
    world = setup_retained_order_with_fleet_cars(
        catalogue=setup_catalogue(include_coating=False),
        completion_date="2026-09-15",
    )

    missing = api_client.get_lease_fleet_car(NON_EXISTENT_UUID, ADMIN)
    validate_error(missing, ApiErrorId.ERR_NOT_FOUND)
    assert missing.status_code == 404

    found = api_client.get_lease_fleet_car(world["car"]["id"], ADMIN)
    assert found.status_code == 200
    stored = validate_success(found)
    assert stored["id"] == world["car"]["id"]
    assert stored["status"] == "HELD"


# ─── Listing and pagination ───────────────────────────

def test_production_order_listing_pagination_defaults_and_has_more(api):
    """PRD §2.3: "Every list endpoint accepts `limit` and `offset` as optional
    query parameters. `limit` defaults to 10, and its smallest permitted value
    is 1 and its largest is 100".
    PRD §2.3: "The `meta` object of a list response carries all four pagination
    fields: `limit`, `offset`, `total_count` and `has_more`. `total_count` is
    the number of records matching the filter across the whole result set, not
    the number in the current page, and `has_more` is true exactly when
    `offset` plus the number of records returned is less than `total_count`."
    PRD §2.3: "`offset` defaults to 0 and counts the number of matching records
    to skip before the first returned record."

    Twelve orders are stored, so the default page stops at ten and still
    reports twelve matches, while the largest permitted page returns the whole
    set.

    Design: Corner/entities/production_order_list_pagination_defaults_and_has_more
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(include_coating=False)
    create_many_orders(catalogue, 12, disposition="SOLD")

    rows, meta = validate_paginated(api_client.list_production_orders(ADMIN))
    assert len(rows) == DEFAULT_PAGE_LIMIT == 10
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 12
    assert meta["has_more"] is True

    rows, meta = validate_paginated(
        api_client.list_production_orders(ADMIN, {"limit": MAX_PAGE_LIMIT, "offset": 0})
    )
    assert len(rows) == 12
    assert meta["total_count"] == 12
    assert meta["has_more"] is False

    rows, meta = validate_paginated(
        api_client.list_production_orders(ADMIN, {"offset": 10})
    )
    assert len(rows) == 2
    assert meta["total_count"] == 12
    assert meta["has_more"] is False


def test_purchase_order_listing_pagination_and_status_filter(api):
    """PRD §2.3: "`total_count` is the number of records matching the filter
    across the whole result set, not the number in the current page, and
    `has_more` is true exactly when `offset` plus the number of records
    returned is less than `total_count`."
    PRD §2.3: "List endpoints accept their documented filters alongside these
    two parameters; filters that name a status, a car type, a component, a
    contract, a car, a production order, a purchase order, a settlement status,
    a shop line, a program or a superseding order narrow the result set before
    pagination is applied."
    PRD §4: "GET | `/api/v1/component-purchase-orders` | List purchase orders,
    filterable by status or component."

    Design: Corner/entities/component_purchase_order_list_pagination_and_status_filter
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
    for quantity in (4, 6, 8):
        validate_success(
            api_client.create_component_purchase_order(
                create_component_purchase_order_payload(
                    component_id=component["id"],
                    qty_ordered=quantity,
                    unit_cost_cents=200000,
                    order_date="2026-09-01",
                    expected_receipt_date="2026-09-11",
                ),
                SUPPLY,
            ),
            expected_status=201,
        )

    rows, meta = validate_paginated(api_client.list_component_purchase_orders(ADMIN))
    assert len(rows) == 3
    assert meta["total_count"] == 3
    assert meta["has_more"] is False

    rows, meta = validate_paginated(
        api_client.list_component_purchase_orders(ADMIN, {"limit": 1, "offset": 0})
    )
    assert len(rows) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    rows, meta = validate_paginated(
        api_client.list_component_purchase_orders(ADMIN, {"status": "PLACED"})
    )
    assert len(rows) == 3
    assert meta["total_count"] == 3
    assert all(row["status"] == "PLACED" for row in rows)


# ─── Body foreign-key resolution ──────────────────────

def test_car_assignment_with_unknown_car_reference_is_rejected(api):
    """PRD §2.11: "Fourth, body referential integrity: every foreign key named
    in the request body must resolve to a persisted row, and a failure is
    rejected with `ERR_COMPONENT_NOT_FOUND` (HTTP 404). This fourth check is
    not limited to component references despite its name — it covers
    `lease_fleet_car_id`, `lease_contract_id`, `lessee_id`, `component_id`,
    `car_type_id`, `production_order_id` and `retrofit_program_id` alike — and
    it guards the creation of production orders, car assignments, lease
    contracts, substitution endorsements, retrofit work orders and component
    purchase orders."

    The contract and the lessee both resolve; only the car does not, so the
    rejection is the body's foreign-key gate and no placement is written.

    Design: Corner/entities/car_assignment_unknown_car_fk_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    world = create_lessee_and_contract(
        legal_name="Acme Leasing LLC",
        credit_tier="A",
        utilization_threshold_pct=50,
        credit_ceiling_cents=50000000,
        lease_type="FULL_SERVICE",
        per_diem_rate_cents=25000,
        liability_bearer="LESSOR",
        term_start_date="2026-09-01",
        term_end_date="2027-09-01",
        fleet_car_cap=10,
    )

    rejected = api_client.create_car_assignment(
        create_car_assignment_payload(
            lease_fleet_car_id=NON_EXISTENT_UUID,
            lease_contract_id=world["contract"]["id"],
            lessee_id=world["lessee"]["id"],
            start_date="2026-10-01",
            end_date="2026-10-31",
            mileage_allowance=1000,
        ),
        LEASE,
    )
    validate_error(rejected, ApiErrorId.ERR_COMPONENT_NOT_FOUND)
    assert rejected.status_code == 404

    rows, meta = validate_paginated(api_client.list_car_assignments(ADMIN))
    assert meta["total_count"] == 0


def test_purchase_order_with_unknown_component_reference_is_rejected(api):
    """PRD §2.11: "Fourth, body referential integrity: every foreign key named
    in the request body must resolve to a persisted row, and a failure is
    rejected with `ERR_COMPONENT_NOT_FOUND` (HTTP 404). This fourth check is
    not limited to component references despite its name — it covers
    `lease_fleet_car_id`, `lease_contract_id`, `lessee_id`, `component_id`,
    `car_type_id`, `production_order_id` and `retrofit_program_id` alike — and
    it guards the creation of production orders, car assignments, lease
    contracts, substitution endorsements, retrofit work orders and component
    purchase orders."
    PRD §3.2: "a body that names a component, a purchase order or any other
    foreign key that does not resolve is rejected with
    `ERR_COMPONENT_NOT_FOUND` (HTTP 404) before any state check runs".

    The component catalogue is empty, so the purchase order's only foreign key
    fails to resolve.

    Design: Corner/entities/component_purchase_order_unknown_component_fk_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    rejected = api_client.create_component_purchase_order(
        create_component_purchase_order_payload(
            component_id=NON_EXISTENT_UUID,
            qty_ordered=4,
            unit_cost_cents=200000,
            order_date="2026-09-01",
            expected_receipt_date="2026-09-11",
        ),
        SUPPLY,
    )
    validate_error(rejected, ApiErrorId.ERR_COMPONENT_NOT_FOUND)
    assert rejected.status_code == 404

    rows, meta = validate_paginated(api_client.list_component_purchase_orders(ADMIN))
    assert meta["total_count"] == 0
