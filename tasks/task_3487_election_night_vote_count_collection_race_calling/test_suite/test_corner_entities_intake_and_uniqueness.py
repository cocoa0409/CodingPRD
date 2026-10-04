"""Corner-design tests: vote-report intake computed fields and the uniqueness
constraints on counties, candidates, feeds, county links, and invoices
(PRD §2.9, §3.1, §3.4, §3.8).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_media_invoice,
    assert_vote_report,
    create_candidate,
    create_candidate_payload,
    create_county_payload,
    create_feed_source,
    create_feed_source_payload,
    create_vote_report_payload,
    create_wirelite_basic,
    generate_invoice,
    get_contest,
    reset_clock_to_setup,
    setup_standard_universe,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_vote_report_computed_fields_derived_at_intake(api):
    """PRD §3.4: "The report's `reported_total` — the sum of the votes across its
    `candidate_votes` entries — is compared with the county's
    `expected_vote_total` to form the `deviation_ratio`: the absolute difference
    between the two, divided by `expected_vote_total`, rounded half up to six
    decimal places."
    PRD §3.4: "the check also computes `swing_deviation`: the absolute difference
    between the county's `historical_dem_share` and the reported DEM share, where
    the reported DEM share is the contest's DEM candidate's votes divided by the
    greater of `reported_total` and 1 — again rounded half up to six decimal
    places."
    PRD §3.4: "Acceptance into the intake queue has three immediate effects. The
    contest's `version` increments by one."

    Design: Corner/entities/vote_report_computed_fields_derived_at_intake
    """
    universe = setup_standard_universe(advance_to="LIVE")
    contest_id = universe["contest"]["id"]
    version_before = universe["contest"]["version"]
    votes = {
        universe["candidates"]["wanda"]["id"]: 4000,
        universe["candidates"]["tom"]["id"]: 3000,
    }
    payload = create_vote_report_payload(
        universe["counties"]["alameda"]["id"], 5, votes, version_before,
        source="FEED",
    )
    resp = api.create_vote_report(
        contest_id, payload, TEST_USERS["feed_operator_headers"],
    )
    data = validate_success(resp, 201)
    assert_vote_report(data)
    assert data["reported_total"] == 7000
    assert data["deviation_ratio"] == 0.3
    assert data["swing_deviation"] == 0.028571
    assert data["status"] == "RECEIVED"
    assert get_contest(contest_id)["version"] == version_before + 1


def test_duplicate_county_fips_rejected(api):
    """PRD §3.1: "a five-digit `county_fips` unique within the event — a
    duplicate is rejected with `ERR_DUPLICATE_COUNTY`"

    Design: Corner/entities/duplicate_county_fips_rejected
    """
    universe = setup_standard_universe(
        advance_to="SETUP", with_contra_costa=False,
    )
    event_id = universe["event"]["id"]
    payload = create_county_payload(
        county_fips="06001", county_name="Alameda Clone",
        expected_precincts=3, expected_vote_total=3000,
    )
    resp = api.create_county(event_id, payload, TEST_USERS["admin_headers"])
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_COUNTY)
    _rows, meta = validate_paginated(
        api.list_counties(event_id, TEST_USERS["admin_headers"])
    )
    assert meta["total_count"] == 1


def test_duplicate_candidate_name_rejected(api):
    """PRD §3.1: "Ballot candidates are added to a contest with a
    `candidate_name` unique within that contest (`ERR_DUPLICATE_CANDIDATE`)"

    Design: Corner/entities/duplicate_candidate_name_rejected
    """
    universe = setup_standard_universe(
        advance_to="SETUP", with_contra_costa=False,
    )
    contest_id = universe["contest"]["id"]
    resp = api.create_candidate(
        contest_id, create_candidate_payload("Wanda Wynn", "REP"),
        TEST_USERS["admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CANDIDATE)


def test_duplicate_feed_name_rejected(api):
    """PRD §3.1: "a `feed_name` unique within the event (`ERR_DUPLICATE_FEED`)"

    Design: Corner/entities/duplicate_feed_name_rejected
    """
    universe = setup_standard_universe(advance_to="SETUP")
    event_id = universe["event"]["id"]
    resp = api.create_feed_source(
        event_id, create_feed_source_payload(state_codes=["NV"]),
        TEST_USERS["admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_FEED)


def test_duplicate_county_link_rejected(api):
    """PRD §3.1: "the same contest-county pair may not be linked twice
    (`ERR_DUPLICATE_COUNTY_LINK`)"

    Design: Corner/entities/duplicate_county_link_rejected
    """
    universe = setup_standard_universe(
        advance_to="SETUP", with_contra_costa=False,
    )
    contest_id = universe["contest"]["id"]
    alameda_id = universe["counties"]["alameda"]["id"]
    resp = api.create_county_link(
        contest_id, alameda_id, TEST_USERS["admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_COUNTY_LINK)
    _rows, meta = validate_paginated(
        api.list_contest_county_links(contest_id, TEST_USERS["admin_headers"])
    )
    assert meta["total_count"] == 1


def test_duplicate_invoice_period_rejected(api):
    """PRD §3.8: "At most one invoice exists per customer and `period`: a second
    generation for the same pair is rejected with `ERR_DUPLICATE_INVOICE`."
    PRD §3.8: "Generating an invoice for a `period` given as a `YYYY-MM` billing
    month counts the customer's deliveries whose `delivered_at` falls inside that
    UTC calendar month — both `SENT` and `STALE` rows are billed, and
    `CALL_CREDIT` rows count — into the invoice's `delivery_count`, and sums
    their already-rounded `fee_cents` into `total_fee_cents`."

    Design: Corner/entities/duplicate_invoice_period_rejected
    """
    reset_clock_to_setup()
    customer = create_wirelite_basic()
    invoice = generate_invoice(customer["id"], "2026-11")
    assert_media_invoice(invoice)
    assert invoice["delivery_count"] == 0
    assert invoice["total_fee_cents"] == 0

    resp = api.create_invoice(
        customer["id"], "2026-11", TEST_USERS["admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_INVOICE)
