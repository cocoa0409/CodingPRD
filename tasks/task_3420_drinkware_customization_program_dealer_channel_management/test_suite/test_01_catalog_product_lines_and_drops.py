"""Catalog: product lines and colorway drops (PRD sections 3.3, 2.4, 2.10)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    boot_clock,
    create_colorway_drop,
    create_order,
    create_product_line,
    get_drop,
    get_order,
    get_product_line,
    make_buyer_headers,
    set_clock,
    setup_catalog,
    validate_error,
    validate_paginated,
    validate_success,
    assert_colorway_drop,
    assert_drop_unit_ledger_invariant,
    assert_product_line,
    TEST_USERS,
)

_ADMIN = TEST_USERS["platform_admin_headers"]


def test_product_line_get_roundtrips_all_fields(api):
    """A created product line reads back with every posted field unchanged and
    status ACTIVE.

    PRD section 3.3: "Each product line carries a display `name`, a `category`
    of `HARD_COOLER`, `SOFT_GOOD`, or `DRINKWARE`, a canonical `base_sku` root
    that must be unique across all product lines — reuse is rejected with
    `ERR_DUPLICATE_SKU` — the customization unit `base_custom_price_cents`, the
    `map_price_cents` dealers must honor as minimum advertised price, the
    `min_custom_quantity` floor for customization orders, and three component
    warranty terms: `warranty_months_lid`, `warranty_months_insulation`, and
    `warranty_months_hardware`."

    Design: Corner/entities/product_line_get_roundtrips_all_fields
    """
    boot_clock()
    line = create_product_line()  # factory defaults: RAMSTD, 3000/3499, MOQ 5, 24/36/12
    assert_product_line(line)

    resp = api.get_product_line(line["id"], TEST_USERS["warranty_agent_headers"])
    data = validate_success(resp)
    assert_product_line(data)
    assert data["base_sku"] == "RAMSTD"
    assert data["warranty_months_lid"] == 24
    assert data["warranty_months_insulation"] == 36
    assert data["warranty_months_hardware"] == 12
    assert data["base_custom_price_cents"] == 3000
    assert data["map_price_cents"] == 3499
    assert data["min_custom_quantity"] == 5
    assert data["status"] == "ACTIVE"


def test_drop_unit_ledgers_computed_at_creation(api):
    """A freshly announced drop reports empty dealer/warranty ledgers and
    unallocated_units == total_units - dtc_reserved_units.

    PRD section 2.10: "For each colorway drop, `dealer_committed_units` is the
    sum of `allocated_units` over the drop's allocations in `ALLOCATED` status,
    `warranty_reserved_units` counts the approved-replacement claims resolved
    to the same colorway against the drop, and `unallocated_units` is
    `total_units` minus `dtc_reserved_units` minus `dealer_committed_units`
    minus `warranty_reserved_units`."

    Design: Corner/entities/drop_unit_ledgers_computed_at_creation
    """
    boot_clock()
    line = create_product_line()
    resp = api.create_colorway_drop(
        {
            "product_line_id": line["id"],
            "color_name": "Ledger Blue",
            "pantone_code": "PMS 301",
            "drop_type": "LIMITED_EDITION",
            "total_units": 100,
            "dtc_reserved_units": 20,
            "dealer_unit_price_cents": 1800,
            "allocation_opens_at": "2026-09-05T00:00:00Z",
            "allocation_closes_at": "2026-09-20T00:00:00Z",
            "go_live_at": "2026-10-01T00:00:00Z",
            "sales_end_at": "2026-12-31T00:00:00Z",
        },
        _ADMIN,
    )
    drop = validate_success(resp, 201)
    assert_colorway_drop(drop)
    assert drop["status"] == "ANNOUNCED"
    assert drop["dealer_committed_units"] == 0
    assert drop["warranty_reserved_units"] == 0
    assert drop["unallocated_units"] == 80, "100 total - 20 dtc with no activity"
    assert_drop_unit_ledger_invariant(drop)


def test_drop_create_with_invalid_enum_drop_type_returns_400(api):
    """drop_type FLASH is outside the declared enum and rejected at the
    request-shape check.

    PRD section 3.3: "a `drop_type` of `STANDARD` or `LIMITED_EDITION`"
    PRD section 2.7: "(3) request-body shape — required fields present, types
    correct, enum values in range, and conditionally required fields satisfied
    ... with any failure reported as `ERR_INVALID_REQUEST`"

    Design: Corner/entities/drop_create_with_invalid_enum_drop_type_returns_400
    """
    boot_clock()
    line = create_product_line()
    resp = api.create_colorway_drop(
        {
            "product_line_id": line["id"],
            "color_name": "Flash Sale",
            "pantone_code": "PMS 000",
            "drop_type": "FLASH",
            "total_units": 100,
            "dtc_reserved_units": 20,
            "dealer_unit_price_cents": 1800,
            "allocation_opens_at": "2026-09-05T00:00:00Z",
            "allocation_closes_at": "2026-09-20T00:00:00Z",
            "go_live_at": "2026-10-01T00:00:00Z",
            "sales_end_at": "2026-12-31T00:00:00Z",
        },
        _ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    data, meta = validate_paginated(
        api.list_colorway_drops(_ADMIN, params={"product_line_id": line["id"]}))
    assert len(data) == 0 and meta["total_count"] == 0


def test_duplicate_sku_returns_409(api):
    """base_sku is globally unique; reusing RAMSTD on an otherwise different
    line is rejected.

    PRD section 3.3: "a canonical `base_sku` root that must be unique across
    all product lines — reuse is rejected with `ERR_DUPLICATE_SKU`"

    Design: Corner/validations/duplicate_sku_returns_409
    """
    boot_clock()
    create_product_line()  # base_sku RAMSTD
    resp = api.create_product_line(
        {
            "name": "Knockoff Line",
            "category": "SOFT_GOOD",
            "base_sku": "RAMSTD",
            "base_custom_price_cents": 999,
            "map_price_cents": 1499,
            "min_custom_quantity": 1,
            "warranty_months_lid": 12,
            "warranty_months_insulation": 12,
            "warranty_months_hardware": 12,
        },
        _ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SKU)

    data, meta = validate_paginated(api.list_product_lines(_ADMIN))
    assert len(data) == 1 and meta["total_count"] == 1


def test_dtc_reserve_and_window_order_violations(api):
    """Two drop-shape guards: dtc_reserved_units may not exceed total_units,
    and the four scheduling instants must be strictly ordered.

    PRD section 3.3: "the `dtc_reserved_units` carved out for the
    direct-to-consumer channel — which may not exceed `total_units`, failing
    with `ERR_DTC_RESERVE_EXCEEDS_TOTAL`"
    PRD section 3.3: "Four instants schedule the drop's life:
    `allocation_opens_at`, `allocation_closes_at`, `go_live_at`, and
    `sales_end_at`, which must be strictly ordered in that sequence or creation
    fails with `ERR_INVALID_WINDOW_ORDER`."

    Design: Corner/validations/dtc_reserve_and_window_order_violations
    """
    boot_clock()
    line = create_product_line()

    resp_dtc = api.create_colorway_drop(
        {
            "product_line_id": line["id"],
            "color_name": "Greedy DTC",
            "pantone_code": "PMS 200",
            "drop_type": "STANDARD",
            "total_units": 50,
            "dtc_reserved_units": 60,
            "dealer_unit_price_cents": 1800,
            "allocation_opens_at": "2026-09-05T00:00:00Z",
            "allocation_closes_at": "2026-09-20T00:00:00Z",
            "go_live_at": "2026-10-01T00:00:00Z",
            "sales_end_at": "2026-12-31T00:00:00Z",
        },
        _ADMIN,
    )
    validate_error(resp_dtc, ApiErrorId.ERR_DTC_RESERVE_EXCEEDS_TOTAL)

    resp_window = api.create_colorway_drop(
        {
            "product_line_id": line["id"],
            "color_name": "Backwards",
            "pantone_code": "PMS 201",
            "drop_type": "STANDARD",
            "total_units": 50,
            "dtc_reserved_units": 10,
            "dealer_unit_price_cents": 1800,
            "allocation_opens_at": "2026-09-20T00:00:00Z",
            "allocation_closes_at": "2026-09-05T00:00:00Z",
            "go_live_at": "2026-10-01T00:00:00Z",
            "sales_end_at": "2026-12-31T00:00:00Z",
        },
        _ADMIN,
    )
    validate_error(resp_window, ApiErrorId.ERR_INVALID_WINDOW_ORDER)

    data, meta = validate_paginated(
        api.list_colorway_drops(_ADMIN, params={"product_line_id": line["id"]}))
    assert len(data) == 0 and meta["total_count"] == 0


def test_discontinued_line_blocks_submit_and_drop_create(api):
    """Discontinuation flips two future gates while the line stays readable.

    PRD section 3.3: "Discontinuation does not block creating new customization
    orders that reference the line, but submitting such an order is rejected
    with `ERR_PRODUCT_LINE_DISCONTINUED`, and announcing a new colorway drop
    for the line is rejected with the same error."

    Design: Corner/validations/discontinued_line_blocks_submit_and_drop_create
    """
    boot_clock()
    catalog = setup_catalog()
    line, drop = catalog["line"], catalog["drop"]
    order = create_order(line["id"], drop["id"])

    resp_disc = api.discontinue_product_line(line["id"], _ADMIN)
    validate_success(resp_disc)

    resp_submit = api.submit_order(order["id"], make_buyer_headers("buyer-std"))
    validate_error(resp_submit, ApiErrorId.ERR_PRODUCT_LINE_DISCONTINUED)

    resp_drop = api.create_colorway_drop(
        {
            "product_line_id": line["id"],
            "color_name": "Late Red",
            "pantone_code": "PMS 186",
            "drop_type": "STANDARD",
            "total_units": 100,
            "dtc_reserved_units": 10,
            "dealer_unit_price_cents": 1800,
            "allocation_opens_at": "2026-09-05T00:00:00Z",
            "allocation_closes_at": "2026-09-20T00:00:00Z",
            "go_live_at": "2026-10-01T00:00:00Z",
            "sales_end_at": "2026-12-31T00:00:00Z",
        },
        _ADMIN,
    )
    validate_error(resp_drop, ApiErrorId.ERR_PRODUCT_LINE_DISCONTINUED)

    data = get_product_line(line["id"])
    assert data["status"] == "DISCONTINUED"


def test_drop_lazy_live_then_closed_by_clock(api):
    """LIVE and CLOSED materialize on reads once the clock passes go_live_at
    and sales_end_at; a submit against the CLOSED drop is rejected.

    PRD section 2.4: "Three status transitions are lazy and clock-driven rather
    than triggered by their own write operations: a colorway drop moves from
    `ALLOCATION_LOCKED` to `LIVE` once the clock reaches its `go_live_at`, and
    from `LIVE` to `CLOSED` once the clock reaches its `sales_end_at`"
    PRD section 3.5: "The chosen drop must belong to the same product line as
    the order and must not be `CLOSED`, failing with
    `ERR_COLORWAY_NOT_AVAILABLE`."
    PRD section 3.5: "Creation checks that the referenced product line and drop
    exist; the line's status and the colorway's coherence are deliberately
    deferred to submit."

    Design: Corner/state_machines/drop_lazy_live_then_closed_by_clock
    """
    boot_clock()
    catalog = setup_catalog()
    line, drop = catalog["line"], catalog["drop"]

    set_clock("2026-09-06T00:00:00Z")
    validate_success(api.open_allocation(drop["id"], _ADMIN))
    current = get_drop(drop["id"])
    set_clock("2026-09-21T00:00:00Z")
    validate_success(api.lock_allocation(
        drop["id"], {"expected_drop_version": current["version"]}, _ADMIN))

    set_clock("2026-10-02T00:00:00Z")
    assert get_drop(drop["id"])["status"] == "LIVE", \
        "clock past go_live_at 2026-10-01 flips ALLOCATION_LOCKED -> LIVE on read"

    set_clock("2027-01-01T00:00:00Z")
    assert get_drop(drop["id"])["status"] == "CLOSED", \
        "clock past sales_end_at 2026-12-31 flips LIVE -> CLOSED on read"

    # Creation still succeeds (existence-only check); submit hits the gate.
    order = create_order(line["id"], drop["id"],
                         requested_ship_date="2027-01-05T00:00:00Z")
    resp_submit = api.submit_order(order["id"], make_buyer_headers("buyer-std"))
    validate_error(resp_submit, ApiErrorId.ERR_COLORWAY_NOT_AVAILABLE)
    assert get_order(order["id"])["payment_status"] == "UNPAID"
