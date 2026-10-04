"""Entity-level corners: plant creation defaults, season posture boundary,
not-found, required fields, uniqueness, defaults, and pagination envelope."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_product_line_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_active_formulation,
    make_contractor,
    make_dealer,
    make_order,
    make_plant,
    create_plant_payload,
    make_product_line,
    make_supplier,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

OPS = TEST_USERS["ops_manager_headers"]
QE = TEST_USERS["quality_engineer_headers"]
PM = TEST_USERS["product_manager_headers"]
PA = TEST_USERS["program_admin_headers"]
DSR = TEST_USERS["dealer_sales_rep_headers"]


def test_plant_create_returns_defaults_and_zeroed_stores(api):
    """PRD §3.1: "At creation the feedstock store and both finished-goods
    ledgers are zeroed and the season posture is computed from the logical
    clock."
    PRD §2.10: "Every key of both ledgers starts at zero at plant creation."
    PRD §1: "the clock never falls back to wall-clock time and only advances
    when explicitly set."

    Design: Corner/entities/plant_create_returns_defaults_and_zeroed_stores
    """
    # Default logical clock reads 2026-09-01T00:00:00Z; 09-01 is outside the
    # 01-01..02-28 window -> SELLING.
    resp = api.create_plant(create_plant_payload(lines=2), OPS)
    plant = validate_success(resp, expected_status=201)
    assert plant["version"] == 1
    assert plant["resin_store"] == {"VIRGIN_PE": 0, "REPRO_PE": 0,
                                    "PCR_FILM": 0, "WOOD_FLOUR": 0}
    assert plant["fg_store"] == {}
    assert plant["reserved_fg_store"] == {}
    assert plant["season_posture"] == "SELLING"
    assert is_valid_uuid(plant["id"])
    assert is_iso8601_timestamp(plant["created_at"])
    assert is_iso8601_timestamp(plant["updated_at"])


def test_plant_create_at_preseason_end_boundary_is_preseason(api):
    """PRD §2.11: "The boundary is inclusive at the end — a date exactly equal
    to `pre_season_window_end` is still `PRE_SEASON`, and the following day is
    `SELLING`."

    Design: Corner/entities/plant_create_at_preseason_end_boundary_is_preseason
    """
    set_clock("2026-02-28T12:00:00Z")
    plant = make_plant(name="Fernley", daily_capacity_lf=5000, lines=1)
    assert plant["season_posture"] == "PRE_SEASON"


def test_supplier_get_unknown_id_returns_not_found(api):
    """PRD §2.5: "Existence comes third: path parameters are validated
    left-to-right against existing resources, and the first missing path
    segment yields `ERR_NOT_FOUND`."

    Design: Corner/entities/supplier_get_unknown_id_returns_not_found
    """
    resp = api.get_supplier(NON_EXISTENT_UUID, QE)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_product_line_create_missing_formulation_returns_invalid_request(api):
    """PRD §2.5: "A malformed payload or a missing required field is rejected
    with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/product_line_create_missing_formulation_returns_invalid_request
    """
    payload = create_product_line_payload()
    assert "formulation_id" not in payload
    resp = api.create_product_line(payload, PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_product_line_create_dangling_formulation_returns_referenced_not_found(api):
    """PRD §2.6: "Foreign keys supplied in request bodies are a separate
    concern from path parameters: body references that do not resolve produce
    `ERR_REFERENCED_NOT_FOUND` rather than `ERR_NOT_FOUND`, and this applies
    to `supplier_id`, `dealer_id`, `product_line_id`, `formulation_id`,
    `module_id`, `contractor_id`, `install_registration_id`,
    `warranty_claim_id`, `price_book_id`, and `reservation_id` wherever they
    appear."

    Design: Corner/entities/product_line_create_dangling_formulation_returns_referenced_not_found
    """
    payload = create_product_line_payload(formulation_id=NON_EXISTENT_UUID)
    resp = api.create_product_line(payload, PM)
    validate_error(resp, ApiErrorId.ERR_REFERENCED_NOT_FOUND)


def test_contractor_email_uniqueness_enforced(api):
    """PRD §3.8: "A `ProgramAdmin` admits a contractor to the certification
    program with a `name` and a unique `email`"
    PRD §2.5: "A malformed payload or a missing required field is rejected
    with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/contractor_email_uniqueness_enforced
    """
    make_contractor(name="Pro A", email="a@build.example")
    resp = api.create_contractor({"name": "Pro A2", "email": "a@build.example"}, PA)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_run_kind_defaults_to_sellable(api):
    """PRD §3.4: "Two optional fields refine the run: `run_kind`, defaulting
    to `SELLABLE` and alternatively `SUPPORT_STOCK` or `NULL_SLOT`"

    Design: Corner/entities/run_kind_defaults_to_sellable
    """
    plant = make_plant()
    form = make_active_formulation()
    line = make_product_line(form["id"])
    plant_now = get_success_data(api.get_plant(plant["id"], OPS))
    resp = api.create_production_run(plant["id"], {
        "product_line_id": line["id"], "planned_lf": 100,
        "production_date": "2026-09-01",
        "expected_plant_version": plant_now["version"],
    }, OPS)
    run = validate_success(resp, expected_status=201)
    assert run["run_kind"] == "SELLABLE"


def test_repair_support_only_defaults_false(api):
    """PRD §3.3: "an optional `repair_support_only` flag defaulting to false."

    Design: Corner/entities/repair_support_only_defaults_false
    """
    form = make_active_formulation(lines=[{"material": "VIRGIN_PE", "weight_fraction_bp": 10000}])
    line = make_product_line(form["id"])
    assert line["repair_support_only"] is False


def test_dealer_list_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items
    to return. If not provided, it defaults to 10, with a minimum of 1 and a
    maximum of 100. The `offset` parameter specifies the number of items to
    skip and defaults to 0."
    PRD §2.3: "Paginated and non-paginated list-based responses include the
    following fields in the `meta` object of the response envelope: `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/dealer_list_pagination_envelope
    """
    dealer = make_dealer()
    form = make_active_formulation(lines=[{"material": "VIRGIN_PE", "weight_fraction_bp": 10000}])
    line = make_product_line(form["id"])
    for _ in range(11):
        make_order(dealer["id"], line["id"], 10, "2026-03-02")

    page1, meta1 = validate_paginated(api.list_dealer_shipment_orders(dealer["id"], DSR))
    assert meta1["total_count"] == 11
    assert len(page1) == 10
    assert meta1["has_more"] is True
    assert meta1["limit"] == 10
    assert meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api.list_dealer_shipment_orders(dealer["id"], DSR, params={"offset": 10}))
    assert len(page2) == 1
    assert meta2["has_more"] is False
    assert meta2["total_count"] == 11
