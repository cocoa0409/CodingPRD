"""Validation-error and RBAC-denial coverage."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data,
    ApiErrorId, TEST_USERS, make_patron_headers,
    create_crawl_job_payload, create_loan_payload, create_waitlist_entry_payload,
    set_clock, make_patron, make_library, make_work, make_batch_with_items,
    setup_work_with_lendable_items, checkout, join_waitlist, get_item, get_entry,
)

ADMIN = TEST_USERS["admin_headers"]
ANON = TEST_USERS["anonymous_headers"]
LIBADMIN = TEST_USERS["library_admin_headers"]
SCANOP = TEST_USERS["scan_operator_headers"]
CRAWLOP = TEST_USERS["crawl_operator_headers"]
LEGAL = TEST_USERS["legal_reviewer_headers"]


def test_missing_auth_headers_rejected():
    """PRD 2.1: "A missing or invalid header — including an `X-User-Role` value
    that is not one of the declared roles — is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401). The sole exception is the `Anonymous`
    role, which carries no `X-User-ID` at all and is used only for self-service
    patron registration."

    Design: Corner/validations/missing_auth_headers_rejected
    """
    resp = api_client.create_work(
        {"title": "No Auth", "author": "NA", "publication_year": 2000},
        headers={"Content-Type": "application/json"},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_crawl_job_rpm_out_of_range():
    """PRD 3.6: "The politeness limit must lie between 1 and 120 requests per
    minute inclusive."
    PRD 3.6: "Marking a site `at_risk` — it defaults to false — signals double
    capture frequency intent for the scheduler, but the politeness cap still
    applies in full; urgency never overrides courtesy."

    Design: Corner/validations/crawl_job_rpm_out_of_range
    """
    set_clock("2026-09-01T00:00:00Z")
    resp0 = api_client.create_crawl_job(
        {"seed_url": "https://rpm0.site/", "scheduled_at": "2026-09-02T00:00:00Z",
         "requests_per_minute": 0},
        CRAWLOP,
    )
    validate_error(resp0, ApiErrorId.ERR_VALIDATION)
    resp121 = api_client.create_crawl_job(
        {"seed_url": "https://rpm121.site/", "scheduled_at": "2026-09-02T00:00:00Z",
         "requests_per_minute": 121},
        CRAWLOP,
    )
    validate_error(resp121, ApiErrorId.ERR_VALIDATION)
    ok = validate_success(
        api_client.create_crawl_job(
            {"seed_url": "https://rpm120.site/", "scheduled_at": "2026-09-02T00:00:00Z",
             "requests_per_minute": 120, "at_risk": True},
            CRAWLOP,
        ),
        expected_status=201,
    )
    assert ok["status"] == "SCHEDULED"


def test_scheduled_at_not_in_future_rejected():
    """PRD 3.6: "The schedule must be strictly in the future relative to the
    logical clock at creation — a `scheduled_at` at or before the present is a
    schema violation."

    Design: Corner/validations/scheduled_at_not_in_future_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api_client.create_crawl_job(
        {"seed_url": "https://now.site/", "scheduled_at": "2026-09-01T00:00:00Z",
         "requests_per_minute": 10},
        CRAWLOP,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_duplicate_waitlist_entry_rejected():
    """PRD 3.5: "at most one entry per (`work_id`, `patron_id`) pair may be live
    in `OPEN` or `OFFERED` status, and a duplicate live entry is
    `ERR_DUPLICATE`."

    Design: Corner/validations/duplicate_waitlist_entry_rejected
    """
    work = make_work(title="Dup Wait", author="DW", publication_year=2005)
    patron = make_patron(email="dw@example.org")
    entry = join_waitlist(work["id"], patron["id"])
    assert entry["status"] == "OPEN"

    resp = api_client.create_waitlist_entry(
        create_waitlist_entry_payload(work["id"], patron["id"]),
        make_patron_headers(patron["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE)

    rows, meta = validate_paginated(
        api_client.list_work_waitlist_entries(
            work["id"], ADMIN, params={"patron_id": patron["id"]}
        )
    )
    assert len(rows) == 1
    assert rows[0]["id"] == entry["id"]


def test_direct_checkout_blocked_by_live_waitlist():
    """PRD 3.4: "no waitlist entry for the work may be `OPEN` or `OFFERED` — the
    queue always wins over a walk-up checkout, and a live queue means
    `ERR_WAITLIST_PRIORITY`"

    Design: Corner/validations/direct_checkout_blocked_by_live_waitlist
    """
    set_clock("2026-09-01T00:00:00Z")
    library = make_library(library_code="LIB-WP")
    work = make_work(title="Queue Wins", author="WP", publication_year=2007)
    # deposit the item but leave the batch unsealed so the item stays DEPOSITED
    batch, items = make_batch_with_items(
        work["id"], library["id"], item_specs=[{}], seal=False
    )
    patron1 = make_patron(email="wp1@example.org")
    patron2 = make_patron(email="wp2@example.org")
    entry = join_waitlist(work["id"], patron1["id"])
    assert entry["status"] == "OPEN"

    # sealing promotes the waiting patron to OFFERED
    get_success_data(api_client.seal_scan_batch(batch["id"], SCANOP))
    assert get_entry(entry["id"])["status"] == "OFFERED"

    resp = api_client.create_loan(
        create_loan_payload(items[0]["id"], patron2["id"]),
        make_patron_headers(patron2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_WAITLIST_PRIORITY)
    assert get_item(items[0]["id"])["status"] == "LENDABLE"


def test_second_loan_same_work_different_item_rejected():
    """PRD 3.4: "the patron must not already hold an `ACTIVE` loan on any other
    item of the same work (`ERR_WORK_ALREADY_BORROWED`)"

    Design: Corner/validations/second_loan_same_work_different_item_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    _lib, work, _batch, items = setup_work_with_lendable_items(
        num_items=2,
        work_overrides={"title": "Already Borrowed", "author": "AB",
                        "publication_year": 2009},
    )
    patron = make_patron(email="ab@example.org")
    checkout(items[0]["id"], patron["id"])

    resp = api_client.create_loan(
        create_loan_payload(items[1]["id"], patron["id"]),
        make_patron_headers(patron["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_WORK_ALREADY_BORROWED)
    assert get_item(items[1]["id"])["status"] == "LENDABLE"


def test_short_read_without_verified_credential_rejected():
    """PRD 3.4: "A `SHORT_READ` checkout carries one further gate: the patron
    must hold a credential in `VERIFIED` status, and without one the request is
    refused with `ERR_ACCESS_CREDENTIAL_REQUIRED`."
    PRD 3.4: "sets `due_at` to 14 days after checkout for a `STANDARD` loan or
    exactly 1 hour after checkout for a `SHORT_READ` loan."

    Design: Corner/validations/short_read_without_verified_credential_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    _lib, work, _batch, items = setup_work_with_lendable_items(
        num_items=2,
        work_overrides={"title": "Credential Gate", "author": "CR",
                        "publication_year": 2013},
    )
    patron = make_patron(email="cr@example.org")
    # submit a credential but leave it PENDING_REVIEW (never decided)
    cred_resp = api_client.create_accessibility_credential(
        {"patron_id": patron["id"], "certifier_reference": "NLS-55"},
        make_patron_headers(patron["id"]),
    )
    assert cred_resp.status_code == 201

    resp = api_client.create_loan(
        create_loan_payload(items[0]["id"], patron["id"], loan_kind="SHORT_READ"),
        make_patron_headers(patron["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ACCESS_CREDENTIAL_REQUIRED)

    loan = validate_success(
        api_client.create_loan(
            create_loan_payload(items[1]["id"], patron["id"], loan_kind="STANDARD"),
            make_patron_headers(patron["id"]),
        ),
        expected_status=201,
    )
    assert loan["status"] == "ACTIVE"
    assert loan["due_at"] == "2026-09-15T00:00:00.000Z" or loan["due_at"].startswith(
        "2026-09-15T00:00:00"
    ), f"STANDARD loan due_at must be checkout + 14 days, got {loan['due_at']}"


def test_patron_cannot_create_works_or_run_sweeps():
    """PRD 2.1: "Once authenticated, a caller whose role is not listed among the
    endpoint's permitted roles — or whose identity fails an entity-backed
    ownership check — is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/roles/patron_cannot_create_works_or_run_sweeps
    """
    patron = make_patron(email="rbac@example.org")
    resp1 = api_client.create_work(
        {"title": "Forbidden", "author": "RB", "publication_year": 2000},
        make_patron_headers(patron["id"]),
    )
    validate_error(resp1, ApiErrorId.ERR_UNAUTHORIZED)
    resp2 = api_client.run_sweep(make_patron_headers(patron["id"]))
    validate_error(resp2, ApiErrorId.ERR_UNAUTHORIZED)


def test_patron_cannot_read_other_patrons_record():
    """PRD 2.1: "When `X-User-Role` is `Patron`, `X-User-ID` is the `id` of the
    acting `Patron`; ownership checks on any resource that references a
    `Patron` — loans, waitlist entries, accessibility credentials, the patron
    record itself — compare the resource's patron foreign-key field to
    `X-User-ID`, and a mismatch is `ERR_UNAUTHORIZED`."

    Design: Corner/roles/patron_cannot_read_other_patrons_record
    """
    patron_a = make_patron(email="pa@example.org")
    patron_b = make_patron(email="pb@example.org")
    resp = api_client.get_patron(patron_b["id"], make_patron_headers(patron_a["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    ok = validate_success(
        api_client.get_patron(patron_a["id"], make_patron_headers(patron_a["id"]))
    )
    assert ok["id"] == patron_a["id"]


def test_crawl_operator_cannot_manage_rights_requests():
    """PRD 2.1: "Once authenticated, a caller whose role is not listed among the
    endpoint's permitted roles — or whose identity fails an entity-backed
    ownership check — is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/roles/crawl_operator_cannot_manage_rights_requests
    """
    set_clock("2026-09-01T00:00:00Z")
    work = make_work(title="Role Split", author="RS", publication_year=2004)
    resp1 = api_client.create_rights_request(
        {"subject_kind": "WORK", "work_id": work["id"],
         "claimant_name": "Wrong Role"},
        CRAWLOP,
    )
    validate_error(resp1, ApiErrorId.ERR_UNAUTHORIZED)
    resp2 = api_client.create_crawl_job(
        {"seed_url": "https://role.site/", "scheduled_at": "2026-09-02T00:00:00Z",
         "requests_per_minute": 10},
        LEGAL,
    )
    validate_error(resp2, ApiErrorId.ERR_UNAUTHORIZED)
