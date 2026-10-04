"""Difficulty coverage (queue A): compensating invariants — the daily
committed-pages total is conserved across create/cancel, and the active pull
count is conserved across create/return."""

import test_helpers as th

E = th.ApiErrorId


def _bob_and_collection():
    th.set_clock()
    bundle = th.setup_public_described_collection()
    bob = th.create_active_researcher(
        "Bob Press", "bob@example.org", "JOURNALIST", "PP-2002"
    )
    return bundle["collection"], bob


def test_daily_committed_pages_conserved(api):
    """PRD §3.8: "`CANCELLED` requests are excluded from the sum, so
    cancelling restores quota immediately."
    PRD §3.8: "the committed pages plus the new request's `page_count` must
    not exceed 200 pages, with the boundary inclusive: a request that brings
    the day to exactly 200 pages succeeds, and one page beyond is rejected with
    `ERR_DAILY_PAGE_LIMIT_EXCEEDED` (409)."
    PRD §3.8: "the owning researcher may cancel a request while it is still
    `QUOTED` (`ERR_REPRO_NOT_CANCELLABLE`, 409, otherwise); cancellation moves
    it to `CANCELLED` and frees its committed pages from the daily quota."

    Design: Difficulty/compensating_invariant/daily_committed_pages_conserved
    """
    collection, bob = _bob_and_collection()
    researcher = th.make_researcher_headers(bob["id"])

    # Forward action: commit 40 pages.
    first = th.validate_success(
        api.create_reproduction_request(
            th.reproduction_payload(bob["id"], collection["id"], 40, "DIGITAL_SCAN"),
            headers=researcher,
        ),
        201,
    )
    assert first["fee_cents"] == 2600  # 1600 + 20*50

    # Compensating action: cancel restores the committed total to zero.
    cancelled = th.validate_success(
        api.cancel_reproduction_request(first["id"], headers=researcher), 200
    )
    assert cancelled["status"] == "CANCELLED"

    # A full 200-page request then succeeds — impossible if any of the 40
    # cancelled pages had leaked out of the conserved total.
    big = th.validate_success(
        api.create_reproduction_request(
            th.reproduction_payload(bob["id"], collection["id"], 200, "DIGITAL_SCAN"),
            headers=researcher,
        ),
        201,
    )
    assert big["fee_cents"] == 8100  # 1600 + 4000 + 100*25

    # And the 201st page pins the conserved total at exactly 200.
    th.validate_error(
        api.create_reproduction_request(
            th.reproduction_payload(bob["id"], collection["id"], 1, "DIGITAL_SCAN"),
            headers=researcher,
        ),
        E.ERR_DAILY_PAGE_LIMIT_EXCEEDED,
    )


def test_daily_committed_pages_count_paid_and_fulfilled(api):
    """PRD §3.8: "Summed across the researcher's requests created on the same
    UTC calendar day as the logical clock and still counted — those in
    `QUOTED`, `PAID`, or `FULFILLED` status — the committed pages plus the new
    request's `page_count` must not exceed 200 pages, with the boundary
    inclusive: a request that brings the day to exactly 200 pages succeeds, and
    one page beyond is rejected with `ERR_DAILY_PAGE_LIMIT_EXCEEDED` (409)."

    Design: Difficulty/compensating_invariant/daily_committed_pages_conserved
    """
    collection, bob = _bob_and_collection()

    # 100 pages move QUOTED -> PAID; the pages stay committed.
    first = th.create_paid_reproduction(bob, collection, 100)
    assert first["status"] == "PAID"
    # A further 100 reaches the inclusive cap exactly.
    second = th.create_reproduction(bob, collection, 100)
    assert second["status"] == "QUOTED"

    # Fulfilling the first does not free pages either: FULFILLED still counts.
    th.fulfill_reproduction(first)
    th.validate_error(
        api.create_reproduction_request(
            th.reproduction_payload(bob["id"], collection["id"], 1, "DIGITAL_SCAN"),
            headers=th.make_researcher_headers(bob["id"]),
        ),
        E.ERR_DAILY_PAGE_LIMIT_EXCEEDED,
    )


def test_active_pull_count_conserved(api):
    """PRD §3.7: "Fifth and last, the researcher's own active-pull limit: a
    researcher may hold fewer than 3 pulls in `REQUESTED` or `PULLED` status,
    so a third active pull succeeds while a fourth is rejected
    (`ERR_ACTIVE_PULL_LIMIT_EXCEEDED`, 409); `RETURNED` and `CANCELLED` pulls
    release their slot."
    PRD §3.7: "A pull that clears every gate starts `REQUESTED`, with
    `due_back_at` computed as its `visit_date` plus 24 hours."

    Design: Difficulty/compensating_invariant/active_pull_count_conserved
    """
    th.set_clock()
    bundle = th.setup_public_described_collection()
    collection = bundle["collection"]
    ada = th.create_active_researcher()
    researcher = th.make_researcher_headers(ada["id"])

    pull_1 = th.create_pull(ada, collection, 1, 5, "2026-09-10T00:00:00Z")
    pull_2 = th.create_pull(ada, collection, 6, 10, "2026-09-12T00:00:00Z")
    pull_3 = th.create_pull(ada, collection, 11, 15, "2026-09-14T00:00:00Z")

    # The fourth active pull exceeds the limit of 3.
    resp = api.create_pull_request(
        th.pull_request_payload(ada["id"], collection["id"], 16, 20,
                                "2026-09-16T00:00:00Z"),
        headers=researcher,
    )
    assert resp.status_code == 409
    th.validate_error(resp, E.ERR_ACTIVE_PULL_LIMIT_EXCEEDED)

    # Compensating pair: fulfill + return releases the slot.
    returned = th.return_pull(th.fulfill_pull(pull_3))
    assert returned["status"] == "RETURNED"
    assert returned["late_return"] is False
    assert th.same_instant(returned["due_back_at"], "2026-09-15T00:00:00Z")

    # The identical create now succeeds — the count is conserved at 3.
    pull_4 = th.validate_success(
        api.create_pull_request(
            th.pull_request_payload(ada["id"], collection["id"], 16, 20,
                                    "2026-09-16T00:00:00Z"),
            headers=researcher,
        ),
        201,
    )
    assert pull_4["status"] == "REQUESTED"

    data, meta = th.validate_paginated(
        api.list_pull_requests(
            headers=th.TEST_USERS["research_room_staff_headers"],
            params={"researcher_id": ada["id"], "status": "REQUESTED"},
        )
    )
    assert len(data) == 3
    assert meta["total_count"] == 3
    assert {p["id"] for p in data} == {pull_1["id"], pull_2["id"], pull_4["id"]}


def test_active_pull_limit_is_per_researcher(api):
    """PRD §3.7: "Fifth and last, the researcher's own active-pull limit: a
    researcher may hold fewer than 3 pulls in `REQUESTED` or `PULLED` status,
    so a third active pull succeeds while a fourth is rejected
    (`ERR_ACTIVE_PULL_LIMIT_EXCEEDED`, 409); `RETURNED` and `CANCELLED` pulls
    release their slot."

    Design: Difficulty/compensating_invariant/active_pull_count_conserved
    """
    th.set_clock()
    bundle = th.setup_public_described_collection()
    collection = bundle["collection"]
    ada = th.create_active_researcher()
    bob = th.create_active_researcher(
        "Bob Press", "bob@example.org", "JOURNALIST", "PP-2002"
    )

    th.create_pull(ada, collection, 1, 5, "2026-09-10T00:00:00Z")
    th.create_pull(ada, collection, 6, 10, "2026-09-12T00:00:00Z")
    th.create_pull(ada, collection, 11, 15, "2026-09-14T00:00:00Z")

    # Ada is at her own cap of 3.
    th.validate_error(
        api.create_pull_request(
            th.pull_request_payload(ada["id"], collection["id"], 16, 20,
                                    "2026-09-16T00:00:00Z"),
            headers=th.make_researcher_headers(ada["id"]),
        ),
        E.ERR_ACTIVE_PULL_LIMIT_EXCEEDED,
    )

    # The limit is per researcher: Bob's count is unaffected by Ada's three.
    bob_pull = th.validate_success(
        api.create_pull_request(
            th.pull_request_payload(bob["id"], collection["id"], 21, 25,
                                    "2026-09-10T00:00:00Z"),
            headers=th.make_researcher_headers(bob["id"]),
        ),
        201,
    )
    assert bob_pull["status"] == "REQUESTED"
