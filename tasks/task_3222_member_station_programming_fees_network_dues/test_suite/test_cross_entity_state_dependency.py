"""State dependencies that cross an entity boundary (queue A,
rule `cross_entity_state_dependency`).

Two pairs are named: a station's projected vote eligibility governs a
candidacy's fate, and an agreement's carriage status governs whether a window
beneath it may reach the schedule.
"""
from test_helpers import (
    AUDITOR,
    GOVERNANCE,
    SCHEDULER,
    api_client,
    create_agreement,
    create_online_feed,
    create_program,
    create_slot,
    create_window,
    get_success_data,
    make_station_eligible,
    make_station_manager_headers,
    refresh_window,
    set_clock,
)

CANDIDACY_STATION = dict(
    call_sign="WPLN", licensee_name="Cumberland Licensee", state_code="TN",
    dma_market_rank=30, dma_households=900000, coverage_population=80000,
    full_time_staff_count=7, newsroom_staff_count=4,
    annual_local_revenue_cents=4800000, board_seat_region="REGION_SOUTH",
)

WINDOW_STATION = dict(
    call_sign="KOPB", licensee_name="Willamette Licensee", state_code="OR",
    dma_market_rank=21, dma_households=1100000, coverage_population=95000,
    full_time_staff_count=7, newsroom_staff_count=4,
    annual_local_revenue_cents=4800000, board_seat_region="REGION_WEST",
)


def setup_qualified_candidate():
    """An open election holding one QUALIFIED candidacy from an ELIGIBLE station."""
    set_clock("2026-09-01T00:00:00Z")
    station = make_station_eligible(**CANDIDACY_STATION)
    headers = make_station_manager_headers(station["id"])
    election = get_success_data(api_client.create_election(
        {"board_region": "REGION_SOUTH", "fiscal_year": 2026, "seats_available": 1,
         "certification_deadline": "2026-12-01T00:00:00Z"}, GOVERNANCE), 201)
    candidate = get_success_data(api_client.create_candidate(
        {"parent_election_id": election["id"], "station_id": station["id"],
         "nomination_statement": "Serve the Cumberland region"}, headers), 201)
    qualified = get_success_data(api_client.qualify_candidate(candidate["id"], GOVERNANCE))
    return {"station": station, "headers": headers, "election": election,
            "candidate": qualified}


def test_qualifying_a_candidacy_stamps_the_candidacy_cycle():
    """PRD §3.10: "A `FILED` candidacy is qualified by a governance officer provided
    the station that filed it has reached its `eligible_from` instant;
    qualification stamps `last_candidacy_cycle` with the current instant, which is
    the timestamp the certification check reads."

    Design: Difficulty/cross_entity_state_dependency/cross_pair_station_eligibility_gates_candidacy
    """
    ctx = setup_qualified_candidate()
    data = ctx["candidate"]

    assert data["candidate_status"] == "QUALIFIED", (
        f"an eligible station's candidacy should qualify, got {data['candidate_status']}"
    )
    assert data["last_candidacy_cycle"] is not None, (
        "qualification must stamp the candidacy cycle instant"
    )


def test_candidacy_lapses_when_its_station_loses_vote_eligibility():
    """PRD §3.10: "any qualified candidacy whose station has lost vote eligibility
    before closure lapses."
    PRD §3.10: "A `SUSPENDED` or `WITHDRAWN` station is neither eligible nor
    projected." PRD §3.9: "must not be `SUSPENDED` or `WITHDRAWN` — the latter
    failing with `ERR_STATION_SUSPENDED`" is what removes a station from the
    electorate; PRD §3.9 separately has "a station suspended during the round
    leaves it".

    The station is suspended between qualification and closure, so it has lost
    vote eligibility and the close act lapses its candidacy.

    Design: Difficulty/cross_entity_state_dependency/cross_pair_station_eligibility_gates_candidacy
    """
    ctx = setup_qualified_candidate()
    get_success_data(api_client.suspend_station(
        ctx["station"]["id"], {"suspension_reason": "Coverage contour dispute"},
        AUDITOR))
    set_clock("2026-12-02T00:00:00Z")
    get_success_data(api_client.close_election(ctx["election"]["id"], GOVERNANCE))

    candidate = get_success_data(api_client.get_candidate(ctx["candidate"]["id"], GOVERNANCE))
    assert candidate["candidate_status"] == "LAPSED", (
        f"the candidacy should lapse with the election, got {candidate['candidate_status']}"
    )


def test_probation_keeps_the_station_in_the_projected_eligible_set():
    """PRD §3.10: "A `PROBATION` station remains vote-eligible by this rule, but it
    holds no vote weight — its class weight table gives it a weight only through
    its class, and probation does not change the class."

    Design: Difficulty/cross_entity_state_dependency/cross_pair_station_eligibility_gates_candidacy
    """
    set_clock("2026-09-01T00:00:00Z")
    station = make_station_eligible(**CANDIDACY_STATION)
    on_probation = get_success_data(api_client.probation(
        station["id"], {"reason_code": "LOCAL_CONTENT_SHORTFALL"}, AUDITOR))

    assert on_probation["eligibility_status"] == "PROBATION"
    assert on_probation["dues_vote_eligible"] is True, (
        "a probation station remains vote-eligible under the projection rule"
    )


def setup_cleared_agreement_with_reserved_slot():
    """An agreement in CLEARED with one cleared window and its RESERVED slot."""
    set_clock("2026-09-01T00:00:00Z")
    station = make_station_eligible(**WINDOW_STATION)
    headers = make_station_manager_headers(station["id"])
    program = create_program(program_code="NP-1006", program_title="Coast Range Journal")
    agreement = create_agreement(station, program_code=program["program_code"])
    feed = create_online_feed(feed_code="FEED-A001")
    window = create_window(agreement, station,
                           window_start="2026-10-05T14:00:00Z",
                           window_end="2026-10-05T15:00:00Z")
    slot = create_slot(feed, station, window,
                       slot_start="2026-10-05T13:30:00Z",
                       slot_end="2026-10-05T15:30:00Z", priority_rank=3)
    get_success_data(api_client.submit_agreement(agreement["id"], headers))
    get_success_data(api_client.review_agreement(agreement["id"], AUDITOR))
    get_success_data(api_client.request_clearance(window["id"], headers))
    get_success_data(api_client.clear_window(window["id"], AUDITOR))
    cleared = get_success_data(api_client.clear_agreement(agreement["id"], AUDITOR))
    return {"station": station, "headers": headers, "program": program,
            "agreement": cleared, "feed": feed, "window": refresh_window(window),
            "slot": slot}


def test_publishing_an_agreement_schedules_the_window_beneath_it():
    """PRD §3.3: "Publishing a `CLEARED` agreement moves it to `CARRIED`, stamps
    `published_at` with the current instant, and requires every window under it to
    be cleared. Four effects land at once. Every window under the agreement that
    is `CLEARED` moves to `SCHEDULED`".

    Design: Difficulty/cross_entity_state_dependency/cross_pair_agreement_status_gates_window_publishing
    """
    ctx = setup_cleared_agreement_with_reserved_slot()
    assert ctx["window"]["clearance_status"] == "CLEARED"

    get_success_data(api_client.publish_agreement(ctx["agreement"]["id"], SCHEDULER))
    window = refresh_window(ctx["window"])

    assert window["clearance_status"] == "SCHEDULED", (
        f"the window should follow its agreement into SCHEDULED, "
        f"got {window['clearance_status']}"
    )


def test_republishing_the_agreement_returns_the_window_to_cleared():
    """PRD §3.3: "The scheduler may return a `CARRIED` agreement to `CLEARED`, which
    clears `published_at`, moves every window under it from `SCHEDULED` back to
    `CLEARED`, and increments the program's `publication_cycle` a second time".

    Design: Difficulty/cross_entity_state_dependency/cross_pair_agreement_status_gates_window_publishing
    """
    ctx = setup_cleared_agreement_with_reserved_slot()
    get_success_data(api_client.publish_agreement(ctx["agreement"]["id"], SCHEDULER))
    get_success_data(api_client.republish_agreement(ctx["agreement"]["id"], SCHEDULER))
    window = refresh_window(ctx["window"])

    assert window["clearance_status"] == "CLEARED", (
        f"the revert edge should return the window to CLEARED, "
        f"got {window['clearance_status']}"
    )