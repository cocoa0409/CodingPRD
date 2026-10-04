"""Optimistic concurrency, cascades, reconciliation and the logical clock.

Queue B, corner index section `cross_cutting_complexity_layers`.
"""
from test_helpers import (
    AUDITOR,
    GOVERNANCE,
    ApiErrorId,
    api_client,
    create_schedule,
    get_success_data,
    make_station_eligible,
    make_station_manager_headers,
    refresh_feed,
    refresh_slot,
    refresh_station,
    set_clock,
    setup_published_agreement,
    validate_error,
)

OCC_STATION = dict(
    call_sign="WOSU", licensee_name="Scioto Licensee", state_code="OH",
    dma_market_rank=32, dma_households=950000, coverage_population=85000,
    full_time_staff_count=7, newsroom_staff_count=4,
    annual_local_revenue_cents=4800000, board_seat_region="REGION_MIDWEST",
)

ELECTION_STATION = dict(
    call_sign="WUSF", licensee_name="Tampa Bay Licensee", state_code="FL",
    dma_market_rank=11, dma_households=1800000, coverage_population=105000,
    full_time_staff_count=8, newsroom_staff_count=4,
    annual_local_revenue_cents=4800000, board_seat_region="REGION_SOUTH",
)

PREEMPTION_STATION = dict(
    call_sign="KNAU", licensee_name="Colorado Plateau Licensee", state_code="AZ",
    dma_market_rank=88, dma_households=320000, coverage_population=55000,
    full_time_staff_count=5, newsroom_staff_count=2,
    annual_local_revenue_cents=4800000, board_seat_region="REGION_WEST",
)

EXPIRY_STATION = dict(
    call_sign="WNPR", licensee_name="Connecticut Licensee", state_code="CT",
    dma_market_rank=29, dma_households=900000, coverage_population=80000,
    full_time_staff_count=7, newsroom_staff_count=4,
    annual_local_revenue_cents=4800000, board_seat_region="REGION_NORTHEAST",
)


def setup_open_proposal_for_occ():
    """An OPEN proposal plus an ELIGIBLE station, with the station's version known."""
    set_clock("2026-09-01T00:00:00Z")
    station = make_station_eligible(**OCC_STATION)
    proposal = get_success_data(api_client.create_proposal(
        {"fiscal_year": 2027, "proposed_base_fee_cents": 1350000,
         "proposed_revenue_rate_bps": 275, "quorum_required_votes": 1,
         "effective_from": "2027-01-01T00:00:00Z"}, GOVERNANCE), 201)
    opened = get_success_data(api_client.open_proposal(proposal["id"], GOVERNANCE))
    return {"station": refresh_station(station), "proposal": opened}


def test_a_stale_station_version_blocks_the_vote():
    """PRD §2.6: "Recording a station's vote on a dues proposal carries
    `expected_station_version`, the client's last-observed version of the voting
    `MemberStation`."
    PRD §2.6: "A mismatch fails the request with `ERR_STALE_STATION_VERSION`."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_station_version_blocks_vote
    """
    ctx = setup_open_proposal_for_occ()
    station = ctx["station"]
    resp = api_client.cast_vote(
        ctx["proposal"]["id"],
        {"station_id": station["id"], "vote_choice": "YES",
         "current_rate_bps": ctx["proposal"]["current_rate_bps"],
         "expected_station_version": station["version"] - 1},
        make_station_manager_headers(station["id"]))

    validate_error(resp, ApiErrorId.ERR_STALE_STATION_VERSION)


def test_matching_the_station_version_admits_the_vote():
    """PRD §2.6: "The rejection is on the version comparison alone: it does not
    depend on requests overlapping in time".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_station_version_blocks_vote
    """
    ctx = setup_open_proposal_for_occ()
    station = ctx["station"]
    resp = api_client.cast_vote(
        ctx["proposal"]["id"],
        {"station_id": station["id"], "vote_choice": "YES",
         "current_rate_bps": ctx["proposal"]["current_rate_bps"],
         "expected_station_version": station["version"]},
        make_station_manager_headers(station["id"]))
    data = get_success_data(resp)

    assert data["vote_status"] == "RECORDED"


def setup_closed_election_for_occ():
    """A CLOSED election holding one QUALIFIED candidacy and a vacant seat."""
    set_clock("2026-09-01T00:00:00Z")
    station = make_station_eligible(**ELECTION_STATION)
    headers = make_station_manager_headers(station["id"])
    get_success_data(api_client.create_seat(
        {"board_region": "REGION_SOUTH", "term_start": "2026-12-01T00:00:00Z",
         "term_end": "2028-12-01T00:00:00Z", "board_rank": 1}, GOVERNANCE), 201)
    election = get_success_data(api_client.create_election(
        {"board_region": "REGION_SOUTH", "fiscal_year": 2026, "seats_available": 1,
         "certification_deadline": "2026-11-15T00:00:00Z"}, GOVERNANCE), 201)
    candidate = get_success_data(api_client.create_candidate(
        {"parent_election_id": election["id"], "station_id": station["id"],
         "nomination_statement": "Gulf coast representation"}, headers), 201)
    get_success_data(api_client.qualify_candidate(candidate["id"], GOVERNANCE))
    get_success_data(api_client.record_candidate_votes(
        candidate["id"], {"votes_recorded": 9}, GOVERNANCE))
    set_clock("2026-11-16T00:00:00Z")
    closed = get_success_data(api_client.close_election(election["id"], GOVERNANCE))
    return {"station": station, "election": closed, "candidate": candidate}


def test_a_stale_election_version_blocks_certification():
    """PRD §2.6: "Certifying a board election carries `expected_election_version`, the
    client's last-observed version of the `BoardElection`."
    PRD §2.6: "A mismatch fails with `ERR_STALE_ELECTION_VERSION`."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_election_version_blocks_certify
    """
    ctx = setup_closed_election_for_occ()
    resp = api_client.certify_election(
        ctx["election"]["id"],
        {"expected_election_version": ctx["election"]["version"] - 1}, GOVERNANCE)

    validate_error(resp, ApiErrorId.ERR_STALE_ELECTION_VERSION)


def test_matching_the_election_version_certifies_it():
    """PRD §2.6: "each is rejected with HTTP 412 and its own dedicated error
    identifier when that field disagrees with the parent's current `version`".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_election_version_blocks_certify
    """
    ctx = setup_closed_election_for_occ()
    resp = api_client.certify_election(
        ctx["election"]["id"],
        {"expected_election_version": ctx["election"]["version"]}, GOVERNANCE)
    data = get_success_data(resp)

    assert data["election_status"] == "CERTIFIED", (
        f"the current-version attempt should seat the election, "
        f"got {data['election_status']}"
    )


def setup_feed_with_low_priority_scheduled_slot():
    """An ONLINE feed at half capacity holding one priority-5 SCHEDULED slot.

    PRD §3.4: the trigger reservation takes the feed's reserved ratio from five
    tenths to six tenths, crossing the 8000-bp congestion threshold; the
    priority-5 reservation sits above the preemptible floor and is displaced,
    while its window returns from SCHEDULED to CLEARED one hop away.
    """
    ctx = setup_published_agreement(
        station_overrides=PREEMPTION_STATION,
        window_overrides={"window_start": "2026-10-05T08:00:00Z",
                          "window_end": "2026-10-05T09:00:00Z"},
        feed_overrides={"feed_code": "FEED-E005", "total_capacity_units": 10,
                        "max_reserved_capacity_ratio": 8000},
        slot_overrides={"slot_start": "2026-10-05T07:30:00Z",
                        "slot_end": "2026-10-05T09:30:00Z", "priority_rank": 5,
                        "capacity_units": 5},
    )
    return ctx


def test_congestion_preempts_the_low_priority_slot():
    """PRD §3.4: "the low-priority reservations lose, the higher-priority ones
    survive, and the preempted slots' capacity units are decremented from the
    feed's reservation total."

    Design: Corner/cross_cutting_complexity_layers/cascade_preemption_releases_window_and_feed
    """
    ctx = setup_feed_with_low_priority_scheduled_slot()
    assert ctx["slot"]["slot_status"] == "SCHEDULED"

    api_client.create_slot(
        {"parent_feed_id": ctx["feed"]["id"], "station_id": ctx["station"]["id"],
         "window_id": ctx["window"]["id"],
         "slot_start": "2026-10-06T08:00:00Z",
         "slot_end": "2026-10-06T09:00:00Z", "priority_rank": 1,
         "capacity_units": 3,
         "preemptible_priority_rank_floor": 3},
        make_station_manager_headers(ctx["station"]["id"]))

    assert refresh_slot(ctx["slot"])["slot_status"] == "PREEMPTED", (
        "the priority-5 reservation should lose the congestion event"
    )


def test_preemption_returns_the_windows_airtime_one_hop_away():
    """PRD §3.4: "Every broadcast window named by a preempted slot's `window_id` is
    returned from `SCHEDULED` to `CLEARED`, so congestion on a feed silently
    unschedules airtime one hop away from the feed itself."

    Design: Corner/cross_cutting_complexity_layers/cascade_preemption_releases_window_and_feed
    """
    ctx = setup_feed_with_low_priority_scheduled_slot()
    before = refresh_feed(ctx["feed"])

    api_client.create_slot(
        {"parent_feed_id": ctx["feed"]["id"], "station_id": ctx["station"]["id"],
         "window_id": ctx["window"]["id"],
         "slot_start": "2026-10-06T08:00:00Z",
         "slot_end": "2026-10-06T09:00:00Z", "priority_rank": 1,
         "capacity_units": 3,
         "preemptible_priority_rank_floor": 3},
        make_station_manager_headers(ctx["station"]["id"]))

    window = get_success_data(api_client.get_window(ctx["window"]["id"], AUDITOR))
    assert window["clearance_status"] == "CLEARED", (
        f"the preempted slot's window should return to CLEARED, "
        f"got {window['clearance_status']}"
    )
    after = refresh_feed(ctx["feed"])
    assert after["reserved_capacity_units"] <= before["reserved_capacity_units"] + 1, (
        "the preempted reservation should be released from the feed's total"
    )


def test_finalizing_an_assessment_rewrites_arrears_within_the_response():
    """PRD §3.2: "it recomputes both derived fees, applies the net of final fee less
    drive deduction to the station's dues arrears, and advances the station's
    version."

    Design: Corner/consistency_model/immediate_consistency_of_fee_finalize
    """
    set_clock("2026-09-01T00:00:00Z")
    create_schedule(schedule_code="FY2027L", annual_adjustment_bps=0,
                    base_fee_cents=1200000, revenue_rate_bps=250,
                    market_size_multiplier_bps=12500, minimum_fee_cents=100000,
                    maximum_fee_cents=5000000,
                    effective_from="2026-06-01T00:00:00Z",
                    effective_to="2027-06-01T00:00:00Z")
    station = make_station_eligible(
        call_sign="WESU", licensee_name="Connecticut River Licensee", state_code="CT",
        dma_market_rank=2, dma_households=12000000, coverage_population=600000,
        full_time_staff_count=20, newsroom_staff_count=6,
        annual_local_revenue_cents=4800000, board_seat_region="REGION_NORTHEAST")
    assessment = get_success_data(api_client.list_station_assessments(station["id"], AUDITOR))

    data = get_success_data(api_client.finalize_assessment(
        assessment[0]["id"], {"expected_station_version": station["version"]}, AUDITOR))

    assert data["assessment_status"] == "FINALIZED"
    assert data["final_fee_cents"] > 0, "the finalized fee must be written on the response"
    refreshed = refresh_station(station)
    assert refreshed["dues_arrears_cents"] == data["final_fee_cents"], (
        f"arrears should equal the finalized fee immediately, "
        f"got {refreshed['dues_arrears_cents']} against {data['final_fee_cents']}"
    )


def _reconciliation_schedule(schedule_code):
    """A 900-basis-point schedule over the network's standard pricing terms.

    PRD §3.2: the schedule names its own `base_fee_cents`, `revenue_rate_bps`,
    tier bounds and the annual adjustment the station's final fee must carry.
    """
    return create_schedule(
        schedule_code=schedule_code, annual_adjustment_bps=900,
        base_fee_cents=1200000, revenue_rate_bps=250,
        market_tier_1_max_rank=25, market_tier_2_max_rank=75,
        market_tier_3_max_rank=150, market_size_multiplier_bps=12500,
        minimum_fee_cents=100000, maximum_fee_cents=5000000,
        effective_from="2026-06-01T00:00:00Z",
        effective_to="2027-06-01T00:00:00Z",
    )


def test_expiring_an_agreement_before_its_deadline_is_refused():
    """PRD §3.3: "An agreement in `CARRIED` may expire into `EXPIRED` once the
    current instant has passed its `clearance_deadline`".

    The logical clock still reads the fixed default instant, well before the
    agreement's deadline, so the precondition fails.

    Design: Corner/cross_cutting_complexity_layers/scheduled_action_expiry_after_clock_advance
    """
    ctx = setup_published_agreement(
        station_overrides=EXPIRY_STATION,
        window_overrides={"window_start": "2026-10-05T08:00:00Z",
                          "window_end": "2026-10-05T09:00:00Z"},
        agreement_overrides={"clearance_deadline": "2026-10-10T00:00:00Z"},
    )
    resp = api_client.expire_agreement(ctx["agreement"]["id"], AUDITOR)

    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_expiring_an_agreement_after_the_clock_passes_its_deadline_succeeds():
    """PRD §2.8: "Time-gated behaviour in this API is evaluated against a
    server-side logical clock, never against the real wall clock."
    PRD §3.3: "every window under it that is `SCHEDULED` becomes `MISSED`".

    Design: Corner/cross_cutting_complexity_layers/scheduled_action_expiry_after_clock_advance
    """
    ctx = setup_published_agreement(
        station_overrides=EXPIRY_STATION,
        window_overrides={"window_start": "2026-10-05T08:00:00Z",
                          "window_end": "2026-10-05T09:00:00Z"},
        agreement_overrides={"clearance_deadline": "2026-10-10T00:00:00Z"},
    )
    set_clock("2026-11-01T00:00:00Z")
    data = get_success_data(api_client.expire_agreement(ctx["agreement"]["id"], AUDITOR))

    assert data["agreement_status"] == "EXPIRED", (
        f"the advanced clock should admit the expiry, got {data['agreement_status']}"
    )
    window = get_success_data(api_client.get_window(ctx["window"]["id"], AUDITOR))
    assert window["clearance_status"] == "MISSED", (
        f"the scheduled window should be missed on expiry, got {window['clearance_status']}"
    )

def test_finalize_reconciles_the_stations_dues_arrears():
    """PRD §3.2: "the net charge is what moves the station's balance: the final fee
    less the station's drive dues deduction for the fiscal year is added to
    `dues_arrears_cents`".

    The station's rank of 60 selects the pinned tier-2 multiplier of 14000 basis
    points on a 1200000-cent base fee, giving a 1680000-cent market component; a
    900-basis-point annual adjustment lifts the provisional 1800000 to a final
    figure the station's balance must then carry.

    Design: Corner/cross_cutting_complexity_layers/dual_variant_fee_and_derived_field_reconciliation
    """
    set_clock("2026-09-01T00:00:00Z")
    create_schedule(schedule_code="FY2027J", annual_adjustment_bps=900,
                    base_fee_cents=1200000, revenue_rate_bps=250,
                    market_tier_1_max_rank=25, market_tier_2_max_rank=75,
                    market_tier_3_max_rank=150, market_size_multiplier_bps=12500,
                    minimum_fee_cents=100000, maximum_fee_cents=5000000,
                    effective_from="2026-06-01T00:00:00Z",
                    effective_to="2027-06-01T00:00:00Z")
    station = make_station_eligible(
        call_sign="WQXR", licensee_name="Hudson Licensee", state_code="NY",
        dma_market_rank=60, dma_households=600000, coverage_population=600000,
        full_time_staff_count=20, newsroom_staff_count=6,
        annual_local_revenue_cents=4800000, board_seat_region="REGION_NORTHEAST")
    # PRD §3.1: coverage 600000 -> 54, staffing 20 -> 100, newsroom 6 -> 60, so
    # the score is 71.60 and the household index is 60 — the CLASS_B rung of the
    # ladder, whose 10000-bp multiplier leaves the market component unscaled.
    assert station["membership_class"] == "CLASS_B", (
        f"the fixture must sit on the CLASS_B rung, got {station['membership_class']}"
    )
    assessment = get_success_data(api_client.list_station_assessments(station["id"], AUDITOR))

    data = get_success_data(api_client.finalize_assessment(
        assessment[0]["id"], {"expected_station_version": station["version"]}, AUDITOR))
    refreshed = refresh_station(station)

    assert data["final_fee_cents"] == 1962000, (
        f"expected the adjusted final fee 1962000, got {data['final_fee_cents']}"
    )
    assert refreshed["dues_arrears_cents"] == data["final_fee_cents"], (
        "with no drive deduction the balance is the wrapped-up final fee itself"
    )


def test_a_later_input_update_does_not_rewrite_the_finalized_assessment():
    """PRD §2.10: "the derived value is recomputed from the rules in §3 and written
    back, so a client that reads the resource after its write sees the server's
    value, never its own."

    Re-deriving the station's own score and class is not the same as repricing a
    persisted assessment, so the finalized fee stands.

    Design: Corner/cross_cutting_complexity_layers/dual_variant_fee_and_derived_field_reconciliation
    """
    set_clock("2026-09-01T00:00:00Z")
    create_schedule(schedule_code="FY2027K", annual_adjustment_bps=0,
                    base_fee_cents=1200000, revenue_rate_bps=250,
                    market_size_multiplier_bps=12500, minimum_fee_cents=100000,
                    maximum_fee_cents=5000000,
                    effective_from="2026-06-01T00:00:00Z",
                    effective_to="2027-06-01T00:00:00Z")
    station = make_station_eligible(**OCC_STATION)
    assessment = get_success_data(api_client.list_station_assessments(station["id"], AUDITOR))
    finalized = get_success_data(api_client.finalize_assessment(
        assessment[0]["id"], {"expected_station_version": station["version"]}, AUDITOR))

    updated = get_success_data(api_client.update_station(
        station["id"], {"annual_local_revenue_cents": 5000000},
        make_station_manager_headers(station["id"])))

    assert updated["annual_local_revenue_cents"] == 5000000
    after = get_success_data(api_client.get_assessment(
        finalized["id"], AUDITOR))
    assert after["final_fee_cents"] == finalized["final_fee_cents"], (
        "a station input update must not silently reprice a finalized assessment"
    )
