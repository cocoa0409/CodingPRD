"""Corner coverage: fee tier boundaries, the strict referral-overdue rule,
and digitization-queue tie-breaking."""

import test_helpers as th

E = th.ApiErrorId


def test_reproduction_fee_tier_boundaries(api):
    """PRD §3.8: "Pages price in three tiers: the first 20 pages at 80 cents
    per page, the next 80 pages (pages 21 through 100) at 50 cents per page,
    and every page beyond 100 at 25 cents per page."
    PRD §3.8: "For any other affiliation the tier subtotals are simply summed."
    PRD §3.8: "Summed across the researcher's requests created on the same UTC
    calendar day as the logical clock and still counted — those in `QUOTED`,
    `PAID`, or `FULFILLED` status — the committed pages plus the new request's
    `page_count` must not exceed 200 pages, with the boundary inclusive"

    Design: Corner/calculations/reproduction_fee_tier_boundaries
    """
    th.set_clock()
    bundle = th.setup_public_described_collection()
    eve = th.create_active_researcher(
        "Eve Gov", "eve@example.org", "GOVERNMENT", "GOV-5005"
    )
    headers = th.make_researcher_headers(eve["id"])
    collection_id = bundle["collection"]["id"]

    def fee_for(pages):
        resp = api.create_reproduction_request(
            th.reproduction_payload(eve["id"], collection_id, pages, "DIGITAL_SCAN"),
            headers=headers,
        )
        return th.validate_success(resp, 201)["fee_cents"]

    assert fee_for(20) == 1600
    assert fee_for(21) == 1650
    th.set_clock("2026-09-02T00:00:00Z")  # fresh UTC day: the quota resets
    assert fee_for(100) == 5600
    th.set_clock("2026-09-03T00:00:00Z")
    assert fee_for(101) == 5625

    assert th.expected_fee_cents(20, "GOVERNMENT") == 1600
    assert th.expected_fee_cents(21, "GOVERNMENT") == 1650
    assert th.expected_fee_cents(100, "GOVERNMENT") == 5600
    assert th.expected_fee_cents(101, "GOVERNMENT") == 5625


def test_referral_overdue_uses_strict_greater_than(api):
    """PRD §3.5: "A `SENT` referral is overdue only when the logical clock is
    strictly later than its `response_due_at`: at exactly the due instant the
    referral is not overdue and still blocks completion, and the completing
    call is rejected with `ERR_REFERRALS_OUTSTANDING` (409)."
    PRD §3.5: "An overdue `SENT` referral is treated as concurrence — silence
    is no objection — and is ignored in the outcome computation."
    PRD §3.5: "Each created referral starts in `SENT` status, with `sent_at`
    stamped from the logical clock, `response_due_at` computed as 21 days after
    `sent_at`, and its `decision` remaining null until the agency answers."

    Design: Corner/calculations/referral_overdue_uses_strict_greater_than
    """
    th.set_clock()
    ctx = th.setup_in_progress_mdr_with_referral()
    review = ctx["review"]
    referral = ctx["referral"]
    reviewer = th.TEST_USERS["declass_reviewer_headers"]
    assert th.same_instant(referral["sent_at"], th.STARTUP_CLOCK_UTC)
    assert th.same_instant(referral["response_due_at"], "2026-09-22T00:00:00Z")

    # At exactly the due instant the referral is not yet overdue.
    th.set_clock("2026-09-22T00:00:00Z")
    th.validate_error(
        api.complete_declass_review(
            review["id"], th.complete_review_payload("DECLASSIFY"), headers=reviewer
        ),
        E.ERR_REFERRALS_OUTSTANDING,
    )

    # One second later the referral is overdue and counts as concurrence.
    th.set_clock("2026-09-22T00:00:01Z")
    completed = th.validate_success(
        api.complete_declass_review(
            review["id"], th.complete_review_payload("DECLASSIFY"), headers=reviewer
        ),
        200,
    )
    assert completed["status"] == "COMPLETED"
    assert completed["outcome"] == "DECLASSIFIED"

    after = th.get_success_data(
        api.get_equity_referral(referral["id"], headers=reviewer)
    )
    assert after["status"] == "SENT"
    assert after["decision"] is None


def test_digitization_queue_tiebreaks_by_cutoff_then_created_at(api):
    """PRD §3.4: "It lists exactly the collections whose `digitization_status`
    is `QUEUED`, ordered by `digitization_priority` descending, then by
    `records_cutoff_date` ascending so that older records come first on a tie,
    then by `created_at` ascending as the final tie-break — a collection's `id`
    is never used for ordering."
    PRD §3.4: "It awards 2 points per whole year of records age, counting at
    most 50 years"

    Design: Corner/calculations/digitization_queue_tiebreaks_by_cutoff_then_created_at
    """
    th.set_clock()
    agency = th.create_agency()
    schedule = th.create_approved_schedule(
        agency, schedule_number="SCH-DOJ-030", title="Open Series Files"
    )
    archivist = th.TEST_USERS["processing_archivist_headers"]

    def accession_mods_collection():
        transfer = th.create_validated_transfer(
            agency, schedule,
            transfer_method="PHYSICAL", metadata_standard="MODS_3_7",
            unit_count=10, records_cutoff_date="1990-06-15T00:00:00Z",
            linear_feet=2.0,
        )
        return th.accession_transfer(transfer)["collection_id"]

    col_e1 = accession_mods_collection()
    # Separate the two accessions by one logical second so the created_at
    # tie-break is decidable.
    th.set_clock("2026-09-01T00:00:01Z")
    col_e2 = accession_mods_collection()

    for col_id in (col_e1, col_e2):
        collection = th.begin_processing(th.read_collection(col_id))
        collection = th.describe_collection(collection)
        enqueued = th.enqueue_digitization(collection)
        assert enqueued["digitization_priority"] == 72
        assert enqueued["digitization_priority"] == th.expected_digitization_priority(
            "2026-09-01T00:00:01Z", "1990-06-15T00:00:00Z"
        )

    data, meta = th.validate_paginated(
        api.get_digitization_queue(headers=archivist)
    )
    assert [row["id"] for row in data] == [col_e1, col_e2]
    assert meta["total_count"] == 2
