"""Non-linear state machines and transitive cascades.

Every test in this module translates exactly one instance of the §1.8 depth
index: the two `non_linear_state_machine` instances and the two
`transitive_cascade` instances.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    ASSIGNMENT_COMPLETED,
    ASSIGNMENT_ESCALATED,
    ASSIGNMENT_FAILED_ATTEMPT,
    ASSIGNMENT_IN_PROGRESS,
    COMPLIANCE_COMPLIANT,
    COMPLIANCE_DELINQUENT,
    CONSEQUENCE_ACTIVE,
    CONSEQUENCE_LIFTED,
    CONSEQUENCE_MFA_REVIEW,
    DELIVERY_CLICKED,
    EMPLOYMENT_ACTIVE,
    LIFT_REASON_MANUAL,
    NOTICE_SENT,
    OUTCOME_CLICKED_NO_REPORT,
    POSTURE_ELEVATED_REVIEW,
    POSTURE_NONE,
    TIER_1,
)
from test_helpers.assertions import (
    assert_assignment,
    assert_consequence,
    assert_delivery,
    assert_instant_equals,
    assert_instant_is_none,
    assert_notice,
    assert_risk_scores,
    assert_sweep_counters,
)
from test_helpers.fixtures import (
    approved_template,
    assign_module,
    click,
    create_published_module,
    delivery_for,
    list_consequences_for,
    list_notices_for,
    read_assignment,
    read_delivery,
    read_employee,
    register_employee,
    register_manager_and_report,
    reset_clock,
    run_sweep,
    running_campaign,
    set_clock,
)
from test_helpers.test_users import ADMIN, make_learner_headers


# --------------------------------------------------------------------------- #
# non_linear_state_machine                                                    #
# --------------------------------------------------------------------------- #


def _started_annual_assignment(api) -> dict:
    """One IN_PROGRESS annual assignment whose module passes at 80."""
    reset_clock(api)
    employee = register_employee(
        api, full_name="Lena Learner", department="SALES",
        role_code="IC", hire_date="2020-03-04",
    )
    module = create_published_module(
        api, code="ANNUAL-SEC-2026", title="Annual Security Awareness 2026",
        module_type="ANNUAL", passing_score_pct=80,
    )
    assignment = assign_module(api, employee, module, assignment_reason="ANNUAL")
    learner = make_learner_headers(employee["id"])
    validate_success(api.start_assignment(assignment["id"], learner))
    return {"employee": employee, "module": module,
            "assignment": assignment, "learner": learner}


def test_failed_attempt_and_retake_re_enter_a_state_already_occupied(api):
    """The loop leaves attempt_count and last_score_pct as its only witnesses.

    PRD §3.3: "From `FAILED_ATTEMPT`, retaking returns the assignment to
    `IN_PROGRESS` and again bumps only the assignment's `version`. That cycle —
    `IN_PROGRESS → FAILED_ATTEMPT → IN_PROGRESS` — may repeat without bound, and
    `attempt_count` is the only field that witnesses how many times it has
    happened."

    Design: Difficulty/non_linear_state_machine/assignment_cycles_in_progress_failed_attempt_and_back
    """
    ctx = _started_annual_assignment(api)

    failed = validate_success(
        api.submit_assignment(ctx["assignment"]["id"], {"score_pct": 55}, ctx["learner"])
    )
    assert_assignment(failed, state=ASSIGNMENT_FAILED_ATTEMPT,
                      attempt_count=1, last_score_pct=55)
    assert_instant_is_none(failed["completed_at"], "completed_at")

    retaken = validate_success(
        api.retake_assignment(ctx["assignment"]["id"], ctx["learner"])
    )
    assert_assignment(retaken, state=ASSIGNMENT_IN_PROGRESS,
                      attempt_count=1, last_score_pct=55)


def test_second_visit_to_in_progress_can_complete_the_assignment(api):
    """The passing submit from the re-entered state carries the loop's history.

    PRD §3.3: "The submission always sets `last_score_pct` to the supplied score
    and increments `attempt_count` by one."

    Design: Difficulty/non_linear_state_machine/assignment_cycles_in_progress_failed_attempt_and_back
    """
    ctx = _started_annual_assignment(api)
    validate_success(
        api.submit_assignment(ctx["assignment"]["id"], {"score_pct": 55}, ctx["learner"])
    )
    validate_success(api.retake_assignment(ctx["assignment"]["id"], ctx["learner"]))

    completed = validate_success(
        api.submit_assignment(ctx["assignment"]["id"], {"score_pct": 88}, ctx["learner"])
    )
    assert_assignment(completed, state=ASSIGNMENT_COMPLETED,
                      attempt_count=2, last_score_pct=88)
    assert_instant_equals(completed["completed_at"], "2026-08-01T00:00:00Z",
                          "completed_at")

    employee = read_employee(api, ctx["employee"]["id"])
    assert employee["compliance_state"] == COMPLIANCE_COMPLIANT
    assert_risk_scores(employee, provisional=0.00)

    validate_error(
        api.retake_assignment(ctx["assignment"]["id"], ctx["learner"]),
        ApiErrorId.ASSIGNMENT_STATE_INVALID.value,
    )


def _escalated_report_with_consequence(api) -> dict:
    """A direct report driven to ELEVATED_REVIEW / DELINQUENT by one sweep."""
    reset_clock(api)
    pair = register_manager_and_report(
        api, department="SALES", report_role_code="IC",
        report_hire_date="2019-06-06", manager_hire_date="2015-02-02",
    )
    module = create_published_module(
        api, code="ANNUAL-SEC-B", title="Annual Security Awareness B",
        module_type="ANNUAL",
    )
    assignment = assign_module(api, pair["report"], module, assignment_reason="ANNUAL")
    set_clock(api, "2026-09-08T00:00:00Z")
    sweep = run_sweep(api)
    consequences = list_consequences_for(api, pair["report"]["id"], state=CONSEQUENCE_ACTIVE)
    return {
        "manager": pair["manager"], "employee": pair["report"],
        "assignment": assignment, "sweep": sweep, "consequences": consequences,
    }


def test_three_employee_axes_hold_an_unorderable_combination(api):
    """Before the lift the three axes sit at three unrelated values.

    PRD §3.1: "An employee carries three state axes that move independently of
    one another, and conflating them is the single most common way to get this
    domain wrong."

    Design: Difficulty/non_linear_state_machine/employee_parallel_axes_move_independently
    """
    ctx = _escalated_report_with_consequence(api)

    employee = read_employee(api, ctx["employee"]["id"])
    assert employee["access_posture"] == POSTURE_ELEVATED_REVIEW
    assert employee["compliance_state"] == COMPLIANCE_DELINQUENT
    assert employee["employment_status"] == EMPLOYMENT_ACTIVE

    assert len(ctx["consequences"]) == 1
    assert_consequence(ctx["consequences"][0], state=CONSEQUENCE_ACTIVE,
                       consequence_type=CONSEQUENCE_MFA_REVIEW)


def test_lifting_the_consequence_moves_only_the_access_axis(api):
    """The access axis returns to NONE while compliance stays DELINQUENT.

    PRD §3.6: "On success the row becomes `LIFTED`, `lifted_at` is stamped with
    the clock, the employee's `access_posture` is recomputed as the posture
    matching the highest `severity_rank` among the rows that remain `ACTIVE`,
    `active_suspension_count` is recomputed, and both the consequence's `version`
    and the employee's `version` are bumped by one."

    Design: Difficulty/non_linear_state_machine/employee_parallel_axes_move_independently
    """
    ctx = _escalated_report_with_consequence(api)
    consequence_id = ctx["consequences"][0]["id"]

    lifted = validate_success(
        api.lift_access_consequence(
            consequence_id, {"lift_reason_code": LIFT_REASON_MANUAL}, ADMIN)
    )
    assert_consequence(lifted, state=CONSEQUENCE_LIFTED,
                       lift_reason_code=LIFT_REASON_MANUAL)
    assert_instant_equals(lifted["lifted_at"], "2026-09-08T00:00:00Z", "lifted_at")

    employee = read_employee(api, ctx["employee"]["id"])
    assert employee["access_posture"] == POSTURE_NONE
    assert employee["compliance_state"] == COMPLIANCE_DELINQUENT
    assert employee["employment_status"] == EMPLOYMENT_ACTIVE
    assert employee["active_suspension_count"] == 0
    assert_risk_scores(employee, provisional=8.00)

    assignment = read_assignment(api, ctx["assignment"]["id"])
    assert_assignment(assignment, state=ASSIGNMENT_ESCALATED, escalation_level=2)


# --------------------------------------------------------------------------- #
# transitive_cascade                                                          #
# --------------------------------------------------------------------------- #


def _sweep_at_eight_days_overdue(api) -> dict:
    """An IT report eight days past an annual deadline, swept exactly once."""
    reset_clock(api)
    pair = register_manager_and_report(
        api, department="IT", report_role_code="IT_ADMIN",
        report_hire_date="2017-07-07", manager_hire_date="2014-04-04",
    )
    module = create_published_module(
        api, code="ANNUAL-SEC-C", title="Annual Security Awareness C",
        module_type="ANNUAL",
    )
    assignment = assign_module(api, pair["report"], module, assignment_reason="ANNUAL")
    set_clock(api, "2026-09-08T00:00:00Z")
    sweep = run_sweep(api)
    return {"manager": pair["manager"], "employee": pair["report"],
            "assignment": assignment, "sweep": sweep}


def test_sweep_walks_every_rung_and_emits_one_notice_per_rung(api):
    """Hops 1 and 2: the ladder fires rungs 1 and 2 in one sweep.

    PRD §3.4: "Crucially, the sweep does **not** advance one rung at a time — it
    walks every rung from one above the current `escalation_level` up to and
    including the target rung, in ascending order, firing the full cascade for
    each."

    Design: Difficulty/transitive_cascade/sweep_cascade_overdue_to_notice_to_consequence_to_posture
    """
    ctx = _sweep_at_eight_days_overdue(api)

    assignment = read_assignment(api, ctx["assignment"]["id"])
    assert_assignment(assignment, state=ASSIGNMENT_ESCALATED,
                      days_overdue=8, escalation_level=2)

    notices = list_notices_for(api, ctx["assignment"]["id"])
    assert len(notices) == 2, "one notice per newly reached rung"
    by_level = {notice["level"]: notice for notice in notices}
    assert sorted(by_level) == [1, 2]
    for level, notice in by_level.items():
        assert_notice(notice, state=NOTICE_SENT, level=level)
        assert notice["manager_id"] == ctx["manager"]["id"]
        assert_instant_equals(notice["sent_at"], "2026-09-08T00:00:00Z", "sent_at")
        assert notice["assignment_id"] == ctx["assignment"]["id"]


def test_only_the_level_two_rung_reaches_the_consequence_and_posture_hops(api):
    """Hops 3 and 4: the rung-1 notice applies nothing, the rung-2 notice does.

    PRD §3.4: "**Hop 3** applies an access consequence — but **only for notices
    whose `level` is 2 or higher**. A rung-1 escalation is notify-only: it
    produces a notice and nothing more, leaving `access_posture` at whatever it
    already was."

    Design: Difficulty/transitive_cascade/sweep_cascade_overdue_to_notice_to_consequence_to_posture
    """
    ctx = _sweep_at_eight_days_overdue(api)

    consequences = validate_success(
        api.list_access_consequences(
            {"source_assignment_id": ctx["assignment"]["id"],
             "state": CONSEQUENCE_ACTIVE}, ADMIN)
    )
    assert len(consequences) == 1, "the level-1 notice applied no consequence"
    assert_consequence(consequences[0], state=CONSEQUENCE_ACTIVE,
                       consequence_type=CONSEQUENCE_MFA_REVIEW, severity_rank=2)
    assert_instant_equals(consequences[0]["applied_at"], "2026-09-08T00:00:00Z",
                          "applied_at")

    employee = read_employee(api, ctx["employee"]["id"])
    assert employee["access_posture"] == POSTURE_ELEVATED_REVIEW
    assert employee["active_suspension_count"] == 0
    assert employee["compliance_state"] == COMPLIANCE_DELINQUENT
    assert_risk_scores(employee, provisional=8.00, settled=8.00)

    assert_sweep_counters(ctx["sweep"], escalations_created_count=2,
                          consequences_applied_count=1)


def _second_click_opens_an_intervention(api) -> dict:
    """One FINANCE employee clicking two separate simulation waves."""
    reset_clock(api)
    employee = register_employee(
        api, full_name="Rick Clicker", department="FINANCE",
        role_code="FINANCE_APPROVER", hire_date="2016-06-06",
    )
    template = approved_template(
        api, name="Invoice Approval Needed", pretext_category="INVOICE_APPROVAL",
        difficulty_tier=TIER_1, theme_tags=["URGENCY"],
        credential_capture_enabled=False,
    )
    first = running_campaign(
        api, scheduled_send_at="2026-08-02T09:00:00Z", template=template,
        name="FIN Wave 1", difficulty_tier=TIER_1, target_departments=["FINANCE"],
    )
    first_delivery = delivery_for(api, first["campaign"]["id"], employee["id"])
    click(api, first_delivery["id"], "2026-08-02T09:30:00Z")

    second = running_campaign(
        api, scheduled_send_at="2026-08-08T09:00:00Z", template=template,
        name="FIN Wave 2", difficulty_tier=TIER_1, target_departments=["FINANCE"],
    )
    second_delivery = delivery_for(api, second["campaign"]["id"], employee["id"])
    set_clock(api, "2026-08-08T10:00:00Z")
    event = validate_success(
        api.append_interaction(
            second_delivery["id"],
            {"event_type": "CLICK", "occurred_at": "2026-08-08T10:00:00Z",
             "source": "LANDING_PAGE"},
            ADMIN,
        ),
        expected_status=201,
    )
    return {"employee": employee, "first_delivery": first_delivery,
            "second_delivery": second_delivery, "event": event}


def test_click_event_records_itself_and_moves_the_delivery(api):
    """Levels 1 and 2 of the cascade: the event row and the delivery transition.

    PRD §3.9: "A `CLICK` on a `DELIVERED` delivery moves `DELIVERED → CLICKED`,
    setting `first_click_at` to the event's `occurred_at` and `outcome_class` to
    `CLICKED_NO_REPORT`."

    Design: Difficulty/transitive_cascade/interaction_cascade_click_to_delivery_to_tier_to_intervention
    """
    ctx = _second_click_opens_an_intervention(api)

    assert ctx["event"]["event_type"] == "CLICK"
    assert ctx["event"]["sequence_index"] == 1, "the first event on that delivery"
    assert ctx["event"]["delivery_id"] == ctx["second_delivery"]["id"]
    assert_instant_equals(ctx["event"]["occurred_at"], "2026-08-08T10:00:00Z",
                          "occurred_at")

    delivery = read_delivery(api, ctx["second_delivery"]["id"])
    assert_delivery(delivery, state=DELIVERY_CLICKED,
                    outcome_class=OUTCOME_CLICKED_NO_REPORT)
    assert_instant_equals(delivery["first_click_at"], "2026-08-08T10:00:00Z",
                          "first_click_at")
    assert delivery["time_to_report_minutes"] is None


def test_click_cascade_reaches_the_tier_and_opens_one_intervention(api):
    """Levels 3 and 4: the rolling tier recomputation and the intervention.

    PRD §3.10: "It normally opens in state `OPEN` — but a tier of exactly 3 at
    the moment of opening puts it straight into `ESCALATED_TO_MANAGER` instead."

    Design: Difficulty/transitive_cascade/interaction_cascade_click_to_delivery_to_tier_to_intervention
    """
    ctx = _second_click_opens_an_intervention(api)

    employee = read_employee(api, ctx["employee"]["id"])
    assert employee["repeat_clicker_tier"] == 2, "two failures inside the window"
    assert employee["consecutive_clean_simulations"] == 0
    assert_risk_scores(employee, provisional=24.00, settled=0.00)

    interventions = validate_success(
        api.list_interventions(
            {"employee_id": ctx["employee"]["id"],
             "triggering_delivery_id": ctx["second_delivery"]["id"]}, ADMIN)
    )
    assert len(interventions) == 1
    intervention = interventions[0]
    assert intervention["state"] == "OPEN"
    assert intervention["tier_at_open"] == 2
    assert intervention["current_tier"] == 2
    assert intervention["simulation_frequency_days"] == 30
    assert_instant_equals(intervention["opened_at"], "2026-08-08T10:00:00Z",
                          "opened_at")

    assert_delivery(read_delivery(api, ctx["first_delivery"]["id"]),
                    state=DELIVERY_CLICKED)
