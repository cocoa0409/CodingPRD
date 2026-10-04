"""Corner-design tests: the event posture ladder and the vote-report review
state machine (PRD §2.5, §3.1, §3.2, §3.4, §3.5).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_report,
    advance_to_archived,
    advance_to_candidates_locked,
    advance_to_certification,
    alameda_payload,
    create_candidate,
    create_contest,
    create_county,
    create_event,
    create_resubmit_payload,
    get_contest,
    get_event,
    link_county,
    propose_coverage,
    reject_report,
    reset_clock_to_setup,
    review_coverage,
    setup_complete_contest,
    setup_standard_universe,
    setup_universe_with_reports,
    submit_feed_report,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_posture_happy_path_setup_to_archived(api):
    """PRD §2.5: "The lifecycle runs `SETUP` → `CANDIDATES_LOCKED` → `LIVE` →
    `TABULATION` → `CERTIFICATION` → `ARCHIVED`, with `ARCHIVED` terminal."
    PRD §2.5: "`CERTIFICATION` → `ARCHIVED` requires that no recount case in
    status `FILED` or `ACTIVE` exists for any contest of the event."

    Design: Corner/state_machines/posture_happy_path_setup_to_archived
    """
    universe = setup_complete_contest()
    event_id = universe["event"]["id"]
    assert universe["event"]["posture"] == "TABULATION"
    assert universe["contest"]["tabulation_status"] == "COMPLETE"

    advance_to_certification(event_id)
    advance_to_archived(event_id)

    assert get_event(event_id)["posture"] == "ARCHIVED"
    assert get_contest(universe["contest"]["id"])["tabulation_status"] == "COMPLETE"


def test_posture_illegal_jump_setup_to_live_returns_invalid_state(api):
    """PRD §2.5: "The requested target must be the declared next state — skipping
    ahead or stepping backward is not admitted"
    PRD §2.5: "A request naming a target that is not the declared next state, or
    whose transition preconditions are unmet, is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/posture_illegal_jump_setup_to_live_returns_invalid_state
    """
    reset_clock_to_setup()
    event = create_event()
    resp = api.transition_posture(
        event["id"], "LIVE", TEST_USERS["admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_event(event["id"])["posture"] == "SETUP"


def test_posture_lock_blocked_until_candidates_and_links_exist(api):
    """PRD §2.5: "`SETUP` → `CANDIDATES_LOCKED` (candidate lock) requires three
    things: at least one contest exists in the event; every contest in the event
    has at least two candidates and at least one county link"

    Design: Corner/state_machines/posture_lock_blocked_until_candidates_and_links_exist
    """
    reset_clock_to_setup()
    event = create_event()
    county = create_county(event["id"], alameda_payload())
    contest = create_contest(event["id"])
    create_candidate(contest["id"], "Wanda Wynn", "DEM")

    resp = api.transition_posture(
        event["id"], "CANDIDATES_LOCKED", TEST_USERS["admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_event(event["id"])["posture"] == "SETUP"

    link_county(contest["id"], county["id"])
    create_candidate(contest["id"], "Tom Traylor", "REP")
    advance_to_candidates_locked(event["id"])
    assert get_event(event["id"])["posture"] == "CANDIDATES_LOCKED"


def test_primary_event_lock_requires_approved_coverage(api):
    """PRD §2.5: "for events whose `event_type` is `PRIMARY` or `SPECIAL`, every
    contest has at least one coverage decision in status `APPROVED` or `FUNDED`."
    PRD §3.2: "which matters because, for `PRIMARY` and `SPECIAL` events,
    candidate lock in §3.1 waits on every contest holding at least one decision
    in `APPROVED` or `FUNDED` status."

    Design: Corner/state_machines/primary_event_lock_requires_approved_coverage
    """
    reset_clock_to_setup()
    event = create_event(
        event_name="2026 Primary CA", event_date="2026-06-02",
        event_type="PRIMARY", total_stringer_hour_budget=100,
    )
    county = create_county(event["id"], alameda_payload())
    contest = create_contest(event["id"])
    link_county(contest["id"], county["id"])
    create_candidate(contest["id"], "Wanda Wynn", "DEM")
    create_candidate(contest["id"], "Tom Traylor", "REP")
    decision = propose_coverage(
        event["id"], contest["id"], 40, "2026-05-30", "2026-06-03",
    )

    resp = api.transition_posture(
        event["id"], "CANDIDATES_LOCKED", TEST_USERS["admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    review_coverage(decision["id"], "APPROVE")
    advance_to_candidates_locked(event["id"])
    assert get_event(event["id"])["posture"] == "CANDIDATES_LOCKED"


def test_first_report_moves_contest_awaiting_to_reporting(api):
    """PRD §3.4: "If this is the contest's first report, its `tabulation_status`
    moves from `AWAITING` to `REPORTING` regardless of the status the report
    itself lands in."

    Design: Corner/state_machines/first_report_moves_contest_awaiting_to_reporting
    """
    universe = setup_standard_universe(advance_to="LIVE")
    contest_id = universe["contest"]["id"]
    assert universe["contest"]["tabulation_status"] == "AWAITING"

    votes = {
        universe["candidates"]["wanda"]["id"]: 4000,
        universe["candidates"]["tom"]["id"]: 3000,
    }
    submit_feed_report(
        contest_id, universe["counties"]["alameda"]["id"], 5, votes,
    )

    contest = get_contest(contest_id)
    assert contest["tabulation_status"] == "REPORTING"
    assert contest["call_status"] == "UNCALLED"


def test_flagged_report_override_accept_feeds_rollup(api):
    """PRD §3.4: "The report lands `FLAGGED` when the `deviation_ratio` is
    strictly greater than 0.40"
    PRD §3.5: "only reports in `ACCEPTED` status ever enter the rollup —
    `RECEIVED`, `FLAGGED`, `REJECTED`, and `VOIDED` reports are excluded
    entirely."

    Design: Corner/state_machines/flagged_report_override_accept_feeds_rollup
    """
    universe = setup_universe_with_reports(
        [{"county": "contra_costa", "precincts_reporting": 2,
          "votes": {"wanda": 1000, "tom": 800}, "accept": False}],
    )
    contest_id = universe["contest"]["id"]
    report = universe["reports"][0]
    assert report["status"] == "FLAGGED"
    assert get_contest(contest_id)["total_votes"] == 0

    accepted = accept_report(report["id"])
    assert accepted["status"] == "ACCEPTED"

    contest = get_contest(contest_id)
    assert contest["total_votes"] == 1800
    assert contest["reported_precincts"] == 2


def test_rejected_report_resubmit_cycle_lands_received(api):
    """PRD §3.4: "The original channel may resubmit it with corrected
    `precincts_reporting` and `candidate_votes`"
    PRD §3.4: "Resubmission is admitted in postures `LIVE` and `TABULATION`,
    enforces the same precinct and candidate-membership bounds as creation, and
    re-runs the quality-control check, landing the report `RECEIVED` or `FLAGGED`
    by exactly the same rule as at creation."

    Design: Corner/state_machines/rejected_report_resubmit_cycle_lands_received
    """
    universe = setup_universe_with_reports(
        [{"county": "contra_costa", "precincts_reporting": 2,
          "votes": {"wanda": 1000, "tom": 800}, "accept": False}],
    )
    report = universe["reports"][0]
    rejected = reject_report(report["id"])
    assert rejected["status"] == "REJECTED"

    votes = {
        universe["candidates"]["wanda"]["id"]: 1300,
        universe["candidates"]["tom"]["id"]: 1200,
    }
    resp = api.resubmit_vote_report(
        report["id"], create_resubmit_payload(3, votes),
        TEST_USERS["feed_operator_headers"],
    )
    data = validate_success(resp, 200)
    assert data["status"] == "RECEIVED"
    assert data["deviation_ratio"] == 0.375
    assert data["reported_total"] == 2500


def test_review_accept_on_accepted_returns_invalid_state(api):
    """PRD §3.4: "ACCEPT moves a `RECEIVED` or `FLAGGED` report to `ACCEPTED`"
    PRD §2.9: "Entity state preconditions on every state-transition endpoint: the
    resource must sit in a from-state that admits the transition, else
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/review_accept_on_accepted_returns_invalid_state
    """
    universe = setup_universe_with_reports(
        [{"county": "alameda", "precincts_reporting": 5,
          "votes": {"wanda": 4000, "tom": 3000}}],
    )
    contest_id = universe["contest"]["id"]
    report = universe["reports"][0]
    assert report["status"] == "ACCEPTED"

    resp = api.review_vote_report(
        report["id"], "ACCEPT", TEST_USERS["clerk_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    assert get_contest(contest_id)["total_votes"] == 7000


def test_void_on_received_returns_invalid_state(api):
    """PRD §3.4: "VOID is the compensation path: it moves an `ACCEPTED` report to
    `VOIDED`"
    PRD §2.9: "Entity state preconditions on every state-transition endpoint: the
    resource must sit in a from-state that admits the transition, else
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/void_on_received_returns_invalid_state
    """
    universe = setup_universe_with_reports(
        [{"county": "alameda", "precincts_reporting": 5,
          "votes": {"wanda": 4000, "tom": 3000}, "accept": False}],
    )
    contest_id = universe["contest"]["id"]
    report = universe["reports"][0]
    assert report["status"] == "RECEIVED"

    resp = api.review_vote_report(
        report["id"], "VOID", TEST_USERS["clerk_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    rows, _meta = validate_paginated(
        api.list_contest_vote_reports(contest_id, TEST_USERS["clerk_headers"])
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[report["id"]]["status"] == "RECEIVED"
