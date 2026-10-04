"""Computed reads and cross-reference links on the endpoint surface.

Queue B, corner index section `endpoints`.
"""
from test_helpers import (
    AUDITOR,
    GOVERNANCE,
    NON_EXISTENT_UUID,
    REJECTED_BASE_CENTS,
    ApiErrorId,
    api_client,
    create_agreement,
    create_program,
    create_proposal,
    create_window,
    get_success_data,
    make_station_eligible,
    make_station_manager_headers,
    set_clock,
    validate_error,
)

ROLLUP_STATION = dict(
    call_sign="WUOT", licensee_name="Tennessee Licensee", state_code="TN",
    dma_market_rank=62, dma_households=470000, coverage_population=65000,
    full_time_staff_count=5, newsroom_staff_count=3,
    annual_local_revenue_cents=4800000, board_seat_region="REGION_SOUTH",
)

VOTE_STATION = dict(
    call_sign="WUOM", licensee_name="Huron Licensee", state_code="MI",
    dma_market_rank=14, dma_households=1700000, coverage_population=10000000,
    full_time_staff_count=20, newsroom_staff_count=10,
    annual_local_revenue_cents=4800000, board_seat_region="REGION_MIDWEST",
)


def setup_agreement_with_cleared_and_rejected_windows():
    """One CLEARED window and one REJECTED window under the same agreement."""
    set_clock("2026-09-01T00:00:00Z")
    station = make_station_eligible(**ROLLUP_STATION)
    headers = make_station_manager_headers(station["id"])
    program = create_program(program_code="NP-1018", program_title="Volunteer State Weekly")
    agreement = create_agreement(station, program_code=program["program_code"])
    cleared = create_window(agreement, station,
                            window_start="2026-10-05T08:00:00Z",
                            window_end="2026-10-05T09:00:00Z")
    rejected = create_window(agreement, station,
                             window_start="2026-10-05T10:00:00Z",
                             window_end="2026-10-05T11:00:00Z")
    get_success_data(api_client.submit_agreement(agreement["id"], headers))
    get_success_data(api_client.review_agreement(agreement["id"], AUDITOR))
    get_success_data(api_client.request_clearance(cleared["id"], headers))
    get_success_data(api_client.clear_window(cleared["id"], AUDITOR))
    get_success_data(api_client.request_clearance(rejected["id"], headers))
    get_success_data(api_client.reject_window(
        rejected["id"], {"rejection_reason": "Missing carriage documentation"}, AUDITOR))
    return {"station": station, "headers": headers, "program": program,
            "agreement": agreement, "cleared": cleared, "rejected": rejected}


def test_agreement_read_reports_the_rejected_windows_accrual():
    """PRD §3.5: "Each window carries its own accrued figure in
    `carriage_exception_liability_cents`, and each agreement carries a rollup."
    PRD §3.5: "A rejected window accrues a flat 25000 cents."

    Design: Corner/endpoints/agreement_liability_rollup_is_computed_read
    """
    ctx = setup_agreement_with_cleared_and_rejected_windows()
    data = get_success_data(api_client.get_agreement(ctx["agreement"]["id"], AUDITOR))

    assert data["exception_liability_cents"] == REJECTED_BASE_CENTS, (
        f"the rollup should carry the single rejected window's accrual, "
        f"got {data['exception_liability_cents']}"
    )


def test_agreement_read_derives_the_ratio_from_the_in_scope_windows_only():
    """PRD §3.5: "The windows in scope are those whose parent agreement is this
    agreement and whose `clearance_status` is `CLEARED`, `SCHEDULED` or
    `BROADCAST` — a `DRAFT`, `PENDING_CLEARANCE`, `REJECTED`, `MISSED` or
    `VIOLATED` window is outside the denominator entirely".
    PRD §3.5: "a set containing one `CLEARED` window and one `VIOLATED` window
    yields 10000 basis points while the agreement simultaneously carries nonzero
    liability, because the violated window is excluded from the denominator rather
    than counted against it."

    Design: Corner/endpoints/agreement_liability_rollup_is_computed_read
    """
    ctx = setup_agreement_with_cleared_and_rejected_windows()
    data = get_success_data(api_client.get_agreement(ctx["agreement"]["id"], AUDITOR))

    assert data["clearance_ratio_bps"] == 10000, (
        f"one cleared window out of one in-scope window is full coverage, "
        f"got {data['clearance_ratio_bps']}"
    )


def test_listing_the_agreements_windows_returns_both_children():
    """PRD §2.7: "The reverse-reachability collections — the windows under an
    agreement, the slots under a feed, the contributions and agreements under a
    program, the candidacies under an election, the votes under a proposal, and
    every collection filtered by `station_id` — are the intended way for a caller
    to walk the hierarchy downward from a parent it already holds."

    Design: Corner/endpoints/agreement_liability_rollup_is_computed_read
    """
    ctx = setup_agreement_with_cleared_and_rejected_windows()
    data = get_success_data(api_client.list_agreement_windows(
        ctx["agreement"]["id"], AUDITOR))

    ids = {window["id"] for window in data}
    assert ids == {ctx["cleared"]["id"], ctx["rejected"]["id"]}


def setup_open_proposal_and_eligible_station():
    set_clock("2026-09-01T00:00:00Z")
    station = make_station_eligible(**VOTE_STATION)
    proposal = create_proposal(fiscal_year=2027, proposed_base_fee_cents=1350000,
                               proposed_revenue_rate_bps=275, quorum_required_votes=1,
                               effective_from="2027-01-01T00:00:00Z")
    opened = get_success_data(api_client.open_proposal(proposal["id"], GOVERNANCE))
    return {"station": station, "proposal": opened}


def test_a_recorded_vote_links_its_station_to_its_proposal():
    """PRD §3.9: "Each recorded vote is a `StationVote` row carrying the `station_id`,
    the `vote_choice`, the `current_rate_bps` that was observed, a derived
    `recorded_weight`, the `cast_at` instant".

    Design: Corner/endpoints/votes_endpoint_cross_reference_link
    """
    ctx = setup_open_proposal_and_eligible_station()
    vote = get_success_data(api_client.cast_vote(
        ctx["proposal"]["id"],
        {"station_id": ctx["station"]["id"], "vote_choice": "YES",
         "current_rate_bps": ctx["proposal"]["current_rate_bps"],
         "expected_station_version": ctx["station"]["version"]},
        make_station_manager_headers(ctx["station"]["id"])))

    assert vote["station_id"] == ctx["station"]["id"]
    assert vote["vote_status"] == "RECORDED"
    assert vote["recorded_weight"] == 3, (
        "a CLASS_A YES records the three-point base weight"
    )


def test_the_proposals_vote_collection_returns_the_recorded_row():
    """PRD §2.7: "a vote listed under one proposal is returned only when its parent
    reference matches the parent named in the path".

    Design: Corner/endpoints/votes_endpoint_cross_reference_link
    """
    ctx = setup_open_proposal_and_eligible_station()
    vote = get_success_data(api_client.cast_vote(
        ctx["proposal"]["id"],
        {"station_id": ctx["station"]["id"], "vote_choice": "YES",
         "current_rate_bps": ctx["proposal"]["current_rate_bps"],
         "expected_station_version": ctx["station"]["version"]},
        make_station_manager_headers(ctx["station"]["id"])))

    data = get_success_data(api_client.list_proposal_votes(ctx["proposal"]["id"], GOVERNANCE))
    assert [row["id"] for row in data] == [vote["id"]]


def test_a_vote_against_an_unknown_station_is_refused():
    """PRD §2.7: "a request naming a station, schedule, agreement, window, feed,
    slot, program, contribution, drive, report, election, candidacy, seat,
    proposal or vote that does not exist fails with `ERR_RESOURCE_NOT_FOUND`
    (HTTP 404) even when the request body is also malformed."

    Design: Corner/endpoints/votes_endpoint_cross_reference_link
    """
    ctx = setup_open_proposal_and_eligible_station()
    resp = api_client.cast_vote(
        ctx["proposal"]["id"],
        {"station_id": NON_EXISTENT_UUID, "vote_choice": "YES",
         "current_rate_bps": ctx["proposal"]["current_rate_bps"],
         "expected_station_version": 1},
        make_station_manager_headers(NON_EXISTENT_UUID))

    validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND)