"""Corner-design tests: the race-call, recount-case, stringer-assignment, and
coverage-decision state machines (PRD §3.2, §3.3, §3.6, §3.7).
"""
import pytest

from test_helpers import (
    ANALYST_KIM_ID,
    ApiErrorId,
    ELECTION_DAY_CLOCK,
    ELECTION_DAY_EARLY_CLOCK,
    ELECTION_DAY_LATE_CLOCK,
    TEST_USERS,
    advance_posture,
    advance_to_candidates_locked,
    assignment_action,
    create_assignment,
    create_stringer,
    dismiss_recount,
    file_recount,
    get_contest,
    get_stringer,
    list_contest_deliveries,
    list_customer_deliveries,
    make_chief_headers,
    make_stringer_headers,
    propose_call,
    propose_coverage,
    publish_call,
    retract_call,
    review_coverage,
    revise_coverage,
    set_clock,
    setup_margin_threshold_contest,
    setup_proposed_call,
    setup_published_call,
    setup_standard_universe,
    validate_error,
    validate_paginated,
)


def _list_call(api, contest_id, call_id):
    rows, _meta = validate_paginated(
        api.list_calls(contest_id, TEST_USERS["admin_headers"])
    )
    by_id = {row["id"]: row for row in rows}
    assert call_id in by_id, f"call {call_id} missing from contest call list"
    return by_id[call_id]


def _list_recount_case(api, contest_id, case_id):
    rows, _meta = validate_paginated(
        api.list_recount_cases(contest_id, TEST_USERS["admin_headers"])
    )
    by_id = {row["id"]: row for row in rows}
    assert case_id in by_id, f"recount case {case_id} missing"
    return by_id[case_id]


def _get_assignment(api, event_id, assignment_id):
    """Assignments have no point read; read back through the event list."""
    rows, _meta = validate_paginated(
        api.list_event_assignments(event_id, TEST_USERS["coordinator_headers"])
    )
    by_id = {row["id"]: row for row in rows}
    assert assignment_id in by_id, f"assignment {assignment_id} missing"
    return by_id[assignment_id]


def test_proposed_call_retract_records_reason_without_deliveries(api):
    """PRD §3.6: "Retracting a `PROPOSED` call — nothing was ever published —
    simply records the supplied `reason` as `retract_reason` and moves the call
    to `RETRACTED`, with no delivery effects at all."

    Design: Corner/state_machines/proposed_call_retract_records_reason_without_deliveries
    """
    universe = setup_proposed_call()
    contest_id = universe["contest"]["id"]
    call = universe["call"]

    retracted = retract_call(call["id"], "analyst withdrew the recommendation")
    assert retracted["status"] == "RETRACTED"
    assert retracted["retract_reason"] == "analyst withdrew the recommendation"

    assert get_contest(contest_id)["call_status"] == "UNCALLED"
    _rows, meta = list_contest_deliveries(contest_id)
    assert meta["total_count"] == 0


def test_retracted_call_is_terminal(api):
    """PRD §3.6: "`RETRACTED` is the call's terminal status."
    PRD §2.9: "Entity state preconditions on every state-transition endpoint: the
    resource must sit in a from-state that admits the transition, else
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/retracted_call_is_terminal
    """
    universe = setup_proposed_call()
    contest_id = universe["contest"]["id"]
    call = universe["call"]
    retract_call(call["id"], "dropped")

    resp = api.decide_call(call["id"], "PUBLISH", make_chief_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    assert _list_call(api, contest_id, call["id"])["status"] == "RETRACTED"


def test_second_publish_on_called_contest_returns_already_published(api):
    """PRD §3.6: "then the state checks, within which an `ACTIVE` recount case on
    the contest is reported as `ERR_RECOUNT_ACTIVE_BLOCKS_CALL` and an
    already-called contest as `ERR_CALL_ALREADY_PUBLISHED`, both ahead of the
    generic `ERR_INVALID_STATE`"
    PRD §3.6: "A contest is `CALLED` exactly while one published call exists for
    it."

    Design: Corner/state_machines/second_publish_on_called_contest_returns_already_published
    """
    universe = setup_published_call(link_contra_costa=False)
    contest_id = universe["contest"]["id"]
    wanda_id = universe["candidates"]["wanda"]["id"]
    tom_id = universe["candidates"]["tom"]["id"]

    call2 = propose_call(contest_id, tom_id, analyst_id=ANALYST_KIM_ID)
    resp = api.decide_call(call2["id"], "PUBLISH", make_chief_headers())
    validate_error(resp, ApiErrorId.ERR_CALL_ALREADY_PUBLISHED)

    assert _list_call(api, contest_id, call2["id"])["status"] == "PROPOSED"
    contest = get_contest(contest_id)
    assert contest["call_status"] == "CALLED"
    assert contest["called_candidate_id"] == wanda_id


def test_dismissed_recount_cannot_activate(api):
    """PRD §3.7: "A case that should not proceed is dismissed, moving from
    `FILED` to `DISMISSED`"
    PRD §3.7: "`DISMISSED`, `RESOLVED_CONFIRMED`, and `RESOLVED_OVERTURNED` are
    all terminal."

    Design: Corner/state_machines/dismissed_recount_cannot_activate
    """
    universe = setup_margin_threshold_contest()
    contest_id = universe["contest"]["id"]
    recount = file_recount(contest_id)
    dismissed = dismiss_recount(recount["id"], note="insufficient basis")
    assert dismissed["status"] == "DISMISSED"

    resp = api.decide_recount_case(
        recount["id"], "ACTIVATE", TEST_USERS["recount_officer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    assert _list_recount_case(api, contest_id, recount["id"])["status"] == "DISMISSED"


def test_dismissed_recount_leaves_published_call_untouched(api):
    """PRD §3.7: "A case that should not proceed is dismissed, moving from
    `FILED` to `DISMISSED`; the dismissal accepts an optional `note` while
    leaving `resolution_note` null."
    PRD §3.7: "Resolving `OVERTURNED` fires a three-hop cascade." (dismissal
    fires none)

    Design: Corner/state_machines/dismissed_recount_leaves_published_call_untouched
    """
    universe = setup_margin_threshold_contest(customers=("premium",))
    universe = setup_proposed_call(universe=universe)
    universe["call"] = publish_call(universe["call"]["id"])
    contest_id = universe["contest"]["id"]

    recount = file_recount(contest_id)
    dismissed = dismiss_recount(recount["id"], note="frivolous")
    assert dismissed["status"] == "DISMISSED"

    assert _list_call(api, contest_id, universe["call"]["id"])["status"] == "PUBLISHED"
    contest = get_contest(contest_id)
    assert contest["call_status"] == "CALLED"
    assert contest["called_candidate_id"] == universe["candidates"]["wanda"]["id"]

    customer = universe["customers"]["premium"]
    rows, _meta = list_customer_deliveries(customer["id"])
    call_rows = [row for row in rows if row["content_type"] == "CALL"]
    assert len(call_rows) == 1
    assert call_rows[0]["status"] == "SENT"
    assert not any(row["content_type"] == "CALL_CREDIT" for row in rows)


def test_no_show_marks_after_window_and_dents_reliability(api):
    """PRD §3.3: "`NO_SHOW` moves a `SCHEDULED` assignment to `NO_SHOW`, admitted
    only once the logical clock has reached or passed the window's end —
    otherwise `ERR_OUTSIDE_ASSIGNMENT_WINDOW`; the mark increments the stringer's
    `no_show_count` by one and recomputes both reliability scores, and `NO_SHOW`
    is absorbing."
    PRD §3.3: "The score starts at 100, subtracts twenty-five points for every
    no-show"

    Design: Corner/state_machines/no_show_marks_after_window_and_dents_reliability
    """
    universe = setup_standard_universe(advance_to="SETUP")
    sally = create_stringer()
    assignment = create_assignment(
        universe["event"]["id"], universe["counties"]["alameda"]["id"],
        stringer_id=sally["id"],
    )
    set_clock(ELECTION_DAY_LATE_CLOCK)

    marked = assignment_action(assignment["id"], "NO_SHOW")
    assert marked["status"] == "NO_SHOW"

    sally = get_stringer(sally["id"])
    assert sally["no_show_count"] == 1
    assert sally["reliability_career"] == 75


def test_checkin_before_window_and_early_no_show_return_outside_window(api):
    """PRD §3.3: "while the logical clock sits inside the half-open window; a
    check-in outside the window is rejected with
    `ERR_OUTSIDE_ASSIGNMENT_WINDOW`."
    PRD §3.3: "`NO_SHOW` moves a `SCHEDULED` assignment to `NO_SHOW`, admitted
    only once the logical clock has reached or passed the window's end —
    otherwise `ERR_OUTSIDE_ASSIGNMENT_WINDOW`"

    Design: Corner/state_machines/checkin_before_window_and_early_no_show_return_outside_window
    """
    universe = setup_standard_universe(advance_to="SETUP")
    event_id = universe["event"]["id"]
    sally = create_stringer()
    assignment = create_assignment(
        event_id, universe["counties"]["alameda"]["id"],
        stringer_id=sally["id"],
    )
    advance_to_candidates_locked(event_id)
    set_clock(ELECTION_DAY_EARLY_CLOCK)
    advance_posture(event_id, "LIVE")

    resp1 = api.check_in_assignment(
        assignment["id"], make_stringer_headers(sally["id"]),
    )
    validate_error(resp1, ApiErrorId.ERR_OUTSIDE_ASSIGNMENT_WINDOW)

    set_clock(ELECTION_DAY_CLOCK)
    resp2 = api.assignment_status_action(
        assignment["id"], "NO_SHOW", TEST_USERS["coordinator_headers"],
    )
    validate_error(resp2, ApiErrorId.ERR_OUTSIDE_ASSIGNMENT_WINDOW)

    assert _get_assignment(api, event_id, assignment["id"])["status"] == "SCHEDULED"


def test_release_from_scheduled_returns_invalid_state(api):
    """PRD §3.3: "`RELEASE` moves an `ACTIVE` assignment to `RELEASED` with no
    further preconditions."
    PRD §2.9: "Entity state preconditions on every state-transition endpoint: the
    resource must sit in a from-state that admits the transition, else
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/release_from_scheduled_returns_invalid_state
    """
    universe = setup_standard_universe(advance_to="SETUP")
    event_id = universe["event"]["id"]
    sally = create_stringer()
    assignment = create_assignment(
        event_id, universe["counties"]["alameda"]["id"],
        stringer_id=sally["id"],
    )

    resp = api.assignment_status_action(
        assignment["id"], "RELEASE", TEST_USERS["coordinator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    assert _get_assignment(api, event_id, assignment["id"])["status"] == "SCHEDULED"


def test_coverage_decline_revise_reapprove_fund_loop(api):
    """PRD §3.2: "The planner may revise a `DECLINED` decision back to
    `PROPOSED`, supplying new `allocated_stringer_hours` and/or new
    `coverage_start` and `coverage_end` values"
    PRD §3.2: "a review of `FUND` moves an `APPROVED` decision to `FUNDED`"
    PRD §3.2: "`FUNDED` is the terminal status."

    Design: Corner/state_machines/coverage_decline_revise_reapprove_fund_loop
    """
    universe = setup_standard_universe(advance_to="SETUP")
    event_id = universe["event"]["id"]
    contest_id = universe["contest"]["id"]

    decision = propose_coverage(event_id, contest_id, 40, "2026-10-30", "2026-11-03")
    declined = review_coverage(decision["id"], "DECLINE")
    assert declined["status"] == "DECLINED"

    revised = revise_coverage(decision["id"], allocated_stringer_hours=30)
    assert revised["status"] == "PROPOSED"
    assert revised["allocated_stringer_hours"] == 30

    approved = review_coverage(decision["id"], "APPROVE")
    assert approved["status"] == "APPROVED"

    funded = review_coverage(decision["id"], "FUND")
    assert funded["status"] == "FUNDED"


def test_fund_from_proposed_returns_invalid_state(api):
    """PRD §3.2: "a review of `FUND` moves an `APPROVED` decision to `FUNDED`"
    PRD §2.9: "Entity state preconditions on every state-transition endpoint: the
    resource must sit in a from-state that admits the transition, else
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/fund_from_proposed_returns_invalid_state
    """
    universe = setup_standard_universe(advance_to="SETUP")
    decision = propose_coverage(
        universe["event"]["id"], universe["contest"]["id"],
    )

    resp = api.review_coverage_decision(
        decision["id"], "FUND", TEST_USERS["admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    rows, _meta = validate_paginated(
        api.list_event_coverage_decisions(
            universe["event"]["id"], TEST_USERS["admin_headers"],
        )
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[decision["id"]]["status"] == "PROPOSED"
