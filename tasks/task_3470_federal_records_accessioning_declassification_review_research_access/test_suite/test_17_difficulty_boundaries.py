"""Difficulty coverage (queue A): boundary precision — the inclusive
25-year systematic-review age gate (including the Feb-29 anniversary rule)
and the inclusive 200-page daily reproduction quota."""

import test_helpers as th

E = th.ApiErrorId


def _systematic_create(api, collection_id):
    payload = th.build_review_create_payload(collection_id, "SYSTEMATIC")
    return api.create_declass_review(
        payload, headers=th.TEST_USERS["processing_archivist_headers"]
    )


def test_systematic_review_age_threshold(api):
    """PRD §3.5: "The systematic flavor adds its age gate on top: the records'
    whole-year age under §2.9 must be at least 25 years, with the boundary
    inclusive, so a collection whose twenty-fifth anniversary is exactly today
    is eligible; a younger collection is rejected with
    `ERR_SYSTEMATIC_REVIEW_PREMATURE` (409)."
    PRD §2.9: "Age in years is computed from the logical clock and a
    `records_cutoff_date` as follows: take the clock's year minus the cutoff's
    year, then subtract one if the clock's month-and-day has not yet reached
    the cutoff's month-and-day — that is, the anniversary of the cutoff must
    already have occurred in the clock's year for the year to count."

    Design: Difficulty/boundary_precision_check/systematic_review_age_threshold
    """
    th.set_clock()
    # Cutoff 2001-03-15: the 25th anniversary is 2026-03-15.
    bundle = th.setup_classified_collection(classification_default="SECRET")
    collection = bundle["collection"]

    # Age 24 (one day before the anniversary): premature.
    th.set_clock("2026-03-14T00:00:00Z")
    version_at_24 = th.current_collection_version(collection["id"])
    resp = _systematic_create(api, collection["id"])
    assert resp.status_code == 409
    th.validate_error(resp, E.ERR_SYSTEMATIC_REVIEW_PREMATURE)

    # The failed create did not mutate the collection.
    assert th.current_collection_version(collection["id"]) == version_at_24

    # Age exactly 25 (the anniversary itself): the boundary is inclusive.
    th.set_clock("2026-03-15T00:00:00Z")
    created = th.validate_success(_systematic_create(api, collection["id"]), 201)
    assert created["status"] == "OPEN"
    assert created["review_type"] == "SYSTEMATIC"
    assert created.get("requester_researcher_id") is None


def test_systematic_review_age_feb29_anniversary(api):
    """PRD §2.9: "When the cutoff falls on February 29 and the clock's year is
    not a leap year, the anniversary is treated as February 28."
    PRD §3.5: "the records' whole-year age under §2.9 must be at least 25
    years, with the boundary inclusive, so a collection whose twenty-fifth
    anniversary is exactly today is eligible; a younger collection is rejected
    with `ERR_SYSTEMATIC_REVIEW_PREMATURE` (409)."

    Design: Difficulty/boundary_precision_check/systematic_review_age_threshold
    """
    th.set_clock()
    # Leap-day cutoff: the 25th anniversary in non-leap 2025 is Feb 28.
    agency = th.create_agency()
    schedule = th.create_approved_schedule(
        agency, schedule_number="SCH-DOJ-032", title="Leap-day Files",
        classification_default="SECRET",
    )
    transfer = th.create_validated_transfer(
        agency, schedule, unit_count=10, records_cutoff_date="2000-02-29T00:00:00Z",
        linear_feet=2.0,
    )
    collection_id = th.accession_transfer(transfer)["collection_id"]

    # 2025-02-27: the anniversary has not yet occurred -> age 24.
    th.set_clock("2025-02-27T00:00:00Z")
    resp = _systematic_create(api, collection_id)
    assert resp.status_code == 409
    th.validate_error(resp, E.ERR_SYSTEMATIC_REVIEW_PREMATURE)

    # 2025-02-28: the observed Feb-29 anniversary -> age 25 -> eligible.
    th.set_clock("2025-02-28T00:00:00Z")
    created = th.validate_success(_systematic_create(api, collection_id), 201)
    assert created["status"] == "OPEN"
    assert created["review_type"] == "SYSTEMATIC"


def test_daily_page_quota_limit(api):
    """PRD §3.8: "Summed across the researcher's requests created on the same
    UTC calendar day as the logical clock and still counted — those in
    `QUOTED`, `PAID`, or `FULFILLED` status — the committed pages plus the new
    request's `page_count` must not exceed 200 pages, with the boundary
    inclusive: a request that brings the day to exactly 200 pages succeeds, and
    one page beyond is rejected with `ERR_DAILY_PAGE_LIMIT_EXCEEDED` (409)."
    PRD §3.8: "Pages price in three tiers: the first 20 pages at 80 cents per
    page, the next 80 pages (pages 21 through 100) at 50 cents per page, and
    every page beyond 100 at 25 cents per page."

    Design: Difficulty/boundary_precision_check/daily_page_quota_limit
    """
    th.set_clock()
    bundle = th.setup_public_described_collection()
    collection_id = bundle["collection"]["id"]
    bob = th.create_active_researcher(
        "Bob Press", "bob@example.org", "JOURNALIST", "PP-2002"
    )
    researcher = th.make_researcher_headers(bob["id"])

    first = th.validate_success(
        api.create_reproduction_request(
            th.reproduction_payload(bob["id"], collection_id, 120, "DIGITAL_SCAN"),
            headers=researcher,
        ),
        201,
    )
    assert first["fee_cents"] == 6100  # 1600 + 80*50 + 20*25, no discount

    # 120 + 80 == 200: the inclusive boundary admits the second request.
    th.validate_success(
        api.create_reproduction_request(
            th.reproduction_payload(bob["id"], collection_id, 80, "PHOTOPRINT"),
            headers=researcher,
        ),
        201,
    )

    # The 201st page of the same UTC day is rejected.
    resp = api.create_reproduction_request(
        th.reproduction_payload(bob["id"], collection_id, 1, "DIGITAL_SCAN"),
        headers=researcher,
    )
    assert resp.status_code == 409
    th.validate_error(resp, E.ERR_DAILY_PAGE_LIMIT_EXCEEDED)


def test_daily_page_quota_resets_on_next_utc_day(api):
    """PRD §3.8: "Summed across the researcher's requests created on the same
    UTC calendar day as the logical clock and still counted — those in
    `QUOTED`, `PAID`, or `FULFILLED` status — the committed pages plus the new
    request's `page_count` must not exceed 200 pages, with the boundary
    inclusive"

    Design: Difficulty/boundary_precision_check/daily_page_quota_limit
    """
    th.set_clock()
    bundle = th.setup_public_described_collection()
    collection_id = bundle["collection"]["id"]
    bob = th.create_active_researcher(
        "Bob Press", "bob@example.org", "JOURNALIST", "PP-2002"
    )
    researcher = th.make_researcher_headers(bob["id"])

    # Fill the day to the inclusive cap.
    th.validate_success(
        api.create_reproduction_request(
            th.reproduction_payload(bob["id"], collection_id, 200, "DIGITAL_SCAN"),
            headers=researcher,
        ),
        201,
    )
    th.validate_error(
        api.create_reproduction_request(
            th.reproduction_payload(bob["id"], collection_id, 1, "DIGITAL_SCAN"),
            headers=researcher,
        ),
        E.ERR_DAILY_PAGE_LIMIT_EXCEEDED,
    )

    # The quota keys on the logical clock's UTC calendar day: the next day a
    # full 200-page request succeeds again.
    th.set_clock("2026-09-02T00:00:00Z")
    fresh = th.validate_success(
        api.create_reproduction_request(
            th.reproduction_payload(bob["id"], collection_id, 200, "DIGITAL_SCAN"),
            headers=researcher,
        ),
        201,
    )
    assert fresh["status"] == "QUOTED"
