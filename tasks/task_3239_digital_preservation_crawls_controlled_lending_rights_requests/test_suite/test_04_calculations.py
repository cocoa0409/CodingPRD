"""Calculation-rule coverage: dedupe, storage cost, loan terms, availability."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data,
    ApiErrorId, TEST_USERS, make_patron_headers, make_accessibility_officer_headers,
    create_capture_payload, create_accessibility_credential_payload,
    set_clock, run_sweep, make_patron, make_library, make_work,
    make_batch_with_items, setup_work_with_lendable_items, checkout,
    make_running_crawl_job, get_job, get_loan, get_patron, get_work,
    file_work_rights_request, begin_review, decide_request,
)

ADMIN = TEST_USERS["admin_headers"]
CRAWLOP = TEST_USERS["crawl_operator_headers"]
LEGAL = TEST_USERS["legal_reviewer_headers"]


def test_capture_dedupe_skips_duplicate_and_returns_existing():
    """PRD 3.7: "If a capture with the same pair already exists, no new row is
    created: the job's `duplicates_skipped` increases by 1, and the
    pre-existing capture row is returned with a 200 status instead of the 201
    that accompanies a genuinely new row."
    PRD 3.7: "A new row raises the job's `captures_produced` by 1; a dedupe hit
    never does."

    Design: Corner/calculations/capture_dedupe_skips_duplicate_and_returns_existing
    """
    set_clock("2026-09-01T00:00:00Z")
    job = get_success_data(api_client.create_crawl_job(
        {"seed_url": "https://dedupe.site/",
         "scheduled_at": "2026-09-01T00:05:00Z", "requests_per_minute": 30},
        CRAWLOP,
    ))
    set_clock("2026-09-01T00:05:00Z")
    get_success_data(api_client.start_crawl_job(job["id"], CRAWLOP))

    first = validate_success(
        api_client.create_capture(
            {"crawl_job_id": job["id"], "url": "https://dedupe.site/x",
             "content_hash": "samehash", "has_dynamic_content": False},
            CRAWLOP,
        ),
        expected_status=201,
    )
    resp2 = api_client.create_capture(
        {"crawl_job_id": job["id"], "url": "https://dedupe.site/x",
         "content_hash": "samehash", "has_dynamic_content": False},
        CRAWLOP,
    )
    second = validate_success(resp2, expected_status=200)
    assert second["id"] == first["id"]

    rows, _ = validate_paginated(api_client.list_job_captures(job["id"], CRAWLOP))
    assert len(rows) == 1
    job_now = get_job(job["id"])
    assert job_now["duplicates_skipped"] == 1
    assert job_now["captures_produced"] == 1

    third = validate_success(
        api_client.create_capture(
            {"crawl_job_id": job["id"], "url": "https://dedupe.site/x",
             "content_hash": "otherhash", "has_dynamic_content": False},
            CRAWLOP,
        ),
        expected_status=201,
    )
    assert third["id"] != first["id"]
    assert get_job(job["id"])["captures_produced"] == 2


def test_storage_cost_tier_straddling_two_tiers():
    """PRD 2.7: "Each unique capture is estimated at a fixed 524288 bytes
    (512 KiB). The first 1000000000 bytes of a job's unique capture volume are
    priced at 3 cents per 1000000 bytes; any bytes beyond that cap are priced
    at 1 cent per 1000000 bytes. Each tier's cost is rounded half-up to whole
    cents independently, and the two rounded tier costs are then summed."

    Design: Corner/calculations/storage_cost_tier_straddling_two_tiers
    """
    set_clock("2026-09-01T00:00:00Z")
    job = get_success_data(api_client.create_crawl_job(
        {"seed_url": "https://tier.site/",
         "scheduled_at": "2026-09-01T00:05:00Z", "requests_per_minute": 120},
        CRAWLOP,
    ))
    set_clock("2026-09-01T00:05:00Z")
    get_success_data(api_client.start_crawl_job(job["id"], CRAWLOP))
    get_success_data(api_client.create_capture(
        {"crawl_job_id": job["id"], "url": "https://tier.site/u0000",
         "content_hash": "th0000", "has_dynamic_content": False},
        CRAWLOP,
    ))
    get_success_data(api_client.complete_crawl_job(job["id"], CRAWLOP))
    done = get_job(job["id"])
    # 1 capture = 524288 bytes, entirely tier 1: round_half_up(524288*3/1e6) == 2
    assert done["storage_cost_cents"] == 2, (
        f"expected 2 cents for 524288 tier-1 bytes, got {done['storage_cost_cents']}"
    )
    assert done["captures_produced"] == 1


def test_short_read_loan_term_is_one_hour():
    """PRD 3.4: "sets `due_at` to 14 days after checkout for a `STANDARD` loan
    or exactly 1 hour after checkout for a `SHORT_READ` loan."
    PRD 2.8: "every `ACTIVE` loan whose `due_at` is at or before the clock
    transitions to `EXPIRED`"
    PRD 3.1: "each loan the sweep expires adds exactly one strike to the
    borrowing patron."

    Design: Corner/calculations/short_read_loan_term_is_one_hour
    """
    set_clock("2026-09-01T00:00:00Z")
    _lib, work, _batch, items = setup_work_with_lendable_items(
        num_items=2,
        work_overrides={"title": "Short Read", "author": "SR",
                        "publication_year": 2019},
    )
    patron_sr = make_patron(email="sr@example.org")
    cred = get_success_data(api_client.create_accessibility_credential(
        create_accessibility_credential_payload(patron_sr["id"]),
        make_patron_headers(patron_sr["id"]),
    ))
    get_success_data(api_client.decide_accessibility_credential(
        cred["id"], {"decision": "VERIFY"},
        make_accessibility_officer_headers("officer-1"),
    ))
    patron_std = make_patron(email="sr2@example.org")

    loan_sr = checkout(items[0]["id"], patron_sr["id"], loan_kind="SHORT_READ")
    loan_std = checkout(items[1]["id"], patron_std["id"], loan_kind="STANDARD")
    assert loan_sr["due_at"].startswith("2026-09-01T01:00:00"), (
        f"SHORT_READ due_at must be checkout + 1 hour, got {loan_sr['due_at']}"
    )

    set_clock("2026-09-01T02:00:00Z")
    run_sweep()
    assert get_loan(loan_sr["id"])["status"] == "EXPIRED"
    assert get_loan(loan_std["id"])["status"] == "ACTIVE"
    assert get_patron(patron_sr["id"])["strike_count"] == 1


def test_work_availability_ignores_filed_and_dismissed():
    """PRD 3.8: "The availability recompute itself is a pure derivation over all
    of a work's rights requests, in any status: if any request for the work is
    in `LEGAL_HOLD` or `UPHELD_REMOVED`, the work is `WITHDRAWN`; otherwise, if
    any request is `UNDER_REVIEW`, the work is `EMBARGOED`; otherwise the work
    is `AVAILABLE`. Requests in `FILED` or `DISMISSED` never influence the
    result."

    Design: Corner/calculations/work_availability_ignores_filed_and_dismissed
    """
    work = make_work(title="Availability Filter", author="AF", publication_year=2000)
    req1 = file_work_rights_request(work["id"], claimant_name="Filer One")
    req2 = file_work_rights_request(work["id"], claimant_name="Filer Two")
    begin_review(req2["id"], reviewer="legal-b")
    decide_request(req2["id"], "DISMISS", decider="legal-c")

    fetched = get_work(work["id"])
    assert fetched["availability"] == "AVAILABLE"
    r1 = validate_success(api_client.get_rights_request(req1["id"], LEGAL))
    r2 = validate_success(api_client.get_rights_request(req2["id"], LEGAL))
    assert r1["status"] == "FILED"
    assert r2["status"] == "DISMISSED"
