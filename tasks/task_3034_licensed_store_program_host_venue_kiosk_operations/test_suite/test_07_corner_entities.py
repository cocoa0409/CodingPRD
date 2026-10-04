"""Corner design — section: entities."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    create_licensee_payload,
    create_sales_report,
    create_supply_order,
    finalize_sales_report,
    is_valid_uuid,
    set_clock,
    setup_operating_store,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    add_assortment_item,
    create_active_agreement,
    create_draft_agreement,
    create_product,
)
from test_helpers.factories import (
    create_distributor_payload,
    create_host_venue_payload,
)
from test_helpers.test_users import make_licensee_manager_headers


def test_create_licensee_returns_201_with_defaults():
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/entities/create_licensee_returns_201_with_defaults
    """
    resp = api_client.create_licensee(
        create_licensee_payload(name="LC", legal_entity_code="LE-C1"), ADMIN)
    data = validate_success(resp, expected_status=201)
    assert is_valid_uuid(data["id"])
    assert data["name"] == "LC"
    assert data["version"] == 1


def test_create_licensee_missing_legal_entity_code_returns_400():
    """PRD §3.1: "A `BrandProgramAdmin` registers a **Licensee** by supplying
    its legal display `name` and a globally unique `legal_entity_code`; a code
    already in use is rejected with `ERR_UNIQUENESS_CONFLICT`."

    Design: Corner/entities/create_licensee_missing_legal_entity_code_returns_400
    """
    resp = api_client.create_licensee({"name": "LC"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_licensee_not_found_returns_404():
    """PRD §2.8: "The request is rejected with `ERR_NOT_FOUND` at the first
    path identifier that does not correspond to an existing resource: creating
    a store under a nonexistent agreement fails on the agreement before the
    body is examined; fetching an order line that does not exist fails on the
    line."

    Design: Corner/entities/get_licensee_not_found_returns_404
    """
    from test_helpers import NON_EXISTENT_UUID
    resp = api_client.get_licensee(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_licensee_list_pagination_defaults():
    """PRD §2.3: "The `limit` parameter bounds the page size: it defaults to
    10, with a minimum of 1 and a maximum of 100. The `offset` parameter says
    how many items to skip and defaults to 0."

    Design: Corner/entities/licensee_list_pagination_defaults
    """
    for i in range(3):
        validate_success(api_client.create_licensee(
            create_licensee_payload(name=f"L{i}", legal_entity_code=f"LE-P{i}"),
            ADMIN), expected_status=201)
    _rows, meta = validate_paginated(api_client.list_licensees(ADMIN))
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0


def test_distributor_approved_defaults_false():
    """PRD §3.1: "Distributors join with a `name` and a non-negative
    `lead_time_days`, and every distributor starts unapproved: its `approved`
    flag is false until the brand flips it, and only approved distributors may
    receive submitted orders."

    Design: Corner/entities/distributor_approved_defaults_false
    """
    data = validate_success(api_client.create_distributor(
        create_distributor_payload(name="D1", lead_time_days=2), ADMIN),
        expected_status=201)
    assert data["approved"] is False


def test_net_sales_cents_computed_not_client_supplied():
    """PRD §3.7: "A report is born `DRAFT`; finalization computes
    `net_sales_cents` as gross minus returns minus loyalty redemptions,
    refusing with `ERR_INVALID_REQUEST` when that figure would go negative,
    stamps `finalized_at` from the logical clock, and moves the report to
    `FINALIZED`, terminal."

    Design: Corner/entities/net_sales_cents_computed_not_client_supplied
    """
    set_clock()
    bundle = setup_operating_store()
    report = create_sales_report(
        bundle["store"]["id"], bundle["licensee_id"],
        period_start_date="2026-09-01", period_end_date="2026-09-14",
        gross_sales_cents=1000, returns_cents=100, loyalty_redemption_cents=50)
    finalized = finalize_sales_report(report["id"], bundle["licensee_id"])
    assert finalized["net_sales_cents"] == 850
    assert finalized["status"] == "FINALIZED"


def test_venue_type_enum_rejects_invalid_value():
    """PRD §3.1: "Host venues are registered the same way, with a `name`, a
    `venue_type` of `GROCERY`, `AIRPORT`, `CAMPUS`, or `HOSPITAL`, the venue's
    daily `open_time_utc` and `close_time_utc` in HH:MM 24-hour UTC form (close
    must be strictly after open), an `access_restricted` flag recording whether
    badge or escort constraints apply to visits, a `security_badge_required`
    flag for inspectors, and a `max_equipment_footprint_units` ceiling of at
    least 1."

    Design: Corner/entities/venue_type_enum_rejects_invalid_value
    """
    payload = create_host_venue_payload(venue_type="MALL")
    resp = api_client.create_host_venue(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_supply_order_line_immutable_no_version():
    """PRD §2.4: "Supply order lines and loyalty account events carry `id` and
    `created_at` only — both `updated_at` and `version` are absent, because a
    line or event is immutable once recorded; any change in the world is
    expressed by writing a new line or event, never by editing the old one."

    Design: Corner/entities/supply_order_line_immutable_no_version
    """
    set_clock()
    bundle = setup_operating_store()
    lic_id = bundle["licensee_id"]
    store_id = bundle["store"]["id"]
    product = create_product(unit_cost_cents=500, case_pack_units=1)
    add_assortment_item(store_id, lic_id, product["id"], par_level=50)
    from test_helpers.fixtures import create_approved_distributor
    distributor = create_approved_distributor()
    order = create_supply_order(
        store_id, lic_id, distributor["id"],
        lines=[{"product_item_id": product["id"], "quantity": 10}])
    lines, _meta = validate_paginated(
        api_client.list_supply_order_lines(ADMIN, params={"supply_order_id": order["id"]}))
    assert len(lines) == 1
    line = lines[0]
    assert line["quantity_ordered"] == 10
    assert line["unit_cost_cents"] == 500
    assert line["line_cost_cents"] == 5000
    assert "version" not in line
    assert "updated_at" not in line


def test_store_creation_requires_active_agreement():
    """PRD §3.3: "Under an `ACTIVE` agreement — store creation against any
    other agreement state is `ERR_AGREEMENT_NOT_ACTIVE` — the licensee (or the
    brand) creates a **LicensedStore** carrying its parent `agreement_id`, with
    a `store_code` unique within the parent agreement (a repeat is
    `ERR_UNIQUENESS_CONFLICT`) and an `equipment_footprint_units` of at least
    1."

    Design: Corner/entities/store_creation_requires_active_agreement
    """
    from test_helpers.fixtures import create_licensee, create_venue
    licensee = create_licensee()
    venue = create_venue()
    agreement = create_draft_agreement(licensee["id"], venue["id"])
    resp = api_client.create_store(
        agreement["id"], {"store_code": "ST1", "equipment_footprint_units": 40},
        make_licensee_manager_headers(licensee["id"]))
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value)
