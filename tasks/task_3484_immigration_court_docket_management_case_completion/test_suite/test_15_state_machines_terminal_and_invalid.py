"""State-machine probes: terminal lockdown and invalid repeated transitions.

A COMPLETED case rejects every further case-targeted mutation outright; a
FINAL decision rejects a new appeal on state alone even inside the still-open
appeal window; a COMPLETED hearing and a DEFECTIVE notice are each terminal
for their own re-trigger operations.
"""

from test_helpers import (
    ApiErrorId,
    case_version,
    create_court,
    get_success_data,
    make_appeal_payload,
    make_closure_payload,
    make_hearing_payload,
    make_judge_headers,
    make_venue_motion_payload,
    read_case,
    read_decision,
    read_hearing,
    same_instant,
    schedule_hearing,
    serve_notice,
    set_clock,
    setup_completed_case,
    setup_docketed_case,
    validate_error,
    validate_success,
    MASTER_HEARING_CLOCK_ISO,
    MASTER_HEARING_START_ISO,
    MERITS_HEARING_CLOCK_ISO,
)


def test_completed_case_rejects_further_mutations(api, admin_headers):
    """PRD §3.2: "any mutation attempted against a case that has reached `COMPLETED` is rejected outright with `ERR_CASE_ALREADY_TERMINAL`, whatever the operation."
    PRD §3.6: "`AFFIRMED` and `DISMISSED` are symmetrical endings: the decision becomes `FINAL`, the case becomes `COMPLETED` with `completed_at` set to the clock, and the case's `version` increments by 1."

    Design: Corner/state_machines/completed_case_rejects_further_mutations
    """
    ctx = setup_completed_case(ruling="AFFIRMED")
    case_id = ctx["case"]["id"]
    judge_id = ctx["judge"]["id"]

    # Hearing creation against the COMPLETED case — with a fresh, correct
    # expected_case_version so only the terminality gate can fire.
    resp = api.create_hearing(
        make_hearing_payload(
            case_id, "MASTER_CALENDAR", "2026-09-10T10:00:00Z", case_version(case_id)
        ),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CASE_ALREADY_TERMINAL)

    # Change-of-venue motion filing against the COMPLETED case.
    dest = create_court()
    resp = api.create_venue_motion(
        make_venue_motion_payload(case_id, dest["id"], "forum convenience"),
        headers=admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CASE_ALREADY_TERMINAL)

    # Direct administrative closure against the COMPLETED case.
    resp = api.administrative_closure(
        case_id,
        make_closure_payload("OTHER"),
        headers=make_judge_headers(judge_id),
    )
    validate_error(resp, ApiErrorId.ERR_CASE_ALREADY_TERMINAL)

    # Nothing moved: the case, its FINAL decision, and its AFFIRMED appeal
    # are all untouched by the rejected mutations.
    case = read_case(case_id)
    assert case["status"] == "COMPLETED"
    assert same_instant(case["completed_at"], MERITS_HEARING_CLOCK_ISO), (
        "completed_at stays stamped at the affirmation clock 2026-09-04T12:00:00Z"
    )
    assert read_decision(ctx["decision"]["id"])["status"] == "FINAL"
    appeal = get_success_data(api.get_appeal(ctx["appeal"]["id"], headers=admin_headers))
    assert appeal["status"] == "AFFIRMED"


def test_final_decision_rejects_late_appeal_attempt(api, admin_headers):
    """PRD §3.6: "The decision must still be `ISSUED` (otherwise `ERR_DECISION_NOT_APPEALABLE`), and the clock must be at or before the decision's `appeal_deadline`: the 30-day window is inclusive, so a filing at exactly the deadline succeeds while one a second later fails with `ERR_APPEAL_WINDOW_EXPIRED`."

    Design: Corner/state_machines/final_decision_rejects_late_appeal_attempt
    """
    # The case completed by affirmation at 2026-09-04T12:00:00Z; the clock
    # still sits inside the decision's original appeal window (deadline
    # 2026-10-04T12:00:00Z), so the decision's FINAL state alone rejects.
    ctx = setup_completed_case(ruling="AFFIRMED")
    assert ctx["decision"]["status"] == "FINAL"

    resp = api.create_appeal(
        make_appeal_payload(ctx["decision"]["id"]),
        headers=admin_headers,
    )
    # Asserting the exact error id also proves it is not
    # ERR_APPEAL_WINDOW_EXPIRED — the window is still open here.
    validate_error(resp, ApiErrorId.ERR_DECISION_NOT_APPEALABLE)

    assert read_decision(ctx["decision"]["id"])["status"] == "FINAL"


def test_hearing_complete_twice_rejected(api, admin_headers):
    """PRD §3.4: "Completing a hearing requires it to be `SCHEDULED` (otherwise `ERR_HEARING_NOT_SCHEDULED`), requires the clock to have reached its `scheduled_start` (earlier attempts fail with `ERR_HEARING_NOT_YET_DUE`), and requires the caller to be the hearing's own judge — `X-User-ID` equal to the hearing's `judge_id`, otherwise `ERR_NOT_HEARING_JUDGE`. Completion moves the hearing `SCHEDULED → COMPLETED`, and when the completed hearing was a master-calendar hearing of a `CALENDAR` case, the case itself advances `CALENDAR → MERITS` with its `version` incremented by 1. That master-calendar completion is the only path into the merits phase."

    Design: Corner/state_machines/hearing_complete_twice_rejected
    """
    ctx = setup_docketed_case()
    judge_id = ctx["judge"]["id"]
    hearing = schedule_hearing(ctx["case"], "MASTER_CALENDAR", MASTER_HEARING_START_ISO)
    set_clock(MASTER_HEARING_CLOCK_ISO)

    # First completion: 200, hearing COMPLETED, case advanced CALENDAR -> MERITS.
    resp = api.complete_hearing(
        hearing["id"], headers=make_judge_headers(judge_id)
    )
    completed = validate_success(resp, expected_status=200)
    assert completed["status"] == "COMPLETED"
    case_id = ctx["case"]["id"]
    assert read_case(case_id)["status"] == "MERITS"

    # Second completion against the now-terminal hearing: 409.
    resp = api.complete_hearing(
        hearing["id"], headers=make_judge_headers(judge_id)
    )
    validate_error(resp, ApiErrorId.ERR_HEARING_NOT_SCHEDULED)

    # The case-advance side effect did not re-fire.
    assert read_case(case_id)["status"] == "MERITS"
    assert read_hearing(hearing["id"])["status"] == "COMPLETED"


def test_notice_mark_defective_twice_rejected(api, admin_headers):
    """PRD §3.4: "If service later proves defective (a wrong address discovered, for instance), the administrator may mark the notice defective; a notice already `DEFECTIVE` rejects a repeated marking with `ERR_NOTICE_ALREADY_DEFECTIVE`."

    Design: Corner/state_machines/notice_mark_defective_twice_rejected
    """
    ctx = setup_docketed_case()
    hearing = schedule_hearing(ctx["case"], "MASTER_CALENDAR", MASTER_HEARING_START_ISO)
    notice = serve_notice(hearing["id"])
    assert notice["status"] == "SERVED"

    resp = api.mark_notice_defective(notice["id"], headers=admin_headers)
    marked = validate_success(resp, expected_status=200)
    assert marked["status"] == "DEFECTIVE"

    # DEFECTIVE is terminal for the notice: the repeated marking is rejected.
    resp = api.mark_notice_defective(notice["id"], headers=admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOTICE_ALREADY_DEFECTIVE)
