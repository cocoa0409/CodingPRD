"""The layers that cut across every workflow: versions, recounts and paged reads."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import ERR_STALE_CONSULTATION_VERSION
from test_helpers.assertions import (
    assert_created_at_ascending,
    assert_page_meta,
    ids_of,
)
from test_helpers.fixtures import (
    accept_quote,
    book_consultation,
    build_quote,
    charter_territory,
    configure_opening,
    hire_designer,
    intake_lead,
    onboard_vendor,
    place_order,
    present_quote,
    read_consultation,
    read_opening,
    read_order,
    read_territory,
    receive_order,
    record_opening,
    request_remake,
    ship_order,
)
from test_helpers.test_users import (
    designer_headers,
    franchisee_headers,
    franchisor_headers,
)

CORDED_AND_CORDLESS = {"base_lead_time_days": 10, "motorization_extra_days": 3,
                       "cutoff_hour_utc": 15, "remake_policy": "SHARED_50_50",
                       "concurrent_capacity": 5,
                       "supported_lift_systems": ["CORDED", "CORDLESS"]}


def test_the_appointment_version_moves_only_for_the_writes_that_land(api):
    """A refused create leaves the version where the client just read it, and its peer alone.

    "Most resources additionally carry `updated_at`, an ISO 8601 UTC instant in the same
    format that is refreshed on every mutation, and `version`, an integer that starts at 1
    on creation and increments by one on every mutation of the row."

    "The parent appointment's `measured_opening_count` is re-derived and its `version`
    increments — which is precisely why the stale-version guard of §2.8 makes a quote
    writer re-read the consultation."

    "If that value does not equal the consultation's current `version`, the request is
    rejected with `ERR_STALE_CONSULTATION_VERSION` (HTTP 412) and nothing is written."

    "Fields the server owns — anything described in this document as derived, computed or
    system-stamped — are **silently ignored** when a client supplies them, never
    rejected."

    Design: Corner/cross_cutting_complexity_layers/the_consultation_version_is_per_row_monotonic_and_never_bumped_by_a_refusal
    """
    territory = charter_territory(api, postal_codes=["30301"])
    designer = hire_designer(api, territory)
    acting = designer_headers(designer["id"])
    first_lead = intake_lead(api, territory)
    second_lead = intake_lead(api, territory, customer_name="Bo Chen",
                              source="REFERRAL",
                              requested_at="2026-08-01T09:00:00.000Z")
    subject = book_consultation(api, designer, first_lead)
    bystander = book_consultation(
        api, designer, second_lead,
        scheduled_start_at="2026-08-03T16:00:00.000Z",
        scheduled_end_at="2026-08-03T17:00:00.000Z")
    assert subject["version"] == 1
    assert bystander["version"] == 1
    at_creation = subject["version"]

    configure_opening(api, designer,
                      record_opening(api, designer, subject, label="Den"),
                      fabric_code="LT-SHEER", lift_system="CORDED")
    after_children = read_consultation(api, designer, subject["id"])
    assert after_children["version"] > at_creation
    assert after_children["configured_opening_count"] == 1

    # The value read at creation is now stale, and the guard says so.
    validate_error(
        api.create_quote(f.quote_payload(subject["id"], at_creation), acting),
        ERR_STALE_CONSULTATION_VERSION, 412)

    # A client that reads, fails and retries with what it just read must recover.
    after_refusal = read_consultation(api, designer, subject["id"])
    assert after_refusal["version"] == after_children["version"]
    quote = validate_success(
        api.create_quote(
            f.quote_payload(subject["id"], after_refusal["version"]), acting),
        201)
    assert quote["opening_count"] == 1

    after_success = read_consultation(api, designer, subject["id"])
    assert after_success["version"] > after_refusal["version"]
    assert validate_success(
        api.present_quote(quote["id"], acting))["subtotal_cents"] == 4960

    # Nothing that happened to one appointment touched the other.
    assert read_consultation(api, designer,
                             bystander["id"])["version"] == bystander["version"]

    # The counter is the server's own: a supplied value is ignored, not rejected.
    third_lead = intake_lead(api, territory, customer_name="Cleo Marsh",
                             source="WALK_IN",
                             requested_at="2026-08-01T10:00:00.000Z")
    smuggled = validate_success(
        api.create_consultation(
            dict(f.consultation_payload(
                third_lead["id"], designer["id"],
                scheduled_start_at="2026-08-04T14:00:00.000Z",
                scheduled_end_at="2026-08-04T15:00:00.000Z"), version=99),
            acting), 201)
    assert smuggled["version"] == 1


def test_every_derived_counter_is_recounted_rather_than_incremented(api):
    """One opening configured twice, an order received and then remade: no tally drifts.

    "The first counter counts the appointment's openings whose `measure_status` is
    `MEASURED`, `CONFIGURED` or `QUOTED`; the second counts only those that are
    `CONFIGURED`; the third counts its check-outs still in status `OPEN`."

    "Re-configuration drives `CONFIGURED → CONFIGURED`: it overwrites `fabric_code`,
    `lift_system` and `motorization_option`, re-prices the opening from scratch rather
    than adjusting the previous figure, and raises the appointment's `version`."

    "The rates per square foot are 620 cents for `LT-SHEER`, 940 cents for `CL-LINEN`,
    1280 cents for `BO-THERMAL` and 1550 cents for `WD-FAUX`."

    "The order's wholesale exposure, `order_cost_cents`, is 42 percent of the summed
    `list_price_cents` of the named openings, rounded half up to a whole cent **once**,
    over the summed retail figure."

    "Receipt is the point at which the vendor's production slot is released and the
    franchise's exposure falls: the vendor's `open_order_count` and the territory's
    `open_order_exposure_cents` are both re-derived downward, the latter by that order's
    `order_cost_cents`."

    "A `SHARED_50_50` vendor's target is half of `remake_cost_cents` rounded **down** to a
    whole cent, and the territory's target is whatever remains — so on an odd cost of 7403
    cents the vendor takes 3701 and the territory 3702, the extra cent landing on the
    territory rather than on the manufacturer."

    Design: Corner/cross_cutting_complexity_layers/every_derived_counter_is_recounted_rather_than_incremented
    """
    territory = charter_territory(api, postal_codes=["30301"])
    designer = hire_designer(api, territory)
    vendor = onboard_vendor(api, **CORDED_AND_CORDLESS)
    headquarters = franchisor_headers()
    lead = intake_lead(api, territory)
    consultation = book_consultation(api, designer, lead)
    left = record_opening(api, designer, consultation, label="Left")
    right = record_opening(api, designer, consultation, label="Right")

    first = configure_opening(api, designer, left, fabric_code="LT-SHEER",
                              lift_system="CORDED")
    assert first["list_price_cents"] == 4960
    assert read_consultation(
        api, designer, consultation["id"])["configured_opening_count"] == 1

    # The same opening re-priced from scratch: 8.000 sqft at 1280 plus 1800.
    second = configure_opening(api, designer, left, fabric_code="BO-THERMAL",
                               lift_system="CORDLESS")
    assert second["list_price_cents"] == 12040
    assert read_consultation(
        api, designer, consultation["id"])["configured_opening_count"] == 1

    configure_opening(api, designer, right, fabric_code="LT-SHEER",
                      lift_system="CORDED")
    assert read_consultation(
        api, designer, consultation["id"])["configured_opening_count"] == 2

    quote = build_quote(api, designer, consultation)
    priced = present_quote(api, designer, quote)
    assert priced["subtotal_cents"] == 17000
    assert priced["install_fee_cents"] == 12500
    assert priced["pre_discount_total_cents"] == 29500
    assert priced["discount_pct"] == 0
    assert priced["discount_cents"] == 0
    assert priced["total_cents"] == 29500
    assert priced["net_sales_cents"] == 17000

    accepted = accept_quote(api, designer, quote)
    assert accepted["recognized_net_sales_cents"] == 17000

    order = place_order(api, territory, quote, [left["id"], right["id"]],
                        vendor)
    assert order["order_cost_cents"] == 7140
    assert validate_success(
        api.get_vendor(vendor["id"], headquarters))["open_order_count"] == 1
    assert read_territory(api, territory)["open_order_exposure_cents"] == 7140

    ship_order(api, vendor, order)
    receive_order(api, territory, order)
    assert validate_success(
        api.get_vendor(vendor["id"], headquarters))["open_order_count"] == 0
    banked = read_territory(api, territory)
    assert banked["open_order_exposure_cents"] == 0
    assert banked["net_sales_cents"] == 17000
    assert banked["royalty_accrued_cents"] == 935

    # The remake puts the same order back on both books, recomputed not remembered.
    remade = request_remake(api, territory, order, credit_scope="REPLACEMENT")
    assert remade["remake_cost_cents"] == 7140
    assert remade["vendor_absorbed_cents"] == 3570
    assert remade["territory_absorbed_cents"] == 3570
    assert remade["customer_absorbed_cents"] == 0
    assert validate_success(
        api.get_vendor(vendor["id"], headquarters))["open_order_count"] == 1
    reopened = read_territory(api, territory)
    assert reopened["open_order_exposure_cents"] == 7140
    assert reopened["remake_chargeback_cents"] == 3570

    # A fresh placement of the same row rather than a second row.
    replaced = read_order(api, territory, order["id"])
    assert replaced["status"] == "PLACED"
    assert replaced["remake_count"] == 1
    assert replaced["received_at"] is None
    assert replaced["order_cost_cents"] == 7140

    reconfigured = read_opening(api, designer, left["id"])
    assert reconfigured["list_price_cents"] == 12040
    assert reconfigured["fabric_code"] == "BO-THERMAL"

    live_orders, live_meta = validate_paginated(api.list_vendor_orders(
        headquarters, vendor_id=vendor["id"], status="PLACED"))
    assert ids_of(live_orders) == [order["id"]]
    assert_page_meta(live_meta, total_count=1, has_more=False)

    on_quote, quote_meta = validate_paginated(
        api.list_openings(designer_headers(designer["id"]),
                          quote_id=quote["id"]))
    assert ids_of(on_quote) == [left["id"], right["id"]]
    assert_page_meta(quote_meta, total_count=2, has_more=False)

    quotes, quotes_meta = validate_paginated(
        api.list_quotes(designer_headers(designer["id"]),
                        consultation_id=consultation["id"]))
    assert ids_of(quotes) == [quote["id"]]
    assert_page_meta(quotes_meta, total_count=1, has_more=False)

    appointments, appointment_meta = validate_paginated(
        api.list_consultations(designer_headers(designer["id"]),
                              designer_id=designer["id"]))
    assert ids_of(appointments) == [consultation["id"]]
    assert_page_meta(appointment_meta, total_count=1, has_more=False)


def test_paging_and_filtering_compose_over_one_collection(api):
    """Three routed and two queued leads, read through filters and through pages.

    "Every list endpoint accepts two optional query-string parameters. `limit` controls
    page size: it defaults to 10, may not be smaller than 1, and may not be larger than
    100. `offset` controls the starting position: it defaults to 0 and may not be
    negative. Both are echoed back in `meta`, alongside `total_count` (the number of rows
    matching the request's filters before pagination is applied) and `has_more` (true when
    rows remain beyond the current page)."

    "Unless a specific endpoint states otherwise, list results are ordered by `created_at`
    ascending — oldest row first."

    "Filter parameters on list endpoints are query-string parameters and combine
    conjunctively: a request supplying both a territory filter and a status filter returns
    only rows matching both."

    "If at least one `ACTIVE` territory does list the lead's `postal_code` but every such
    territory has an `open_leads_count` at or above its `lead_capacity_per_week`, the lead
    moves `NEW → QUEUED` with `territory_id` and `routed_at` left null — a retryable
    capacity outcome."

    Design: Corner/cross_cutting_complexity_layers/paging_and_filtering_compose_and_the_limit_domain_is_enforced
    """
    territory = charter_territory(api, postal_codes=["30301"],
                                 lead_capacity_per_week=3)
    owner = franchisee_headers(territory["id"])
    headquarters = franchisor_headers()

    intake = [
        ("Lead One", "WEB_FORM", "2026-08-01T08:00:00.000Z"),
        ("Lead Two", "WEB_FORM", "2026-08-01T09:00:00.000Z"),
        ("Lead Three", "REFERRAL", "2026-08-01T10:00:00.000Z"),
        ("Lead Four", "REFERRAL", "2026-08-01T11:00:00.000Z"),
        ("Lead Five", "WALK_IN", "2026-08-01T12:00:00.000Z"),
    ]
    leads = [intake_lead(api, territory, customer_name=name, source=source,
                         requested_at=requested_at)
             for name, source, requested_at in intake]
    routed, queued = leads[:3], leads[3:]

    for lead in routed:
        assert lead["status"] == "ROUTED"
        assert lead["territory_id"] == territory["id"]
    for lead in queued:
        assert lead["status"] == "QUEUED"
        assert lead["territory_id"] is None
        assert lead["routed_at"] is None

    # The two filters see different subsets of one table.
    by_territory, territory_meta = validate_paginated(
        api.list_leads(owner, territory_id=territory["id"]))
    assert ids_of(by_territory) == ids_of(routed)
    assert_page_meta(territory_meta, total_count=3, has_more=False, limit=10,
                     offset=0)
    assert_created_at_ascending(by_territory)

    by_status, status_meta = validate_paginated(
        api.list_leads(headquarters, status="QUEUED"))
    assert ids_of(by_status) == ids_of(queued)
    assert_page_meta(status_meta, total_count=2, has_more=False)

    # The paged walk over the whole collection, two rows at a time.
    first_page, first_meta = validate_paginated(
        api.list_leads(headquarters, limit=2, offset=0))
    assert ids_of(first_page) == ids_of(leads[:2])
    assert_page_meta(first_meta, total_count=5, has_more=True, limit=2,
                     offset=0)

    last_page, last_meta = validate_paginated(
        api.list_leads(headquarters, limit=2, offset=4))
    assert ids_of(last_page) == [leads[4]["id"]]
    assert_page_meta(last_meta, total_count=5, has_more=False, limit=2,
                     offset=4)

    # An offset past the end is an empty page, not a refusal.
    beyond = api.list_leads(headquarters, limit=2, offset=10)
    assert beyond.status_code == 200
    empty_rows, empty_meta = validate_paginated(beyond)
    assert empty_rows == []
    assert_page_meta(empty_meta, total_count=5, has_more=False, limit=2,
                     offset=10)

    # The top of the declared limit domain is admitted and returns everything.
    whole, whole_meta = validate_paginated(
        api.list_leads(headquarters, limit=100))
    assert ids_of(whole) == ids_of(leads)
    assert_page_meta(whole_meta, total_count=5, has_more=False, limit=100,
                     offset=0)

    # Conjunction, not union: every queued lead has a null territory.
    intersected, intersected_meta = validate_paginated(
        api.list_leads(owner, territory_id=territory["id"], status="QUEUED"))
    assert intersected == []
    assert_page_meta(intersected_meta, total_count=0, has_more=False)
