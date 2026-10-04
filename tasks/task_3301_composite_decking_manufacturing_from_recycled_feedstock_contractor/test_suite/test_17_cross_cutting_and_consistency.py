"""Cross-cutting corners: optimistic concurrency on plant-mutating writes,
allocation expiry at capacity review, idempotent warranty activation; and
consistency: invoice visible immediately on the ship response."""
from test_helpers import (
    ApiErrorId,
    confirm_order,
    get_success_data,
    make_active_formulation,
    make_allocation_commitment,
    make_certified_contractor,
    make_completed_run,
    make_contractor_headers,
    make_dealer,
    make_enhanced_registration,
    make_order,
    make_plant,
    make_price_book,
    make_product_line,
    make_supplier,
    set_clock,
    ship_order,
    stock_resin,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

OPS = TEST_USERS["ops_manager_headers"]
DSR = TEST_USERS["dealer_sales_rep_headers"]
CM = TEST_USERS["channel_manager_headers"]
PA = TEST_USERS["program_admin_headers"]


def _occ_setup(api):
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant()
    form = make_active_formulation(lines=[{"material": "VIRGIN_PE", "weight_fraction_bp": 10000}])
    line = make_product_line(form["id"])
    book = make_price_book(base_prices={line["id"]: 500})
    dealer = make_dealer(credit_limit_cents=1000000)
    return plant, line, book, dealer


def test_occ_stale_version_on_allocation_create(api):
    """PRD §2.9: "If the supplied `expected_plant_version` does not match the
    plant's current `version` at the moment the request is processed, the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.9: "reserving finished goods through an allocation commitment, and
    scheduling a production run. Both are exposed as plant-scoped creation
    endpoints, and both require a non-optional request field
    `expected_plant_version`"

    Design: Corner/cross_cutting/occ_stale_version_on_allocation_create
    """
    plant, line, book, dealer = _occ_setup(api)
    plant0 = get_success_data(api.get_plant(plant["id"], OPS))
    payload1 = {
        "dealer_id": dealer["id"], "product_line_id": line["id"],
        "reserved_lf": 100, "price_book_id": book["id"],
        "expected_plant_version": plant0["version"],
    }
    ac1 = validate_success(
        api.create_allocation_commitment(plant["id"], payload1, DSR), expected_status=201)
    assert ac1["status"] == "OPEN"

    # Same stale version on the second create: the first bumped Plant.version.
    payload2 = dict(payload1, reserved_lf=50)
    resp = api.create_allocation_commitment(plant["id"], payload2, DSR)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_occ_stale_version_on_run_create(api):
    """PRD §2.9: "If the supplied `expected_plant_version` does not match the
    plant's current `version` at the moment the request is processed, the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/occ_stale_version_on_run_create
    """
    plant, line, book, dealer = _occ_setup(api)
    plant0 = get_success_data(api.get_plant(plant["id"], OPS))
    payload1 = {
        "product_line_id": line["id"], "planned_lf": 100,
        "production_date": "2026-09-02", "run_kind": "NULL_SLOT",
        "expected_plant_version": plant0["version"],
    }
    validate_success(api.create_production_run(plant["id"], payload1, OPS), expected_status=201)
    payload2 = dict(payload1, production_date="2026-09-03")
    resp = api.create_production_run(plant["id"], payload2, OPS)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_allocation_expiry_at_review_releases_reservation(api):
    """PRD §3.12: "Allocation commitments still `OPEN` whose creation date is
    more than 90 days before the review date transition to `EXPIRED`,
    releasing their remaining `reserved_fg_store` contribution."

    Design: Corner/cross_cutting/allocation_expiry_at_review_releases_reservation
    """
    set_clock("2026-01-01T00:00:00Z")
    plant = make_plant()
    form = make_active_formulation(lines=[{"material": "VIRGIN_PE", "weight_fraction_bp": 10000}])
    line = make_product_line(form["id"])
    book = make_price_book(base_prices={line["id"]: 500})
    dealer = make_dealer(credit_limit_cents=1000000)
    ac = make_allocation_commitment(plant["id"], dealer["id"], line["id"], 100, book["id"])
    plant_mid = get_success_data(api.get_plant(plant["id"], OPS))
    assert plant_mid["reserved_fg_store"][line["id"]] == 100

    # 2026-04-15 is 104 days after 2026-01-01: more than 90.
    set_clock("2026-04-15T00:00:00Z")
    get_success_data(api.run_capacity_review(plant["id"], OPS))
    ac_after = get_success_data(api.get_allocation_commitment(ac["id"], DSR))
    assert ac_after["status"] == "EXPIRED"
    plant_after = get_success_data(api.get_plant(plant["id"], OPS))
    assert plant_after["reserved_fg_store"].get(line["id"], 0) == 0


def test_activate_warranty_twice_rejected(api):
    """PRD §3.9: "the `enhanced_warranty` flag must still be false — a repeat
    activation is rejected with `ERR_ALREADY_ENHANCED` (HTTP 409)."
    PRD §3.9: "recomputes the contractor's `enhanced_warranty_count`, which
    counts registrations of that contractor whose enhanced warranty was
    activated within the trailing 12 months."

    Design: Corner/cross_cutting/activate_warranty_twice_rejected
    """
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant()
    form = make_active_formulation()
    line = make_product_line(form["id"], name="Enhance", color="Brown",
                             profile="SQUARE", emboss="SMOOTH", board_length_ft=12)
    dealer = make_dealer(credit_limit_cents=1000000)
    supplier = make_supplier()
    stock_resin(plant, supplier["id"], weight_lbs=500)
    _run, lot = make_completed_run(plant["id"], line["id"], 200, "2026-03-01")
    contractor, _module = make_certified_contractor()
    reg = make_enhanced_registration(contractor["id"], dealer["id"], line["id"],
                                     "2026-03-02", lot["id"])
    resp = api.activate_warranty(reg["id"], make_contractor_headers(contractor["id"]))
    validate_error(resp, ApiErrorId.ERR_ALREADY_ENHANCED)
    contractor_after = get_success_data(api.get_contractor(contractor["id"], PA))
    assert contractor_after["enhanced_warranty_count"] == 1


def test_invoice_visible_immediately_on_ship_response(api):
    """PRD §3.6: "The result is persisted to `invoiced_cents`, the
    `actual_ship_date` is stamped, and the amount is added to the dealer's
    `outstanding_cents`."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/consistency/invoice_visible_immediately_on_ship_response
    """
    set_clock("2026-03-01T00:00:00Z")
    plant = make_plant()
    form = make_active_formulation()
    line = make_product_line(form["id"])
    make_price_book(base_prices={line["id"]: 500})
    dealer = make_dealer()
    supplier = make_supplier()
    stock_resin(plant, supplier["id"], weight_lbs=500)
    make_completed_run(plant["id"], line["id"], 200, "2026-03-01")
    order = make_order(dealer["id"], line["id"], 100, "2026-03-02")
    confirm_order(order["id"])
    set_clock("2026-03-02T00:00:00Z")
    resp = api.ship_shipment_order(order["id"], DSR)
    shipped = validate_success(resp, expected_status=200)
    assert shipped["status"] == "SHIPPED"
    assert shipped["invoiced_cents"] == 50000
    dealer_after = get_success_data(api.get_dealer(dealer["id"], CM))
    assert dealer_after["outstanding_cents"] == 50000
