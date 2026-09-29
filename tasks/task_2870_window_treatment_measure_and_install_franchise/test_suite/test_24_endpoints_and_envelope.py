"""The published surface itself: the envelope, the projections and the control call."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_ROLE_NOT_PERMITTED,
    ERR_SAMPLE_KIT_NOT_FOUND,
    ERR_TERRITORY_NOT_ACTIVE,
)
from test_helpers.assertions import (
    assert_created_at_ascending,
    assert_date_string,
    assert_instant_equals,
    assert_instant_millis_format,
    assert_kit_conservation,
    assert_ledger_entry,
    assert_page_meta,
    ids_of,
)
from test_helpers.fixtures import (
    accept_quote,
    add_sample_kit,
    book_consultation,
    build_quote,
    charter_territory,
    checkout_kit,
    configure_opening,
    hire_designer,
    intake_lead,
    onboard_vendor,
    place_order,
    present_quote,
    read_designer,
    read_opening,
    read_territory,
    receive_order,
    record_opening,
    return_kit,
    schedule_install,
    ship_order,
)
from test_helpers.test_users import (
    designer_headers,
    franchisee_headers,
    franchisor_headers,
    vendor_rep_headers,
)

ABSENT_KIT_ID = "11111111-1111-4111-8111-111111111111"

CORDED_CAPACITY_FIVE = {"base_lead_time_days": 10, "motorization_extra_days": 3,
                        "cutoff_hour_utc": 15, "remake_policy": "SHARED_50_50",
                        "concurrent_capacity": 5,
                        "supported_lift_systems": ["CORDED"]}

HOLD_START = "2026-08-02T09:00:00.000Z"
HOLD_END = "2026-08-05T17:00:00.000Z"
THREE_DAYS_LATE = "2026-08-08T09:00:00.000Z"


def test_the_envelope_carries_both_response_types_and_the_pagination_block(api):
    """One library, four envelopes: a create, a single read, a paged list and a 404.

    "The `api_request_id` is a server-generated unique identifier for the request that
    starts with `req_`."

    "Pagination-related fields in `meta` (`limit`, `offset`, `total_count`,
    `has_more`) are included for list endpoints."

    "Both are echoed back in `meta`, alongside `total_count` (the number of rows
    matching the request's filters before pagination is applied) and `has_more` (true
    when rows remain beyond the current page)."

    "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."

    Design: Corner/endpoints/the_envelope_carries_both_response_types_and_the_pagination_block
    """
    territory = charter_territory(api, postal_codes=["30301"])
    owner = franchisee_headers(territory["id"])
    designer = hire_designer(api, territory)

    created = api.create_sample_kit(
        f.sample_kit_payload(territory["id"], kit_code="SHEERS-A",
                             replacement_value_cents=50000), owner)
    first = validate_success(created, 201)
    written = created.json()
    assert written["response_type"] == "object"
    assert written["meta"]["api_request_id"].startswith("req_")
    assert_instant_millis_format(written["meta"]["api_request_timestamp"],
                                 "api_request_timestamp")
    assert first["kit_code"] == "SHEERS-A"
    assert first["replacement_value_cents"] == 50000

    second = add_sample_kit(api, territory, kit_code="LINENS-B",
                            replacement_value_cents=42000)
    third = add_sample_kit(api, territory, kit_code="WOODS-C",
                           replacement_value_cents=61000)

    # A single-resource read puts the row itself under data, not a one-element array.
    single = api.get_sample_kit(first["id"], designer_headers(designer["id"]))
    assert validate_success(single)["id"] == first["id"]
    assert single.json()["response_type"] == "object"

    listing = api.list_sample_kits(owner, territory_id=territory["id"])
    assert listing.json()["response_type"] == "array"
    rows, meta = validate_paginated(listing)
    assert_page_meta(meta, total_count=3, has_more=False, limit=10, offset=0)
    assert ids_of(rows) == [first["id"], second["id"], third["id"]]
    assert_created_at_ascending(rows)

    page_one, first_page = validate_paginated(api.list_sample_kits(
        owner, territory_id=territory["id"], limit=2, offset=0))
    assert_page_meta(first_page, total_count=3, has_more=True, limit=2, offset=0)
    page_two, second_page = validate_paginated(api.list_sample_kits(
        owner, territory_id=territory["id"], limit=2, offset=2))
    assert_page_meta(second_page, total_count=3, has_more=False, limit=2,
                     offset=2)
    assert len(page_one) == 2
    assert len(page_two) == 1
    # The walk visits each of the three rows exactly once, with no repeats.
    assert ids_of(page_one) + ids_of(page_two) == [first["id"], second["id"],
                                                  third["id"]]

    missing = api.get_sample_kit(ABSENT_KIT_ID, owner)
    validate_error(missing, ERR_SAMPLE_KIT_NOT_FOUND, 404)
    refusal = missing.json()
    assert refusal["response_type"] == "error"
    assert isinstance(refusal["data"]["message"], str)
    assert refusal["data"]["message"] != ""
    assert set(refusal["meta"]) == {"api_request_id", "api_request_timestamp"}
    assert refusal["meta"]["api_request_id"].startswith("req_")

    # No read moved anything: the filtered collection is still three available kits.
    _, unchanged = validate_paginated(api.list_sample_kits(
        owner, territory_id=territory["id"], status="AVAILABLE"))
    assert_page_meta(unchanged, total_count=3, has_more=False)


def test_the_territory_read_is_a_pure_projection_of_nine_derived_counters(api):
    """Money, work in flight and inventory reconciled on one GET, then re-read unchanged.

    "Every count and running total described in this document as derived — a
    territory's open-lead count, its four money totals and its three kit counters, a
    kit's loan counters, a consultation's three opening and loan counters, a quote's
    opening counts, a vendor's open-order count, a designer's three incident counters —
    is recomputed from the rows it counts each time one of those rows changes state."

    "A successful placement stamps the order `PLACED` with `placed_at` from the logical
    clock, `remake_count` zero and `credit_scope` `NONE`, stores the three lead-time
    results, re-derives the vendor's `open_order_count` and the territory's
    `open_order_exposure_cents` — which sums `order_cost_cents` across the territory's
    orders in status `PLACED`, `SHIPPED` or `REMAKE_REQUESTED` — and increments the
    quote's `version`."

    "For any territory, `available_kit_count` plus `on_loan_kit_count` plus
    `lost_kit_count` equals the total number of kit rows the territory owns;
    `on_loan_kit_count` equals the number of check-outs in status `OPEN` whose kit
    belongs to that territory; and a kit's `open_loan_count` is always either zero or
    one, and is one exactly when the kit's `status` is `ON_LOAN`."

    Design: Corner/endpoints/the_territory_read_is_a_pure_projection_of_nine_derived_counters
    """
    territory = charter_territory(api, postal_codes=["30301"])
    owner = franchisee_headers(territory["id"])
    designer = hire_designer(api, territory)
    loaned = add_sample_kit(api, territory, kit_code="SHEERS-A",
                            replacement_value_cents=50000)
    shelved = add_sample_kit(api, territory, kit_code="LINENS-B",
                             replacement_value_cents=42000)
    vendor = onboard_vendor(api, **CORDED_CAPACITY_FIVE)
    lead = intake_lead(api, territory, customer_name="Ana Ruiz")
    consultation = book_consultation(api, designer, lead)
    checkout_kit(api, designer, loaned, consultation, HOLD_START, HOLD_END)

    left = configure_opening(
        api, designer,
        record_opening(api, designer, consultation, label="Left"),
        fabric_code="LT-SHEER", lift_system="CORDED")
    right = configure_opening(
        api, designer,
        record_opening(api, designer, consultation, label="Right"),
        fabric_code="LT-SHEER", lift_system="CORDED")
    quote = build_quote(api, designer, consultation)
    present_quote(api, designer, quote)
    quote = accept_quote(api, designer, quote)
    assert quote["net_sales_cents"] == 9920
    order = place_order(api, territory, quote, [left["id"], right["id"]], vendor)
    assert order["order_cost_cents"] == 4166

    counters = read_territory(api, territory)

    # Money: the accepted quote's net sales and the royalty on it, nothing remade.
    assert counters["net_sales_cents"] == 9920
    assert counters["royalty_accrued_cents"] == 546
    assert counters["remake_chargeback_cents"] == 0

    # Work in flight: one PLACED order over both openings, rounded once over 9920.
    assert counters["open_order_exposure_cents"] == order["order_cost_cents"]
    assert counters["open_order_exposure_cents"] == 4166
    # Acceptance already converted the only lead, so no lead is open any more.
    assert counters["open_leads_count"] == 0
    assert validate_success(api.get_lead(lead["id"], owner))["status"] == "CONVERTED"

    # Inventory: one kit in the van, one on the shelf, none written off.
    assert counters["available_kit_count"] == 1
    assert counters["on_loan_kit_count"] == 1
    assert counters["lost_kit_count"] == 0
    assert_kit_conservation(counters, 2)
    assert validate_success(
        api.get_sample_kit(loaned["id"], owner))["status"] == "ON_LOAN"
    assert validate_success(
        api.get_sample_kit(shelved["id"], owner))["status"] == "AVAILABLE"

    # A read is not a mutation: the same row, twice, with its version standing still.
    headquarters = validate_success(
        api.get_territory(territory["id"], franchisor_headers()))
    assert headquarters == counters
    assert read_territory(api, territory) == counters

    # The endpoint lists only the two money-bearing roles.
    validate_error(
        api.get_territory(territory["id"], designer_headers(designer["id"])),
        ERR_ROLE_NOT_PERMITTED, 403)


def test_setting_the_clock_moves_time_without_advancing_any_row(api):
    """Three days pass over an open loan and nothing happens until the kit comes back.

    "A `Franchisor` may move the clock to any supplied `current_utc` instant."

    "Moving the clock is a pure test-driving operation: it advances no state machine and
    re-runs no calculation."

    "Quote expiry, remake windows and rolling liability windows are all evaluated
    **lazily**, by the next business request that touches the affected row."

    "When `late_fee_cents` is greater than zero a ledger row of type `SAMPLE_LATE_FEE`
    is appended for that amount, with `basis_cents` equal to the kit's
    `replacement_value_cents`, `source_entity_type` `SAMPLE_CHECKOUT` and `memo`
    `sample_late`; a fee of zero writes no row."

    Design: Corner/endpoints/setting_the_clock_moves_time_without_advancing_any_row
    """
    territory = charter_territory(api, postal_codes=["30301"])
    owner = franchisee_headers(territory["id"])
    designer = hire_designer(api, territory)
    acting = designer_headers(designer["id"])
    kit = add_sample_kit(api, territory, kit_code="SHEERS-A",
                         replacement_value_cents=50000)
    lead = intake_lead(api, territory, customer_name="Ana Ruiz")
    consultation = book_consultation(api, designer, lead)
    checkout = checkout_kit(api, designer, kit, consultation, HOLD_START,
                            HOLD_END)
    assert_instant_equals(checkout["due_at"], HOLD_END, "due_at")
    assert checkout["late_fee_cents"] == 0
    assert checkout["days_late"] == 0

    # The clock endpoint lists headquarters only, and the refusal moves nothing.
    validate_error(api.set_clock(THREE_DAYS_LATE, acting),
                   ERR_ROLE_NOT_PERMITTED, 403)
    still_early = validate_success(api.get_sample_checkout(checkout["id"],
                                                           acting))
    assert still_early["days_late"] == 0

    moved = api.set_clock(THREE_DAYS_LATE, franchisor_headers())
    # A control operation, not a create: 200 with an empty data object.
    assert validate_success(moved) == {}
    assert moved.json()["response_type"] == "object"

    stale = validate_success(api.get_sample_checkout(checkout["id"], acting))
    assert stale["status"] == "OPEN"
    assert stale["late_fee_cents"] == 0
    assert stale["days_late"] == 0
    assert validate_success(
        api.get_sample_kit(kit["id"], owner))["status"] == "ON_LOAN"
    _, quiet = validate_paginated(
        api.list_ledger_entries(territory["id"], owner))
    assert_page_meta(quiet, total_count=0, has_more=False)

    # The business request is what reads the clock: two days sixteen hours is three days.
    returned = return_kit(api, designer, checkout)
    assert returned["status"] == "RETURNED"
    assert returned["days_late"] == 3
    assert returned["late_fee_cents"] == 2250

    rows, meta = validate_paginated(
        api.list_ledger_entries(territory["id"], owner))
    assert_page_meta(meta, total_count=1, has_more=False)
    assert_ledger_entry(rows[0], "SAMPLE_LATE_FEE", 2250, 50000, "sample_late",
                        "SAMPLE_CHECKOUT", source_entity_id=checkout["id"],
                        territory_id=territory["id"])

    settled = read_territory(api, territory)
    assert settled["available_kit_count"] == 1
    assert settled["on_loan_kit_count"] == 0
    assert settled["lost_kit_count"] == 0


def test_patching_a_territory_only_cascades_when_the_status_field_is_present(api):
    """A terms patch is surgical, a status patch closes the door, and ACTIVE reopens it.

    "Headquarters may later re-state a territory's standing or its terms, supplying any
    subset of `status`, `royalty_rate_pct`, `lead_capacity_per_week`,
    `credit_limit_cents` and `liability_window`; the row's `version` increments."

    "Only an `ACTIVE` territory receives routed leads or permits new work; `PROBATION`,
    `SUSPENDED` and `TERMINATED` all block it identically, with
    `ERR_TERRITORY_NOT_ACTIVE` (HTTP 409)."

    "Closing a franchise to new work does not disturb rows already in flight — a
    suspension cancels nothing retroactively."

    Design: Corner/endpoints/patching_a_territory_only_cascades_when_the_status_field_is_present
    """
    territory = charter_territory(api, postal_codes=["30301"])
    owner = franchisee_headers(territory["id"])
    designer = hire_designer(api, territory)
    acting = designer_headers(designer["id"])
    first_lead = intake_lead(api, territory, customer_name="Ana Ruiz")
    second_lead = intake_lead(api, territory, customer_name="Bo Chen",
                              source="REFERRAL",
                              requested_at="2026-08-01T09:00:00.000Z")
    booked = book_consultation(api, designer, first_lead)

    # Routing the two leads already re-derived the counters, so read the version now.
    before = read_territory(api, territory)

    # A franchisee cannot re-state its own standing.
    validate_error(api.patch_territory(territory["id"],
                                       f.territory_patch(status="PROBATION"),
                                       owner),
                   ERR_ROLE_NOT_PERMITTED, 403)

    terms = validate_success(api.patch_territory(
        territory["id"], f.territory_patch(royalty_rate_pct=0.07),
        franchisor_headers()))
    assert terms["royalty_rate_pct"] == 0.07
    assert terms["status"] == "ACTIVE"
    assert terms["lead_capacity_per_week"] == 5
    assert terms["credit_limit_cents"] == 2000000
    assert terms["liability_window"] == "ROLLING_180D"
    assert terms["version"] == before["version"] + 1

    # Still ACTIVE, so the fixture was workable before the standing changed.
    second_booking = book_consultation(
        api, designer, second_lead,
        scheduled_start_at="2026-08-04T14:00:00.000Z",
        scheduled_end_at="2026-08-04T15:00:00.000Z")
    assert second_booking["status"] == "SCHEDULED"

    probation = validate_success(api.patch_territory(
        territory["id"], f.territory_patch(status="PROBATION"),
        franchisor_headers()))
    assert probation["status"] == "PROBATION"
    assert probation["version"] == terms["version"] + 1

    # Rows already in flight are untouched by the change of standing.
    for standing in (booked, second_booking):
        assert validate_success(api.get_consultation(
            standing["id"], owner))["status"] == "SCHEDULED"
    assert read_designer(api, territory, designer["id"])["status"] == "ACTIVE"
    assert validate_success(
        api.get_lead(first_lead["id"], owner))["status"] == "ROUTED"

    third = f.consultation_payload(
        second_lead["id"], designer["id"],
        scheduled_start_at="2026-08-05T14:00:00.000Z",
        scheduled_end_at="2026-08-05T15:00:00.000Z")
    validate_error(api.create_consultation(third, acting),
                   ERR_TERRITORY_NOT_ACTIVE, 409)
    _, refused = validate_paginated(
        api.list_consultations(owner, designer_id=designer["id"]))
    assert_page_meta(refused, total_count=2, has_more=False)

    # The gate is read live from the grandparent rather than copied onto the children.
    reopened = validate_success(api.patch_territory(
        territory["id"], f.territory_patch(status="ACTIVE"),
        franchisor_headers()))
    assert reopened["status"] == "ACTIVE"
    admitted = validate_success(api.create_consultation(third, acting), 201)
    assert admitted["status"] == "SCHEDULED"

    # A rate change accrues nothing: the new rate applies to future acceptances only.
    assert read_territory(api, territory)["royalty_accrued_cents"] == 0
    _, ledger = validate_paginated(
        api.list_ledger_entries(territory["id"], owner))
    assert_page_meta(ledger, total_count=0, has_more=False)


def test_every_filtered_list_is_the_reverse_of_one_declared_foreign_key(api):
    """Four keys walked backwards, including the self-referential one and an intersection.

    "Each entity has a single-resource read endpoint, and the list endpoints accept
    filter parameters that invert each stored reference: designers and sample kits and
    leads by `territory_id`, consultations by `lead_id` and `designer_id`, sample
    check-outs by `sample_kit_id` and `consultation_id`, openings by `consultation_id`,
    by `quote_id` and by the self-referential `replaces_opening_id`, quotes by
    `consultation_id`, vendor orders by `quote_id` and `vendor_id`, and install jobs by
    `vendor_order_id` and `designer_id`."

    "Filter parameters on list endpoints are query-string parameters and combine
    conjunctively: a request supplying both a territory filter and a status filter
    returns only rows matching both."

    "Status filters are available alongside them — `status` on designers, sample kits,
    leads, consultations, sample check-outs, quotes and vendor orders, `measure_status`
    and `install_outcome` on openings, and `install_status` and `commissioning_status`
    on install jobs."

    Design: Corner/endpoints/every_filtered_list_is_the_reverse_of_one_declared_foreign_key
    """
    north = charter_territory(api, legal_name="Northgate Blinds LLC",
                              postal_codes=["30301"])
    south = charter_territory(api, legal_name="Southmark Window Fashions",
                              postal_codes=["30401"])
    dana = hire_designer(api, north, full_name="Dana Reed",
                         home_postal_code="30301")
    priya = hire_designer(api, south, full_name="Priya Nair",
                          home_postal_code="30401")
    stocked = add_sample_kit(api, north, kit_code="SHEERS-A")
    untouched = add_sample_kit(api, south, kit_code="SHEERS-B")
    vendor = onboard_vendor(api, **CORDED_CAPACITY_FIVE)

    ana = intake_lead(api, north, customer_name="Ana Ruiz",
                      postal_code="30301")
    bo = intake_lead(api, south, customer_name="Bo Chen", postal_code="30401",
                     requested_at="2026-08-01T09:00:00.000Z")
    busy = book_consultation(api, dana, ana, service_postal_code="30301")
    barren = book_consultation(api, priya, bo, service_postal_code="30401")

    loan = checkout_kit(api, dana, stocked, busy, HOLD_START,
                        "2026-08-04T17:00:00.000Z")
    superseded = record_opening(api, dana, busy, label="First attempt")
    remeasure = configure_opening(
        api, dana,
        record_opening(api, dana, busy, label="Re-measure",
                       replaces_opening_id=superseded["id"]),
        fabric_code="LT-SHEER", lift_system="CORDED")

    quote = build_quote(api, dana, busy)
    present_quote(api, dana, quote)
    quote = accept_quote(api, dana, quote)
    order = place_order(api, north, quote, [remeasure["id"]], vendor)
    ship_order(api, vendor, order)
    receive_order(api, north, order)
    job = schedule_install(api, north, order, dana)

    local = designer_headers(dana["id"])
    away = designer_headers(priya["id"])

    # Both the superseded opening and its re-measure hang off the one appointment.
    rows, meta = validate_paginated(
        api.list_openings(local, consultation_id=busy["id"]))
    assert_page_meta(meta, total_count=2, has_more=False)
    assert ids_of(rows) == [superseded["id"], remeasure["id"]]

    # Naming a childless parent is an empty page, not a 404.
    childless, childless_meta = validate_paginated(
        api.list_openings(away, consultation_id=barren["id"]))
    assert childless == []
    assert_page_meta(childless_meta, total_count=0, has_more=False)

    # The self-referential key reverses exactly once and in one direction only.
    supersedes, supersedes_meta = validate_paginated(
        api.list_openings(local, replaces_opening_id=superseded["id"]))
    assert_page_meta(supersedes_meta, total_count=1, has_more=False)
    assert ids_of(supersedes) == [remeasure["id"]]
    _, backwards = validate_paginated(
        api.list_openings(local, replaces_opening_id=remeasure["id"]))
    assert_page_meta(backwards, total_count=0, has_more=False)

    # Two filters intersect rather than union: only the configured re-measure was swept.
    attached, attached_meta = validate_paginated(api.list_openings(
        local, quote_id=quote["id"], measure_status="QUOTED"))
    assert_page_meta(attached_meta, total_count=1, has_more=False)
    assert ids_of(attached) == [remeasure["id"]]

    # The far territory's kit exists and has never been loaned.
    _, never = validate_paginated(api.list_sample_checkouts(
        franchisee_headers(south["id"]), sample_kit_id=untouched["id"]))
    assert_page_meta(never, total_count=0, has_more=False)
    loans, loans_meta = validate_paginated(api.list_sample_checkouts(
        franchisee_headers(north["id"]), sample_kit_id=stocked["id"]))
    assert_page_meta(loans_meta, total_count=1, has_more=False)
    assert ids_of(loans) == [loan["id"]]

    jobs, jobs_meta = validate_paginated(api.list_install_jobs(
        franchisee_headers(north["id"]), vendor_order_id=order["id"]))
    assert_page_meta(jobs_meta, total_count=1, has_more=False)
    assert ids_of(jobs) == [job["id"]]

    # The status filter narrows the same manufacturer's own collection.
    manufacturer = vendor_rep_headers(vendor["id"])
    received, received_meta = validate_paginated(api.list_vendor_orders(
        manufacturer, vendor_id=vendor["id"], status="RECEIVED"))
    assert_page_meta(received_meta, total_count=1, has_more=False)
    assert ids_of(received) == [order["id"]]
    _, still_placed = validate_paginated(api.list_vendor_orders(
        manufacturer, vendor_id=vendor["id"], status="PLACED"))
    assert_page_meta(still_placed, total_count=0, has_more=False)


def test_one_placement_over_three_openings_is_costed_and_scheduled_as_a_set(api):
    """Three openings, one order, one rounding, one motor adder and one frozen channel.

    "Step two computes `install_fee_cents` as a base labour charge of 7500 cents, plus
    2500 cents for each attached opening, plus a further 4500 cents for each attached
    opening that carries a motor package — that is, 2500 cents multiplied by
    `opening_count` plus 4500 cents multiplied by `motorized_opening_count`, added to
    the 7500-cent base."

    "The order's wholesale exposure, `order_cost_cents`, is 42 percent of the summed
    `list_price_cents` of the named openings, rounded half up to a whole cent **once**,
    over the summed retail figure."

    "Second the adders: the raw day count is the vendor's `base_lead_time_days`, plus
    its `motorization_extra_days` when any opening on the order carries a
    `motorization_option` other than `NONE`."

    "A new job is stamped `install_status` `SCHEDULED`, and its
    `motorized_channel_count` is **frozen** at creation as the number of openings in
    the order's `opening_ids` whose `motorization_option` is anything other than
    `NONE`."

    Design: Corner/endpoints/one_placement_over_three_openings_is_costed_and_scheduled_as_a_set
    """
    territory = charter_territory(api, postal_codes=["30301"])
    owner = franchisee_headers(territory["id"])
    designer = hire_designer(api, territory,
                             certifications=["MOTORIZATION"])
    vendor = onboard_vendor(api, base_lead_time_days=10,
                            motorization_extra_days=3, cutoff_hour_utc=15,
                            remake_policy="SHARED_50_50",
                            concurrent_capacity=5,
                            supported_lift_systems=["CORDED", "MOTORIZED"],
                            supported_hub_platforms=["ALEXA"])
    lead = intake_lead(api, territory, customer_name="Ana Ruiz")
    consultation = book_consultation(
        api, designer, lead, scheduled_end_at="2026-08-03T16:00:00.000Z")

    plan = (("Set A left", "OFFICE", "CORDED", None),
            ("Set A right", "OFFICE", "CORDED", None),
            ("Set A motorized", "LIVING_ROOM", "MOTORIZED", "BATTERY"),
            ("Set B left", "OFFICE", "CORDED", None),
            ("Set B right", "OFFICE", "CORDED", None))
    openings = [
        configure_opening(
            api, designer,
            record_opening(api, designer, consultation, label=label,
                           room_type=room),
            fabric_code="LT-SHEER", lift_system=lift,
            motorization_option=motor)
        for label, room, lift, motor in plan
    ]
    left, right, motorized, spare_left, spare_right = openings
    assert left["list_price_cents"] == 4960
    assert motorized["list_price_cents"] == 17460

    quote = build_quote(api, designer, consultation)
    assert quote["opening_count"] == 5
    assert quote["motorized_opening_count"] == 1
    quote = present_quote(api, designer, quote)
    assert quote["subtotal_cents"] == 37300
    assert quote["install_fee_cents"] == 24500
    assert quote["pre_discount_total_cents"] == 61800
    assert quote["discount_pct"] == 0
    assert quote["total_cents"] == 61800
    quote = accept_quote(api, designer, quote)

    # Three openings produce ONE row, costed once over 27380 rather than three times.
    set_a = place_order(api, territory, quote,
                        [left["id"], right["id"], motorized["id"]], vendor)
    assert len(set_a["opening_ids"]) == 3
    assert sorted(set_a["opening_ids"]) == sorted(
        [left["id"], right["id"], motorized["id"]])
    assert set_a["order_cost_cents"] == 11500
    assert set_a["lead_time_days"] == 13
    assert set_a["effective_placement_date"] == "2026-08-01"
    assert set_a["promised_ship_date"] == "2026-08-14"
    assert_date_string(set_a["promised_ship_date"], "promised_ship_date")

    # The same vendor at the same instant, without a motor, waits ten days.
    set_b = place_order(api, territory, quote,
                        [spare_left["id"], spare_right["id"]], vendor)
    assert set_b["order_cost_cents"] == 4166
    assert set_b["lead_time_days"] == 10
    assert set_b["promised_ship_date"] == "2026-08-11"

    _, placements = validate_paginated(
        api.list_vendor_orders(owner, quote_id=quote["id"]))
    assert_page_meta(placements, total_count=2, has_more=False)
    assert read_territory(api, territory)["open_order_exposure_cents"] == 15666

    ship_order(api, vendor, set_a)
    received = receive_order(api, territory, set_a)
    job = schedule_install(api, territory, received, designer,
                           scheduled_end_at="2026-08-20T13:00:00.000Z")
    # Only one member carries a motor, though the job covers three openings.
    assert job["motorized_channel_count"] == 1
    assert job["commissioning_status"] == "PENDING"
    assert job["paired_channel_count"] == 0

    # Exposure drops by the whole set at once when that set is received.
    assert read_territory(api, territory)["open_order_exposure_cents"] == 4166
    for member in (left, right, motorized):
        current = read_opening(api, designer, member["id"])
        assert current["quote_id"] == quote["id"]
        assert current["measure_status"] == "QUOTED"
        assert current["install_outcome"] == "PENDING"
