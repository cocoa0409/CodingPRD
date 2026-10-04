"""Endpoint coverage: OCC, playback suppression, directive retract, sweeps,
promotion selector policy, and immediate consistency."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data,
    ApiErrorId, TEST_USERS, make_patron_headers, make_legal_reviewer_headers,
    create_crawl_job_payload, create_exclusion_directive_payload,
    set_clock, run_sweep, make_patron, make_library, make_work,
    make_batch_with_items, setup_work_with_lendable_items, checkout, join_waitlist,
    get_entry, get_item, get_patron, get_capture, get_job,
    make_grant, make_budget_line, get_grant,
    begin_review, decide_request,
)

ADMIN = TEST_USERS["admin_headers"]
CRAWLOP = TEST_USERS["crawl_operator_headers"]
FINANCE = TEST_USERS["finance_admin_headers"]
LEGAL = TEST_USERS["legal_reviewer_headers"]


def test_waitlist_claim_occ_happy_path_and_stale_replay():
    """PRD 2.6: "Claiming an offered waitlist entry requires the request to
    carry `expected_entry_version`, equal to the `WaitlistEntry`'s `version` as
    the claimant last observed it. If the entry's version has advanced since
    that observation ... the claim is rejected with `ERR_STALE_VERSION` (HTTP
    412) ... A successful claim itself increments the entry's `version` by 1."

    Design: Corner/endpoints/waitlist_claim_occ_happy_path_and_stale_replay
    """
    set_clock("2026-09-01T00:00:00Z")
    library = make_library(library_code="LIB-OC")
    work = make_work(title="OCC Claim", author="OC", publication_year=2015)
    batch, items = make_batch_with_items(
        work["id"], library["id"], item_specs=[{}], seal=False
    )
    patron = make_patron(email="oc@example.org")
    entry = join_waitlist(work["id"], patron["id"])
    get_success_data(api_client.seal_scan_batch(batch["id"], TEST_USERS["scan_operator_headers"]))
    offered = get_entry(entry["id"])
    assert offered["status"] == "OFFERED"
    version = offered["version"]

    headers = make_patron_headers(patron["id"])
    loan = validate_success(
        api_client.claim_waitlist_entry(
            entry["id"], {"expected_entry_version": version}, headers
        ),
        expected_status=201,
    )
    assert loan["status"] == "ACTIVE"
    assert get_entry(entry["id"])["status"] == "CLAIMED"
    assert get_patron(patron["id"])["active_loan_count"] == 1

    # Replays of the spent token are rejected. After the successful claim the
    # entry is terminally CLAIMED, so PRD 2.5's state precondition (priority
    # 6) pre-empts the OCC check (priority 23) and the same-token replay draws
    # ERR_INVALID_STATE; the OCC-specific path is exercised below on a live
    # offer whose version has advanced.
    resp = api_client.claim_waitlist_entry(
        entry["id"], {"expected_entry_version": version}, headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_patron(patron["id"])["active_loan_count"] == 1

    # The patron returns the item; promotion re-offers the SAME entry (PRD
    # 3.5: the offer "moves the entry from `OPEN` to `OFFERED`", so the
    # terminal CLAIMED entry is untouched and a fresh entry is offered
    # instead) — build that fresh entry on a second patron to exercise the
    # stale-token rejection on a live OFFERED entry whose version advanced.
    get_success_data(api_client.return_loan(loan["id"], headers))
    assert get_patron(patron["id"])["active_loan_count"] == 0

    patron2 = make_patron(email="oc2@example.org")
    entry2 = join_waitlist(work["id"], patron2["id"])
    offered2 = get_entry(entry2["id"])
    assert offered2["status"] == "OFFERED"
    version2 = offered2["version"]

    # Advance the entry's version without a claim: a patron-initiated OPEN
    # cancel is not exposed in v1, so the version bump comes from the offer
    # lifecycle — expire the offer (version bumps OFFERED -> EXPIRED_OFFER)
    # and let re-promotion re-offer a fresh entry for patron2.
    set_clock("2026-09-04T00:00:00Z")  # past offer_expires_at (offered_at + 48h)
    run_sweep()
    assert get_entry(entry2["id"])["status"] == "EXPIRED_OFFER"

    entry3 = join_waitlist(work["id"], patron2["id"])
    offered3 = get_entry(entry3["id"])
    assert offered3["status"] == "OFFERED"
    stale_token = offered3["version"] - 1

    # The version-advanced replay is rejected with ERR_STALE_VERSION (PRD 2.6:
    # "If the entry's version has advanced since that observation ... the
    # claim is rejected with `ERR_STALE_VERSION` (HTTP 412)").
    headers2 = make_patron_headers(patron2["id"])
    resp = api_client.claim_waitlist_entry(
        entry3["id"], {"expected_entry_version": stale_token}, headers2
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert get_patron(patron2["id"])["active_loan_count"] == 0

    # The correct token claims cleanly and bumps the entry version by 1.
    loan3 = validate_success(
        api_client.claim_waitlist_entry(
            entry3["id"], {"expected_entry_version": offered3["version"]}, headers2
        ),
        expected_status=201,
    )
    assert loan3["status"] == "ACTIVE"
    assert get_entry(entry3["id"])["version"] == offered3["version"] + 1


def test_budget_settle_occ_stale_version_rejected():
    """PRD 2.6: "Settling or releasing a budget line requires
    `expected_grant_version`, equal to the funding grant's current `version` as
    the finance administrator last observed it. A mismatch is rejected with
    `ERR_STALE_VERSION` (HTTP 412), because grant counters (`reserved_cents`,
    `spent_cents`) may have moved under the caller and the resulting status
    recomputation would be based on a stale baseline."

    Design: Corner/endpoints/budget_settle_occ_stale_version_rejected
    """
    grant = make_grant(amount_cents=100000, donor_name="OCC Donor")
    line_a = make_budget_line(grant["id"], 50000, "STORAGE")
    stale_version = get_grant(grant["id"])["version"]
    line_b = make_budget_line(grant["id"], 10000, "BANDWIDTH")

    resp = api_client.settle_budget_line(
        line_a["id"],
        {"actual_spend_cents": 40000, "expected_grant_version": stale_version},
        FINANCE,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert validate_success(api_client.get_budget_line(line_a["id"], FINANCE))["status"] == "OPEN"

    fresh_version = get_grant(grant["id"])["version"]
    settled = validate_success(
        api_client.settle_budget_line(
            line_a["id"],
            {"actual_spend_cents": 40000, "expected_grant_version": fresh_version},
            FINANCE,
        )
    )
    assert settled["status"] == "SETTLED"
    grant_now = get_grant(grant["id"])
    assert grant_now["reserved_cents"] == 10000
    assert grant_now["spent_cents"] == 40000


def test_playback_suppressed_by_upheld_rights_request():
    """PRD 3.7: "Suppression is then evaluated live — never cached — before any
    candidate is served: if an `ACTIVE` exclusion directive scoped
    `PLAYBACK_ONLY` or `BOTH` has a `url_prefix` that is a string prefix of the
    requested URL, or if a rights request of subject kind `CAPTURE_URL_PREFIX`
    in `LEGAL_HOLD` or `UPHELD_REMOVED` status has a `url_prefix` covering the
    URL, the resolution is `SUPPRESSED` with no capture."

    Design: Corner/endpoints/playback_suppressed_by_upheld_rights_request
    """
    set_clock("2026-09-01T00:00:00Z")
    job = get_success_data(api_client.create_crawl_job(
        create_crawl_job_payload(
            seed_url="https://rights.site/",
            scheduled_at="2026-09-01T00:05:00Z",
            requests_per_minute=10,
        ),
        CRAWLOP,
    ))
    set_clock("2026-09-01T00:05:00Z")
    get_success_data(api_client.start_crawl_job(job["id"], CRAWLOP))
    cap = get_success_data(api_client.create_capture(
        {"crawl_job_id": job["id"], "url": "https://rights.site/page",
         "content_hash": "rh1", "has_dynamic_content": False},
        CRAWLOP,
    ))
    get_success_data(api_client.complete_crawl_job(job["id"], CRAWLOP))
    request = get_success_data(api_client.create_rights_request(
        {"subject_kind": "CAPTURE_URL_PREFIX", "url_prefix": "https://rights.site/",
         "claimant_name": "Site Owner"},
        LEGAL,
    ))
    begin_review(request["id"], reviewer="legal-b")

    pre = validate_success(
        api_client.get_playback(ADMIN, params={"url": "https://rights.site/page"})
    )
    assert pre["mode"] == "FULL"

    decide_request(request["id"], "UPHOLD", decider="legal-c")
    post = validate_success(
        api_client.get_playback(ADMIN, params={"url": "https://rights.site/page"})
    )
    assert post["mode"] == "SUPPRESSED"
    assert post["capture_id"] is None
    assert get_capture(cap["id"])["playback_status"] == "SUPPRESSED"


def test_directive_retract_restores_playback():
    """PRD 3.6: "Retracting an `ACTIVE` directive moves it to `RETRACTED` and
    restores playback where the retracted directive was the last thing
    standing: every capture that had been suppressed by this directive flips
    its `playback_status` back to `PLAYABLE`, unless some other `ACTIVE`
    directive scoped for playback or an upheld rights request on a URL prefix
    still covers that capture's URL, in which case it stays `SUPPRESSED`."

    Design: Corner/endpoints/directive_retract_restores_playback
    """
    set_clock("2026-09-01T00:00:00Z")
    job = get_success_data(api_client.create_crawl_job(
        create_crawl_job_payload(
            seed_url="https://multi.site/",
            scheduled_at="2026-09-01T00:05:00Z",
            requests_per_minute=10,
        ),
        CRAWLOP,
    ))
    set_clock("2026-09-01T00:05:00Z")
    get_success_data(api_client.start_crawl_job(job["id"], CRAWLOP))
    cap_a = get_success_data(api_client.create_capture(
        {"crawl_job_id": job["id"], "url": "https://multi.site/a",
         "content_hash": "ma", "has_dynamic_content": False},
        CRAWLOP,
    ))
    cap_b = get_success_data(api_client.create_capture(
        {"crawl_job_id": job["id"], "url": "https://multi.site/b",
         "content_hash": "mb", "has_dynamic_content": False},
        CRAWLOP,
    ))
    d1 = validate_success(api_client.create_exclusion_directive(
        {"url_prefix": "https://multi.site/", "scope": "PLAYBACK_ONLY",
         "reason": "d1"},
        CRAWLOP,
    ), expected_status=201)
    d2 = validate_success(api_client.create_exclusion_directive(
        {"url_prefix": "https://multi.site/b", "scope": "PLAYBACK_ONLY",
         "reason": "d2"},
        CRAWLOP,
    ), expected_status=201)

    get_success_data(api_client.retract_exclusion_directive(d1["directive_id"], CRAWLOP))
    assert get_capture(cap_a["id"])["playback_status"] == "PLAYABLE"
    assert get_capture(cap_b["id"])["playback_status"] == "SUPPRESSED"

    play_a = validate_success(
        api_client.get_playback(ADMIN, params={"url": "https://multi.site/a"})
    )
    assert play_a["mode"] == "FULL"
    play_b = validate_success(
        api_client.get_playback(ADMIN, params={"url": "https://multi.site/b"})
    )
    assert play_b["mode"] == "SUPPRESSED"


def test_sweep_expires_offer_and_promotes_next_in_line():
    """PRD 2.8: "The sweep then expires waitlist offers: every `OFFERED` entry
    whose `offer_expires_at` is at or before the clock transitions to
    `EXPIRED_OFFER`, processed in order of `offer_expires_at` ascending, each
    followed by re-promotion for the same work."
    PRD 2.8: "The sweep's response reports four lists: `expired_loan_ids`,
    `expired_offer_ids`, `suspended_patron_ids`, and `offered_entry_ids`
    (entries newly promoted during the run)."
    PRD 3.5: "`offer_expires_at` is set exactly 48 hours after `offered_at`."

    Design: Corner/cross_cutting_layers/sweep_expires_offer_and_promotes_next_in_line
    """
    set_clock("2026-09-01T00:00:00Z")
    library = make_library(library_code="LIB-SW")
    work = make_work(title="Sweep Promote", author="SW", publication_year=2006)
    batch, items = make_batch_with_items(
        work["id"], library["id"], item_specs=[{}], seal=False
    )
    patron1 = make_patron(email="sw1@example.org")
    patron2 = make_patron(email="sw2@example.org")
    entry1 = join_waitlist(work["id"], patron1["id"])
    entry2 = join_waitlist(work["id"], patron2["id"])
    # seal offers the head entry at 2026-09-01T00:00:00Z (expires 09-03T00:00:00Z)
    get_success_data(api_client.seal_scan_batch(batch["id"], TEST_USERS["scan_operator_headers"]))
    assert get_entry(entry1["id"])["status"] == "OFFERED"
    assert get_entry(entry2["id"])["status"] == "OPEN"

    set_clock("2026-09-03T01:00:00Z")
    sweep = run_sweep()
    assert entry1["id"] in sweep["expired_offer_ids"]
    assert entry2["id"] in sweep["offered_entry_ids"]
    e1 = get_entry(entry1["id"])
    e2 = get_entry(entry2["id"])
    assert e1["status"] == "EXPIRED_OFFER"
    assert e2["status"] == "OFFERED"
    assert e2["offer_expires_at"].startswith("2026-09-05T01:00:00"), (
        f"offer_expires_at must be sweep time + 48h, got {e2['offer_expires_at']}"
    )


def test_promotion_skips_ineligible_head_and_offers_next():
    """PRD 3.5: "A patron whose `active_loan_count` has reached their
    `max_concurrent_loans` is transiently ineligible: the entry stays `OPEN`
    and is simply skipped, to be reconsidered on the next promotion run."
    PRD 3.5: "The first eligible patron wins: the entry moves from `OPEN` to
    `OFFERED`"

    Design: Corner/cross_cutting_layers/promotion_skips_ineligible_head_and_offers_next
    """
    set_clock("2026-09-01T00:00:00Z")
    library = make_library(library_code="LIB-SK")
    work = make_work(title="Skip Head", author="SK", publication_year=2003)
    fillers = [
        make_work(title=f"Filler {i}", author="SK", publication_year=2003)
        for i in range(1, 6)
    ]
    # batch 1: one item per filler work, sealed so all five are lendable
    batch1, filler_items = make_batch_with_items(
        fillers[0]["id"], library["id"], item_specs=[{}], seal=False
    )
    for w in fillers[1:]:
        get_success_data(api_client.create_item(
            {"batch_id": batch1["id"], "work_id": w["id"],
             "owning_library_id": library["id"], "page_count": 10,
             "condition_grade": "GOOD"},
            TEST_USERS["scan_operator_headers"],
        ))
    get_success_data(api_client.seal_scan_batch(batch1["id"], TEST_USERS["scan_operator_headers"]))

    head = make_patron(email="sk1@example.org")
    tail = make_patron(email="sk2@example.org")
    item_rows, _ = validate_paginated(
        api_client.list_batch_items(batch1["id"], TEST_USERS["scan_operator_headers"])
    )
    assert len(item_rows) == 5
    for row in item_rows:
        checkout(row["id"], head["id"])
    assert get_patron(head["id"])["active_loan_count"] == 5

    entry_head = join_waitlist(work["id"], head["id"])
    entry_tail = join_waitlist(work["id"], tail["id"])

    batch2, items2 = make_batch_with_items(
        work["id"], library["id"], item_specs=[{}], seal=False
    )
    get_success_data(api_client.seal_scan_batch(batch2["id"], TEST_USERS["scan_operator_headers"]))

    assert get_entry(entry_head["id"])["status"] == "OPEN"
    assert get_entry(entry_tail["id"])["status"] == "OFFERED"
    assert get_item(items2[0]["id"])["status"] == "LENDABLE"


def test_checkout_effects_visible_immediately():
    """PRD 3.4: "A successful checkout stamps `checked_out_at` with the current
    logical clock and sets `due_at` to 14 days after checkout for a `STANDARD`
    loan or exactly 1 hour after checkout for a `SHORT_READ` loan. The item
    moves from `LENDABLE` to `ON_LOAN`, and the patron's `active_loan_count`
    increases by 1."

    Design: Corner/consistency_model/checkout_effects_visible_immediately
    """
    set_clock("2026-09-01T00:00:00Z")
    _lib, work, _batch, items = setup_work_with_lendable_items(
        num_items=1,
        work_overrides={"title": "Immediate", "author": "IC",
                        "publication_year": 2017},
    )
    patron = make_patron(email="ic@example.org")
    loan = checkout(items[0]["id"], patron["id"])
    assert loan["status"] == "ACTIVE"
    assert loan["due_at"].startswith("2026-09-15T00:00:00")

    assert get_patron(patron["id"])["active_loan_count"] == 1
    rows, _ = validate_paginated(api_client.list_work_items(work["id"], ADMIN))
    assert len(rows) == 1
    assert rows[0]["status"] == "ON_LOAN"
