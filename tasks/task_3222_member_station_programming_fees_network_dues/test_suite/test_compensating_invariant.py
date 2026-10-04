"""Compensating actions and the quantities they conserve (queue A,
rule `compensating_invariant`).

Both pairs here are compensating in the strict sense: the return edge must
restore exactly the mass the forward edge displaced.
"""
from test_helpers import (
    AUDITOR,
    GOVERNANCE,
    api_client,
    create_schedule,
    create_seat,
    get_success_data,
    make_station_eligible,
    make_station_manager_headers,
    no_vote_weight,
    refresh_proposal,
    set_clock,
    yes_vote_weight,
)

VOTE_STATION = dict(
    call_sign="KCRW", licensee_name="Santa Monica Licensee", state_code="CA",
    dma_market_rank=2, dma_households=12000000, coverage_population=10000000,
    full_time_staff_count=20, newsroom_staff_count=10,
    annual_local_revenue_cents=4800000, board_seat_region="REGION_WEST",
)

SEAT_STATION = dict(
    call_sign="WUSF", licensee_name="Tampa Bay Licensee", state_code="FL",
    dma_market_rank=11, dma_households=12000000, coverage_population=10000000,
    full_time_staff_count=20, newsroom_staff_count=10,
    annual_local_revenue_cents=4800000, board_seat_region="REGION_SOUTH",
)


def setup_recorded_yes_vote():
    """One CLASS_A station with a live YES vote on one open proposal."""
    set_clock("2026-09-01T00:00:00Z")
    station = make_station_eligible(**VOTE_STATION)
    headers = make_station_manager_headers(station["id"])
    proposal = get_success_data(api_client.create_proposal(
        {"fiscal_year": 2027, "proposed_base_fee_cents": 1350000,
         "proposed_revenue_rate_bps": 275, "quorum_required_votes": 1,
         "effective_from": "2027-01-01T00:00:00Z"}, GOVERNANCE), 201)
    proposal = get_success_data(api_client.open_proposal(proposal["id"], GOVERNANCE))
    vote = get_success_data(api_client.cast_vote(
        proposal["id"],
        {"station_id": station["id"], "vote_choice": "YES",
         "current_rate_bps": proposal["current_rate_bps"],
         "expected_station_version": station["version"]},
        headers))
    return {"station": station, "headers": headers, "proposal": proposal, "vote": vote}


def test_class_a_yes_vote_records_the_class_base_weight():
    """PRD §3.9: "A `CLASS_A` station carries a base weight of 3" and "A `YES` vote
    records that base weight as its `recorded_weight`".

    Design: Difficulty/compensating_invariant/invariant_dues_vote_pair_weight_conservation
    """
    ctx = setup_recorded_yes_vote()
    assert ctx["station"]["membership_class"] == "CLASS_A"
    assert yes_vote_weight("CLASS_A") == 3
    assert ctx["vote"]["recorded_weight"] == 3, (
        f"expected a weight of 3, got {ctx['vote']['recorded_weight']}"
    )
    proposal = refresh_proposal(ctx["proposal"])
    assert proposal["yes_votes"] == 3
    assert proposal["votes_cast_count"] == 1


def test_superseding_a_yes_vote_recomputes_the_tally_to_the_no_weight():
    """PRD §3.9: "A `NO` vote records a derived figure instead: the base weight plus
    one, integer-divided by two, with a floor of 1 — but only when the base weight
    is above zero".
    PRD §3.9: "`recorded_weight` contributes only while a row's `vote_status` is
    `RECORDED` — a `SUPERSEDED` or `INVALIDATED` row contributes zero to all
    three tallies".

    A CLASS_A NO records max(1, (3+1)//2) = 2, so the tally moves to two no weight.

    Design: Difficulty/compensating_invariant/invariant_dues_vote_pair_weight_conservation
    """
    ctx = setup_recorded_yes_vote()
    assert no_vote_weight("CLASS_A") == 2

    replacement = get_success_data(api_client.supersede_vote(
        ctx["vote"]["id"], {"vote_choice": "NO"}, ctx["headers"]))
    proposal = refresh_proposal(ctx["proposal"])

    assert replacement["vote_status"] == "RECORDED"
    assert replacement["vote_choice"] == "NO"
    assert replacement["recorded_weight"] == 2
    assert proposal["no_votes"] == 2, (
        f"expected two no weight, got {proposal['no_votes']}"
    )


def test_restoring_the_superseded_vote_conserves_the_recorded_weight():
    """PRD §3.9: "`recorded_weight` contributes only while a row's `vote_status` is
    `RECORDED` — a `SUPERSEDED` or `INVALIDATED` row contributes zero to all
    three tallies, though its weight is not destroyed, since the pair is designed
    to conserve total recorded weight across the two rows."

    Restoring the original row must return the tally to the three yes weight it
    carried before the supersede.

    Design: Difficulty/compensating_invariant/invariant_dues_vote_pair_weight_conservation
    """
    ctx = setup_recorded_yes_vote()
    replacement = get_success_data(api_client.supersede_vote(
        ctx["vote"]["id"], {"vote_choice": "NO"}, ctx["headers"]))
    # PRD §2.10: "a superseded vote is restored by invalidating its superseder"
    # — the restore acts on the row that was superseded, which is the row whose
    # `superseded_by_vote_id` points at the replacement the assertion below
    # expects to be collapsed.
    get_success_data(api_client.restore_vote(ctx["vote"]["id"], GOVERNANCE))
    proposal = refresh_proposal(ctx["proposal"])

    assert replacement["vote_status"] == "RECORDED"
    assert proposal["yes_votes"] == 3, (
        f"the compensating pair should restore the three yes weight, "
        f"got {proposal['yes_votes']}"
    )
    assert proposal["no_votes"] == 0


STARTING_ARREARS_SCHEDULE = dict(
    schedule_code="FY2026P", fiscal_year=2026, base_fee_cents=1200000,
    revenue_rate_bps=250, market_size_multiplier_bps=12500,
    minimum_fee_cents=100000, maximum_fee_cents=5000000,
    annual_adjustment_bps=0, effective_from="2026-06-01T00:00:00Z",
    effective_to="2027-06-01T00:00:00Z",
)


def setup_certified_seat():
    """A SOUTH seat seated by a certified election, the station's arrears zeroed."""
    set_clock("2026-09-01T00:00:00Z")
    station = make_station_eligible(**SEAT_STATION)
    headers = make_station_manager_headers(station["id"])
    seat = create_seat(board_region="REGION_SOUTH", term_start="2026-12-01T00:00:00Z",
                       term_end="2028-12-01T00:00:00Z", board_rank=1)
    election = get_success_data(api_client.create_election(
        {"board_region": "REGION_SOUTH", "fiscal_year": 2026, "seats_available": 1,
         "certification_deadline": "2026-11-15T00:00:00Z"}, GOVERNANCE), 201)
    candidate = get_success_data(api_client.create_candidate(
        {"parent_election_id": election["id"], "station_id": station["id"],
         "nomination_statement": "Gulf coast representation"}, headers), 201)
    get_success_data(api_client.qualify_candidate(candidate["id"], GOVERNANCE))
    get_success_data(api_client.record_candidate_votes(
        candidate["id"], {"votes_recorded": 12}, GOVERNANCE))
    set_clock("2026-11-16T00:00:00Z")
    closed = get_success_data(api_client.close_election(election["id"], GOVERNANCE))
    certified = get_success_data(api_client.certify_election(
        closed["id"], {"expected_election_version": closed["version"]}, GOVERNANCE))
    return {"station": station, "seat": get_success_data(
        api_client.get_seat(seat["id"], GOVERNANCE)),
        "election": certified, "candidate": candidate}


def test_an_elected_candidacy_fills_the_regions_seat():
    """PRD §3.10: "each `ELECTED` candidacy's `BoardSeat` moves from `VACANT` to
    `FILLED` with its `station_id` set to the elected candidate's station and its
    `term_start` to the current instant".

    Design: Difficulty/compensating_invariant/invariant_seat_allocation_carried_credit
    """
    ctx = setup_certified_seat()

    assert ctx["seat"]["seat_status"] == "FILLED", (
        f"the seat should be FILLED, got {ctx['seat']['seat_status']}"
    )
    assert ctx["seat"]["station_id"] == ctx["station"]["id"], (
        "the seat should be held by the elected candidate's station"
    )


def test_seating_the_station_zeroes_its_dues_arrears():
    """PRD §3.10: "seating the station then sets that station's `dues_arrears_cents`
    to zero, which recomputes its dues-vote eligibility projection."

    The setup finalized the station's assessment so a positive balance exists
    before the election seats it.

    Design: Difficulty/compensating_invariant/invariant_seat_allocation_carried_credit
    """
    set_clock("2026-09-01T00:00:00Z")
    create_schedule(**STARTING_ARREARS_SCHEDULE)
    station = make_station_eligible(**SEAT_STATION)
    headers = make_station_manager_headers(station["id"])
    assessment = get_success_data(api_client.list_station_assessments(station["id"], AUDITOR))
    get_success_data(api_client.finalize_assessment(
        assessment[0]["id"], {"expected_station_version": station["version"]}, AUDITOR))
    before = get_success_data(api_client.get_station(station["id"], AUDITOR))
    assert before["dues_arrears_cents"] > 0, "fixture must start with a positive balance"

    create_seat(board_region="REGION_SOUTH", term_start="2026-12-01T00:00:00Z",
                term_end="2028-12-01T00:00:00Z", board_rank=1)
    election = get_success_data(api_client.create_election(
        {"board_region": "REGION_SOUTH", "fiscal_year": 2026, "seats_available": 1,
         "certification_deadline": "2026-11-15T00:00:00Z"}, GOVERNANCE), 201)
    candidate = get_success_data(api_client.create_candidate(
        {"parent_election_id": election["id"], "station_id": station["id"],
         "nomination_statement": "Gulf coast representation"}, headers), 201)
    get_success_data(api_client.qualify_candidate(candidate["id"], GOVERNANCE))
    get_success_data(api_client.record_candidate_votes(
        candidate["id"], {"votes_recorded": 12}, GOVERNANCE))
    set_clock("2026-11-16T00:00:00Z")
    closed = get_success_data(api_client.close_election(election["id"], GOVERNANCE))
    get_success_data(api_client.certify_election(
        closed["id"], {"expected_election_version": closed["version"]}, GOVERNANCE))

    after = get_success_data(api_client.get_station(station["id"], AUDITOR))
    assert after["dues_arrears_cents"] == 0, (
        f"seating the station should clear its arrears, got {after['dues_arrears_cents']}"
    )


def test_deallocating_the_seat_returns_it_to_vacant_with_no_carried_credit():
    """PRD §3.10: "a governance officer deallocates a `FILLED` seat by supplying a
    `deallocation_of_seat_id` that must equal that very seat's `id`, which clears
    `station_id` and `term_start`, sets `carried_credit_cents` back to zero, and
    returns the seat to `VACANT`."

    Design: Difficulty/compensating_invariant/invariant_seat_allocation_carried_credit
    """
    ctx = setup_certified_seat()
    seat = ctx["seat"]
    resp = api_client.deallocate_seat(
        seat["id"], {"deallocation_of_seat_id": seat["id"]}, GOVERNANCE)
    data = get_success_data(resp)

    assert data["seat_status"] == "VACANT", (
        f"the compensating action should return the seat to VACANT, "
        f"got {data['seat_status']}"
    )
    assert data["carried_credit_cents"] == 0, (
        f"the carried credit must be released with the seat, got "
        f"{data['carried_credit_cents']}"
    )
    assert not data.get("station_id"), "the seat must hold no station once deallocated"