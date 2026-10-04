"""Difficulty coverage (queue A): resource/temporal overlap — pairwise
inclusive unit-range exclusion with half-open occupation windows, and the
aggregate 8-seat daily reading-room capacity."""

import test_helpers as th

E = th.ApiErrorId


def test_unit_range_pairwise_exclusion(api):
    """PRD §3.7: "Third, the reservation must not collide with another pull: a
    conflict exists when another pull request on the same collection, in
    `REQUESTED` or `PULLED` status, reserves a unit range sharing at least one
    integer unit with the new range and occupies a time window sharing at least
    one instant with the new pull's window (`ERR_UNIT_RESERVATION_CONFLICT`,
    409). A pull's occupation window is the half-open interval from its
    `visit_date` through two days later; adjacent unit ranges such as units
    10–20 versus 21–30 share no unit and never conflict, disjoint windows never
    conflict even for identical ranges, and pulls on different collections
    never conflict."

    Design: Difficulty/resource_temporal_overlap/unit_range_pairwise_exclusion
    """
    th.set_clock()
    bundle = th.setup_public_described_collection()
    collection_id = bundle["collection"]["id"]
    ada = th.create_active_researcher()
    bob = th.create_active_researcher(
        "Bob Press", "bob@example.org", "JOURNALIST", "PP-2002"
    )

    # Ada holds [10,20] visiting 2026-09-10 (occupation [09-10, 09-12)).
    pull_a = th.create_pull(ada, bundle["collection"], 10, 20, "2026-09-10T00:00:00Z")
    assert pull_a["status"] == "REQUESTED"

    # [15,25] on the same day shares units 15-20 and the same window.
    resp = api.create_pull_request(
        th.pull_request_payload(bob["id"], collection_id, 15, 25,
                                "2026-09-10T00:00:00Z"),
        headers=th.make_researcher_headers(bob["id"]),
    )
    assert resp.status_code == 409
    th.validate_error(resp, E.ERR_UNIT_RESERVATION_CONFLICT)

    # [21,30] is adjacent to [10,20]: the inclusive ranges share no unit.
    pull_b = th.validate_success(
        api.create_pull_request(
            th.pull_request_payload(bob["id"], collection_id, 21, 30,
                                    "2026-09-10T00:00:00Z"),
            headers=th.make_researcher_headers(bob["id"]),
        ),
        201,
    )
    assert pull_b["status"] == "REQUESTED"

    # Identical range on a disjoint window: [09-10, 09-12) vs [09-20, 09-22).
    pull_c = th.validate_success(
        api.create_pull_request(
            th.pull_request_payload(ada["id"], collection_id, 10, 20,
                                    "2026-09-20T00:00:00Z"),
            headers=th.make_researcher_headers(ada["id"]),
        ),
        201,
    )
    assert pull_c["status"] == "REQUESTED"


def test_unit_range_window_edges_and_different_collections(api):
    """PRD §3.7: "A pull's occupation window is the half-open interval from
    its `visit_date` through two days later; adjacent unit ranges such as units
    10–20 versus 21–30 share no unit and never conflict, disjoint windows never
    conflict even for identical ranges, and pulls on different collections
    never conflict."
    PRD §3.7: "a conflict exists when another pull request on the same
    collection, in `REQUESTED` or `PULLED` status, reserves a unit range
    sharing at least one integer unit with the new range and occupies a time
    window sharing at least one instant with the new pull's window
    (`ERR_UNIT_RESERVATION_CONFLICT`, 409)"

    Design: Difficulty/resource_temporal_overlap/unit_range_pairwise_exclusion
    """
    th.set_clock()
    agency = th.create_agency()
    bundle_a = th.setup_public_described_collection(
        agency=agency, schedule_kwargs={"schedule_number": "SCH-DOJ-080"}
    )
    bundle_b = th.setup_public_described_collection(
        agency=agency, schedule_kwargs={"schedule_number": "SCH-DOJ-081"}
    )
    ada = th.create_active_researcher()
    bob = th.create_active_researcher(
        "Bob Press", "bob@example.org", "JOURNALIST", "PP-2002"
    )
    bob_headers = th.make_researcher_headers(bob["id"])

    # Ada holds [10,20] on collection A visiting 09-10 (window [09-10, 09-12)).
    th.create_pull(ada, bundle_a["collection"], 10, 20, "2026-09-10T00:00:00Z")

    # Containment inside Ada's range on an overlapping window: conflict.
    th.validate_error(
        api.create_pull_request(
            th.pull_request_payload(bob["id"], bundle_a["collection"]["id"],
                                    12, 15, "2026-09-11T00:00:00Z"),
            headers=bob_headers,
        ),
        E.ERR_UNIT_RESERVATION_CONFLICT,
    )

    # The identical range whose window starts exactly when Ada's ends
    # (half-open boundary): no shared instant, no conflict.
    resp = api.create_pull_request(
        th.pull_request_payload(bob["id"], bundle_a["collection"]["id"],
                                10, 20, "2026-09-12T00:00:00Z"),
        headers=bob_headers,
    )
    th.validate_success(resp, 201)

    # The identical range on a different collection never conflicts.
    resp = api.create_pull_request(
        th.pull_request_payload(bob["id"], bundle_b["collection"]["id"],
                                10, 20, "2026-09-10T00:00:00Z"),
        headers=bob_headers,
    )
    th.validate_success(resp, 201)


def _fill_eight_seats(collection):
    """Eight REQUESTED pulls with disjoint 5-unit ranges, all visiting
    2026-09-10 — the room's 8 seats on 09-10 and 09-11 are exactly full."""
    ada = th.create_active_researcher()
    bob = th.create_active_researcher(
        "Bob Press", "bob@example.org", "JOURNALIST", "PP-2002"
    )
    cid = th.create_active_researcher(
        "Cid Dealer", "cid@example.org", "COMMERCIAL", "PP-3003"
    )
    pulls = []
    for researcher, start in (
        (ada, 1), (ada, 6), (ada, 11),
        (bob, 16), (bob, 21), (bob, 26),
        (cid, 31), (cid, 36),
    ):
        pulls.append(
            th.create_pull(researcher, collection, start, start + 4,
                           "2026-09-10T00:00:00Z")
        )
    return ada, bob, cid, pulls


def test_reading_room_seat_aggregate_capacity(api):
    """PRD §3.7: "Fourth, reading-room seat capacity: a pull occupies one seat
    on each UTC day of its occupation window — the visit day and the following
    day — and for each of those days the total number of seated pulls across
    all researchers and all collections, counting `REQUESTED` and `PULLED`
    pulls whose windows cover that day, must remain within the room's 8 seats;
    the eighth pull seated on a day succeeds and the ninth is rejected
    (`ERR_READING_ROOM_CAPACITY`, 409)."

    Design: Difficulty/resource_temporal_overlap/reading_room_seat_aggregate_capacity
    """
    th.set_clock()
    bundle = th.setup_public_described_collection()
    collection = bundle["collection"]
    _, _, cid, pulls = _fill_eight_seats(collection)
    assert all(p["status"] == "REQUESTED" for p in pulls)

    # The ninth pull seated on 09-10 exceeds the room's 8 seats — even though
    # its unit range overlaps nothing.
    resp = api.create_pull_request(
        th.pull_request_payload(cid["id"], collection["id"], 41, 45,
                                "2026-09-10T00:00:00Z"),
        headers=th.make_researcher_headers(cid["id"]),
    )
    assert resp.status_code == 409
    th.validate_error(resp, E.ERR_READING_ROOM_CAPACITY)

    # Shifting the visit to 09-12 moves the occupation window to
    # [09-12, 09-14), which shares no day with the eight [09-10, 09-12)
    # windows.
    shifted = th.validate_success(
        api.create_pull_request(
            th.pull_request_payload(cid["id"], collection["id"], 41, 45,
                                    "2026-09-12T00:00:00Z"),
            headers=th.make_researcher_headers(cid["id"]),
        ),
        201,
    )
    assert shifted["status"] == "REQUESTED"


def test_reading_room_seat_released_on_return(api):
    """PRD §3.7: "for each of those days the total number of seated pulls
    across all researchers and all collections, counting `REQUESTED` and
    `PULLED` pulls whose windows cover that day, must remain within the room's
    8 seats; the eighth pull seated on a day succeeds and the ninth is rejected
    (`ERR_READING_ROOM_CAPACITY`, 409)"
    PRD §3.7: "The return stamps `returned_at` from the logical clock and
    computes `late_return`: the pull is late when `returned_at` falls strictly
    after `due_back_at` — a return at exactly the due instant is on time."

    Design: Difficulty/resource_temporal_overlap/reading_room_seat_aggregate_capacity
    """
    th.set_clock()
    bundle = th.setup_public_described_collection()
    collection = bundle["collection"]
    _, _, cid, pulls = _fill_eight_seats(collection)

    # The ninth pull is rejected while all eight seats are held...
    th.validate_error(
        api.create_pull_request(
            th.pull_request_payload(cid["id"], collection["id"], 41, 45,
                                    "2026-09-10T00:00:00Z"),
            headers=th.make_researcher_headers(cid["id"]),
        ),
        E.ERR_READING_ROOM_CAPACITY,
    )

    # ...but returning one pull (on time: due_back_at is 09-11) moves it out
    # of the counted REQUESTED/PULLED statuses and frees its seat.
    returned = th.return_pull(th.fulfill_pull(pulls[0]))
    assert returned["status"] == "RETURNED"
    assert returned["late_return"] is False

    ninth = th.validate_success(
        api.create_pull_request(
            th.pull_request_payload(cid["id"], collection["id"], 41, 45,
                                    "2026-09-10T00:00:00Z"),
            headers=th.make_researcher_headers(cid["id"]),
        ),
        201,
    )
    assert ninth["status"] == "REQUESTED"
