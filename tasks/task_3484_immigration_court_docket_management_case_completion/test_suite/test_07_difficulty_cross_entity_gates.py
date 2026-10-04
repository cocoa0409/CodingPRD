"""Difficulty probes: cross-entity state dependencies.

The set of legal hearing types for a new hearing depends on the parent case's
phase (Hearing -> Case), and an appeal's legality depends on its decision's
posture (Appeal -> Decision).
"""

from test_helpers import (
    ApiErrorId,
    advance_case_to_merits,
    case_version,
    complete_hearing,
    issue_decision,
    list_case_hearings,
    make_appeal_payload,
    make_hearing_payload,
    read_case,
    read_decision,
    schedule_hearing,
    set_clock,
    setup_docketed_case,
    setup_remanded_case,
    validate_error,
    validate_success,
)


def test_merits_hearing_rejected_while_case_in_calendar(api, admin_headers):
    """PRD §3.3: "The hearing type must match the phase: a `MASTER_CALENDAR` hearing is valid only while the case is `CALENDAR`, and an `INDIVIDUAL_MERITS` hearing only while the case is `MERITS`, with a mismatch drawing `ERR_HEARING_TYPE_STAGE_MISMATCH`."

    Design: Difficulty/cross_entity_state_dependency/merits_hearing_gated_on_case_merits_state
    """
    ctx = setup_docketed_case()
    # The case stands CALENDAR; the supplied version is current, so the
    # state-tier gate is the only check that can fire.
    payload = make_hearing_payload(
        ctx["case"]["id"], "INDIVIDUAL_MERITS", "2026-09-08T10:00:00Z",
        case_version(ctx["case"]["id"]),
    )
    resp = api.create_hearing(payload, headers=admin_headers)
    validate_error(resp, ApiErrorId.ERR_HEARING_TYPE_STAGE_MISMATCH)
    assert read_case(ctx["case"]["id"])["status"] == "CALENDAR"
    assert list_case_hearings(ctx["case"]["id"]) == [], "rejected creation writes nothing"


def test_merits_hearing_accepted_once_case_enters_merits():
    """PRD §3.3: "The hearing type must match the phase: a `MASTER_CALENDAR` hearing is valid only while the case is `CALENDAR`, and an `INDIVIDUAL_MERITS` hearing only while the case is `MERITS`, with a mismatch drawing `ERR_HEARING_TYPE_STAGE_MISMATCH`."
    PRD §3.3: "A successful creation copies the case's `assigned_judge_id` onto the hearing's `judge_id`, marks the hearing `SCHEDULED` with `auto_created` false and `supersedes_hearing_id` null, and increments the case's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/merits_hearing_gated_on_case_merits_state
    """
    ctx = setup_docketed_case()
    # Completing the master hearing flips the case CALENDAR -> MERITS.
    advanced = advance_case_to_merits(ctx["case"], judge_id=ctx["judge"]["id"])
    assert advanced["case"]["status"] == "MERITS"
    # The identical creation that was rejected while CALENDAR now succeeds.
    hearing = schedule_hearing(
        advanced["case"], "INDIVIDUAL_MERITS", "2026-09-08T10:00:00Z"
    )
    assert hearing["status"] == "SCHEDULED"
    assert hearing["hearing_type"] == "INDIVIDUAL_MERITS"
    assert hearing["judge_id"] == ctx["judge"]["id"]


def test_appeal_rejected_against_remanded_decision(api, admin_headers):
    """PRD §3.6: "The decision must still be `ISSUED` (otherwise `ERR_DECISION_NOT_APPEALABLE`), and the clock must be at or before the decision's `appeal_deadline`: the 30-day window is inclusive, so a filing at exactly the deadline succeeds while one a second later fails with `ERR_APPEAL_WINDOW_EXPIRED`."

    Design: Difficulty/cross_entity_state_dependency/appeal_gated_on_decision_issued_state
    """
    # The first decision was appealed and REMANDED, so it is no longer ISSUED.
    # The clock (2026-09-04T12:00Z) is well inside its appeal window, leaving
    # the decision-posture gate as the only check that can fire.
    ctx = setup_remanded_case()
    resp = api.create_appeal(
        make_appeal_payload(ctx["decision"]["id"]), headers=admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_DECISION_NOT_APPEALABLE)
    assert read_decision(ctx["decision"]["id"])["status"] == "REMANDED"


def test_appeal_accepted_against_freshly_issued_decision(api, admin_headers):
    """PRD §3.6: "The decision must still be `ISSUED` (otherwise `ERR_DECISION_NOT_APPEALABLE`), and the clock must be at or before the decision's `appeal_deadline`: the 30-day window is inclusive, so a filing at exactly the deadline succeeds while one a second later fails with `ERR_APPEAL_WINDOW_EXPIRED`."
    PRD §3.6: "A filed appeal copies its `case_id` from the decision, records its `filed_at` at the clock, starts `FILED` with `decided_by_board_member_id` and `decided_at` null, moves the decision from `ISSUED` to `APPEAL_PENDING`, moves the case from its `DECIDED` or `IN_ABSENTIA` posture to `APPEALED`, and increments the case's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/appeal_gated_on_decision_issued_state
    """
    ctx = setup_remanded_case()
    judge_id = ctx["judge"]["id"]
    case_id = ctx["case"]["id"]
    # Re-decide the remanded case: complete the auto-created remand merits
    # hearing at its start (2026-10-16T12:00Z), then issue a fresh decision.
    set_clock("2026-10-16T12:00:00Z")
    complete_hearing(ctx["remand_hearing"], judge_id=judge_id)
    decision2 = issue_decision(read_case(case_id), "TERMINATION", judge_id=judge_id)
    assert decision2["status"] == "ISSUED"
    # The gate reopens with the fresh ISSUED decision: the appeal succeeds.
    resp = api.create_appeal(make_appeal_payload(decision2["id"]), headers=admin_headers)
    appeal2 = validate_success(resp, 201)
    assert appeal2["status"] == "FILED"
    assert appeal2["case_id"] == case_id
    assert read_decision(decision2["id"])["status"] == "APPEAL_PENDING"
    assert read_case(case_id)["status"] == "APPEALED"
