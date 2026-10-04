"""Corner-design tests: tabulation rollup selection and precision, the QC
deviation and swing thresholds, the multi-seat certainty gate, and the
reliability-score walk (PRD §3.3, §3.4, §3.5, §3.6).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    accept_report,
    advance_to_candidates_locked,
    advance_to_live,
    check_in_assignment,
    create_assignment,
    create_stringer_with_no_show_history,
    get_contest,
    get_stringer,
    get_tabulation,
    make_chief_headers,
    propose_call,
    publish_call,
    set_clock,
    setup_standard_universe,
    setup_universe_with_reports,
    submit_feed_report,
    submit_stringer_report,
    validate_error,
    validate_paginated,
    TEST_USERS,
    void_report,
)


def test_rollup_uses_latest_accepted_report_per_county(api):
    """PRD §3.5: "For each county linked to the contest, the rollup selects that
    county's latest accepted report: the one with the greatest `accepted_at`,
    with ties broken by the greatest `created_at`, never by identifier."

    Design: Corner/calculations/rollup_uses_latest_accepted_report_per_county
    """
    universe = setup_universe_with_reports(
        [{"county": "alameda", "precincts_reporting": 5,
          "votes": {"wanda": 4000, "tom": 3000}}],
        link_contra_costa=False,
    )
    contest_id = universe["contest"]["id"]
    alameda_id = universe["counties"]["alameda"]["id"]
    first = universe["reports"][0]

    set_clock("2026-11-03T14:00:00Z")
    votes = {
        universe["candidates"]["wanda"]["id"]: 6500,
        universe["candidates"]["tom"]["id"]: 2500,
    }
    second = submit_feed_report(contest_id, alameda_id, 8, votes)
    accept_report(second["id"])

    board = get_tabulation(contest_id)
    assert board["reported_precincts"] == 8
    assert board["total_votes"] == 9000
    # 6500 - 2500 over 9000: only the later accepted report feeds the totals.
    assert board["margin_pct"] == 0.444444

    rows, _meta = validate_paginated(
        api.list_contest_vote_reports(contest_id, TEST_USERS["clerk_headers"])
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[first["id"]]["status"] == "ACCEPTED"


def test_rollup_excludes_received_and_flagged_reports(api):
    """PRD §3.5: "only reports in `ACCEPTED` status ever enter the rollup —
    `RECEIVED`, `FLAGGED`, `REJECTED`, and `VOIDED` reports are excluded
    entirely."
    PRD §3.4: "If this is the contest's first report, its `tabulation_status`
    moves from `AWAITING` to `REPORTING` regardless of the status the report
    itself lands in."

    Design: Corner/calculations/rollup_excludes_received_and_flagged_reports
    """
    universe = setup_universe_with_reports(
        [
            {"county": "alameda", "precincts_reporting": 5,
             "votes": {"wanda": 4000, "tom": 3000}, "accept": False},
            {"county": "contra_costa", "precincts_reporting": 2,
             "votes": {"wanda": 1000, "tom": 800}, "accept": False},
        ],
    )
    contest = get_contest(universe["contest"]["id"])
    assert contest["total_votes"] == 0
    assert contest["reported_precincts"] == 0
    assert contest["tabulation_status"] == "REPORTING"
    assert universe["reports"][1]["status"] == "FLAGGED"


def test_margin_pct_rounds_to_six_decimals(api):
    """PRD §3.5: "The contest's `margin_pct` is the difference between the top
    candidate's total and the runner-up's total, divided by the greater of
    `total_votes` and 1, rounded half up to six decimal places"
    PRD §2.8: "Ratios — `margin_pct`, `deviation_ratio`, `swing_deviation`, and
    the filed-margin snapshot — are numbers carried to 6 decimal places, rounded
    half up."

    Design: Corner/calculations/margin_pct_rounds_to_six_decimals
    """
    universe = setup_universe_with_reports(
        [{"county": "contra_costa", "precincts_reporting": 5,
          "votes": {"wanda": 2000, "tom": 1999}}],
        link_alameda=False,
    )
    contest = get_contest(universe["contest"]["id"])
    # 1/3999 = 0.0002500625... stores as 0.00025, not the float echo.
    assert contest["margin_pct"] == 0.00025
    assert contest["total_votes"] == 3999
    assert universe["reports"][0]["deviation_ratio"] == 0.00025


def test_qc_deviation_exactly_at_040_passes(api):
    """PRD §3.4: "The report lands `FLAGGED` when the `deviation_ratio` is
    strictly greater than 0.40 — forty percent of the expected total — or when a
    non-null `swing_deviation` is strictly greater than 0.25, and it lands
    `RECEIVED` otherwise. Both thresholds are strict: a `deviation_ratio` of
    exactly 0.400000 does not flag."

    Design: Corner/calculations/qc_deviation_exactly_at_040_passes
    """
    universe = setup_standard_universe(advance_to="LIVE")
    contest_id = universe["contest"]["id"]
    wanda_id = universe["candidates"]["wanda"]["id"]
    tom_id = universe["candidates"]["tom"]["id"]

    at_threshold = submit_feed_report(
        contest_id, universe["counties"]["contra_costa"]["id"], 2,
        {wanda_id: 3000, tom_id: 2600},
    )
    assert at_threshold["deviation_ratio"] == 0.4
    assert at_threshold["status"] == "RECEIVED"

    over_threshold = submit_feed_report(
        contest_id, universe["counties"]["alameda"]["id"], 5,
        {wanda_id: 8001, tom_id: 6000},
    )
    assert over_threshold["deviation_ratio"] == 0.4001
    assert over_threshold["status"] == "FLAGGED"


def test_qc_swing_breach_against_historical_pattern_flags(api):
    """PRD §3.4: "The report lands `FLAGGED` when the `deviation_ratio` is
    strictly greater than 0.40 — forty percent of the expected total — or when a
    non-null `swing_deviation` is strictly greater than 0.25, and it lands
    `RECEIVED` otherwise."
    PRD §3.4: "the reported DEM share is the contest's DEM candidate's votes
    divided by the greater of `reported_total` and 1"

    Design: Corner/calculations/qc_swing_breach_against_historical_pattern_flags
    """
    universe = setup_standard_universe(advance_to="LIVE")
    contest_id = universe["contest"]["id"]
    votes = {
        universe["candidates"]["wanda"]["id"]: 3135,
        universe["candidates"]["tom"]["id"]: 6365,
    }
    report = submit_feed_report(
        contest_id, universe["counties"]["alameda"]["id"], 5, votes,
    )
    # 3135/9500 == 0.33 against the 0.60 baseline: swing 0.27 trips alone.
    assert report["deviation_ratio"] == 0.05
    assert report["swing_deviation"] == 0.27
    assert report["status"] == "FLAGGED"


def test_multi_seat_certainty_compares_against_third_place(api):
    """PRD §3.6: "For a multi-seat contest, consider the candidate ranked one
    place below the last winning rank; when fewer candidates have any votes than
    `seats` plus one, W is callable exactly when W's total is greater than zero,
    and otherwise W is callable only when W's total strictly exceeds that next
    candidate's total plus the `outstanding_estimate` and W ranks within the
    first `seats` places."

    Design: Corner/calculations/multi_seat_certainty_compares_against_third_place
    """
    universe = setup_universe_with_reports(
        [
            {"county": "alameda", "precincts_reporting": 8,
             "votes": {"wanda": 5000, "tom": 2500, "ivy": 500}},
            {"county": "contra_costa", "precincts_reporting": 4,
             "votes": {"wanda": 2000, "tom": 1000, "ivy": 300}},
        ],
        advance_to="TABULATION",
        seats=2,
        extra_candidates=[("ivy", "Ivy Irwin", "IND")],
    )
    contest_id = universe["contest"]["id"]
    wanda_id = universe["candidates"]["wanda"]["id"]
    tom_id = universe["candidates"]["tom"]["id"]

    # Rank-2 Tom (3500) fails against rank-3 Ivy (800 + 2800 = 3600).
    call_t = propose_call(contest_id, tom_id)
    resp = api.decide_call(call_t["id"], "PUBLISH", make_chief_headers())
    validate_error(resp, ApiErrorId.ERR_CERTAINTY_NOT_MET)

    # Rank-1 Wanda (7000 > 3600) ranks within the first 2 seats.
    call_w = propose_call(contest_id, wanda_id)
    published = publish_call(call_w["id"])
    assert published["status"] == "PUBLISHED"

    contest = get_contest(contest_id)
    assert contest["call_status"] == "CALLED"
    assert contest["called_candidate_id"] == wanda_id


def test_reliability_accept_credit_and_void_penalty(api):
    """PRD §3.3: "The score starts at 100, subtracts twenty-five points for every
    no-show, subtracts ten points for every authored report that was voided after
    acceptance, adds two points for every authored report that was accepted, and
    is then clamped so it never falls below 0 and never rises above 100."
    PRD §3.4: "when the report is stringer-authored, the author's
    `accepted_report_count` increments by one and both reliability scores
    recompute."
    PRD §3.4: "A stringer-authored report additionally increments its author's
    `voided_report_count` by one with a reliability recompute."

    Design: Corner/calculations/reliability_accept_credit_and_void_penalty
    """
    history = create_stringer_with_no_show_history()
    sally_id = history["stringer"]["id"]

    universe = setup_standard_universe(advance_to="SETUP")
    event_id = universe["event"]["id"]
    contest_id = universe["contest"]["id"]
    alameda_id = universe["counties"]["alameda"]["id"]
    assignment = create_assignment(event_id, alameda_id, stringer_id=sally_id)
    advance_to_candidates_locked(event_id)
    advance_to_live(event_id, universe["event"]["event_date"])
    check_in_assignment(assignment["id"], sally_id)

    votes = {
        universe["candidates"]["wanda"]["id"]: 4000,
        universe["candidates"]["tom"]["id"]: 3000,
    }
    report = submit_stringer_report(contest_id, alameda_id, sally_id, 5, votes)
    assert report["submitted_by_stringer_id"] == sally_id

    accept_report(report["id"])
    sally = get_stringer(sally_id)
    assert sally["accepted_report_count"] == 1
    assert sally["reliability_career"] == 77

    void_report(report["id"])
    sally = get_stringer(sally_id)
    assert sally["voided_report_count"] == 1
    assert sally["reliability_career"] == 67
