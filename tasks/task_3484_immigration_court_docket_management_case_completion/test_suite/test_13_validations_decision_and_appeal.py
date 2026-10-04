"""Validation probes: decision issuance, appeal rulings, closure, recalendar.

Decision issuance checks ownership before readiness and the case phase before
the completed-merits-hearing prerequisite; the in absentia outcome is
system-only; a REMANDED ruling without instructions is a 422 while the appeal
stands FILED; a decided appeal is terminal; recalendar is gated to
ADMIN_CLOSED and administrative closure to CALENDAR or MERITS.
"""

from test_helpers import (
    ApiErrorId,
    MERITS_HEARING_CLOCK_ISO,
    MERITS_HEARING_START_ISO,
    advance_case_to_merits,
    assert_decision,
    case_version,
    complete_hearing,
    create_judge,
    decide_appeal,
    get_success_data,
    list_case_decisions,
    make_appeal_ruling_payload,
    make_closure_payload,
    make_decision_payload,
    make_judge_headers,
    read_case,
    read_decision,
    schedule_hearing,
    set_clock,
    setup_appealed_case,
    setup_case_in_absentia,
    setup_completed_case,
    setup_docketed_case,
    validate_error,
    validate_success,
)


def test_decision_issuance_ownership_precedes_merits_hearing_readiness(api):
    """PRD §3.6: "Issuance requires the case to be `MERITS` (otherwise `ERR_CASE_NOT_IN_MERITS`), requires at least one `COMPLETED` individual-merits hearing to exist for the case (otherwise `ERR_NO_COMPLETED_MERITS_HEARING`), and binds the caller to the case's `assigned_judge_id` (`ERR_NOT_ASSIGNED_JUDGE`); per §2.6 the case's own phase is evaluated before the completed-merits-hearing prerequisite."
    PRD §2.6: "4. **Role-entity ownership (HTTP 403).** Judge-scoped actions bind the caller to the record: `ERR_NOT_ASSIGNED_JUDGE` when the case's `assigned_judge_id` differs from `X-User-ID`, and `ERR_NOT_HEARING_JUDGE` when the hearing's `judge_id` differs from it."

    Design: Corner/validations/decision_issuance_guards
    """
    ctx = setup_docketed_case()
    other_judge = create_judge(ctx["court"]["id"], full_name="Judge Other")
    advance_case_to_merits(ctx["case"], judge_id=ctx["judge"]["id"])
    case_id = ctx["case"]["id"]
    version = case_version(case_id)

    # The case is MERITS but holds no completed merits hearing, so the
    # readiness gate would fail — yet the unassigned judge is rejected at the
    # earlier ownership tier (4) before any tier-5 state check runs.
    resp = api.create_decision(
        make_decision_payload(case_id, "REMOVAL", version),
        headers=make_judge_headers(other_judge["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_JUDGE)

    # The assigned judge passes ownership and hits the readiness gate.
    resp = api.create_decision(
        make_decision_payload(case_id, "REMOVAL", version),
        headers=make_judge_headers(ctx["judge"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NO_COMPLETED_MERITS_HEARING)

    assert list_case_decisions(case_id) == [], "rejected issuance wrote no decision"


def test_decision_requires_merits_state(api):
    """PRD §3.6: "Issuance requires the case to be `MERITS` (otherwise `ERR_CASE_NOT_IN_MERITS`), requires at least one `COMPLETED` individual-merits hearing to exist for the case (otherwise `ERR_NO_COMPLETED_MERITS_HEARING`), and binds the caller to the case's `assigned_judge_id` (`ERR_NOT_ASSIGNED_JUDGE`); per §2.6 the case's own phase is evaluated before the completed-merits-hearing prerequisite."

    Design: Corner/validations/decision_requires_merits_state
    """
    ctx = setup_docketed_case()
    case_id = ctx["case"]["id"]
    # The caller is the assigned judge (ownership passes), the case is
    # CALENDAR, and no hearing of any kind exists — the phase gate fires first.
    resp = api.create_decision(
        make_decision_payload(case_id, "REMOVAL", case_version(case_id)),
        headers=make_judge_headers(ctx["judge"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_IN_MERITS)
    assert list_case_decisions(case_id) == []


def test_in_absentia_outcome_cannot_be_posted_directly(api):
    """PRD §3.6: "The fourth, `IN_ABSENTIA_REMOVAL`, is system-only — it enters the system exclusively through the §3.5 no-show cascade, and supplying it to the judge-issued decision operation is rejected with `ERR_IN_ABSENTIA_OUTCOME_NOT_CREATABLE` (HTTP 422). Correspondingly, a judge-issued decision's `source_hearing_id` is always null."
    PRD §3.6: "A judge-issued decision is born `ISSUED`, with `issued_at` at the clock, an `appeal_deadline` exactly 30 days later, and `reopen_deadline` null."
    PRD §3.5: "That `reopen_deadline` is set only on `IN_ABSENTIA_REMOVAL` decisions; every other decision carries it as null."

    Design: Corner/validations/in_absentia_outcome_cannot_be_posted_directly
    """
    ctx = setup_docketed_case()
    progressed = advance_case_to_merits(ctx["case"], judge_id=ctx["judge"]["id"])
    merits = schedule_hearing(
        progressed["case"], "INDIVIDUAL_MERITS", MERITS_HEARING_START_ISO
    )
    set_clock(MERITS_HEARING_CLOCK_ISO)
    complete_hearing(merits, judge_id=ctx["judge"]["id"])
    case_id = ctx["case"]["id"]
    version = case_version(case_id)

    # The system-only outcome is rejected even for the assigned judge on a
    # decision-ready case (the rejection writes nothing, so the version holds).
    resp = api.create_decision(
        make_decision_payload(case_id, "IN_ABSENTIA_REMOVAL", version),
        headers=make_judge_headers(ctx["judge"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_IN_ABSENTIA_OUTCOME_NOT_CREATABLE)

    # A judge-creatable outcome on the same case succeeds.
    resp = api.create_decision(
        make_decision_payload(case_id, "TERMINATION", version),
        headers=make_judge_headers(ctx["judge"]["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert_decision(data)
    assert data["status"] == "ISSUED"
    assert data["source_hearing_id"] is None
    assert data["reopen_deadline"] is None


def test_remand_without_instructions_rejected_then_affirm_succeeds(
    api, admin_headers, board_headers
):
    """PRD §3.6: "`REMANDED` instead returns the case for further proceedings: it requires `remand_instructions` to accompany the ruling (omitting them is `ERR_REMAND_INSTRUCTIONS_REQUIRED`, HTTP 422), records those instructions on the appeal, moves the decision to `REMANDED`, returns the case `APPEALED → MERITS`, increments its `version` by 1, and auto-creates the remand hearing — an `INDIVIDUAL_MERITS` hearing 42 days out from the clock, `auto_created` true, the case's assigned judge presiding, the interpreter re-selected, and the candidate slot advanced a day at a time until the scheduling checks of §3.3 pass."
    PRD §3.6: "`AFFIRMED` and `DISMISSED` are symmetrical endings: the decision becomes `FINAL`, the case becomes `COMPLETED` with `completed_at` set to the clock, and the case's `version` increments by 1."

    Design: Corner/validations/remand_without_instructions_returns_422
    """
    ctx = setup_appealed_case()
    appeal_id = ctx["appeal"]["id"]

    # A REMANDED ruling without remand_instructions is rejected.
    resp = api.decide_appeal(
        appeal_id, make_appeal_ruling_payload("REMANDED"), headers=board_headers
    )
    validate_error(resp, ApiErrorId.ERR_REMAND_INSTRUCTIONS_REQUIRED)

    # The rejected ruling wrote nothing: the appeal still stands FILED...
    pending = get_success_data(api.get_appeal(appeal_id, headers=admin_headers))
    assert pending["status"] == "FILED"

    # ...so a subsequent AFFIRMED ruling succeeds and ends the case.
    appeal = decide_appeal(appeal_id, "AFFIRMED")
    assert appeal["status"] == "AFFIRMED"
    assert read_case(ctx["case"]["id"])["status"] == "COMPLETED"
    assert read_decision(ctx["decision"]["id"])["status"] == "FINAL"


def test_appeal_decide_twice_rejected(api, admin_headers, board_headers):
    """PRD §3.6: "The appeal must still be `FILED` — ruling twice is `ERR_APPEAL_ALREADY_DECIDED` — and the ruling stamps `decided_by_board_member_id` with the acting member's `X-User-ID` and `decided_at` with the clock."
    PRD §2.6: "Two ordering rules apply within this tier. First, the acting entity's own phase is checked before gates that look past it — on decision issuance, for example, whether the case is `MERITS` is evaluated before whether a completed merits hearing exists."

    Design: Corner/validations/appeal_decide_twice_rejected
    """
    ctx = setup_completed_case(ruling="AFFIRMED")
    appeal_id = ctx["appeal"]["id"]

    # The appeal's own posture gate (it stands AFFIRMED) is checked before the
    # gate that looks past it to the now-COMPLETED case.
    resp = api.decide_appeal(
        appeal_id, make_appeal_ruling_payload("DISMISSED"), headers=board_headers
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_ALREADY_DECIDED)

    after = get_success_data(api.get_appeal(appeal_id, headers=admin_headers))
    assert after["status"] == "AFFIRMED"


def test_recalendar_requires_admin_closed_case(api):
    """PRD §3.4: "The assigned judge may later recalendar the case, an operation that requires the case to be `ADMIN_CLOSED` (otherwise `ERR_CASE_NOT_ADMIN_CLOSED`), requires the same ownership binding, and returns the case `ADMIN_CLOSED → MERITS`, incrementing `version` once more."

    Design: Corner/validations/recalendar_requires_admin_closed
    """
    ctx = setup_docketed_case()
    # The caller is the assigned judge (ownership passes) but the case is
    # CALENDAR, not ADMIN_CLOSED.
    resp = api.recalendar_case(
        ctx["case"]["id"], headers=make_judge_headers(ctx["judge"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_ADMIN_CLOSED)
    assert read_case(ctx["case"]["id"])["status"] == "CALENDAR"


def test_closure_requires_calendar_or_merits_case(api):
    """PRD §3.4: "The direct administrative-closure operation takes a `closure_reason` and requires the case to be `CALENDAR` or `MERITS` (otherwise `ERR_CASE_STATE_FORBIDS_CLOSURE`) and the caller to be the assigned judge (`ERR_NOT_ASSIGNED_JUDGE`)."
    PRD §3.5: "The case — whether it stood at `CALENDAR` or at `MERITS` — moves to `IN_ABSENTIA`, retaining its `assigned_judge_id`, and its `version` increments by 1."

    Design: Corner/validations/closure_requires_calendar_or_merits
    """
    ctx = setup_case_in_absentia()
    # The in absentia case retains its assigned judge, so the ownership gate
    # passes and the posture gate is the one that fires.
    resp = api.administrative_closure(
        ctx["case"]["id"],
        make_closure_payload("OTHER"),
        headers=make_judge_headers(ctx["judge"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CASE_STATE_FORBIDS_CLOSURE)
    assert read_case(ctx["case"]["id"])["status"] == "IN_ABSENTIA"
