"""Layer claims: both concurrency guards, one retroactive cascade, pagination, filters, sweeps."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_INVALID_REQUEST,
    ERR_STALE_LEASE_VERSION,
    ERR_STALE_PARCEL_VERSION,
)
from test_helpers.assertions import (
    assert_acres_equals,
    assert_cents_equals,
    assert_instant_equals,
    assert_null,
    assert_page_meta,
    assert_score_equals,
    assert_status,
    assert_version_advanced,
    assert_version_is,
)
from test_helpers.factories import invoice_payload, option_payload
from test_helpers.fixtures import (
    accept_option,
    book_site_access,
    client,
    execute_option,
    exercise_option,
    parcels_page,
    post_security,
    publish_setback_rule,
    read_booking,
    read_consent,
    read_landowner,
    read_lease,
    read_parcel,
    register_landowner,
    register_parcel,
    request_consent,
    rescreen,
    send_option,
    set_clock,
)
from test_helpers.test_users import (
    LAND_AGENT,
    PAYMENT_ADMIN,
    PORTFOLIO_MANAGER,
    PORTFOLIO_MANAGER_2,
    TITLE_COUNSEL,
)

SANDHILL = {
    "legal_name": "Sandhill Prairie LLC",
    "entity_type": "LLC",
    "mailing_state": "TX",
    "contact_email": "ops@sandhill.example",
    "w9_on_file": True,
    "payment_hold": False,
}

CAPROCK_TRUST = {
    "legal_name": "Caprock Grazing Trust",
    "entity_type": "TRUST",
    "mailing_state": "TX",
    "contact_email": "trustee@caprock.example",
    "w9_on_file": True,
    "payment_hold": False,
}

CLEAN_COUNTY = "48451"

CLEAN_INPUTS = {
    "county_fips": CLEAN_COUNTY,
    "gross_acres": 200.00,
    "interconnection_distance_km": 3.50,
    "resource_capacity_factor": 0.38,
    "slope_pct": 4.0,
    "title_condition_grade": "B",
    "zoning_code": "AG2",
}

PER_ACRE_TERMS = {
    "option_term_days": 365,
    "option_fee_per_acre_cents": 2500,
    "extension_count_allowed": 1,
    "extension_fee_per_acre_cents": 3000,
    "rent_structure_type": "PER_ACRE",
    "base_rent_per_acre_cents": 120000,
    "royalty_rate_bps": 0,
    "escalator_pct_bps": 200,
    "escalator_mode": "SIMPLE",
}


def _owner_and_tract(apn: str = "R-9001-001", **overrides):
    """One owner and one clean tract in an unregulated county."""
    landowner_id = register_landowner(**SANDHILL)["id"]
    inputs = dict(CLEAN_INPUTS)
    inputs.update(overrides)
    return landowner_id, register_parcel(landowner_id, apn=apn, **inputs)


def _tract_rescreened_without_changing_anything():
    """A tract re-screened under the same desktop variant it was born under."""
    landowner_id, parcel = _owner_and_tract()
    assert_acres_equals(parcel["buildable_acres"], 200.00, "buildable_acres")
    assert_score_equals(parcel["screening_score"], 82.15, "screening_score")
    assert_status(parcel, "QUALIFIED", "parcel")
    rescreened = rescreen(parcel["id"], "DESKTOP")
    return landowner_id, parcel, rescreened


def test_a_rescreen_that_changes_nothing_still_moves_the_version():
    """
    The same desktop variant is re-run over the same inputs, so every observable figure
    comes back identical — and the version still advances by one, because the write
    itself is the mutation.

    PRD: "Re-screening re-derives the acreage, recomputes the score under the requested
    variant, re-evaluates qualification and resynchronises the landowner posture, and
    increments the parcel's `version`."

    Design: Corner/complexity_layers/option_create_with_a_stale_parcel_version_returns_412
    """
    _landowner_id, parcel, rescreened = _tract_rescreened_without_changing_anything()

    assert_score_equals(rescreened["screening_score"], 82.15, "screening_score")
    assert_acres_equals(rescreened["buildable_acres"], 200.00, "buildable_acres")
    assert_status(rescreened, "QUALIFIED", "parcel")
    # PRD 2.4 shows a cascade-driven parcel write landing "two or three higher",
    # so only the advance itself is pinned, not the size of the step.
    assert_version_advanced(parcel, rescreened, "rescreened parcel")


def test_a_draft_quoting_the_version_from_before_the_rescreen_is_refused():
    """
    The client's snapshot is stale only in its version number: nothing it could have
    read off the parcel has changed. The guard is on the counter, so the draft is
    refused and no agreement is written.

    PRD: "If that value does not equal the parcel's current stored `version`, the create
    is rejected with `ERR_STALE_PARCEL_VERSION` and HTTP 412."

    Design: Corner/complexity_layers/option_create_with_a_stale_parcel_version_returns_412
    """
    landowner_id, parcel, _rescreened = _tract_rescreened_without_changing_anything()

    response = client().create_option_agreement(
        option_payload(parcel["id"], landowner_id, parcel["version"], **PER_ACRE_TERMS),
        LAND_AGENT,
    )

    validate_error(response, ERR_STALE_PARCEL_VERSION, 412)
    _rows, meta = validate_paginated(
        client().list_option_agreements(LAND_AGENT, {"parcel_id": parcel["id"]})
    )
    assert_page_meta(meta, total_count=0)


def test_the_same_draft_quoting_the_rescreened_version_is_accepted():
    """
    Re-reading the parcel is the whole remedy, and the accepted draft then advances the
    parcel's own version again — which is why a client drafting twice must re-read in
    between.

    PRD: "A successful draft itself increments the parcel's `version`, so a client
    drafting two options against one parcel must re-read the parcel between them."

    Design: Corner/complexity_layers/option_create_with_a_stale_parcel_version_returns_412
    """
    landowner_id, parcel, rescreened = _tract_rescreened_without_changing_anything()
    refused = client().create_option_agreement(
        option_payload(parcel["id"], landowner_id, parcel["version"], **PER_ACRE_TERMS),
        LAND_AGENT,
    )
    validate_error(refused, ERR_STALE_PARCEL_VERSION, 412)

    response = client().create_option_agreement(
        option_payload(
            parcel["id"], landowner_id, rescreened["version"], **PER_ACRE_TERMS
        ),
        LAND_AGENT,
    )

    option = validate_success(response, 201)
    assert_status(option, "DRAFT", "option")
    assert_version_is(
        read_parcel(parcel["id"]), rescreened["version"] + 1, "parcel after the draft"
    )


def _lease_whose_version_moved_under_the_security_posting():
    """A lease read at exercise, then staled by the payables role's own posting."""
    landowner_id, parcel = _owner_and_tract()
    option = validate_success(
        client().create_option_agreement(
            option_payload(
                parcel["id"], landowner_id, parcel["version"], **PER_ACRE_TERMS
            ),
            LAND_AGENT,
        ),
        201,
    )
    send_option(option["id"])
    accept_option(option["id"], landowner_id)
    execute_option(option["id"], PORTFOLIO_MANAGER)
    lease = exercise_option(option["id"], "NOE-2026-0001", PORTFOLIO_MANAGER_2)
    assert_cents_equals(
        lease["total_security_required_cents"], 10450000, "total_security_required_cents"
    )
    posted = post_security(lease["id"], 10450000)
    assert_cents_equals(posted["security_posted_cents"], 10450000, "security_posted_cents")
    assert_version_is(posted, lease["version"] + 1, "lease after posting")
    return lease, posted


def test_an_invoice_quoting_the_version_from_before_the_posting_is_refused():
    """
    The second concurrency pair guards a different entity under a differently named
    field, and the write that staled it was the payables role's own: the administrator
    posts the security and then quotes the version from before it.

    PRD: "If that value does not equal the lease's current stored `version`, the create
    is rejected with `ERR_STALE_LEASE_VERSION` and HTTP 412."

    Design: Corner/complexity_layers/invoice_create_with_a_stale_lease_version_returns_412
    """
    lease, _posted = _lease_whose_version_moved_under_the_security_posting()

    response = client().create_rent_invoice(
        lease["id"], invoice_payload(lease["version"], 1, 0), PAYMENT_ADMIN
    )

    validate_error(response, ERR_STALE_LEASE_VERSION, 412)
    _rows, meta = validate_paginated(
        client().list_rent_invoices(PAYMENT_ADMIN, {"lease_agreement_id": lease["id"]})
    )
    assert_page_meta(meta, total_count=0)


def test_the_same_invoice_quoting_the_posted_version_bills_the_provisional_variant():
    """
    Re-quoted against the current version the invoice is raised, and it is computed
    under the variant the lease's recording dimension reads at that instant: the
    memorandum is still unrecorded, so the figure is the provisional one.

    PRD: "This guard exists because the variant an invoice is computed under is read from
    the lease's `recording_status` at the instant of creation, and because a replacement
    invoice for a period whose prior invoice was voided legitimately supersedes it: a
    stale lease snapshot would silently bill the wrong variant."

    Design: Corner/complexity_layers/invoice_create_with_a_stale_lease_version_returns_412
    """
    lease, posted = _lease_whose_version_moved_under_the_security_posting()
    refused = client().create_rent_invoice(
        lease["id"], invoice_payload(lease["version"], 1, 0), PAYMENT_ADMIN
    )
    validate_error(refused, ERR_STALE_LEASE_VERSION, 412)

    response = client().create_rent_invoice(
        lease["id"], invoice_payload(posted["version"], 1, 0), PAYMENT_ADMIN
    )

    invoice = validate_success(response, 201)
    assert invoice["rent_variant"] == "PROVISIONAL", invoice["rent_variant"]
    assert_acres_equals(invoice["acre_basis"], 200.00, "acre_basis")
    assert_cents_equals(invoice["gross_rent_cents"], 24000000, "gross_rent_cents")
    assert read_lease(lease["id"])["recording_status"] == "UNRECORDED"


def _two_tracts_of_one_owner_before_any_ordinance():
    """A hundred-acre tract and a two-hundred-acre tract, both freely buildable."""
    landowner_id = register_landowner(**SANDHILL)["id"]
    small = register_parcel(
        landowner_id, apn="R-9001-001", **dict(CLEAN_INPUTS, gross_acres=100.00)
    )
    large = register_parcel(landowner_id, apn="R-9001-002", **CLEAN_INPUTS)
    assert_status(small, "QUALIFIED", "small parcel")
    assert_acres_equals(small["buildable_acres"], 100.00, "buildable_acres")
    assert_status(large, "QUALIFIED", "large parcel")
    assert_acres_equals(large["buildable_acres"], 200.00, "buildable_acres")
    assert_status(read_landowner(landowner_id), "ENGAGED", "landowner")
    return landowner_id, small, large


def test_one_publication_re_derives_every_parcel_in_the_jurisdiction():
    """
    A single ordinance at a quarter-acre per deeded acre reaches both tracts and lands
    differently on each: the smaller falls through the eighty-acre floor and reverts to
    screening, while the larger keeps a hundred and fifty acres and stays qualified.

    PRD: "Every existing parcel whose `county_fips` equals the new rule's
    `jurisdiction_code` is re-processed in `created_at` ascending order, and each one runs
    the full four-procedure chain of §2.8: acreage re-derivation, screening
    re-computation, qualification re-evaluation and landowner posture synchronisation."

    Design: Corner/complexity_layers/setback_rule_publication_cascades_to_every_matching_parcel
    """
    _landowner_id, small, large = _two_tracts_of_one_owner_before_any_ordinance()

    publish_setback_rule(
        jurisdiction_code=CLEAN_COUNTY,
        rule_type="PROPERTY_LINE",
        setback_feet=500,
        encumbrance_rate_per_acre=0.2500,
        consent_waivable=True,
    )

    after_small = read_parcel(small["id"])
    assert_acres_equals(after_small["raw_setback_acres"], 25.00, "raw_setback_acres")
    assert_acres_equals(
        after_small["consent_released_acres"], 0.00, "consent_released_acres"
    )
    assert_acres_equals(
        after_small["setback_encumbered_acres"], 25.00, "setback_encumbered_acres"
    )
    assert_acres_equals(after_small["buildable_acres"], 75.00, "buildable_acres")
    assert_status(after_small, "SCREENING", "small parcel")
    after_large = read_parcel(large["id"])
    assert_acres_equals(after_large["raw_setback_acres"], 50.00, "raw_setback_acres")
    assert_acres_equals(
        after_large["setback_encumbered_acres"], 50.00, "setback_encumbered_acres"
    )
    assert_acres_equals(after_large["buildable_acres"], 150.00, "buildable_acres")
    assert_status(after_large, "QUALIFIED", "large parcel")


def test_the_cascade_moves_both_versions_without_touching_either_score():
    """
    Acreage does not feed the screening score, so the retroactive re-derivation leaves
    both scores exactly where intake put them while bumping both rows — and the owner
    stays engaged, because one of the two tracts survived the ordinance.

    PRD: "`created_at` is the ISO 8601 UTC instant at which the row was inserted,
    rendered with exactly three fractional digits; `updated_at` is the same format and is
    refreshed on every mutation of the row, including mutations the row's owner did not
    request but a cascade performed; and `version` is an integer that starts at 1 on
    creation and increases by exactly 1 on every mutation, again including cascade-driven
    mutations."

    Design: Corner/complexity_layers/setback_rule_publication_cascades_to_every_matching_parcel
    """
    landowner_id, small, large = _two_tracts_of_one_owner_before_any_ordinance()

    publish_setback_rule(
        jurisdiction_code=CLEAN_COUNTY,
        rule_type="PROPERTY_LINE",
        setback_feet=500,
        encumbrance_rate_per_acre=0.2500,
        consent_waivable=True,
    )

    after_small = read_parcel(small["id"])
    after_large = read_parcel(large["id"])
    assert_score_equals(after_small["screening_score"], 82.15, "screening_score")
    assert_score_equals(after_large["screening_score"], 82.15, "screening_score")
    assert after_small["version"] > small["version"], after_small["version"]
    assert after_large["version"] > large["version"], after_large["version"]
    assert_status(read_landowner(landowner_id), "ENGAGED", "landowner")


def test_a_tract_in_another_county_is_untouched_by_the_publication():
    """
    The input set is keyed on the county alone, so a tract of the same owner one county
    over keeps every deeded acre while its neighbours lose a quarter of theirs.

    PRD: "The applicable rules are every setback rule whose `jurisdiction_code` equals
    this parcel's `county_fips` — setback rules have no lifecycle, so there is no status
    filter — taken in `created_at` ascending order."

    Design: Corner/complexity_layers/setback_rule_publication_cascades_to_every_matching_parcel
    """
    landowner_id, small, _large = _two_tracts_of_one_owner_before_any_ordinance()
    elsewhere = register_parcel(
        landowner_id, apn="R-9001-003", **dict(CLEAN_INPUTS, county_fips="48029")
    )

    publish_setback_rule(
        jurisdiction_code=CLEAN_COUNTY,
        rule_type="PROPERTY_LINE",
        setback_feet=500,
        encumbrance_rate_per_acre=0.2500,
        consent_waivable=True,
    )

    after = read_parcel(elsewhere["id"])
    assert_acres_equals(after["raw_setback_acres"], 0.00, "raw_setback_acres")
    assert_acres_equals(after["buildable_acres"], 200.00, "buildable_acres")
    assert_status(after, "QUALIFIED", "out-of-county parcel")
    assert_version_is(after, elsewhere["version"], "out-of-county parcel")
    assert_acres_equals(read_parcel(small["id"])["buildable_acres"], 75.00, "buildable_acres")


def test_a_page_size_past_the_hundred_record_ceiling_is_refused():
    """
    One over the ceiling is a bad request on the query string, not a page silently
    clamped to a hundred: the response is the error envelope, carrying no rows at all.

    PRD: "A `limit` outside the inclusive range from 1 to 100, a non-integer `limit` or
    `offset`, or a negative `offset`, is rejected with `ERR_INVALID_REQUEST` and HTTP
    400."

    Design: Corner/complexity_layers/pagination_limit_above_the_maximum_returns_invalid_request
    """
    _landowner_id, _parcel = _owner_and_tract()

    response = client().list_parcels(LAND_AGENT, {"limit": 101, "offset": 0})

    validate_error(response, ERR_INVALID_REQUEST, 400)
    body = response.json()
    assert body["response_type"] == "error", body["response_type"]
    assert not isinstance(body["data"], list), "an error response returned a data array"


def test_a_page_size_of_exactly_one_hundred_is_admitted():
    """
    The bound is inclusive, so the very same collection that refused a hundred and one
    serves a hundred without complaint, and reports the one record it holds.

    PRD: "`limit` is the page size: it defaults to 10 when omitted, may be no smaller
    than 1 and no larger than 100."

    Design: Corner/complexity_layers/pagination_limit_above_the_maximum_returns_invalid_request
    """
    _landowner_id, _parcel = _owner_and_tract()
    refused = client().list_parcels(LAND_AGENT, {"limit": 101, "offset": 0})
    validate_error(refused, ERR_INVALID_REQUEST, 400)

    response = client().list_parcels(LAND_AGENT, {"limit": 100, "offset": 0})

    rows, meta = validate_paginated(response)
    assert_page_meta(meta, total_count=1, has_more=False, limit=100, offset=0)
    assert len(rows) == 1, len(rows)


def test_a_negative_offset_is_refused_on_the_same_collection():
    """
    The other half of the pagination contract: skipping a negative number of records is
    meaningless, so it is refused with the same code rather than treated as zero.

    PRD: "`offset` is the number of records to skip: it defaults to 0 and may be no
    smaller than 0."

    Design: Corner/complexity_layers/pagination_limit_above_the_maximum_returns_invalid_request
    """
    _landowner_id, _parcel = _owner_and_tract()

    response = client().list_parcels(LAND_AGENT, {"limit": 10, "offset": -1})

    validate_error(response, ERR_INVALID_REQUEST, 400)
    _rows, meta = parcels_page(LAND_AGENT)
    assert_page_meta(meta, total_count=1)


def _three_tracts_across_two_owners():
    """Two owners, three tracts, arranged so each filter alone matches two of them."""
    owner_a = register_landowner(**SANDHILL)["id"]
    owner_b = register_landowner(**CAPROCK_TRUST)["id"]
    first = register_parcel(owner_a, apn="R-9001-001", **CLEAN_INPUTS)
    second = register_parcel(
        owner_a, apn="R-9001-002", **dict(CLEAN_INPUTS, gross_acres=60.00)
    )
    third = register_parcel(owner_b, apn="R-9001-003", **CLEAN_INPUTS)
    assert_status(first, "QUALIFIED", "first parcel")
    assert_status(second, "SCREENING", "second parcel")
    assert_status(third, "QUALIFIED", "third parcel")
    return owner_a, owner_b, first, second, third


def test_two_filters_on_the_parcel_list_narrow_conjunctively():
    """
    Each filter alone would match two of the three tracts, so only their conjunction
    picks out one — and the envelope counts what matched both, before the page was cut.

    PRD: "For list responses the `meta` object additionally carries `limit`, `offset`,
    `total_count` (the number of records matching the filters before pagination) and
    `has_more` (true when records remain beyond the current page)."

    Design: Corner/complexity_layers/two_filters_combine_conjunctively_on_the_parcel_list
    """
    owner_a, _owner_b, first, _second, _third = _three_tracts_across_two_owners()

    rows, meta = parcels_page(
        LAND_AGENT, landowner_id=owner_a, status="QUALIFIED", limit=10, offset=0
    )

    assert_page_meta(meta, total_count=1, has_more=False)
    assert len(rows) == 1, len(rows)
    assert rows[0]["id"] == first["id"], rows[0]["id"]
    assert_acres_equals(rows[0]["buildable_acres"], 200.00, "buildable_acres")


def test_each_parcel_filter_alone_matches_two_of_the_three_tracts():
    """
    The arithmetic that makes the conjunction meaningful: the owner filter alone finds
    two, the status filter alone finds a different two, and the unfiltered collection
    holds all three.

    PRD: "Parcels may be filtered by `landowner_id`, `county_fips`, `screening_tier` and
    `status`."

    Design: Corner/complexity_layers/two_filters_combine_conjunctively_on_the_parcel_list
    """
    owner_a, owner_b, _first, _second, _third = _three_tracts_across_two_owners()

    _rows, by_owner = parcels_page(LAND_AGENT, landowner_id=owner_a)
    _rows, by_status = parcels_page(LAND_AGENT, status="QUALIFIED")
    _rows, unfiltered = parcels_page(LAND_AGENT)

    assert_page_meta(by_owner, total_count=2)
    assert_page_meta(by_status, total_count=2)
    assert_page_meta(unfiltered, total_count=3)
    assert_status(read_landowner(owner_a), "ENGAGED", "owner A")
    assert_status(read_landowner(owner_b), "ENGAGED", "owner B")


def _one_consent_and_one_booking_awaiting_the_clock():
    """A consent lapsing on the thirty-first and a booking closing on the tenth."""
    landowner_id = register_landowner(**SANDHILL)["id"]
    rule = publish_setback_rule(
        jurisdiction_code=CLEAN_COUNTY,
        rule_type="PROPERTY_LINE",
        setback_feet=150,
        encumbrance_rate_per_acre=0.0500,
        consent_waivable=True,
    )
    parcel = register_parcel(landowner_id, apn="R-9001-001", **CLEAN_INPUTS)
    assert_acres_equals(parcel["raw_setback_acres"], 10.00, "raw_setback_acres")
    assert_acres_equals(parcel["buildable_acres"], 190.00, "buildable_acres")
    assert_status(parcel, "QUALIFIED", "parcel")
    consent = request_consent(
        parcel["id"], rule["id"], neighbor_name="H. Vaughn", consent_expiry_days=30
    )
    assert_status(consent, "REQUESTED", "consent")
    booking = book_site_access(
        parcel["id"],
        TITLE_COUNSEL,
        purpose="GEOTECH",
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-10T00:00:00Z",
        crew_count=2,
    )
    assert_status(booking, "BOOKED", "booking")
    return parcel["id"], consent["id"], booking["id"]


def test_one_clock_advance_drives_two_sweeps_and_reports_all_four():
    """
    A single advance past both deadlines expires the consent and completes the booking,
    each reported in its own counter, while the two sweeps with no candidates report
    zero rather than going missing.

    PRD: "Having set the clock, the endpoint immediately runs four time sweeps **in this
    pinned order**, each iterating its candidate set in `created_at` ascending order, and
    reports what each one did:"

    Design: Corner/complexity_layers/clock_advance_expires_the_consent_and_completes_the_booking_in_pinned_order
    """
    _parcel_id, consent_id, booking_id = _one_consent_and_one_booking_awaiting_the_clock()

    sweeps = set_clock("2026-08-31T00:00:00Z")

    assert_instant_equals(sweeps["current_utc"], "2026-08-31T00:00:00Z", "current_utc")
    assert sweeps["expired_option_count"] == 0, sweeps["expired_option_count"]
    assert sweeps["expired_consent_count"] == 1, sweeps["expired_consent_count"]
    assert sweeps["completed_booking_count"] == 1, sweeps["completed_booking_count"]
    assert sweeps["delinquent_lease_count"] == 0, sweeps["delinquent_lease_count"]
    assert_status(read_consent(consent_id), "EXPIRED", "consent")
    assert_status(read_booking(booking_id, TITLE_COUNSEL), "COMPLETED", "booking")


def test_the_consent_sweep_recomputes_no_acreage_on_its_way_past():
    """
    The consent lapsed without ever being granted, so it had released nothing to take
    back: the parcel's encumbrance is exactly where the ordinance left it and the tract
    is still qualified.

    PRD: "Every neighbor consent still in status `REQUESTED` whose `consent_expiry_at` is
    at or before the new clock value becomes `EXPIRED`."

    Design: Corner/complexity_layers/clock_advance_expires_the_consent_and_completes_the_booking_in_pinned_order
    """
    parcel_id, consent_id, _booking_id = _one_consent_and_one_booking_awaiting_the_clock()

    set_clock("2026-08-31T00:00:00Z")

    consent = read_consent(consent_id)
    assert_acres_equals(consent["released_acres"], 0.00, "released_acres")
    assert_null(consent["granted_at"], "granted_at")
    parcel = read_parcel(parcel_id)
    assert_acres_equals(
        parcel["setback_encumbered_acres"], 10.00, "setback_encumbered_acres"
    )
    assert_acres_equals(parcel["consent_released_acres"], 0.00, "consent_released_acres")
    assert_acres_equals(parcel["buildable_acres"], 190.00, "buildable_acres")
    assert_status(parcel, "QUALIFIED", "parcel")


def test_a_second_identical_advance_finds_nothing_left_to_sweep():
    """
    Both candidates have already reached their terminal statuses, so replaying the same
    clock value reports four zeroes rather than counting them a second time.

    PRD: "All four counts are integers, and a sweep that finds no candidates reports zero
    rather than omitting its key."

    Design: Corner/complexity_layers/clock_advance_expires_the_consent_and_completes_the_booking_in_pinned_order
    """
    _parcel_id, consent_id, booking_id = _one_consent_and_one_booking_awaiting_the_clock()
    first = set_clock("2026-08-31T00:00:00Z")
    assert first["expired_consent_count"] == 1, first["expired_consent_count"]

    again = set_clock("2026-08-31T00:00:00Z")

    assert again["expired_option_count"] == 0, again["expired_option_count"]
    assert again["expired_consent_count"] == 0, again["expired_consent_count"]
    assert again["completed_booking_count"] == 0, again["completed_booking_count"]
    assert again["delinquent_lease_count"] == 0, again["delinquent_lease_count"]
    assert_status(read_consent(consent_id), "EXPIRED", "consent")
    assert_status(read_booking(booking_id, TITLE_COUNSEL), "COMPLETED", "booking")
