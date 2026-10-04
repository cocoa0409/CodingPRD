"""Difficulty-design tests: non-linear state machines and transitive cascades.

Covers the Contest call-status cycle running independent of the tabulation
dimension, the assignment ACTIVE -> RELEASED -> ACTIVE loop, the depth-3
recount-overturn cascade, and the depth-2 acceptance-to-completion rollup
chain (PRD §2.5, §3.3, §3.4, §3.5, §3.6, §3.7).
"""
import pytest

from test_helpers import (
    RECOUNT_OVERTURNED_REASON,
    TEST_USERS,
    accept_report,
    advance_to_archived,
    advance_to_certification,
    assignment_action,
    get_contest,
    get_event,
    get_stringer,
    list_customer_deliveries,
    list_contest_deliveries,
    propose_call,
    publish_call,
    resolve_recount,
    retract_call,
    setup_active_assignment,
    setup_active_recount_after_certification,
    setup_published_call,
    setup_universe_with_reports,
    submit_feed_report,
    validate_paginated,
    validate_success,
)


def _list_call(api, contest_id, call_id):
    """Read back one RaceCall via the contest's call list (no point read exists)."""
    rows, _meta = validate_paginated(
        api.list_calls(contest_id, TEST_USERS["admin_headers"])
    )
    by_id = {row["id"]: row for row in rows}
    assert call_id in by_id, f"call {call_id} missing from contest call list"
    return by_id[call_id]


def test_contest_call_dimension_cycles_while_tabulation_dimension_holds(api):
    """PRD §3.6: "The contest's two state dimensions evolve independently:
    retracting a call never changes `tabulation_status`, and the `UNCALLED` →
    `CALLED` → `UNCALLED` cycle may repeat."
    PRD §3.6: "A published call flips the contest's `call_status` from `UNCALLED`
    to `CALLED` and records the winner in the contest's `called_candidate_id`."

    Design: Difficulty/non_linear_state_machine/contest_call_dimension_cycles_while_tabulation_dimension_holds
    """
    universe = setup_published_call(link_contra_costa=False)
    contest_id = universe["contest"]["id"]
    wanda_id = universe["candidates"]["wanda"]["id"]
    call_a = universe["call"]

    retracted_a = retract_call(call_a["id"], "desk reversal on corrected estimate")
    assert retracted_a["status"] == "RETRACTED"

    call_b = propose_call(contest_id, wanda_id)
    published_b = publish_call(call_b["id"])

    assert _list_call(api, contest_id, call_a["id"])["status"] == "RETRACTED"
    assert published_b["status"] == "PUBLISHED"
    contest = get_contest(contest_id)
    assert contest["call_status"] == "CALLED"
    assert contest["called_candidate_id"] == wanda_id
    assert contest["tabulation_status"] == "COMPLETE"


def test_assignment_redeploy_cycle_releases_and_reactivates(api):
    """PRD §3.3: "`RELEASE` moves an `ACTIVE` assignment to `RELEASED` with no
    further preconditions."
    PRD §3.3: "`REDEPLOY` moves a `RELEASED` assignment back to `ACTIVE`,
    requiring the logical clock to still be strictly before the window's end."

    Design: Difficulty/non_linear_state_machine/assignment_redeploy_cycle_releases_and_reactivates
    """
    universe = setup_active_assignment()
    assignment_id = universe["assignment"]["id"]
    assert universe["assignment"]["status"] == "ACTIVE"

    released = assignment_action(assignment_id, "RELEASE")
    assert released["status"] == "RELEASED"

    redeployed = assignment_action(assignment_id, "REDEPLOY")
    assert redeployed["status"] == "ACTIVE"
    assert redeployed["auto_selected"] is False

    sally = get_stringer(universe["stringer"]["id"])
    assert sally["reliability_career"] == 100
    assert sally["no_show_count"] == 0


def test_recount_overturn_retracts_call_and_stales_deliveries(api):
    """PRD §3.7: "Resolving `OVERTURNED` fires a three-hop cascade. First, the
    contest's published race call, if one exists, is retracted with the fixed
    `retract_reason` `RECOUNT_OVERTURNED`. Second, that retraction flips the
    contest's `call_status` from `CALLED` back to `UNCALLED` and clears
    `called_candidate_id` to null. Third, the delivery compensation of §3.8
    fires: every `CALL` delivery of the contest still in `SENT` status flips to
    `STALE`, and each customer that received such a delivery is issued a
    compensating `CALL_CREDIT` delivery."
    PRD §3.7: "if the event's posture is `CERTIFICATION` at that moment, the
    event automatically returns from `CERTIFICATION` to `TABULATION`"

    Design: Difficulty/transitive_cascade/recount_overturn_retracts_call_and_stales_deliveries
    """
    universe = setup_active_recount_after_certification(customers=("premium",))
    contest_id = universe["contest"]["id"]
    customer = universe["customers"]["premium"]

    resolved = resolve_recount(
        universe["recount"]["id"], "OVERTURNED",
        note="hand recount reverses certified margin",
    )
    assert resolved["status"] == "RESOLVED_OVERTURNED"
    assert resolved["filed_margin_pct"] == 0.005

    call = _list_call(api, contest_id, universe["call"]["id"])
    assert call["status"] == "RETRACTED"
    assert call["retract_reason"] == RECOUNT_OVERTURNED_REASON

    contest = get_contest(contest_id)
    assert contest["call_status"] == "UNCALLED"
    assert contest["called_candidate_id"] is None

    rows, meta = list_contest_deliveries(contest_id)
    assert meta["total_count"] == 4
    by_type = {}
    for row in rows:
        by_type.setdefault(row["content_type"], []).append(row)
    assert len(by_type["VOTE_UPDATE"]) == 2
    assert all(row["status"] == "SENT" for row in by_type["VOTE_UPDATE"])
    assert len(by_type["CALL"]) == 1
    assert by_type["CALL"][0]["status"] == "STALE"
    assert by_type["CALL"][0]["customer_id"] == customer["id"]
    assert len(by_type["CALL_CREDIT"]) == 1
    assert by_type["CALL_CREDIT"][0]["fee_cents"] == -4999
    assert by_type["CALL_CREDIT"][0]["status"] == "SENT"
    assert by_type["CALL_CREDIT"][0]["customer_id"] == customer["id"]

    event = get_event(universe["event"]["id"])
    assert event["posture"] == "TABULATION"


def test_report_acceptance_rolls_up_county_then_contest_completion(api):
    """PRD §3.5: "the contest's `tabulation_status` becomes `COMPLETE` precisely
    when every linked county is complete and at least one county is linked"
    PRD §3.5: "The county's `status` reads `PENDING` before any accepted report
    names it, `REPORTING` once one does, and `COMPLETE` when a linked contest's
    latest accepted report for the county covers a precinct count equal to the
    county's `expected_precincts`."
    PRD §3.4: "The report's `accepted_at` stamps the logical clock"

    Design: Difficulty/transitive_cascade/report_acceptance_rolls_up_county_then_contest_completion
    """
    universe = setup_universe_with_reports(
        [{"county": "alameda", "precincts_reporting": 10,
          "votes": {"wanda": 6000, "tom": 4000}}],
    )
    contest_id = universe["contest"]["id"]
    assert universe["contest"]["tabulation_status"] == "REPORTING"

    votes = {
        universe["candidates"]["wanda"]["id"]: 2200,
        universe["candidates"]["tom"]["id"]: 1800,
    }
    rep_b = submit_feed_report(
        contest_id, universe["counties"]["contra_costa"]["id"], 5, votes,
    )
    accepted = accept_report(rep_b["id"])

    assert accepted["status"] == "ACCEPTED"
    assert accepted["accepted_at"] is not None

    contest = get_contest(contest_id)
    assert contest["tabulation_status"] == "COMPLETE"
    assert contest["reported_precincts"] == 15
    assert contest["total_votes"] == 14000
    assert contest["outstanding_estimate"] == 0

    for key in ("alameda", "contra_costa"):
        county = validate_success(
            api.get_county(
                universe["counties"][key]["id"], TEST_USERS["admin_headers"],
            )
        )
        assert county["status"] == "COMPLETE", f"{key} county must be COMPLETE"
