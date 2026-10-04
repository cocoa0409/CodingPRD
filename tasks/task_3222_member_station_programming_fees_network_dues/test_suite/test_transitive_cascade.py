"""Cross-aggregate cascades (queue A, rule `transitive_cascade`).

One decision reaches resources the request never named: a station suspension
drops its vote projection out of the electorate, and sending a published program
back for rework withdraws the licence that had been granted under it.
"""
from test_helpers import (
    AUDITOR,
    EDITOR,
    GOVERNANCE,
    api_client,
    create_program,
    get_success_data,
    make_station_eligible,
    make_station_manager_headers,
    refresh_program,
    refresh_station,
    set_clock,
)

VOTE_STATION = dict(
    call_sign="KERA", licensee_name="Trinity Licensee", state_code="TX",
    dma_market_rank=5, dma_households=2400000, coverage_population=140000,
    full_time_staff_count=9, newsroom_staff_count=5,
    annual_local_revenue_cents=4800000, board_seat_region="REGION_SOUTH",
)

PROGRAM_STATION = dict(
    call_sign="WNYC", licensee_name="New York Licensee", state_code="NY",
    dma_market_rank=1, dma_households=7000000, coverage_population=150000,
    full_time_staff_count=9, newsroom_staff_count=5,
    annual_local_revenue_cents=4800000, board_seat_region="REGION_NORTHEAST",
)


def setup_voting_station():
    """An ELIGIBLE station with a live YES vote on one open proposal."""
    set_clock("2026-09-01T00:00:00Z")
    station = make_station_eligible(**VOTE_STATION)
    proposal = get_success_data(api_client.create_proposal(
        {"fiscal_year": 2027, "proposed_base_fee_cents": 1350000,
         "proposed_revenue_rate_bps": 275, "quorum_required_votes": 1,
         "effective_from": "2027-01-01T00:00:00Z"}, GOVERNANCE), 201)
    proposal = get_success_data(api_client.open_proposal(proposal["id"], GOVERNANCE))
    fresh = refresh_station(station)
    get_success_data(api_client.cast_vote(
        proposal["id"],
        {"station_id": fresh["id"], "vote_choice": "YES",
         "current_rate_bps": proposal["current_rate_bps"],
         "expected_station_version": fresh["version"]},
        make_station_manager_headers(fresh["id"])))
    return {"station": fresh, "proposal": proposal}


def test_suspension_drops_the_stations_vote_projection():
    """PRD §3.10: "it reads true only while the station's `eligibility_status` is
    `ELIGIBLE` or `PROBATION` *and* the station's `eligible_from` instant is no
    later than the current instant".
    PRD §3.1: "Suspension removes the station from every dues-proposal quorum
    denominator by dropping its projection row out of the eligible set".

    Design: Difficulty/transitive_cascade/cascade_vote_eligibility_full_recompute
    """
    ctx = setup_voting_station()
    resp = api_client.suspend_station(
        ctx["station"]["id"], {"suspension_reason": "Coverage contour dispute"}, AUDITOR)
    data = get_success_data(resp)

    assert data["eligibility_status"] == "SUSPENDED"
    assert data["dues_vote_eligible"] is False, (
        "a suspended station must leave the vote-eligible set"
    )
    body = get_success_data(api_client.list_eligibility_projections(
        AUDITOR, {"station_id": ctx["station"]["id"]}))
    assert all(p["dues_vote_eligible"] is False for p in body), (
        "every projection row for the station must report dues_vote_eligible false"
    )


def test_suspension_leaves_the_station_balance_untouched():
    """PRD §3.1: "From `ELIGIBLE`, an auditor supplying a non-empty
    `suspension_reason` may suspend the station".
    PRD §2.10: suspension's named cascade is the projection leaving the eligible
    set, not a movement of money.

    Design: Difficulty/transitive_cascade/cascade_vote_eligibility_full_recompute
    """
    ctx = setup_voting_station()
    before = ctx["station"]["dues_arrears_cents"]
    resp = api_client.suspend_station(
        ctx["station"]["id"], {"suspension_reason": "Coverage contour dispute"}, AUDITOR)
    data = get_success_data(resp)

    assert data["dues_arrears_cents"] == before, (
        "suspension should not move the station's dues arrears"
    )


def test_suspension_recomputes_the_open_proposal_denominator():
    """PRD §3.9: "a station suspended during the round leaves it — suspension
    recomputes the quorum denominator of every open proposal whose scope includes
    the station".

    Design: Difficulty/transitive_cascade/cascade_vote_eligibility_full_recompute
    """
    ctx = setup_voting_station()
    before = get_success_data(api_client.get_proposal(ctx["proposal"]["id"], GOVERNANCE))
    get_success_data(api_client.suspend_station(
        ctx["station"]["id"], {"suspension_reason": "Coverage contour dispute"}, AUDITOR))
    after = get_success_data(api_client.get_proposal(ctx["proposal"]["id"], GOVERNANCE))

    assert after["eligible_station_count"] < before["eligible_station_count"], (
        f"the denominator should drop: before {before['eligible_station_count']}, "
        f"after {after['eligible_station_count']}"
    )


def setup_published_program_with_licensed_piece():
    """A PUBLISHED program carrying one LICENSED contribution."""
    set_clock("2026-09-01T00:00:00Z")
    station = make_station_eligible(**PROGRAM_STATION)
    headers = make_station_manager_headers(station["id"])
    program = create_program(
        program_code="NP-1003", program_title="The Takeaway Weekly",
        strand_type="TALK", national_premiere_at="2026-09-15T00:00:00Z",
        clearance_required=False)
    program = get_success_data(api_client.program_move_to_production(program["id"], EDITOR))
    program = get_success_data(api_client.program_schedule(program["id"], EDITOR))
    set_clock("2026-09-16T00:00:00Z")
    program = get_success_data(api_client.program_premiere(program["id"], EDITOR))
    contribution = get_success_data(api_client.create_contribution(
        {"station_id": station["id"], "program_id": program["id"],
         "headline": "Harbor cleanup stalls", "duration_seconds": 180}, headers), 201)
    get_success_data(api_client.submit_contribution(contribution["id"], headers))
    get_success_data(api_client.shortlist_contribution(contribution["id"], EDITOR))
    program = refresh_program(program)
    contribution = get_success_data(api_client.license_contribution(
        contribution["id"], {"expected_program_version": program["version"]}, EDITOR))
    program = get_success_data(api_client.program_publish(program["id"], EDITOR))
    return {"station": station, "program": program, "contribution": contribution}


def test_return_to_development_withdraws_the_licensed_piece():
    """PRD §3.6: "Returning a `PUBLISHED` program to development is the rework path,
    and it has a consequence one hop away: every `ContentContribution` under the
    program in `LICENSED` status moves to `WITHDRAWN`".

    Design: Difficulty/transitive_cascade/cascade_program_retirement_license_revocation
    """
    ctx = setup_published_program_with_licensed_piece()
    assert ctx["contribution"]["contribution_status"] == "LICENSED"

    get_success_data(api_client.program_return_to_development(ctx["program"]["id"], EDITOR))
    refreshed = get_success_data(api_client.get_contribution(
        ctx["contribution"]["id"], EDITOR))

    assert refreshed["contribution_status"] == "WITHDRAWN", (
        f"the licence should be withdrawn by the program rework, "
        f"got {refreshed['contribution_status']}"
    )


def test_return_to_development_bumps_the_publication_cycle():
    """PRD §3.6: "sending a `PUBLISHED` program back for rework increments the
    cycle as well. Nothing resets the counter".

    The program has already been published once during setup, so the rework is
    the second publication round recorded.

    Design: Difficulty/transitive_cascade/cascade_program_retirement_license_revocation
    """
    ctx = setup_published_program_with_licensed_piece()
    before = ctx["program"]["publication_cycle"]

    data = get_success_data(api_client.program_return_to_development(
        ctx["program"]["id"], EDITOR))

    assert data["production_status"] == "RESCHEDULED"
    assert data["publication_cycle"] == before + 1, (
        f"the rework should advance the cycle from {before}, "
        f"got {data['publication_cycle']}"
    )
    assert data["licensed_contribution_count"] == 0, (
        "the counter tracks live licences, so the withdrawal should clear it"
    )