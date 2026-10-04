"""Composite setup helpers — multi-step preambles built only from PRD endpoints.

Every helper builds its preconditions from scratch because the harness restarts
the server against an empty database before each test. Fixtures use the lenient
`get_success_data()` so a broken setup surfaces as a clear "Setup failed" error.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_CLOCK,
    DEFAULT_MAX_RESERVED_CAPACITY_RATIO_BPS,
    DEFAULT_PREEMPTIBLE_PRIORITY_RANK_FLOOR,
)
from .factories import (
    clock_payload,
    create_agreement_payload,
    create_audience_report_payload,
    create_candidate_payload,
    create_contribution_payload,
    create_drive_payload,
    create_election_payload,
    create_feed_payload,
    create_program_payload,
    create_proposal_payload,
    create_schedule_payload,
    create_seat_payload,
    create_slot_payload,
    create_station_payload,
    create_underwriting_payload,
    create_window_payload,
)
from .test_users import (
    TEST_USERS,
    make_station_manager_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
SCHEDULER = TEST_USERS["scheduler_headers"]
EDITOR = TEST_USERS["program_editor_headers"]
UNDERWRITING = TEST_USERS["underwriting_headers"]
GOVERNANCE = TEST_USERS["governance_headers"]

_schedule_counter = itertools.count()
_program_counter = itertools.count()
_feed_counter = itertools.count()
_station_counter = itertools.count()


def _next_schedule_code() -> str:
    """PRD §3.2: a `schedule_code` is `FY` + four digits + one uppercase letter.

    The counter rolls the alpha suffix after 26 so the format never widens — a
    code like `FY2026AL` is refused by the declared pattern.
    """
    i = next(_schedule_counter)
    return f"FY{2026 + (i // 26)}{chr(65 + (i % 26))}"


def _next_program_code() -> str:
    return f"NP-{1000 + next(_program_counter)}"


def _next_feed_code() -> str:
    return f"FEED-{chr(65 + (next(_feed_counter) % 26))}{(next(_feed_counter) % 1000):03d}"


def _next_call_sign() -> str:
    i = next(_station_counter)
    return "W" + chr(65 + ((i // 26) % 26)) + chr(65 + (i % 26))


def set_clock(instant: str = DEFAULT_CLOCK):
    """PRD §2.8: pin the logical clock before any time-gated precondition."""
    return get_success_data(api_client.set_clock(instant, ADMIN))


def setup_baseline_clock():
    """Pin the logical clock to its fixed default instant."""
    return set_clock(DEFAULT_CLOCK)


def _station_headers(station: dict) -> dict:
    return make_station_manager_headers(station["id"])


# ---------------------------------------------------------------------------
# Tier 1 — state progression
# ---------------------------------------------------------------------------

def create_station(**overrides) -> dict:
    """Register a MemberStation as an APPLICANT (PRD §3.1)."""
    overrides.setdefault("call_sign", _next_call_sign())
    resp = api_client.create_station(create_station_payload(**overrides), ADMIN)
    return get_success_data(resp, 201)


def create_applicant(**overrides) -> dict:
    return create_station(**overrides)


def submit_station_for_eligibility(station: dict) -> dict:
    resp = api_client.submit_eligibility(station["id"], _station_headers(station))
    return get_success_data(resp)


def approve_station(station: dict) -> dict:
    resp = api_client.approve_eligibility(station["id"], AUDITOR)
    return get_success_data(resp)


def make_station_eligible(**overrides) -> dict:
    """Create a station and walk it to ELIGIBLE, minting its assessment.

    PRD §3.1: approval requires coverage at least 50000, at least 3 full-time
    staff and at least 2 newsroom staff, so the defaults satisfy every floor.
    """
    station = create_station(**overrides)
    submit_station_for_eligibility(station)
    return approve_station(station)


def create_and_activate_station(**overrides) -> dict:
    return make_station_eligible(**overrides)


def make_station_under_review(**overrides) -> dict:
    station = create_station(**overrides)
    return submit_station_for_eligibility(station)


def make_station_deficient(**overrides) -> dict:
    """UNDER_REVIEW -> DEFICIENT (PRD §3.1: a staffing or coverage floor is unmet)."""
    overrides.setdefault("newsroom_staff_count", 1)
    station = make_station_under_review(**overrides)
    resp = api_client.record_deficiency(
        station["id"], {"deficiency_factors": ["NEWSROOM_STAFF"]}, AUDITOR)
    return get_success_data(resp)


def make_station_remediated(**overrides) -> dict:
    """DEFICIENT -> REMEDIATION_SUBMITTED."""
    station = make_station_deficient(**overrides)
    resp = api_client.remediation(
        station["id"], {"remediated_factors": ["NEWSROOM_STAFF"]}, _station_headers(station))
    return get_success_data(resp)


def make_station_on_probation(**overrides) -> dict:
    """ELIGIBLE -> PROBATION (PRD §3.1)."""
    station = make_station_eligible(**overrides)
    resp = api_client.probation(
        station["id"], {"reason_code": "LOCAL_CONTENT_SHORTFALL"}, AUDITOR)
    return get_success_data(resp)


def make_station_suspended(**overrides) -> dict:
    """ELIGIBLE -> PROBATION -> SUSPENDED.

    PRD §3.1: suspension from PROBATION requires dues_arrears_cents above zero,
    which this helper does not arrange; the station is therefore suspended
    straight from ELIGIBLE, which the same subsection admits on a non-empty
    suspension_reason alone.
    """
    station = make_station_eligible(**overrides)
    resp = api_client.suspend_station(
        station["id"], {"suspension_reason": "Coverage contour dispute"}, AUDITOR)
    return get_success_data(resp)


def make_station_withdrawn(**overrides) -> dict:
    station = create_station(**overrides)
    resp = api_client.withdraw_station(station["id"], _station_headers(station))
    return get_success_data(resp)


def make_station_with_arrears(**overrides):
    """An ELIGIBLE station that carries dues arrears above zero.

    PRD §3.2: finalizing the assessment minted at approval adds the net fee to
    the station's arrears, which is the cheapest route to a positive balance.
    """
    station = make_station_eligible(**overrides)
    assessment = first_station_assessment(station)
    resp = api_client.finalize_assessment(
        assessment["id"], {"expected_station_version": station["version"]}, AUDITOR)
    finalized = get_success_data(resp)
    refreshed = api_client.get_station(station["id"], AUDITOR)
    return get_success_data(refreshed), finalized


# ---------------------------------------------------------------------------
# Tier 2 — entity hierarchy
# ---------------------------------------------------------------------------

def create_schedule(**overrides) -> dict:
    """Create a fiscal-year ProgrammingFeeSchedule (PRD §3.2)."""
    overrides.setdefault("schedule_code", _next_schedule_code())
    resp = api_client.create_schedule(create_schedule_payload(**overrides), ADMIN)
    return get_success_data(resp, 201)


def create_program(**overrides) -> dict:
    """Create a NationalProgram in DEVELOPMENT (PRD §3.6)."""
    overrides.setdefault("program_code", _next_program_code())
    resp = api_client.create_program(create_program_payload(**overrides), EDITOR)
    return get_success_data(resp, 201)


def create_feed(**overrides) -> dict:
    """Create a DistributionFeed in PLANNED status (PRD §3.4)."""
    overrides.setdefault("feed_code", _next_feed_code())
    overrides.setdefault(
        "max_reserved_capacity_ratio", DEFAULT_MAX_RESERVED_CAPACITY_RATIO_BPS)
    resp = api_client.create_feed(create_feed_payload(**overrides), SCHEDULER)
    return get_success_data(resp, 201)


def create_online_feed(**overrides) -> dict:
    """Create a feed and bring it ONLINE (PRD §3.4)."""
    feed = create_feed(**overrides)
    resp = api_client.bring_feed_online(feed["id"], SCHEDULER)
    return get_success_data(resp)


def create_agreement(station: dict, **overrides) -> dict:
    """Create a CarriageAgreement as DRAFT under an eligible station (PRD §3.3)."""
    overrides.setdefault("station_id", station["id"])
    resp = api_client.create_agreement(create_agreement_payload(**overrides), _station_headers(station))
    return get_success_data(resp, 201)


def create_window(agreement: dict, station: dict, **overrides) -> dict:
    """Create a BroadcastWindow as DRAFT under an agreement (PRD §3.3)."""
    overrides.setdefault("parent_agreement_id", agreement["id"])
    overrides.setdefault("station_id", station["id"])
    overrides.setdefault("program_code", agreement["program_code"])
    resp = api_client.create_window(create_window_payload(**overrides), _station_headers(station))
    return get_success_data(resp, 201)


def create_slot(feed: dict, station: dict, window: dict, **overrides) -> dict:
    """Reserve an UplinkSlot on a feed for one window (PRD §3.4).

    Every reservation carries the PRD's `preemptible_priority_rank_floor`, so
    the congestion rule's displacement has a floor to compare `priority_rank`
    against rather than falling back to an implementation's own default.
    """
    overrides.setdefault("parent_feed_id", feed["id"])
    overrides.setdefault("station_id", station["id"])
    overrides.setdefault("window_id", window["id"])
    overrides.setdefault(
        "preemptible_priority_rank_floor", DEFAULT_PREEMPTIBLE_PRIORITY_RANK_FLOOR)
    resp = api_client.create_slot(create_slot_payload(**overrides), _station_headers(station))
    return get_success_data(resp, 201)


def move_program_premiere_ahead(program: dict, new_premiere_at: str,
                                station: dict = None, headers: dict = None) -> dict:
    """Push a program's premiere ahead of an already-created window's start.

    PRD §3.6: `reschedule-airings` moves the premiere of a `PUBLISHED` program,
    and publishing requires a `RUNNING` program carrying at least one licensed
    contribution — so the program is walked to `PUBLISHED` first. When a station
    is supplied, one of its pieces is licensed to satisfy that gate.
    """
    program = get_success_data(api_client.program_move_to_production(program["id"], EDITOR))
    program = get_success_data(api_client.program_schedule(program["id"], EDITOR))
    # PRD §3.6: a `SCHEDULED` program may premiere once the clock has reached
    # its premiere instant, so the clock is advanced to it first.
    set_clock(program["national_premiere_at"].replace("+00:00", "Z")
              if program["national_premiere_at"].endswith("+00:00")
              else program["national_premiere_at"])
    program = get_success_data(api_client.program_premiere(program["id"], EDITOR))
    if station is not None:
        contribution = get_success_data(api_client.create_contribution(
            create_contribution_payload(station_id=station["id"], program_id=program["id"]),
            headers or _station_headers(station)), 201)
        get_success_data(api_client.submit_contribution(
            contribution["id"], headers or _station_headers(station)))
        get_success_data(api_client.shortlist_contribution(contribution["id"], EDITOR))
        # PRD §3.6: publishing "requires at least one licensed contribution under
        # it, meaning `licensed_contribution_count` of one or greater", so the
        # piece is licensed before the publish step.
        program = refresh_program(program)
        get_success_data(api_client.license_contribution(
            contribution["id"], {"expected_program_version": program["version"]}, EDITOR))
    program = refresh_program(program)
    get_success_data(api_client.program_publish(program["id"], EDITOR))
    program = refresh_program(program)
    return get_success_data(api_client.program_reschedule_airings(
        program["id"], {"new_premiere_at": new_premiere_at}, EDITOR))


def submit_agreement(agreement: dict, station: dict) -> dict:
    resp = api_client.submit_agreement(agreement["id"], _station_headers(station))
    return get_success_data(resp)


def review_agreement(agreement: dict) -> dict:
    resp = api_client.review_agreement(agreement["id"], AUDITOR)
    return get_success_data(resp)


def request_window_clearance(window: dict, station: dict) -> dict:
    resp = api_client.request_clearance(window["id"], _station_headers(station))
    return get_success_data(resp)


def clear_window(window: dict) -> dict:
    resp = api_client.clear_window(window["id"], AUDITOR)
    return get_success_data(resp)


def clear_agreement(agreement: dict) -> dict:
    resp = api_client.clear_agreement(agreement["id"], AUDITOR)
    return get_success_data(resp)


def publish_agreement(agreement: dict) -> dict:
    resp = api_client.publish_agreement(agreement["id"], SCHEDULER)
    return get_success_data(resp)


def republish_agreement(agreement: dict) -> dict:
    resp = api_client.republish_agreement(agreement["id"], SCHEDULER)
    return get_success_data(resp)


def refresh_station(station: dict) -> dict:
    return get_success_data(api_client.get_station(station["id"], AUDITOR))


def refresh_agreement(agreement: dict) -> dict:
    return get_success_data(api_client.get_agreement(agreement["id"], AUDITOR))


def refresh_window(window: dict) -> dict:
    return get_success_data(api_client.get_window(window["id"], AUDITOR))


def refresh_feed(feed: dict) -> dict:
    return get_success_data(api_client.get_feed(feed["id"], SCHEDULER))


def refresh_slot(slot: dict) -> dict:
    return get_success_data(api_client.get_slot(slot["id"], SCHEDULER))


def refresh_program(program: dict) -> dict:
    return get_success_data(api_client.get_program(program["id"], EDITOR))


def refresh_drive(drive: dict) -> dict:
    return get_success_data(api_client.get_drive(drive["id"], AUDITOR))


def refresh_proposal(proposal: dict) -> dict:
    return get_success_data(api_client.get_proposal(proposal["id"], GOVERNANCE))


def first_station_assessment(station: dict) -> dict:
    """The INITIAL assessment cascaded onto a station by approval (PRD §3.1)."""
    resp = api_client.list_station_assessments(station["id"], AUDITOR)
    data, _meta = _paginate(resp)
    assert data, "Setup failed: approval should have cascaded an assessment"
    return data[0]


def _paginate(resp):
    body = get_success_data(resp)
    return body, resp.json().get("meta", {})

# ---------------------------------------------------------------------------
# Tier 3 — full lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_eligible_station_with_schedule(station_overrides=None, schedule_overrides=None):
    """One fee schedule plus one ELIGIBLE station priced under it.

    Returns ``{"schedule":…, "station":…, "assessment":…}``. The station's
    approval has already cascaded an INITIAL assessment for the fiscal year.
    """
    schedule = create_schedule(**(schedule_overrides or {}))
    station = make_station_eligible(**(station_overrides or {}))
    return {
        "schedule": schedule,
        "station": station,
        "assessment": first_station_assessment(station),
    }


def create_cleared_window(station, agreement, **window_overrides):
    """Agreement to UNDER_REVIEW, window to CLEARED. Returns the window."""
    window = create_window(agreement, station, **window_overrides)
    submit_agreement(agreement, station)
    review_agreement(agreement)
    request_window_clearance(window, station)
    return clear_window(window)


def setup_cleared_agreement(station_overrides=None, schedule_overrides=None,
                            window_overrides=None):
    """A station with an ELIGIBLE standing, a program and one CLEARED window.

    Returns ``{"station", "program", "agreement", "window"}``.
    """
    station = make_station_eligible(**(station_overrides or {}))
    program = create_program()
    agreement = create_agreement(station, program_code=program["program_code"])
    window = create_cleared_window(station, agreement, **(window_overrides or {}))
    return {"station": station, "program": program, "agreement": agreement, "window": window}


def setup_published_agreement(station_overrides=None, window_overrides=None,
                              feed_overrides=None, slot_overrides=None,
                              agreement_overrides=None):
    """Full carriage lifecycle: agreement CARRIED with its window SCHEDULED.

    Returns ``{"station", "program", "agreement", "window", "feed", "slot"}``.
    PRD §3.3: publication requires every window cleared and an uplink
    reservation in RESERVED, SCHEDULED or AIRED status for each cleared window.
    """
    station = make_station_eligible(**(station_overrides or {}))
    program = create_program()
    agreement = create_agreement(station, program_code=program["program_code"],
                                 **(agreement_overrides or {}))
    feed = create_online_feed(**(feed_overrides or {}))
    window = create_window(agreement, station, **(window_overrides or {}))
    slot = create_slot(feed, station, window, **(slot_overrides or {}))
    submit_agreement(agreement, station)
    review_agreement(agreement)
    request_window_clearance(window, station)
    clear_window(window)
    clear_agreement(agreement)
    carried = publish_agreement(agreement)
    return {
        "station": station, "program": program, "agreement": carried,
        "window": refresh_window(window), "feed": feed, "slot": refresh_slot(slot),
    }


def setup_shortlisted_contribution(station_overrides=None, program_overrides=None,
                                   contribution_overrides=None):
    """A program plus one SHORTLISTED local piece from an eligible station."""
    station = make_station_eligible(**(station_overrides or {}))
    program = create_program(**(program_overrides or {}))
    payload = create_contribution_payload(station_id=station["id"], program_id=program["id"])
    payload.update(contribution_overrides or {})
    contribution = get_success_data(
        api_client.create_contribution(payload, _station_headers(station)), 201)
    get_success_data(api_client.submit_contribution(contribution["id"], _station_headers(station)))
    get_success_data(api_client.shortlist_contribution(contribution["id"], EDITOR))
    refreshed = get_success_data(api_client.get_contribution(contribution["id"], EDITOR))
    return {"station": station, "program": program, "contribution": refreshed}


def setup_licensed_contribution(station_overrides=None, program_overrides=None,
                                contribution_overrides=None):
    """The shortlisted piece walked one hop further to LICENSED."""
    ctx = setup_shortlisted_contribution(station_overrides, program_overrides,
                                         contribution_overrides)
    program = refresh_program(ctx["program"])
    resp = api_client.license_contribution(
        ctx["contribution"]["id"],
        {"expected_program_version": program["version"]},
        EDITOR,
    )
    licensed = get_success_data(resp)
    ctx["contribution"] = licensed
    ctx["program"] = refresh_program(program)
    ctx["station"] = refresh_station(ctx["station"])
    return ctx


def setup_reported_drive(pledge_cents=100000, collected_cents=55000,
                         station_overrides=None, close_at="2026-10-15T00:00:00Z"):
    """A drive carried through PLANNED -> ACTIVE -> CLOSED -> REPORTED.

    PRD §3.7: opening needs the station ELIGIBLE or PROBATION and at least one
    AudienceReport for the fiscal year; closing needs the clock to have reached
    ``drive_close_at``.
    """
    station = make_station_eligible(**(station_overrides or {}))
    report = get_success_data(api_client.create_audience_report(
        create_audience_report_payload(station_id=station["id"]), _station_headers(station)), 201)
    drive = get_success_data(api_client.create_drive(
        create_drive_payload(station_id=station["id"], drive_close_at=close_at),
        _station_headers(station)), 201)
    get_success_data(api_client.open_drive(drive["id"], _station_headers(station)))
    get_success_data(api_client.pledge_drive(
        drive["id"], {"pledge_cents": pledge_cents, "collected_cents": collected_cents},
        _station_headers(station)))
    set_clock("2026-10-16T00:00:00Z")
    get_success_data(api_client.close_drive(drive["id"], _station_headers(station)))
    reported = get_success_data(api_client.report_drive(drive["id"], _station_headers(station)))
    return {"station": station, "report": report, "drive": reported}


def setup_open_proposal(proposal_overrides=None, station_overrides=None):
    """One open DuesStructureProposal and one ELIGIBLE station.

    PRD §3.9: opening freezes the electorate, so it must happen after the
    station reaches eligibility.
    """
    station = make_station_eligible(**(station_overrides or {}))
    proposal = get_success_data(api_client.create_proposal(
        create_proposal_payload(**(proposal_overrides or {})), GOVERNANCE), 201)
    opened = get_success_data(api_client.open_proposal(proposal["id"], GOVERNANCE))
    return {"station": station, "proposal": opened}


def cast_station_vote(ctx, vote_choice="YES"):
    """Record the station's weighted vote on the open proposal (PRD §3.9)."""
    station = refresh_station(ctx["station"])
    resp = api_client.cast_vote(
        ctx["proposal"]["id"],
        {
            "station_id": station["id"],
            "vote_choice": vote_choice,
            "current_rate_bps": ctx["proposal"]["current_rate_bps"],
            "expected_station_version": station["version"],
        },
        _station_headers(station),
    )
    vote = get_success_data(resp)
    ctx["station"] = station
    ctx["vote"] = vote
    return vote


def setup_open_proposal_with_vote(vote_choice="YES", proposal_overrides=None,
                                  station_overrides=None):
    ctx = setup_open_proposal(proposal_overrides, station_overrides)
    cast_station_vote(ctx, vote_choice)
    ctx["proposal"] = refresh_proposal(ctx["proposal"])
    return ctx


def setup_closed_election_with_qualified_candidate(
        election_overrides=None, station_overrides=None, votes_recorded=12,
        seat_overrides=None):
    """A CLOSED election holding one QUALIFIED candidacy from an eligible station.

    PRD §3.10: qualification needs the station's eligible_from reached; closing
    needs the logical clock at or past the certification deadline.
    """
    station = make_station_eligible(**(station_overrides or {}))
    seat = None
    if seat_overrides is not None:
        seat = get_success_data(api_client.create_seat(
            create_seat_payload(**seat_overrides), GOVERNANCE), 201)
    election = get_success_data(api_client.create_election(
        create_election_payload(**(election_overrides or {})), GOVERNANCE), 201)
    candidate = get_success_data(api_client.create_candidate(
        create_candidate_payload(parent_election_id=election["id"], station_id=station["id"]),
        _station_headers(station)), 201)
    get_success_data(api_client.qualify_candidate(candidate["id"], GOVERNANCE))
    if votes_recorded is not None:
        get_success_data(api_client.record_candidate_votes(
            candidate["id"], {"votes_recorded": votes_recorded}, GOVERNANCE))
    set_clock("2026-11-16T00:00:00Z")
    closed = get_success_data(api_client.close_election(election["id"], GOVERNANCE))
    return {
        "station": station,
        "election": closed,
        "candidate": get_success_data(api_client.get_candidate(candidate["id"], GOVERNANCE)),
        "seat": seat,
    }


def setup_board_seat_in_election(seat_overrides=None, station_overrides=None,
                                 election_overrides=None):
    """A VACANT seat plus a certified election that has seated the station."""
    ctx = setup_closed_election_with_qualified_candidate(
        election_overrides=election_overrides,
        station_overrides=station_overrides,
        seat_overrides=seat_overrides or {},
    )
    certified = get_success_data(api_client.certify_election(
        ctx["election"]["id"],
        {"expected_election_version": ctx["election"]["version"]},
        GOVERNANCE,
    ))
    ctx["election"] = certified
    ctx["seat"] = get_success_data(api_client.get_seat(ctx["seat"]["id"], GOVERNANCE))
    ctx["candidate"] = get_success_data(api_client.get_candidate(ctx["candidate"]["id"], GOVERNANCE))
    ctx["station"] = refresh_station(ctx["station"])
    return ctx


def setup_two_eligible_stations(schedule_overrides=None, first_overrides=None,
                                second_overrides=None):
    """Two ELIGIBLE stations in one fiscal year, each with its own assessment.

    PRD §3.9's allocation batch addresses a single assessment and distributes
    the pool across every eligible station in the batch.
    """
    create_schedule(**(schedule_overrides or {}))
    first = make_station_eligible(**(first_overrides or {
        "call_sign": "WKAR", "dma_market_rank": 5, "dma_households": 2200000,
        "coverage_population": 130000, "full_time_staff_count": 9,
        "newsroom_staff_count": 5, "board_seat_region": "REGION_MIDWEST",
    }))
    second = make_station_eligible(**(second_overrides or {
        "call_sign": "WETA", "dma_market_rank": 22, "dma_households": 700000,
        "coverage_population": 60000, "full_time_staff_count": 6,
        "newsroom_staff_count": 3, "board_seat_region": "REGION_SOUTH",
    }))
    return {
        "stations": [first, second],
        "assessments": [first_station_assessment(first), first_station_assessment(second)],
    }


def setup_underwriting_agreement(station, ack_script_text=None, **overrides):
    """Create an UnderwritingAgreement in SUBMITTED status (PRD §3.8)."""
    payload = create_underwriting_payload(station_id=station["id"], **overrides)
    if ack_script_text is not None:
        payload["ack_script_text"] = ack_script_text
    return get_success_data(api_client.create_underwriting(payload, UNDERWRITING), 201)


# ---------------------------------------------------------------------------
# Tier 4 — accumulation / threshold targeting
# ---------------------------------------------------------------------------

def setup_probation_station_with_score(target_score_inputs):
    """An ELIGIBLE station whose scored inputs are fixed before probation.

    ``target_score_inputs`` is a dict of coverage/staffing/newsroom inputs; the
    station is approved (which recomputes the score) and then placed on
    probation so the restore floor can be exercised.
    """
    station = make_station_eligible(**target_score_inputs)
    restored = get_success_data(api_client.probation(
        station["id"], {"reason_code": "AUDIT_FINDING"}, AUDITOR))
    return restored


def setup_station_at_household_gate(dma_households, coverage_population=1000000,
                                    full_time_staff_count=6, newsroom_staff_count=9,
                                    **overrides):
    """A station created with an exact household input, for the class ladder gate."""
    overrides.update({
        "dma_households": dma_households,
        "coverage_population": coverage_population,
        "full_time_staff_count": full_time_staff_count,
        "newsroom_staff_count": newsroom_staff_count,
    })
    return create_station(**overrides)


# ---------------------------------------------------------------------------
# Tier 5 — finalization / terminal state
# ---------------------------------------------------------------------------

def setup_finalized_assessment(station_overrides=None, schedule_overrides=None):
    """An ELIGIBLE station whose INITIAL assessment has been finalized."""
    ctx = setup_eligible_station_with_schedule(station_overrides, schedule_overrides)
    station = ctx["station"]
    finalized = get_success_data(api_client.finalize_assessment(
        ctx["assessment"]["id"], {"expected_station_version": station["version"]}, AUDITOR))
    ctx["finalized"] = finalized
    ctx["station"] = refresh_station(station)
    return ctx


def setup_retirable_program(station_overrides=None, contribution_overrides=None):
    """A PUBLISHED program carrying one LICENSED contribution.

    PRD §3.6: publishing needs RUNNING status and at least one licensed piece;
    premiere needs the clock at or past the premiere instant.
    """
    station = make_station_eligible(**(station_overrides or {}))
    program = create_program(national_premiere_at="2026-09-15T00:00:00Z",
                             clearance_required=False)
    program = get_success_data(api_client.program_move_to_production(program["id"], EDITOR))
    program = get_success_data(api_client.program_schedule(program["id"], EDITOR))
    set_clock("2026-09-16T00:00:00Z")
    program = get_success_data(api_client.program_premiere(program["id"], EDITOR))
    payload = create_contribution_payload(station_id=station["id"], program_id=program["id"])
    payload.update(contribution_overrides or {})
    contribution = get_success_data(
        api_client.create_contribution(payload, _station_headers(station)), 201)
    get_success_data(api_client.submit_contribution(contribution["id"], _station_headers(station)))
    get_success_data(api_client.shortlist_contribution(contribution["id"], EDITOR))
    program = refresh_program(program)
    contribution = get_success_data(api_client.license_contribution(
        contribution["id"], {"expected_program_version": program["version"]}, EDITOR))
    program = get_success_data(api_client.program_publish(program["id"], EDITOR))
    return {
        "station": station, "program": program,
        "contribution": get_success_data(api_client.get_contribution(contribution["id"], EDITOR)),
    }


# ---------------------------------------------------------------------------
# Governance primitives (PRD §3.9, §3.10)
# ---------------------------------------------------------------------------

def create_proposal(**overrides) -> dict:
    """Draft a DuesStructureProposal (PRD §3.9)."""
    resp = api_client.create_proposal(create_proposal_payload(**overrides), GOVERNANCE)
    return get_success_data(resp, 201)


def create_election(**overrides) -> dict:
    """Open a BoardElection for a governance region (PRD §3.10)."""
    resp = api_client.create_election(create_election_payload(**overrides), GOVERNANCE)
    return get_success_data(resp, 201)


def create_candidate(election: dict, station: dict, **overrides) -> dict:
    """File a candidacy for a station in an election (PRD §3.10)."""
    overrides.setdefault("parent_election_id", election["id"])
    overrides.setdefault("station_id", station["id"])
    resp = api_client.create_candidate(create_candidate_payload(**overrides),
                                       _station_headers(station))
    return get_success_data(resp, 201)


def create_seat(**overrides) -> dict:
    """Create a BoardSeat in VACANT status (PRD §3.10)."""
    resp = api_client.create_seat(create_seat_payload(**overrides), GOVERNANCE)
    return get_success_data(resp, 201)


def create_contribution(station: dict, program: dict, **overrides) -> dict:
    """File a local reporting piece against a national program (PRD §3.6)."""
    overrides.setdefault("station_id", station["id"])
    overrides.setdefault("program_id", program["id"])
    resp = api_client.create_contribution(create_contribution_payload(**overrides),
                                          _station_headers(station))
    return get_success_data(resp, 201)


def open_proposal(proposal: dict) -> dict:
    """Open a DRAFT or TABLED proposal, freezing the electorate (PRD §3.9)."""
    return get_success_data(api_client.open_proposal(proposal["id"], GOVERNANCE))


def create_and_certify_election(seat: dict, station: dict, **overrides) -> dict:
    """Open an election, seat the station, and certify it (PRD §3.10)."""
    election = create_election(**overrides)
    candidate = create_candidate(election, station)
    api_client.qualify_candidate(candidate["id"], GOVERNANCE)
    set_clock("2026-11-16T00:00:00Z")
    closed = get_success_data(api_client.close_election(election["id"], GOVERNANCE))
    certified = get_success_data(api_client.certify_election(
        closed["id"], {"expected_election_version": closed["version"]}, GOVERNANCE))
    return {"election": certified, "seat": get_success_data(
        api_client.get_seat(seat["id"], GOVERNANCE)), "candidate": candidate}
