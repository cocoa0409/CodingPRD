"""The three placement checks: inventory collision, candidate separation, daily cap."""

from test_helpers import (
    ApiErrorId,
    add_spot,
    create_order,
    create_spot_payload,
    classify_candidate_advertiser,
    create_election,
    create_rate_class,
    create_station,
    make_advertiser_agent_headers,
    read_order,
    set_clock,
    setup_issue_order,
    validate_error,
    validate_paginated,
    validate_success,
)


def _overlap_scenario():
    """One issue buyer with a DRAFT order holding a 30-second spot at [1000, 1030)."""
    built = setup_issue_order(
        call_sign="WOVR-TV",
        market_code="DMA-144",
        station_overrides={
            "licensee_name": "Overlap Broadcast Partners",
            "political_file_posting_deadline_hours": 24,
            "daily_political_seconds_cap": 300,
        },
        classification=None,
        spots=[
            {
                "air_date": "2026-08-20",
                "start_offset_seconds": 1000,
                "duration_seconds": 30,
                "program_code": "EN-1",
            }
        ],
    )
    return built


def test_spot_starting_exactly_where_the_incumbent_ends_does_not_collide(api):
    """PRD §3.4: "Treat every spot as the half-open interval that begins at its
    `start_offset_seconds` and ends `duration_seconds` later — the start instant belongs
    to the spot, the end instant does not."
    PRD §3.4: "Because the intervals are half-open, exact adjacency is legal: a spot
    beginning at the precise second another one ends does not collide, and neither does
    one ending at the precise second another one begins."

    Design: Difficulty/resource_temporal_overlap/rate_class_inventory_uses_half_open_overlap_so_touching_spots_are_legal
    """
    built = _overlap_scenario()
    order, advertiser = built["order"], built["advertiser"]
    headers = make_advertiser_agent_headers(advertiser["id"])

    touching = validate_success(
        api.add_spot(
            order["id"],
            create_spot_payload(
                air_date="2026-08-20", start_offset_seconds=1030, program_code="EN-2"
            ),
            headers,
        ),
        201,
    )
    assert touching["start_offset_seconds"] == 1030
    assert touching["status"] == "SCHEDULED"

    refreshed = read_order(order["id"], advertiser["id"])
    assert refreshed["spot_count"] == 2

    rows, meta = validate_paginated(api.list_spots(headers, params={"order_id": order["id"]}))
    assert meta["total_count"] == 2
    assert len(rows) == 2


def test_spot_overlapping_the_incumbent_by_one_second_collides(api):
    """PRD §3.4: "The new spot collides with such a spot when the new spot's start is
    strictly earlier than that spot's end *and* that spot's start is strictly earlier
    than the new spot's end. Any collision is rejected with `ERR_SPOT_SLOT_COLLISION`
    (HTTP 409)."
    PRD §3.4: "Gather every existing spot that is priced from the same rate class as the
    new spot, that falls on the same `air_date`, that is itself `SCHEDULED` or `AIRED`,
    and whose owning order is in any of `DRAFT`, `SUBMITTED`, `ACCEPTED`, `SUSPENDED`,
    `RUNNING` or `COMPLETED`."

    Design: Difficulty/resource_temporal_overlap/rate_class_inventory_uses_half_open_overlap_so_touching_spots_are_legal
    """
    built = _overlap_scenario()
    order, advertiser = built["order"], built["advertiser"]
    headers = make_advertiser_agent_headers(advertiser["id"])

    add_spot(
        order["id"],
        advertiser["id"],
        air_date="2026-08-20",
        start_offset_seconds=1030,
        program_code="EN-2",
    )

    validate_error(
        api.add_spot(
            order["id"],
            create_spot_payload(
                air_date="2026-08-20", start_offset_seconds=1029, program_code="EN-3"
            ),
            headers,
        ),
        ApiErrorId.ERR_SPOT_SLOT_COLLISION,
    )

    refreshed = read_order(order["id"], advertiser["id"])
    assert refreshed["spot_count"] == 2, "the refused placement adds no spot"
    _rows, meta = validate_paginated(api.list_spots(headers, params={"order_id": order["id"]}))
    assert meta["total_count"] == 2


def _separation_scenario():
    """Two opposing candidates on one election; the incumbent spot occupies [30000, 30030)."""
    set_clock("2026-08-05T09:00:00Z")
    station = create_station(
        call_sign="WSEP-TV",
        licensee_name="Separation Media Holdings",
        market_code="DMA-177",
        political_file_posting_deadline_hours=24,
        daily_political_seconds_cap=300,
    )
    election = create_election(station["id"], office_sought="Governor", election_type="PRIMARY")
    early_news = create_rate_class(station["id"], class_code="RC-EN")
    prime = create_rate_class(
        station["id"],
        class_code="RC-PR",
        daypart="PRIME",
        preemptible=False,
        preemption_priority=0,
        posted_rate_cents=100000,
    )
    okafor = classify_candidate_advertiser(
        station["id"],
        election["id"],
        legal_name="Okafor For Governor",
        candidate_name="Lena Okafor",
        office_sought="Governor",
        qualification_evidence_ref="FEC-F2-2026-0101",
    )
    whitlock = classify_candidate_advertiser(
        station["id"],
        election["id"],
        legal_name="Whitlock For Governor",
        candidate_name="Ray Whitlock",
        office_sought="Governor",
        qualification_evidence_ref="FEC-F2-2026-0102",
    )
    okafor_order = create_order(
        station["id"],
        okafor["id"],
        early_news["id"],
        payment_terms="NET_30",
        sponsorship_disclosure_text=(
            "PAID FOR BY Okafor For Governor; AUTHORIZED BY Okafor For Governor"
        ),
        election_id=election["id"],
    )
    okafor_spot = add_spot(
        okafor_order["id"],
        okafor["id"],
        air_date="2026-08-20",
        start_offset_seconds=30000,
        program_code="EN-O1",
    )
    whitlock_order = create_order(
        station["id"],
        whitlock["id"],
        prime["id"],
        payment_terms="NET_30",
        sponsorship_disclosure_text=(
            "PAID FOR BY Whitlock For Governor; AUTHORIZED BY Whitlock For Governor"
        ),
        election_id=election["id"],
    )
    return {
        "station": station,
        "election": election,
        "okafor": okafor,
        "whitlock": whitlock,
        "okafor_order": okafor_order,
        "okafor_spot": okafor_spot,
        "whitlock_order": whitlock_order,
    }


def test_opposing_candidate_spot_899_seconds_away_violates_the_separation_buffer(api):
    """PRD §3.4: "For each such spot, measure the gap: take the later of the two start
    offsets and the earlier of the two end offsets, subtract the second from the first,
    and treat any negative result as a gap of zero. If any gap is strictly less than the
    separation buffer of 900 seconds — fifteen minutes — the placement is rejected with
    `ERR_CANDIDATE_SEPARATION_VIOLATION` (HTTP 409)."
    PRD §3.4: "Gather every existing spot on the same `air_date`, in any rate class,
    that is `SCHEDULED` or `AIRED`, whose owning order is attributed to the same
    election as the new spot's order — both `election_id` values must be non-null and
    equal — whose owning order belongs to a *different* advertiser, whose owning order
    is in any of `DRAFT`, `SUBMITTED`, `ACCEPTED`, `SUSPENDED`, `RUNNING` or
    `COMPLETED`, and where the advertiser behind that order *and* the advertiser behind
    the new spot's order are **both** sitting in `CLASSIFIED_CANDIDATE`."

    Design: Difficulty/resource_temporal_overlap/election_candidate_separation_uses_900_second_buffer_across_rate_classes
    """
    scenario = _separation_scenario()
    headers = make_advertiser_agent_headers(scenario["whitlock"]["id"])

    validate_error(
        api.add_spot(
            scenario["whitlock_order"]["id"],
            create_spot_payload(
                air_date="2026-08-20", start_offset_seconds=30929, program_code="PR-W1"
            ),
            headers,
        ),
        ApiErrorId.ERR_CANDIDATE_SEPARATION_VIOLATION,
    )

    assert read_order(scenario["whitlock_order"]["id"], scenario["whitlock"]["id"])["spot_count"] == 0
    assert read_order(scenario["okafor_order"]["id"], scenario["okafor"]["id"])["spot_count"] == 1


def test_opposing_candidate_spot_exactly_900_seconds_away_is_accepted(api):
    """PRD §3.4: "Overlapping and merely adjacent intervals both yield a gap of zero and
    are therefore both violations; a gap of exactly 900 seconds is permitted."
    PRD §3.4: "If any gap is strictly less than the separation buffer of 900 seconds —
    fifteen minutes — the placement is rejected with
    `ERR_CANDIDATE_SEPARATION_VIOLATION` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/election_candidate_separation_uses_900_second_buffer_across_rate_classes
    """
    scenario = _separation_scenario()
    headers = make_advertiser_agent_headers(scenario["whitlock"]["id"])

    permitted = validate_success(
        api.add_spot(
            scenario["whitlock_order"]["id"],
            create_spot_payload(
                air_date="2026-08-20", start_offset_seconds=30930, program_code="PR-W2"
            ),
            headers,
        ),
        201,
    )
    assert permitted["start_offset_seconds"] == 30930
    assert permitted["status"] == "SCHEDULED"

    assert read_order(scenario["whitlock_order"]["id"], scenario["whitlock"]["id"])["spot_count"] == 1
    assert read_order(scenario["okafor_order"]["id"], scenario["okafor"]["id"])["spot_count"] == 1
