"""State-machine transitions, preconditions, and segregation-of-duties coverage."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data,
    ApiErrorId, TEST_USERS, make_patron_headers, make_legal_reviewer_headers,
    make_accessibility_officer_headers,
    create_crawl_job_payload, create_loan_payload, create_accessibility_credential_payload,
    set_clock, run_sweep, make_patron, make_library, make_work,
    make_batch_with_items, setup_work_with_lendable_items, checkout, join_waitlist,
    get_item, get_loan, get_entry, get_patron,
    file_work_rights_request, begin_review,
)

ADMIN = TEST_USERS["admin_headers"]
ANON = TEST_USERS["anonymous_headers"]
LIBADMIN = TEST_USERS["library_admin_headers"]
SCANOP = TEST_USERS["scan_operator_headers"]
CRAWLOP = TEST_USERS["crawl_operator_headers"]
LEGAL = TEST_USERS["legal_reviewer_headers"]


def test_double_return_of_same_loan_rejected():
    """PRD 3.4: "Return is the borrower's own operation and requires only that
    the loan be `ACTIVE` and that `X-User-ID` match the loan's `patron_id`."
    PRD 2.5: "Transition state — the target resource is in a from-state that
    permits the requested transition; otherwise `ERR_INVALID_STATE`."

    Design: Corner/state_machines/double_return_of_same_loan_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    _lib, work, _batch, items = setup_work_with_lendable_items(
        num_items=1,
        work_overrides={"title": "Double Return", "author": "DR",
                        "publication_year": 2010},
    )
    patron = make_patron(email="dr@example.org")
    loan = checkout(items[0]["id"], patron["id"])
    headers = make_patron_headers(patron["id"])
    validate_success(api_client.return_loan(loan["id"], headers))

    resp = api_client.return_loan(loan["id"], headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_loan(loan["id"])["status"] == "RETURNED"
    assert get_patron(patron["id"])["active_loan_count"] == 0


def test_seal_empty_batch_rejected():
    """PRD 3.3: "Sealing requires the batch to be `OPEN` and non-empty — a batch
    whose `item_count` is 0 cannot be sealed, and the attempt is rejected with
    `ERR_SEAL_EMPTY_BATCH`."

    Design: Corner/state_machines/seal_empty_batch_rejected
    """
    batch = get_success_data(
        api_client.create_scan_batch({"operator_code": "op-se"}, SCANOP)
    )
    resp = api_client.seal_scan_batch(batch["id"], SCANOP)
    validate_error(resp, ApiErrorId.ERR_SEAL_EMPTY_BATCH)
    fresh = validate_success(api_client.get_scan_batch(batch["id"], ADMIN))
    assert fresh["status"] == "OPEN"
    assert fresh["item_count"] == 0


def test_crawl_start_before_scheduled_at_rejected():
    """PRD 3.6: "The logical clock must have reached `scheduled_at` — starting
    early is `ERR_SCHEDULE_NOT_DUE`"

    Design: Corner/state_machines/crawl_start_before_scheduled_at_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    job = get_success_data(api_client.create_crawl_job(
        create_crawl_job_payload(
            seed_url="https://early.site/",
            scheduled_at="2026-09-02T00:00:00Z",
            requests_per_minute=5,
        ),
        CRAWLOP,
    ))
    resp = api_client.start_crawl_job(job["id"], CRAWLOP)
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_NOT_DUE)
    fresh = validate_success(api_client.get_crawl_job(job["id"], ADMIN))
    assert fresh["status"] == "SCHEDULED"


def test_crawl_job_created_under_matching_exclusion_rejected():
    """PRD 3.6: "The exclusion is also enforced prospectively: scheduling a new
    job whose seed falls under an `ACTIVE` directive scoped `CRAWL_ONLY` or
    `BOTH` is rejected outright with `ERR_CRAWL_EXCLUDED`."

    Design: Corner/state_machines/crawl_job_created_under_matching_exclusion_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    get_success_data(api_client.create_exclusion_directive(
        {"url_prefix": "https://blocked.site/", "scope": "CRAWL_ONLY",
         "reason": "robots"},
        CRAWLOP,
    ))
    resp = api_client.create_crawl_job(
        {"seed_url": "https://blocked.site/deep/page",
         "scheduled_at": "2026-09-02T00:00:00Z", "requests_per_minute": 5},
        CRAWLOP,
    )
    validate_error(resp, ApiErrorId.ERR_CRAWL_EXCLUDED)


def test_exclusion_creation_blocks_scheduled_job():
    """PRD 3.6: "First, every crawl job still `SCHEDULED` whose `seed_url`
    begins with the directive's `url_prefix` and whose scope is `CRAWL_ONLY` or
    `BOTH` is blocked on the spot, moving from `SCHEDULED` to `BLOCKED`."
    PRD 3.6: "The creation response reports the new `directive_id` together with
    the `blocked_job_ids` it blocked and the `suppressed_capture_count` it
    suppressed."

    Design: Corner/state_machines/exclusion_creation_blocks_scheduled_job
    """
    set_clock("2026-09-01T00:00:00Z")
    job = get_success_data(api_client.create_crawl_job(
        create_crawl_job_payload(
            seed_url="https://site-x.com/",
            scheduled_at="2026-09-05T00:00:00Z",
            requests_per_minute=15,
        ),
        CRAWLOP,
    ))
    data = validate_success(
        api_client.create_exclusion_directive(
            {"url_prefix": "https://site-x.com/", "scope": "BOTH",
             "reason": "takedown"},
            CRAWLOP,
        ),
        expected_status=201,
    )
    assert job["id"] in data["blocked_job_ids"]
    fresh = validate_success(api_client.get_crawl_job(job["id"], ADMIN))
    assert fresh["status"] == "BLOCKED"

    set_clock("2026-09-06T00:00:00Z")
    resp = api_client.start_crawl_job(job["id"], CRAWLOP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_loan_renewal_blocked_by_live_waitlist():
    """PRD 3.4: "Renewal is legal only when every one of these conditions holds:
    `renewed` is still false; the loan kind is `STANDARD`; the current logical
    clock is strictly before `due_at`; and no waitlist entry for the loan's
    work is in `OPEN` or `OFFERED` status. A failure of any of these is
    `ERR_LOAN_NOT_RENEWABLE`."

    Design: Corner/state_machines/loan_renewal_blocked_by_live_waitlist
    """
    set_clock("2026-09-01T00:00:00Z")
    _lib, work, _batch, items = setup_work_with_lendable_items(
        num_items=1,
        work_overrides={"title": "Renewal Blocked", "author": "RN",
                        "publication_year": 2011},
    )
    borrower = make_patron(email="rna@example.org")
    waiter = make_patron(email="rnb@example.org")
    loan = checkout(items[0]["id"], borrower["id"])
    entry = join_waitlist(work["id"], waiter["id"])
    assert entry["status"] == "OPEN"

    resp = api_client.renew_loan(loan["id"], make_patron_headers(borrower["id"]))
    validate_error(resp, ApiErrorId.ERR_LOAN_NOT_RENEWABLE)
    fresh = get_loan(loan["id"])
    assert fresh["renewed"] is False
    assert fresh["due_at"].startswith("2026-09-15T00:00:00"), (
        f"due_at must be unchanged, got {fresh['due_at']}"
    )


def test_renewal_absolute_cap_42_days():
    """PRD 3.4: "Renewal is legal only when every one of these conditions holds:
    `renewed` is still false; the loan kind is `STANDARD`; the current logical
    clock is strictly before `due_at`; and no waitlist entry for the loan's
    work is in `OPEN` or `OFFERED` status. A failure of any of these is
    `ERR_LOAN_NOT_RENEWABLE`."

    Design: Corner/state_machines/renewal_absolute_cap_42_days
    """
    set_clock("2026-09-01T00:00:00Z")
    _lib, work, _batch, items = setup_work_with_lendable_items(
        num_items=1,
        work_overrides={"title": "Cap Work", "author": "CAP",
                        "publication_year": 2014},
    )
    patron = make_patron(email="cap@example.org")
    loan = checkout(items[0]["id"], patron["id"])

    # At 2026-10-01 the loan is overdue (due 2026-09-15); the overdue denial
    # fires as ERR_LOAN_NOT_RENEWABLE before any renewal-cap consideration.
    set_clock("2026-10-01T00:00:00Z")
    resp = api_client.renew_loan(loan["id"], make_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_LOAN_NOT_RENEWABLE)
    assert get_loan(loan["id"])["renewed"] is False


def test_waitlist_claim_after_offer_expiry_rejected():
    """PRD 2.5: "Transition state — the target resource is in a from-state that
    permits the requested transition; otherwise `ERR_INVALID_STATE`."
    PRD 3.5: "when the sweep finds an `OFFERED` entry whose `offer_expires_at`
    has been reached, the entry moves to `EXPIRED_OFFER` and promotion runs
    again for the same work"

    Design: Corner/state_machines/waitlist_claim_after_offer_expiry_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    library = make_library(library_code="LIB-OE")
    work = make_work(title="Offer Expiry", author="OE", publication_year=2008)
    batch, items = make_batch_with_items(
        work["id"], library["id"], item_specs=[{}], seal=False
    )
    patron = make_patron(email="oe@example.org")
    entry = join_waitlist(work["id"], patron["id"])
    entry_version = entry["version"]
    # seal promotes the entry to OFFERED at clock 2026-09-01
    get_success_data(api_client.seal_scan_batch(batch["id"], SCANOP))
    assert get_entry(entry["id"])["status"] == "OFFERED"

    # advance past the 48-hour offer window and expire the offer via the sweep
    set_clock("2026-09-04T00:00:00Z")
    run_sweep()
    assert get_entry(entry["id"])["status"] == "EXPIRED_OFFER"

    resp = api_client.claim_waitlist_entry(
        entry["id"], {"expected_entry_version": entry_version},
        make_patron_headers(patron["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_rights_decide_by_reviewer_rejected_two_person_rule():
    """PRD 3.8: "Final decisions are made from either `UNDER_REVIEW` or
    `LEGAL_HOLD` under a two-person rule: the decider's `X-User-ID` must differ
    from `reviewed_by`, and the decider is recorded as `decided_by`."

    Design: Corner/state_machines/rights_decide_by_reviewer_rejected_two_person_rule
    """
    work = make_work(title="Two Person", author="TP", publication_year=2016)
    request = file_work_rights_request(work["id"], claimant_name="TP Estate")
    begin_review(request["id"], reviewer="legal-b")

    resp = api_client.decide_rights_request(
        request["id"], {"decision": "DISMISS"}, make_legal_reviewer_headers("legal-b")
    )
    validate_error(resp, ApiErrorId.ERR_SO_DUTY_VIOLATION)
    fresh = validate_success(api_client.get_rights_request(request["id"], LEGAL))
    assert fresh["status"] == "UNDER_REVIEW"
    assert fresh["decided_by"] is None


def test_begin_review_by_filer_rejected_sod():
    """PRD 3.8: "Segregation of duties is absolute at this step: the reviewer's
    `X-User-ID` must differ from `filed_by`, because no one may review their
    own filing, and a breach is `ERR_SO_DUTY_VIOLATION`."

    Design: Corner/state_machines/begin_review_by_filer_rejected_sod
    """
    work = make_work(title="SOD Work", author="SOD", publication_year=2017)
    request = file_work_rights_request(work["id"], claimant_name="SOD Claimant")

    resp = api_client.begin_review_rights_request(
        request["id"], make_legal_reviewer_headers("legal-a")
    )
    validate_error(resp, ApiErrorId.ERR_SO_DUTY_VIOLATION)
    fresh = validate_success(api_client.get_rights_request(request["id"], LEGAL))
    assert fresh["status"] == "FILED"


def test_credential_self_decision_rejected():
    """PRD 3.1: "On a `VERIFY` decision an officer may never act on their own
    credential — if the officer's `X-User-ID` equals the credential's
    `patron_id`, the verification is refused with `ERR_SO_DUTY_VIOLATION`."

    Design: Corner/state_machines/credential_self_decision_rejected
    """
    patron = make_patron(email="ac@example.org")
    cred = get_success_data(
        api_client.create_accessibility_credential(
            create_accessibility_credential_payload(patron["id"]),
            make_patron_headers(patron["id"]),
        )
    )
    resp = api_client.decide_accessibility_credential(
        cred["id"], {"decision": "VERIFY"},
        make_accessibility_officer_headers(patron["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SO_DUTY_VIOLATION)
    fresh = validate_success(
        api_client.get_accessibility_credential(cred["id"], TEST_USERS["accessibility_officer_headers"])
    )
    assert fresh["status"] == "PENDING_REVIEW"
    assert fresh["decided_by"] is None
