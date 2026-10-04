"""Sweep cascades, strike suspension boundary, temporal gates, and the
library-withdrawal loan gate."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data,
    ApiErrorId, TEST_USERS, make_patron_headers,
    create_loan_payload, create_crawl_job_payload,
    set_clock, run_sweep, make_patron, make_library, make_work,
    make_batch_with_items, setup_work_with_lendable_items, checkout, join_waitlist,
    get_entry, get_item, get_loan, get_patron, get_job,
)

ADMIN = TEST_USERS["admin_headers"]
LIBADMIN = TEST_USERS["library_admin_headers"]
SCANOP = TEST_USERS["scan_operator_headers"]
CRAWLOP = TEST_USERS["crawl_operator_headers"]


def test_sweep_expiry_to_patron_suspension_cascade_third_expiry_suspends():
    """PRD 3.1: "The moment a patron's `strike_count` reaches exactly 3 as a
    consequence of a loan expiry, the patron's `status` flips from `ACTIVE` to
    `SUSPENDED`, and — as the fourth hop of that same cascade — every waitlist
    entry the patron holds in `OFFERED` status is cancelled outright."

    Design: Difficulty/transitive_cascade/sweep_expiry_to_patron_suspension_cascade
    """
    set_clock("2026-09-01T00:00:00Z")
    # PRD 3.4 caps a patron at one ACTIVE loan per work, so the three strikes
    # must come from loans on three distinct works.
    _lib, work, _batch, items = setup_work_with_lendable_items(
        num_items=1,
        work_overrides={"title": "Cascade Studies", "author": "C. Chain",
                        "publication_year": 2010},
    )
    _libB, workB, _batchB, itemsB = setup_work_with_lendable_items(
        num_items=1,
        work_overrides={"title": "Second Source", "author": "S. Source",
                        "publication_year": 2008},
    )
    _libC, workC, _batchC, itemsC = setup_work_with_lendable_items(
        num_items=1,
        work_overrides={"title": "Third Strike", "author": "T. Strike",
                        "publication_year": 2005},
    )
    patron = make_patron(email="p3@example.org")
    loan_a = checkout(items[0]["id"], patron["id"])
    loan_b = checkout(itemsB[0]["id"], patron["id"])
    # while the only copy is on loan the patron joins the work's queue (OPEN)
    entry = join_waitlist(work["id"], patron["id"])
    assert get_entry(entry["id"])["status"] == "OPEN"

    # first sweep: both loans expire; promotion offers the patron's entry
    set_clock("2026-09-16T00:00:00Z")
    run_sweep()
    assert get_entry(entry["id"])["status"] == "OFFERED"
    assert get_patron(patron["id"])["strike_count"] == 2

    # The patron's live OFFERED entry makes a walk-up checkout on that work
    # illegal (PRD 3.4 waitlist priority: "no waitlist entry for the work may
    # be `OPEN` or `OFFERED`"), so the third strike comes from a loan on the
    # third work, whose queue is empty.
    loan_c = checkout(itemsC[0]["id"], patron["id"])
    set_clock("2026-10-01T00:00:00Z")
    run_sweep()
    assert get_loan(loan_c["id"])["status"] == "EXPIRED"
    assert get_item(itemsC[0]["id"])["status"] == "LENDABLE"
    patron_now = get_patron(patron["id"])
    assert patron_now["strike_count"] == 3
    assert patron_now["status"] == "SUSPENDED"


def test_sweep_expiry_to_patron_suspension_cascade_cancels_offered_entries():
    """PRD 3.1: "The moment a patron's `strike_count` reaches exactly 3 as a
    consequence of a loan expiry, the patron's `status` flips from `ACTIVE` to
    `SUSPENDED`, and — as the fourth hop of that same cascade — every waitlist
    entry the patron holds in `OFFERED` status is cancelled outright."

    Design: Difficulty/transitive_cascade/sweep_expiry_to_patron_suspension_cascade
    """
    set_clock("2026-09-01T00:00:00Z")
    # PRD 3.4 caps a patron at one ACTIVE loan per work, so the two strikes
    # before the offer must come from loans on two distinct works.
    _lib, work, _batch, items = setup_work_with_lendable_items(
        num_items=1,
        work_overrides={"title": "Cascade Studies", "author": "C. Chain",
                        "publication_year": 2010},
    )
    _libB, workB, _batchB, itemsB = setup_work_with_lendable_items(
        num_items=1,
        work_overrides={"title": "Second Source", "author": "S. Source",
                        "publication_year": 2008},
    )
    patron = make_patron(email="p3@example.org")
    checkout(items[0]["id"], patron["id"])
    checkout(itemsB[0]["id"], patron["id"])
    entry = join_waitlist(work["id"], patron["id"])

    set_clock("2026-09-16T00:00:00Z")
    run_sweep()
    offered = get_entry(entry["id"])
    assert offered["status"] == "OFFERED"
    assert offered["offered_at"] is not None

    # The third strike must come from a different work: the first work's live
    # OFFERED entry blocks walk-up checkout (PRD 3.4 waitlist priority).
    _libC, workC, _batchC, itemsC = setup_work_with_lendable_items(
        num_items=1,
        work_overrides={"title": "Third Strike", "author": "T. Strike",
                        "publication_year": 2005},
    )
    checkout(itemsC[0]["id"], patron["id"])
    set_clock("2026-10-01T00:00:00Z")
    run_sweep()
    # hop 4: suspension cancels the patron's in-flight OFFERED entry
    assert get_entry(entry["id"])["status"] == "CANCELLED"


def test_strike_count_third_expiry_suspension_boundary_two_expiries_keep_active():
    """PRD 3.1: "The moment a patron's `strike_count` reaches exactly 3 as a
    consequence of a loan expiry, the patron's `status` flips from `ACTIVE` to
    `SUSPENDED`"

    Design: Difficulty/boundary_precision_check/strike_count_third_expiry_suspension_boundary
    """
    set_clock("2026-09-01T00:00:00Z")
    _lib, work, _batch, items = setup_work_with_lendable_items(
        num_items=1,
        work_overrides={"title": "Boundary Tests", "author": "F. Edge",
                        "publication_year": 1999},
    )
    patron = make_patron(email="p8@example.org")
    checkout(items[0]["id"], patron["id"])
    set_clock("2026-09-16T00:00:00Z")
    run_sweep()
    checkout(items[0]["id"], patron["id"])
    set_clock("2026-10-01T00:00:00Z")
    run_sweep()

    patron_now = get_patron(patron["id"])
    # two strikes: the threshold is exactly 3, so the patron is still ACTIVE
    assert patron_now["strike_count"] == 2
    assert patron_now["status"] == "ACTIVE"


def test_strike_count_third_expiry_suspension_boundary_third_suspends():
    """PRD 3.1: "The moment a patron's `strike_count` reaches exactly 3 as a
    consequence of a loan expiry, the patron's `status` flips from `ACTIVE` to
    `SUSPENDED`"
    PRD 3.4: "the patron must be `ACTIVE` (else `ERR_PATRON_SUSPENDED`)"

    Design: Difficulty/boundary_precision_check/strike_count_third_expiry_suspension_boundary
    """
    set_clock("2026-09-01T00:00:00Z")
    _lib, work, _batch, items = setup_work_with_lendable_items(
        num_items=1,
        work_overrides={"title": "Boundary Tests", "author": "F. Edge",
                        "publication_year": 1999},
    )
    patron = make_patron(email="p8@example.org")
    for clock in ("2026-09-16T00:00:00Z", "2026-10-01T00:00:00Z",
                  "2026-10-16T00:00:00Z"):
        checkout(items[0]["id"], patron["id"])
        set_clock(clock)
        run_sweep()

    patron_now = get_patron(patron["id"])
    assert patron_now["strike_count"] == 3
    assert patron_now["status"] == "SUSPENDED"

    resp = api_client.create_loan(
        create_loan_payload(items[0]["id"], patron["id"]),
        make_patron_headers(patron["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PATRON_SUSPENDED)


def test_loan_expiry_vs_renewal_clock_boundary_before_due_succeeds():
    """PRD 3.4: "the current logical clock is strictly before `due_at`"
    PRD 3.4: "When renewal succeeds, `renewed` flips to true and `due_at` is
    recomputed as the current logical clock plus 14 days — not the old `due_at`
    plus 14 days, so renewing early does not bank unused time."

    Design: Difficulty/resource_temporal_overlap/loan_expiry_vs_renewal_clock_boundary
    """
    set_clock("2026-09-01T00:00:00Z")
    _lib, work, _batch, items = setup_work_with_lendable_items(
        num_items=1,
        work_overrides={"title": "Half-Open Hours", "author": "I. Interval",
                        "publication_year": 2020},
    )
    patron = make_patron(email="p12@example.org")
    loan = checkout(items[0]["id"], patron["id"])

    set_clock("2026-09-14T23:59:59.999Z")
    renewed = validate_success(
        api_client.renew_loan(loan["id"], make_patron_headers(patron["id"]))
    )
    assert renewed["renewed"] is True
    assert renewed["due_at"].startswith("2026-09-28T23:59:59.999"), (
        f"due_at must be clock + 14 days, got {renewed['due_at']}"
    )


def test_loan_expiry_vs_renewal_clock_boundary_at_due_rejected():
    """PRD 3.4: "the current logical clock is strictly before `due_at`"
    PRD 3.4: "A failure of any of these is `ERR_LOAN_NOT_RENEWABLE`."

    Design: Difficulty/resource_temporal_overlap/loan_expiry_vs_renewal_clock_boundary
    """
    set_clock("2026-09-01T00:00:00Z")
    _lib, work, _batch, items = setup_work_with_lendable_items(
        num_items=1,
        work_overrides={"title": "Half-Open Hours", "author": "I. Interval",
                        "publication_year": 2020},
    )
    patron = make_patron(email="p12@example.org")
    loan = checkout(items[0]["id"], patron["id"])

    set_clock("2026-09-15T00:00:00Z")
    resp = api_client.renew_loan(loan["id"], make_patron_headers(patron["id"]))
    validate_error(resp, ApiErrorId.ERR_LOAN_NOT_RENEWABLE)
    # only the sweep expires loans; the loan is still ACTIVE before any sweep
    assert get_loan(loan["id"])["status"] == "ACTIVE"


def test_crawl_start_schedule_gate_closed_start_succeeds():
    """PRD 3.6: "The logical clock must have reached `scheduled_at` — starting
    early is `ERR_SCHEDULE_NOT_DUE`"

    Design: Difficulty/resource_temporal_overlap/crawl_start_schedule_gate_and_offer_expiry_boundary
    """
    set_clock("2026-08-31T23:00:00Z")
    job = get_success_data(api_client.create_crawl_job(
        create_crawl_job_payload(
            seed_url="https://sched.site/",
            scheduled_at="2026-09-01T00:00:00Z",
            requests_per_minute=10,
        ),
        CRAWLOP,
    ))
    set_clock("2026-09-01T00:00:00Z")
    started = validate_success(api_client.start_crawl_job(job["id"], CRAWLOP))
    assert started["status"] == "RUNNING"


def test_crawl_start_schedule_gate_claim_at_expiry_rejected():
    """PRD 3.5: "the current logical clock to be strictly before
    `offer_expires_at` — a claim attempted exactly at the expiry instant is
    already too late and is rejected with `ERR_OFFER_EXPIRED`."

    Design: Difficulty/resource_temporal_overlap/crawl_start_schedule_gate_and_offer_expiry_boundary
    """
    set_clock("2026-09-01T00:00:00Z")
    library = make_library(library_code="LIB-J")
    work = make_work(title="Offer Windows", author="J. Lapse", publication_year=2012)
    batch, items = make_batch_with_items(
        work["id"], library["id"], item_specs=[{}], seal=False
    )
    patron = make_patron(email="p13@example.org")
    entry = join_waitlist(work["id"], patron["id"])
    # seal offers the entry at 2026-09-01T00:00:00Z; expires 2026-09-03T00:00:00Z
    get_success_data(api_client.seal_scan_batch(batch["id"], SCANOP))
    offered = get_entry(entry["id"])
    assert offered["status"] == "OFFERED"
    assert offered["offer_expires_at"].startswith("2026-09-03T00:00:00")

    set_clock("2026-09-03T00:00:00Z")
    resp = api_client.claim_waitlist_entry(
        entry["id"], {"expected_entry_version": offered["version"]},
        make_patron_headers(patron["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED)
    # the failed claim does not consume the offer: entry is still OFFERED
    assert get_entry(entry["id"])["status"] == "OFFERED"


def test_library_withdrawal_gated_by_active_loans_blocked_then_succeeds():
    """PRD 3.2: "if any scan item owned by the library is currently `ON_LOAN`,
    the withdrawal is rejected with `ERR_LIBRARY_HAS_ACTIVE_LOANS`. When the
    withdrawal succeeds, every item the library owns in `LENDABLE` or
    `DEPOSITED` status is retired to `RETIRED`"

    Design: Difficulty/cross_entity_state_dependency/library_withdrawal_gated_by_active_loans
    """
    set_clock("2026-09-01T00:00:00Z")
    _lib, work, _batch, items = setup_work_with_lendable_items(
        num_items=1,
        work_overrides={"title": "Withdrawal Ledger", "author": "H. Vault",
                        "publication_year": 1975},
    )
    patron = make_patron(email="p11@example.org")
    loan = checkout(items[0]["id"], patron["id"])

    resp = api_client.withdraw_partner_library(_lib["id"], LIBADMIN)
    validate_error(resp, ApiErrorId.ERR_LIBRARY_HAS_ACTIVE_LOANS)

    validate_success(
        api_client.return_loan(loan["id"], make_patron_headers(patron["id"]))
    )
    withdrawn = validate_success(
        api_client.withdraw_partner_library(_lib["id"], LIBADMIN)
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert get_item(items[0]["id"])["status"] == "RETIRED"


def test_library_withdrawal_gated_by_active_loans_retired_item_not_lendable():
    """PRD 2.5: "Item lendability — the item must be `LENDABLE` with an
    `ACTIVE` owning library, and at claim time a lendable item of the work must
    still exist; otherwise `ERR_ITEM_NOT_LENDABLE`."

    Design: Difficulty/cross_entity_state_dependency/library_withdrawal_gated_by_active_loans
    """
    set_clock("2026-09-01T00:00:00Z")
    _lib, work, _batch, items = setup_work_with_lendable_items(
        num_items=1,
        work_overrides={"title": "Withdrawal Ledger", "author": "H. Vault",
                        "publication_year": 1975},
    )
    patron = make_patron(email="p11@example.org")
    loan = checkout(items[0]["id"], patron["id"])
    validate_success(
        api_client.return_loan(loan["id"], make_patron_headers(patron["id"]))
    )
    validate_success(api_client.withdraw_partner_library(_lib["id"], LIBADMIN))

    resp = api_client.create_loan(
        create_loan_payload(items[0]["id"], patron["id"]),
        make_patron_headers(patron["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ITEM_NOT_LENDABLE)
