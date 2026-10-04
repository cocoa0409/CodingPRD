"""Difficulty probes: validation pairs that conflict on one request.

The PRD pins a single validation order; when a request would fail checks in
two tiers, the earlier tier's error is the one returned. Each pair is shown
both ways: the combined double-failure scenario and an isolated
single-failure control.
"""

from test_helpers import (
    ApiErrorId,
    file_continuance,
    get_success_data,
    make_appeal_payload,
    make_judge_headers,
    mark_notice_defective,
    read_case,
    read_decision,
    read_hearing,
    schedule_hearing,
    serve_notice,
    set_clock,
    setup_appealed_case,
    setup_docketed_case,
    validate_error,
)


def test_appeal_on_pending_decision_reports_state_error_past_deadline(api, admin_headers):
    """PRD §2.6: "A request that would fail several checks receives exactly one error: the check in the earliest tier below that fails. The eleven tiers are evaluated in this order, and the ordering is itself part of the contract."
    PRD §2.6 tier 5 lists the decision's posture (`ERR_DECISION_NOT_APPEALABLE`, `ERR_DECISION_NOT_RESCINDABLE`) among the state preconditions, while tier 8 is: "8. **Temporal rules (HTTP 409).** Every clock comparison: `ERR_HEARING_IN_PAST`, `ERR_HEARING_NOT_YET_DUE`, `ERR_DETAINED_HEARING_PAST_EXPEDITED_DEADLINE`, `ERR_CONTINUANCE_TOO_LATE`, `ERR_APPEAL_WINDOW_EXPIRED`, and `ERR_REOPEN_WINDOW_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/appeal_state_error_beats_temporal_error
    """
    # Decision issued at 2026-09-04T12:00Z (appeal deadline 2026-10-04T12:00Z)
    # and already appealed once, so it stands APPEAL_PENDING.
    ctx = setup_appealed_case()
    # One second past the deadline: the tier-8 temporal check would also fail.
    set_clock("2026-10-04T12:00:01Z")
    resp = api.create_appeal(
        make_appeal_payload(ctx["decision"]["id"]), headers=admin_headers
    )
    # The tier-5 state check fires first: the decision is no longer ISSUED.
    validate_error(resp, ApiErrorId.ERR_DECISION_NOT_APPEALABLE)


def test_appeal_on_pending_decision_reports_state_error_within_window(api, admin_headers):
    """PRD §3.6: "The decision must still be `ISSUED` (otherwise `ERR_DECISION_NOT_APPEALABLE`), and the clock must be at or before the decision's `appeal_deadline`: the 30-day window is inclusive, so a filing at exactly the deadline succeeds while one a second later fails with `ERR_APPEAL_WINDOW_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/appeal_state_error_beats_temporal_error
    """
    # Control: the clock is comfortably inside the appeal window, so the
    # temporal check cannot fail; only the decision-posture gate can fire.
    ctx = setup_appealed_case()
    resp = api.create_appeal(
        make_appeal_payload(ctx["decision"]["id"]), headers=admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_DECISION_NOT_APPEALABLE)
    assert read_decision(ctx["decision"]["id"])["status"] == "APPEAL_PENDING"


def test_no_show_with_defective_notice_and_pending_continuance_reports_safety_error(
    api, admin_headers
):
    """PRD §2.6: "A request that would fail several checks receives exactly one error: the check in the earliest tier below that fails. The eleven tiers are evaluated in this order, and the ordering is itself part of the contract."
    PRD §2.6 tier 7 is: "7. **Due process (HTTP 409).** Notice requirements around in absentia practice: `ERR_NOTICE_NOT_SERVED`, `ERR_NOTICE_DEFECTIVE_BLOCKS_IN_ABSENTIA`, and `ERR_NOTICE_NOT_DEFECTIVE`." — and tier 9 carries `ERR_CONTINUANCE_PENDING_BLOCKS_NO_SHOW` among the capacity and cardinality constraints.
    PRD §3.5: "that notice must be `SERVED` rather than `DEFECTIVE` — an in absentia order may not rest on defective notice, so a defective one blocks the recording with `ERR_NOTICE_DEFECTIVE_BLOCKS_IN_ABSENTIA`; no `PENDING` continuance may target the hearing (`ERR_CONTINUANCE_PENDING_BLOCKS_NO_SHOW`)".

    Design: Difficulty/priority_pair_validation_conflict/no_show_safety_error_beats_constraint_error
    """
    ctx = setup_docketed_case()
    hearing = schedule_hearing(ctx["case"], "MASTER_CALENDAR", "2026-09-05T10:00:00Z")
    notice = serve_notice(
        hearing["id"], service_method="ELECTRONIC", served_at="2026-08-25T00:00:00Z"
    )
    # Filed at the 2026-09-01 clock anchor, more than 24h before the start.
    request = file_continuance(ctx["case"]["id"], hearing["id"], "EVIDENCE_GATHERING")
    # Both violations now stand: the notice is DEFECTIVE (tier 7) and a
    # PENDING continuance targets the hearing (tier 9).
    mark_notice_defective(notice["id"])
    set_clock("2026-09-05T10:30:00Z")
    resp = api.record_no_show(
        hearing["id"], headers=make_judge_headers(ctx["judge"]["id"])
    )
    # The due-process safety check fires before the constraint check.
    validate_error(resp, ApiErrorId.ERR_NOTICE_DEFECTIVE_BLOCKS_IN_ABSENTIA)
    # A rejected request writes nothing: no partial cascade.
    assert read_hearing(hearing["id"])["status"] == "SCHEDULED"
    assert read_case(ctx["case"]["id"])["status"] == "CALENDAR"
    pending = get_success_data(
        api.get_continuance_request(request["id"], headers=admin_headers)
    )
    assert pending["status"] == "PENDING"


def test_no_show_with_pending_continuance_alone_reports_constraint_error(api, admin_headers):
    """PRD §3.5: "no `PENDING` continuance may target the hearing (`ERR_CONTINUANCE_PENDING_BLOCKS_NO_SHOW`); and the caller must be the hearing's judge (`ERR_NOT_HEARING_JUDGE`)."
    PRD §2.6 tier 9 is: "9. **Capacity, uniqueness, and conflict (HTTP 409).** The scheduling and cardinality constraints: `ERR_JUDGE_SCHEDULE_CONFLICT`, `ERR_JUDGE_DAILY_MINUTES_EXCEEDED`, `ERR_DETAINED_DAILY_CAPACITY_REACHED`, `ERR_DETAINED_REQUIRES_REMOTE`, `ERR_CASE_HAS_SCHEDULED_HEARING`, `ERR_CONTINUANCE_ALREADY_PENDING`, `ERR_CONTINUANCE_PENDING_BLOCKS_NO_SHOW`, `ERR_CONTINUANCE_CAP_REACHED`, `ERR_VENUE_MOTION_ALREADY_PENDING`, `ERR_MOTION_ALREADY_PENDING`, `ERR_NOTICE_ALREADY_RECORDED`, `ERR_JUDGE_CASELOAD_FULL`, `ERR_CASE_NUMBER_NOT_UNIQUE`, `ERR_COURT_CODE_NOT_UNIQUE`, `ERR_DETAINED_NOT_REASSIGNABLE`, and `ERR_COURT_NOT_BACKLOG_CRITICAL`."

    Design: Difficulty/priority_pair_validation_conflict/no_show_safety_error_beats_constraint_error
    """
    # Control: the notice stays SERVED, so the tier-7 due-process checks pass
    # and the pending-continuance constraint is the only failing gate.
    ctx = setup_docketed_case()
    hearing = schedule_hearing(ctx["case"], "MASTER_CALENDAR", "2026-09-05T10:00:00Z")
    serve_notice(
        hearing["id"], service_method="ELECTRONIC", served_at="2026-08-25T00:00:00Z"
    )
    file_continuance(ctx["case"]["id"], hearing["id"], "EVIDENCE_GATHERING")
    set_clock("2026-09-05T10:30:00Z")
    resp = api.record_no_show(
        hearing["id"], headers=make_judge_headers(ctx["judge"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_CONTINUANCE_PENDING_BLOCKS_NO_SHOW)
    assert read_hearing(hearing["id"])["status"] == "SCHEDULED"
    assert read_case(ctx["case"]["id"])["status"] == "CALENDAR"
