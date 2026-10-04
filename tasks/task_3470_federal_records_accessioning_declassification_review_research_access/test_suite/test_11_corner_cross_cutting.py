"""Corner coverage: optimistic concurrency on review creation, the
late-return suspension cascade, and on-the-spot priority recomputation."""

import test_helpers as th

E = th.ApiErrorId


def test_occ_stale_collection_version_on_review_create(api):
    """PRD §2.7: "A request to open a review must carry
    `expected_collection_version`, holding the `version` of the target
    collection as the client last observed it. If that value does not equal the
    collection's current `version` — because, for example, another writer has
    already opened a review against the same collection (which advances the
    collection's `version` as review demand is recorded) or a posture-relevant
    cascade has recomputed the collection — the request is rejected with
    `ERR_STALE_COLLECTION_VERSION` (HTTP 412), and no review is created."

    Design: Corner/cross_cutting_layers/occ_stale_collection_version_on_review_create
    """
    th.set_clock()
    bundle = th.setup_classified_collection(classification_default="SECRET")
    collection = bundle["collection"]
    ada = th.create_active_researcher()
    researcher = th.make_researcher_headers(ada["id"])

    observed_version = th.current_collection_version(collection["id"])
    payload = th.declass_review_payload(
        collection["id"], "MANDATORY", observed_version,
        requester_researcher_id=ada["id"], justification="first",
    )
    first = th.validate_success(
        api.create_declass_review(payload, headers=researcher), 201
    )
    assert first["status"] == "OPEN"
    assert th.current_collection_version(collection["id"]) == observed_version + 1

    # The same observed version is now stale.
    stale_payload = th.declass_review_payload(
        collection["id"], "MANDATORY", observed_version,
        requester_researcher_id=ada["id"], justification="stale retry",
    )
    th.validate_error(
        api.create_declass_review(stale_payload, headers=researcher),
        E.ERR_STALE_COLLECTION_VERSION,
    )

    data, meta = th.validate_paginated(
        api.list_declass_reviews(
            headers=th.TEST_USERS["declass_reviewer_headers"],
            params={"collection_id": collection["id"]},
        )
    )
    assert len(data) == 1
    assert meta["total_count"] == 1


def test_late_return_suspension_cascade(api):
    """PRD §3.7: "The return stamps `returned_at` from the logical clock and
    computes `late_return`: the pull is late when `returned_at` falls strictly
    after `due_back_at` — a return at exactly the due instant is on time."
    PRD §3.7: "A late return suspends the researcher: their registration moves
    to `SUSPENDED` with `suspension_reason` set to `LATE_RETURN`, and the
    suspension cascades in the same transaction — every sibling pull request of
    that researcher still in `REQUESTED` is cancelled, and every reproduction
    request of theirs still in `QUOTED` is cancelled, freeing the pages those
    reproductions had committed against the daily quota."

    Design: Corner/cross_cutting_layers/late_return_suspension_cascade
    """
    th.set_clock()
    bundle = th.setup_public_described_collection()
    collection = bundle["collection"]
    dan = th.create_active_researcher(
        "Dan Roots", "dan@example.org", "GENEALOGIST", "PP-4004"
    )
    cid = th.create_active_researcher(
        "Cid Dealer", "cid@example.org", "COMMERCIAL", "PP-3003"
    )
    staff = th.TEST_USERS["research_room_staff_headers"]

    dan_pull = th.create_fulfilled_pull(dan, collection, 1, 5, "2026-09-01T00:00:00Z")
    cid_pull1 = th.create_fulfilled_pull(cid, collection, 6, 10, "2026-09-01T00:00:00Z")
    cid_pull2 = th.create_pull(cid, collection, 11, 15, "2026-09-05T00:00:00Z")
    cid_repro = th.create_reproduction(cid, collection, 10)

    # Return at exactly due_back_at: on time (the boundary is strict).
    th.set_clock("2026-09-02T00:00:00Z")
    dan_returned = th.validate_success(
        api.return_pull_request(dan_pull["id"], headers=staff), 200
    )
    assert dan_returned["late_return"] is False
    dan_after = th.get_success_data(api.get_researcher(dan["id"], headers=staff))
    assert dan_after["status"] == "ACTIVE"

    # Return one day late: suspension and its cascade fire.
    th.set_clock("2026-09-03T00:00:00Z")
    cid_returned = th.validate_success(
        api.return_pull_request(cid_pull1["id"], headers=staff), 200
    )
    assert cid_returned["late_return"] is True
    assert cid_returned["status"] == "RETURNED"

    cid_after = th.get_success_data(api.get_researcher(cid["id"], headers=staff))
    assert cid_after["status"] == "SUSPENDED"
    assert cid_after["suspension_reason"] == "LATE_RETURN"

    pull2_after = th.get_success_data(
        api.get_pull_request(cid_pull2["id"], headers=staff)
    )
    assert pull2_after["status"] == "CANCELLED"
    repro_after = th.get_success_data(
        api.get_reproduction_request(cid_repro["id"], headers=staff)
    )
    assert repro_after["status"] == "CANCELLED"

    th.validate_error(
        api.create_pull_request(
            th.pull_request_payload(cid["id"], collection["id"], 16, 20,
                                    "2026-09-05T00:00:00Z"),
            headers=th.make_researcher_headers(cid["id"]),
        ),
        E.ERR_RESEARCHER_NOT_ACTIVE,
    )


def test_priority_recompute_on_demand_mutation(api):
    """PRD §3.4: "The score is not frozen at enqueue: while a collection
    remains `QUEUED`, any mutation of `pull_count_total`,
    `repro_pages_fulfilled`, or `foia_release_count` recomputes
    `digitization_priority` on the spot."
    PRD §3.8: "Fulfillment adds the request's `page_count` to the collection's
    `repro_pages_fulfilled`, advances the collection's `version`, and
    recomputes `digitization_priority` when the collection is `QUEUED`."
    PRD §3.4: "plus 1 point per 50 fulfilled reproduction pages, where the page
    count is capped at 500 before being divided by 50 and rounded down"

    Design: Corner/cross_cutting_layers/priority_recompute_on_demand_mutation
    """
    th.set_clock()
    bundle = th.setup_queued_collection()  # cutoff 2001-03-15 -> age 25
    collection = bundle["collection"]
    assert collection["digitization_priority"] == 50
    assert collection["digitization_priority"] == th.expected_digitization_priority(
        th.STARTUP_CLOCK_UTC, "2001-03-15T00:00:00Z"
    )

    bob = th.create_active_researcher(
        "Bob Press", "bob@example.org", "JOURNALIST", "PP-2002"
    )
    repro = th.create_paid_reproduction(
        bob, collection, 120, "DIGITAL_SCAN", payment_reference="card-txn-120"
    )
    fulfilled = th.fulfill_reproduction(repro)
    assert fulfilled["status"] == "FULFILLED"

    after = th.read_collection(collection["id"])
    assert after["repro_pages_fulfilled"] == 120
    assert after["digitization_priority"] == 52
    assert after["digitization_priority"] == th.expected_digitization_priority(
        th.STARTUP_CLOCK_UTC, "2001-03-15T00:00:00Z", repro_pages_fulfilled=120
    )
