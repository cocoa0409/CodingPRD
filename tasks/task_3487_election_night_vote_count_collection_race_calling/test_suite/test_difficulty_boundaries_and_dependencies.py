"""Difficulty-design tests: boundary precision, cross-entity state gates, and
priority-ordered validation conflicts.

Covers the strict-inequality certainty boundary, the inclusive recount margin
threshold, the CERTIFICATION gate over every contest's tabulation state, the
active-recount publish veto, and two priority pairs where the lower-numbered
check must surface (PRD §2.5, §2.9, §3.2, §3.3, §3.6, §3.7).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_report,
    advance_to_candidates_locked,
    advance_to_certification,
    advance_to_live,
    advance_to_tabulation,
    alameda_payload,
    big_county_payload,
    create_assignment,
    create_assignment_payload,
    create_candidate,
    create_contest,
    create_county,
    create_event,
    create_feed_source,
    create_stringer,
    exactshire_payload,
    file_recount,
    get_contest,
    get_event,
    link_county,
    make_chief_headers,
    propose_call,
    reset_clock_to_setup,
    setup_margin_threshold_contest,
    setup_standard_universe,
    setup_universe_with_reports,
    sierra_payload,
    submit_feed_report,
    activate_recount,
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


def test_certainty_equality_is_not_certainty(api):
    """PRD §3.6: "For a single-seat contest, W is callable only when W's total
    strictly exceeds every other candidate's total plus the contest's
    `outstanding_estimate`; exact equality fails, because a trailing candidate
    could still tie, and a tie is not certainty."
    PRD §2.9: "The calling standard on call publication: the certainty evaluation
    must pass for the proposed winner, else `ERR_CERTAINTY_NOT_MET`."

    Design: Difficulty/boundary_precision_check/certainty_equality_is_not_certainty
    """
    universe = setup_universe_with_reports(
        [{"county": "alameda", "precincts_reporting": 5,
          "votes": {"wanda": 7000, "tom": 2000}}],
        advance_to="TABULATION",
        link_contra_costa=False,
    )
    contest_id = universe["contest"]["id"]
    # outstanding = max(floor(10000 * 5 / 10), max(8000 - 9000, 0)) = 5000,
    # and 7000 > 2000 + 5000 is false at exact equality.
    assert universe["contest"]["outstanding_estimate"] == 5000

    call = propose_call(contest_id, universe["candidates"]["wanda"]["id"])
    resp = api.decide_call(call["id"], "PUBLISH", make_chief_headers())
    validate_error(resp, ApiErrorId.ERR_CERTAINTY_NOT_MET)

    assert _list_call(api, contest_id, call["id"])["status"] == "PROPOSED"
    contest = get_contest(contest_id)
    assert contest["call_status"] == "UNCALLED"
    assert contest["outstanding_estimate"] == 5000


def test_recount_margin_exactly_at_threshold_fileable(api):
    """PRD §3.7: "Filing requires the contest's `tabulation_status` to be
    `COMPLETE` — a contest still collecting reports is rejected with
    `ERR_INVALID_STATE` — and its `margin_pct` to be no greater than 0.005, half
    a percentage point, with the threshold inclusive: a margin of exactly 0.005
    is fileable, while anything wider is rejected with
    `ERR_RECOUNT_MARGIN_EXCEEDED`."
    PRD §3.7: "The filing accepts an optional `note`, snapshots the contest's
    current `margin_pct` into the case's `filed_margin_pct`, and lands the case
    in `FILED`."

    Design: Difficulty/boundary_precision_check/recount_margin_exactly_at_threshold_fileable
    """
    reset_clock_to_setup()
    event = create_event()
    big = create_county(event["id"], big_county_payload())
    exact = create_county(event["id"], exactshire_payload())

    assembly = create_contest(
        event["id"], office_name="State Assembly D1", contest_type="STATE",
    )
    link_county(assembly["id"], big["id"])
    pat = create_candidate(assembly["id"], "Pat Pro", "DEM")
    quinn = create_candidate(assembly["id"], "Quinn Con", "REP")

    senate = create_contest(
        event["id"], office_name="State Senate D3", contest_type="STATE",
    )
    link_county(senate["id"], exact["id"])
    wes = create_candidate(senate["id"], "Wes Win", "DEM")
    thea = create_candidate(senate["id"], "Thea Trail", "REP")

    create_feed_source(event["id"])
    advance_to_candidates_locked(event["id"])
    advance_to_live(event["id"], event["event_date"])

    rep_p = submit_feed_report(
        assembly["id"], big["id"], 4, {pat["id"]: 100500, quinn["id"]: 99500},
    )
    accept_report(rep_p["id"])
    rep_q = submit_feed_report(
        senate["id"], exact["id"], 2, {wes["id"]: 10051, thea["id"]: 9949},
    )
    accept_report(rep_q["id"])
    advance_to_tabulation(event["id"])

    case = file_recount(assembly["id"])
    assert case["status"] == "FILED"
    assert case["filed_margin_pct"] == 0.005

    resp = api.create_recount_case(
        senate["id"], TEST_USERS["recount_officer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_RECOUNT_MARGIN_EXCEEDED)

    assert get_contest(assembly["id"])["margin_pct"] == 0.005
    assert get_contest(senate["id"])["margin_pct"] == 0.0051


def test_certification_requires_every_contest_complete(api):
    """PRD §2.5: "`TABULATION` → `CERTIFICATION` requires every contest in the
    event to have reached `tabulation_status` `COMPLETE`."
    PRD §2.5: "A request naming a target that is not the declared next state, or
    whose transition preconditions are unmet, is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/certification_requires_every_contest_complete
    """
    universe = setup_standard_universe(advance_to="SETUP")
    event_id = universe["event"]["id"]
    senate_id = universe["contest"]["id"]
    alameda_id = universe["counties"]["alameda"]["id"]
    contra_costa_id = universe["counties"]["contra_costa"]["id"]
    wanda_id = universe["candidates"]["wanda"]["id"]
    tom_id = universe["candidates"]["tom"]["id"]

    governor = create_contest(
        event_id, office_name="Governor", contest_type="STATE",
    )
    link_county(governor["id"], contra_costa_id)
    gail = create_candidate(governor["id"], "Gail Govern", "DEM")
    ron = create_candidate(governor["id"], "Ron Rival", "REP")

    advance_to_candidates_locked(event_id)
    advance_to_live(event_id, universe["event"]["event_date"])

    rep_a = submit_feed_report(senate_id, alameda_id, 10, {wanda_id: 6000, tom_id: 4000})
    accept_report(rep_a["id"])
    rep_b = submit_feed_report(senate_id, contra_costa_id, 5, {wanda_id: 2200, tom_id: 1800})
    accept_report(rep_b["id"])
    rep_g = submit_feed_report(governor["id"], contra_costa_id, 2, {gail["id"]: 1000, ron["id"]: 800})
    accept_report(rep_g["id"])  # clerk override: lands FLAGGED, still acceptable
    advance_to_tabulation(event_id)

    resp = api.transition_posture(event_id, "CERTIFICATION", TEST_USERS["admin_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_event(event_id)["posture"] == "TABULATION"

    rep_g2 = submit_feed_report(governor["id"], contra_costa_id, 5, {gail["id"]: 2500, ron["id"]: 1500})
    accept_report(rep_g2["id"])
    assert get_contest(governor["id"])["tabulation_status"] == "COMPLETE"

    advance_to_certification(event_id)
    assert get_event(event_id)["posture"] == "CERTIFICATION"


def test_active_recount_blocks_publish(api):
    """PRD §3.6: "then the state checks, within which an `ACTIVE` recount case on
    the contest is reported as `ERR_RECOUNT_ACTIVE_BLOCKS_CALL` and an
    already-called contest as `ERR_CALL_ALREADY_PUBLISHED`, both ahead of the
    generic `ERR_INVALID_STATE`"
    PRD §3.7: "if the event's posture is `CERTIFICATION` at that moment, the
    event automatically returns from `CERTIFICATION` to `TABULATION`"

    Design: Difficulty/cross_entity_state_dependency/active_recount_blocks_publish
    """
    universe = setup_margin_threshold_contest()
    contest_id = universe["contest"]["id"]
    call = propose_call(contest_id, universe["candidates"]["wanda"]["id"])
    recount = file_recount(contest_id)
    activate_recount(recount["id"])

    resp = api.decide_call(call["id"], "PUBLISH", make_chief_headers())
    validate_error(resp, ApiErrorId.ERR_RECOUNT_ACTIVE_BLOCKS_CALL)

    assert _list_call(api, contest_id, call["id"])["status"] == "PROPOSED"
    contest = get_contest(contest_id)
    assert contest["call_status"] == "UNCALLED"
    # Activation outside CERTIFICATION does not reopen the contest.
    assert contest["tabulation_status"] == "COMPLETE"


def test_publish_into_awaiting_contest_state_error_beats_certainty(api):
    """PRD §2.9: "When a single request would violate several rules, the check
    with the lowest priority number produces the response"
    PRD §3.6: "then the state checks, within which an `ACTIVE` recount case on
    the contest is reported as `ERR_RECOUNT_ACTIVE_BLOCKS_CALL` and an
    already-called contest as `ERR_CALL_ALREADY_PUBLISHED`, both ahead of the
    generic `ERR_INVALID_STATE` that covers the remaining from-state violations
    (the contest's `tabulation_status` must be `REPORTING` or `COMPLETE`, and its
    `call_status` must be `UNCALLED`); then segregation of duties, under which a
    chief whose `X-User-ID` equals the call's `proposed_by` is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403); and only then the certainty standard,
    whose failure rejects with `ERR_CERTAINTY_NOT_MET` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/publish_into_awaiting_contest_state_error_beats_certainty
    """
    universe = setup_standard_universe(advance_to="SETUP")
    event_id = universe["event"]["id"]
    senate_id = universe["contest"]["id"]
    wanda_id = universe["candidates"]["wanda"]["id"]
    tom_id = universe["candidates"]["tom"]["id"]

    governor = create_contest(
        event_id, office_name="Governor", contest_type="STATE",
    )
    link_county(governor["id"], universe["counties"]["contra_costa"]["id"])
    gail = create_candidate(governor["id"], "Gail Govern", "DEM")
    create_candidate(governor["id"], "Ron Rival", "REP")

    advance_to_candidates_locked(event_id)
    advance_to_live(event_id, universe["event"]["event_date"])
    rep = submit_feed_report(
        senate_id, universe["counties"]["alameda"]["id"], 5,
        {wanda_id: 4000, tom_id: 3000},
    )
    accept_report(rep["id"])
    advance_to_tabulation(event_id)

    call = propose_call(governor["id"], gail["id"])
    resp = api.decide_call(call["id"], "PUBLISH", make_chief_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    assert _list_call(api, governor["id"], call["id"])["status"] == "PROPOSED"
    assert get_contest(governor["id"])["call_status"] == "UNCALLED"


def test_cross_event_assignment_beats_window_overlap(api):
    """PRD §2.9: "When a single request would violate several rules, the check
    with the lowest priority number produces the response"
    PRD §2.9: "Cross-event reference: a `county_id` or `contest_id` supplied to a
    nested creation must belong to the path's event, else
    `ERR_CROSS_EVENT_REFERENCE` — on assignment creation, coverage-decision
    creation, and county linking."

    Design: Difficulty/priority_pair_validation_conflict/cross_event_assignment_beats_window_overlap
    """
    reset_clock_to_setup()
    event = create_event()
    alameda = create_county(event["id"], alameda_payload())
    other_event = create_event(
        event_name="2026 Special CD-5", event_type="SPECIAL",
        total_stringer_hour_budget=100,
    )
    sierra = create_county(other_event["id"], sierra_payload())
    sally = create_stringer()
    create_assignment(
        event["id"], alameda["id"], stringer_id=sally["id"],
        window_start="2026-11-03T08:00:00Z", window_end="2026-11-03T20:00:00Z",
    )

    payload = create_assignment_payload(
        sierra["id"],
        window_start="2026-11-03T19:00:00Z",
        window_end="2026-11-03T23:00:00Z",
        stringer_id=sally["id"],
    )
    resp = api.create_assignment(
        event["id"], payload, TEST_USERS["coordinator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_CROSS_EVENT_REFERENCE)

    _rows, meta = validate_paginated(
        api.list_stringer_assignments(
            sally["id"], TEST_USERS["coordinator_headers"],
        )
    )
    assert meta["total_count"] == 1
