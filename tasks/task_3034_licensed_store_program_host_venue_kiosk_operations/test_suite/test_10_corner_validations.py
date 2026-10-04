"""Corner design — section: validations."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    create_product,
    set_clock,
    setup_operating_store,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    activate_agreement,
    add_assortment_item,
    create_approved_distributor,
    create_draft_agreement,
    create_licensee,
    create_sales_report,
    create_store,
    create_supply_order,
    create_venue,
    finalize_sales_report,
)
from test_helpers.test_users import (
    make_host_venue_manager_headers,
    make_inspector_headers,
    make_licensee_manager_headers,
)


def test_footprint_equality_allowed_excess_rejected():
    """PRD §3.4: "Footprint: the venue's total usage — summed over the venue's
    stores under `ACTIVE` or `SUSPENDED` agreements, each contributing its
    `equipment_footprint_units` plus the `footprint_units` of every active
    assortment product — must stay at or below the venue's cap. Equality with
    the cap is allowed; one unit over is `ERR_FOOTPRINT_EXCEEDED`."

    Design: Corner/validations/footprint_equality_allowed_excess_rejected
    """
    set_clock()
    licensee = create_licensee()
    venue = create_venue(max_equipment_footprint_units=60)
    agreement = activate_agreement(
        create_draft_agreement(licensee["id"], venue["id"]))
    store = create_store(agreement["id"], licensee["id"],
                         store_code="ST1", equipment_footprint_units=40)
    p15 = create_product(category="BEVERAGE_CORE", footprint_units=15)
    p6 = create_product(category="BEVERAGE_CORE", footprint_units=6)
    lic_headers = make_licensee_manager_headers(licensee["id"])
    validate_success(api_client.create_assortment_item(
        store["id"], {"product_item_id": p15["id"], "par_level": 10}, lic_headers),
        expected_status=201)
    resp = api_client.create_assortment_item(
        store["id"], {"product_item_id": p6["id"], "par_level": 10}, lic_headers)
    validate_error(resp, ApiErrorId.ERR_FOOTPRINT_EXCEEDED.value)


def test_venue_cap_shrink_below_usage_rejected():
    """PRD §3.1: "Venue settings are not frozen at registration: the venue's
    own manager (or the brand) may later patch hours, access flags, or the
    footprint ceiling — but shrinking the ceiling below the venue's current
    usage is refused with `ERR_FOOTPRINT_EXCEEDED`, since the footprint rule is
    re-evaluated against the new cap on every such change."

    Design: Corner/validations/venue_cap_shrink_below_usage_rejected
    """
    set_clock()
    licensee = create_licensee()
    venue = create_venue(max_equipment_footprint_units=100)
    agreement = activate_agreement(
        create_draft_agreement(licensee["id"], venue["id"]))
    create_store(agreement["id"], licensee["id"],
                 store_code="ST1", equipment_footprint_units=40)
    venue_headers = make_host_venue_manager_headers(venue["id"])
    resp = api_client.update_host_venue(
        venue["id"], {"max_equipment_footprint_units": 39}, venue_headers)
    validate_error(resp, ApiErrorId.ERR_FOOTPRINT_EXCEEDED.value)
    updated = validate_success(api_client.update_host_venue(
        venue["id"], {"max_equipment_footprint_units": 40}, venue_headers))
    assert updated["max_equipment_footprint_units"] == 40


def test_inspection_outside_venue_hours_rejected():
    """PRD §3.8: "Venue hours: the inspection's times of day must fall within
    the venue's `open_time_utc` to `close_time_utc` window, else
    `ERR_INSPECTION_OUTSIDE_VENUE_HOURS`."

    Design: Corner/validations/inspection_outside_venue_hours_rejected
    """
    set_clock()
    bundle = setup_operating_store()
    resp = api_client.create_inspection(
        bundle["store"]["id"],
        {"scheduled_start_utc": "2026-09-03T21:00:00Z",
         "scheduled_end_utc": "2026-09-03T23:00:00Z"},
        make_inspector_headers("insp-Z"))
    validate_error(resp, ApiErrorId.ERR_INSPECTION_OUTSIDE_VENUE_HOURS.value)


def test_sales_period_overlap_closed_interval():
    """PRD §3.7: "Two finalized reports for the same store may not cover
    overlapping date intervals — the intervals are closed, so reports touching
    even a single shared date conflict, and the second finalization is
    `ERR_SALES_PERIOD_OVERLAP`."

    Design: Corner/validations/sales_period_overlap_closed_interval
    """
    set_clock()
    bundle = setup_operating_store()
    lic_id = bundle["licensee_id"]
    store_id = bundle["store"]["id"]
    r1 = create_sales_report(
        store_id, lic_id, period_start_date="2026-09-01",
        period_end_date="2026-09-14", gross_sales_cents=1000)
    finalize_sales_report(r1["id"], lic_id)
    r2 = create_sales_report(
        store_id, lic_id, period_start_date="2026-09-10",
        period_end_date="2026-09-20", gross_sales_cents=1000)
    r3 = create_sales_report(
        store_id, lic_id, period_start_date="2026-09-15",
        period_end_date="2026-09-30", gross_sales_cents=1000)
    resp = api_client.finalize_sales_report(
        r2["id"], make_licensee_manager_headers(lic_id))
    validate_error(resp, ApiErrorId.ERR_SALES_PERIOD_OVERLAP.value)
    finalized = finalize_sales_report(r3["id"], lic_id)
    assert finalized["status"] == "FINALIZED"


def test_unapproved_distributor_blocks_submit():
    """PRD §3.5: "It requires lines (an empty submission is
    `ERR_EMPTY_ORDER`), requires the store to be `OPERATING` (else
    `ERR_STORE_NOT_OPERATING`), requires the distributor's `approved` flag
    (else `ERR_DISTRIBUTOR_NOT_APPROVED`), and requires the total to fit within
    the per-order budget ceiling of 20000000 cents (else
    `ERR_ORDER_BUDGET_EXCEEDED`)."

    Design: Corner/validations/unapproved_distributor_blocks_submit
    """
    set_clock()
    bundle = setup_operating_store()
    lic_id = bundle["licensee_id"]
    store_id = bundle["store"]["id"]
    product = create_product()
    add_assortment_item(store_id, lic_id, product["id"], par_level=50)
    from test_helpers.factories import create_distributor_payload
    distributor = validate_success(api_client.create_distributor(
        create_distributor_payload(name="D1", lead_time_days=2), ADMIN),
        expected_status=201)
    order = create_supply_order(
        store_id, lic_id, distributor["id"],
        lines=[{"product_item_id": product["id"], "quantity": 10}])
    resp = api_client.submit_supply_order(
        order["id"], make_licensee_manager_headers(lic_id))
    validate_error(resp, ApiErrorId.ERR_DISTRIBUTOR_NOT_APPROVED.value)
    order = validate_success(api_client.get_supply_order(order["id"], ADMIN))
    assert order["status"] == "DRAFT"
