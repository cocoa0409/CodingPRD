"""Cross-entity state gates, temporal overlaps and compensating invariants.

Every test in this module translates exactly one instance of the §1.8 depth
index: the two `cross_entity_state_dependency` instances, the two
`resource_temporal_overlap` instances and the two `compensating_invariant`
instances.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    ASSIGNMENT_ASSIGNED,
    ASSIGNMENT_ESCALATED,
    ASSIGNMENT_VOIDED,
    CAMPAIGN_APPROVED,
    CAMPAIGN_CANCELLED,
    CAMPAIGN_IN_REVIEW,
    CAMPAIGN_SCHEDULED,
    COMPLIANCE_COMPLIANT,
    CONSEQUENCE_ACTIVE,
    CONSEQUENCE_MFA_REVIEW,
    CONSEQUENCE_SUSPENSION,
    CONSEQUENCE_VOIDED,
    DELIVERY_EXCLUDED,
    DELIVERY_QUEUED,
    EXCLUDED_REASON_CAMPAIGN_CANCELLED,
    LIFT_REASON_ASSIGNMENT_VOIDED,
    MODULE_RETIRED,
    NOTICE_EXPIRED,
    NOTICE_SENT,
    POSTURE_NONE,
    POSTURE_SUSPENDED,
    TEMPLATE_APPROVED_FOR_USE,
    TEMPLATE_DRAFT,
    TIER_1,
    TIER_2,
)
from test_helpers.assertions import (
    assert_assignment,
    assert_consequence,
    assert_delivery,
    assert_instant_equals,
    assert_instant_is_none,
    assert_notice,
    assert_risk_scores,
)
from test_helpers.factories import schedule_payload
from test_helpers.fixtures import (
    approved_campaign,
    approved_template,
    assign_module,
    create_campaign,
    create_published_module,
    create_template,
    declare_window,
    delivery_for,
    list_consequences_for,
    list_deliveries,
    list_notices_for,
    read_assignment,
    read_delivery,
    read_employee,
    register_employee,
    register_manager_and_report,
    reset_clock,
    run_sweep,
    running_campaign,
    scheduled_campaign,
    set_clock,
)
from test_helpers.test_users import (
    ADMIN,
    APPROVER,
    APPROVER_1_ID,
    AUTHOR,
    make_learner_headers,
)


# --------------------------------------------------------------------------- #
# cross_entity_state_dependency                                               #
# --------------------------------------------------------------------------- #


def _assignment_whose_module_was_retired(api) -> dict:
    """An ASSIGNED role-specific assignment whose module has since been retired."""
    reset_clock(api)
    employee = register_employee(
        api, full_name="Fay Finance", department="FINANCE",
        role_code="FINANCE_APPROVER", hire_date="2016-04-04",
    )
    module = create_published_module(
        api, code="ROLE-WIRE-FRAUD", title="Wire Fraud Controls",
        module_type="ROLE_SPECIFIC", applies_to_role_codes=["FINANCE_APPROVER"],
    )
    assignment = assign_module(api, employee, module, assignment_reason="ROLE_CHANGE")
    set_clock(api, "2026-08-03T00:00:00Z")
    retired = validate_success(api.retire_module(module["id"], ADMIN))
    return {"employee": employee, "module": retired, "assignment": assignment,
            "learner": make_learner_headers(employee["id"])}


def test_start_reads_the_module_status_and_refuses_a_retired_module(api):
    """The assignment is legal to start; the foreign module's state forbids it.

    PRD §3.3: "All three also require the referenced module's `status` to still be
    `PUBLISHED`; a module retired since the assignment was raised makes the
    assignment unstartable and yields `ERR_MODULE_RETIRED`."

    Design: Difficulty/cross_entity_state_dependency/assignment_start_blocked_by_retired_module_returns_409
    """
    ctx = _assignment_whose_module_was_retired(api)
    assert ctx["module"]["status"] == MODULE_RETIRED
    assert_instant_equals(ctx["module"]["retired_at"], "2026-08-03T00:00:00Z",
                          "retired_at")

    error = validate_error(
        api.start_assignment(ctx["assignment"]["id"], ctx["learner"]),
        ApiErrorId.MODULE_RETIRED.value,
        expected_status=409,
    )
    assert error["error_id"] != ApiErrorId.ASSIGNMENT_STATE_INVALID.value


def test_retirement_leaves_the_existing_assignment_exactly_as_it_was(api):
    """Retirement blocks the action without rewriting the dependent row.

    PRD §3.2: "Retirement does not touch existing assignments — they survive
    untouched in whatever state they hold, but they become unstartable, and any
    attempt to start or retake one is refused with `ERR_MODULE_RETIRED`."

    Design: Difficulty/cross_entity_state_dependency/assignment_start_blocked_by_retired_module_returns_409
    """
    ctx = _assignment_whose_module_was_retired(api)
    validate_error(
        api.start_assignment(ctx["assignment"]["id"], ctx["learner"]),
        ApiErrorId.MODULE_RETIRED.value,
    )

    assignment = read_assignment(api, ctx["assignment"]["id"])
    assert_assignment(assignment, state=ASSIGNMENT_ASSIGNED, attempt_count=0)
    assert assignment["version"] == ctx["assignment"]["version"]
    assert_instant_equals(assignment["effective_due_at"], "2026-08-22T00:00:00Z",
                          "effective_due_at")

    employee = read_employee(api, ctx["employee"]["id"])
    assert employee["compliance_state"] == COMPLIANCE_COMPLIANT


def _campaign_over_a_draft_template(api) -> dict:
    """An IN_REVIEW campaign whose safe-themed template is still DRAFT."""
    reset_clock(api)
    register_employee(
        api, full_name="Ivan IT", department="IT",
        role_code="IT_ADMIN", hire_date="2015-05-05",
    )
    template = create_template(
        api, name="Password Expiry Reminder",
        pretext_category="IT_PASSWORD_RESET", difficulty_tier=TIER_2,
        theme_tags=["URGENCY", "AUTHORITY"], credential_capture_enabled=False,
    )
    assert template["review_state"] == TEMPLATE_DRAFT
    assert template["harmful_flag_hits"] == []
    campaign = create_campaign(
        api, template["id"], AUTHOR, name="IT Password Wave",
        difficulty_tier=TIER_2, target_departments=["IT"],
    )
    in_review = validate_success(api.submit_campaign_for_review(campaign["id"], AUTHOR))
    return {"template": template, "campaign": in_review}


def test_campaign_approval_reads_the_template_review_state(api):
    """The campaign is in the right state; the referenced template is not.

    PRD §3.7: "third, the template's `review_state` must be exactly
    `APPROVED_FOR_USE`, or the request is refused with `ERR_TEMPLATE_NOT_APPROVED`
    (HTTP 409) — which is what a `DRAFT` or `BLOCKED` template yields."

    Design: Difficulty/cross_entity_state_dependency/campaign_approve_blocked_by_draft_template_returns_409
    """
    ctx = _campaign_over_a_draft_template(api)

    error = validate_error(
        api.approve_campaign(ctx["campaign"]["id"], APPROVER),
        ApiErrorId.TEMPLATE_NOT_APPROVED.value,
        expected_status=409,
    )
    assert error["error_id"] != ApiErrorId.HARMFUL_PRETEXT_THEME.value
    assert error["error_id"] != ApiErrorId.SEGREGATION_OF_DUTIES_VIOLATION.value

    campaign = validate_success(api.get_campaign(ctx["campaign"]["id"], ADMIN))
    assert campaign["state"] == CAMPAIGN_IN_REVIEW
    assert campaign["reviewer_user_id"] is None


def test_approving_the_template_unblocks_the_identical_campaign_approval(api):
    """Only the foreign row's state was missing; nothing about the campaign changed.

    PRD §3.7: "**Approval** moves `IN_REVIEW → APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/campaign_approve_blocked_by_draft_template_returns_409
    """
    ctx = _campaign_over_a_draft_template(api)
    validate_error(
        api.approve_campaign(ctx["campaign"]["id"], APPROVER),
        ApiErrorId.TEMPLATE_NOT_APPROVED.value,
    )

    template = validate_success(
        api.approve_template_for_use(ctx["template"]["id"], APPROVER))
    assert template["review_state"] == TEMPLATE_APPROVED_FOR_USE

    approved = validate_success(
        api.approve_campaign(ctx["campaign"]["id"], APPROVER))
    assert approved["state"] == CAMPAIGN_APPROVED
    assert approved["reviewer_user_id"] == APPROVER_1_ID
    assert approved["version"] == ctx["campaign"]["version"] + 1


# --------------------------------------------------------------------------- #
# resource_temporal_overlap                                                   #
# --------------------------------------------------------------------------- #


def _approved_campaign_against_a_scoped_blackout(api) -> dict:
    """A SALES campaign facing a SALES-scoped blackout closing 2026-08-12T00:00Z."""
    reset_clock(api)
    employee = register_employee(
        api, full_name="Sara Sales", department="SALES",
        role_code="IC", hire_date="2018-02-02",
    )
    declare_window(
        api, "2026-08-10T00:00:00Z", "2026-08-12T00:00:00Z",
        reason="Sales kickoff week", scope_department="SALES",
    )
    ctx = approved_campaign(
        api, name="SALES Doc Wave", difficulty_tier=TIER_1,
        target_departments=["SALES"],
        template_overrides={
            "name": "Shared Deal Document",
            "pretext_category": "SHARED_DOCUMENT",
            "difficulty_tier": TIER_1,
            "theme_tags": ["CURIOSITY"],
            "credential_capture_enabled": False,
        },
    )
    ctx["employee"] = employee
    return ctx


def test_blackout_upper_bound_is_inclusive_so_end_at_itself_is_refused(api):
    """A send positioned exactly on `end_at` still lands inside the closed interval.

    PRD §3.8: "defines a **closed** interval: the schedule is refused when
    `scheduled_send_at` is at or after the window's `start_at` and at or before
    its `end_at`. Both endpoints are therefore blocking, and the refusal is
    `ERR_COMMUNICATION_BLACKOUT_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/blackout_closed_interval_rejects_send_exactly_at_end_at_returns_409
    """
    ctx = _approved_campaign_against_a_scoped_blackout(api)
    campaign = ctx["campaign"]

    validate_error(
        api.schedule_campaign(
            campaign["id"],
            schedule_payload("2026-08-12T00:00:00Z", campaign["version"]),
            AUTHOR,
        ),
        ApiErrorId.COMMUNICATION_BLACKOUT_CONFLICT.value,
        expected_status=409,
    )

    unchanged = validate_success(api.get_campaign(campaign["id"], ADMIN))
    assert unchanged["state"] == CAMPAIGN_APPROVED
    assert_instant_is_none(unchanged["scheduled_send_at"], "scheduled_send_at")
    assert unchanged["version"] == campaign["version"]
    assert list_deliveries(api, campaign_id=campaign["id"]) == []
    assert read_employee(api, ctx["employee"]["id"])["reserved_simulation_slots"] == 0


def test_one_second_past_end_at_clears_the_blackout_and_reserves_the_cohort(api):
    """Just outside the closed interval the same reservation is legal.

    PRD §3.8: "Creating the reservation increments each targeted employee's
    `reserved_simulation_slots` by one and bumps each such `Employee.version` by
    one, sets `scheduled_send_at`, `target_count` and `evaluable_count` on the
    campaign, and bumps the campaign's `version` by one."

    Design: Difficulty/resource_temporal_overlap/blackout_closed_interval_rejects_send_exactly_at_end_at_returns_409
    """
    ctx = _approved_campaign_against_a_scoped_blackout(api)
    campaign = ctx["campaign"]

    validate_error(
        api.schedule_campaign(
            campaign["id"],
            schedule_payload("2026-08-12T00:00:00Z", campaign["version"]),
            AUTHOR,
        ),
        ApiErrorId.COMMUNICATION_BLACKOUT_CONFLICT.value,
    )
    scheduled = validate_success(
        api.schedule_campaign(
            campaign["id"],
            schedule_payload("2026-08-12T00:00:01Z", campaign["version"]),
            AUTHOR,
        )
    )
    assert scheduled["state"] == CAMPAIGN_SCHEDULED
    assert_instant_equals(scheduled["scheduled_send_at"], "2026-08-12T00:00:01Z",
                          "scheduled_send_at")
    assert scheduled["target_count"] == 1
    assert scheduled["evaluable_count"] == 1
    assert scheduled["version"] == campaign["version"] + 1
    assert read_employee(api, ctx["employee"]["id"])["reserved_simulation_slots"] == 1


def _second_hr_wave_behind_a_quiet_period(api) -> dict:
    """One HR employee delivered at 09:00, so the quiet period ends 5 days later."""
    reset_clock(api)
    employee = register_employee(
        api, full_name="Quinn HR", department="HR",
        role_code="IC", hire_date="2017-03-03",
    )
    template = approved_template(
        api, name="Benefits Enrollment Window",
        pretext_category="HR_BENEFITS_ENROLLMENT", difficulty_tier=TIER_1,
        theme_tags=["REWARD"], credential_capture_enabled=False,
    )
    first = running_campaign(
        api, scheduled_send_at="2026-08-02T09:00:00Z", template=template,
        name="HR Wave 1", difficulty_tier=TIER_1, target_departments=["HR"],
    )
    first_delivery = delivery_for(api, first["campaign"]["id"], employee["id"])
    second = approved_campaign(
        api, template=template, name="HR Wave 2", difficulty_tier=TIER_1,
        target_departments=["HR"],
    )
    return {"employee": employee, "template": template,
            "first_delivery": first_delivery, "campaign": second["campaign"]}


def test_quiet_period_upper_bound_is_exclusive_so_the_instant_itself_is_allowed(api):
    """A send positioned exactly at `quiet_period_until` falls outside the interval.

    PRD §3.8: "The schedule is refused when `scheduled_send_at` falls at or after
    the reference instant and strictly before `quiet_period_until` for any cohort
    member, with `ERR_SIMULATION_QUIET_PERIOD_CONFLICT` (HTTP 409). Because the
    upper bound is exclusive, a send positioned exactly at `quiet_period_until` is
    allowed."

    Design: Difficulty/resource_temporal_overlap/quiet_period_half_open_allows_send_exactly_at_boundary
    """
    ctx = _second_hr_wave_behind_a_quiet_period(api)
    delivered = read_delivery(api, ctx["first_delivery"]["id"])
    assert_instant_equals(delivered["delivered_at"], "2026-08-02T09:00:00Z",
                          "delivered_at")
    assert_instant_equals(delivered["quiet_period_until"], "2026-08-07T09:00:00Z",
                          "quiet_period_until")

    campaign = ctx["campaign"]
    scheduled = validate_success(
        api.schedule_campaign(
            campaign["id"],
            schedule_payload("2026-08-07T09:00:00Z", campaign["version"]),
            AUTHOR,
        )
    )
    assert scheduled["state"] == CAMPAIGN_SCHEDULED
    assert scheduled["evaluable_count"] == 1

    reserved = delivery_for(api, campaign["id"], ctx["employee"]["id"])
    assert_delivery(reserved, state=DELIVERY_QUEUED)
    assert reserved["base_difficulty_tier"] == TIER_1
    assert read_employee(api, ctx["employee"]["id"])["reserved_simulation_slots"] == 1


def test_one_second_inside_the_quiet_period_is_refused(api):
    """The lower half of the half-open interval still bites at the last second.

    PRD §3.8: "Every non-excluded simulation delivery an employee holds defines a
    **half-open** quiet interval: it begins at a reference instant — the
    delivery's `delivered_at` when that is set, and otherwise the
    `scheduled_send_at` of the campaign that delivery belongs to — and it ends at
    `quiet_period_until`, which is that reference instant advanced by 5 days."

    Design: Difficulty/resource_temporal_overlap/quiet_period_half_open_allows_send_exactly_at_boundary
    """
    ctx = _second_hr_wave_behind_a_quiet_period(api)
    campaign = ctx["campaign"]

    validate_error(
        api.schedule_campaign(
            campaign["id"],
            schedule_payload("2026-08-07T08:59:59Z", campaign["version"]),
            AUTHOR,
        ),
        ApiErrorId.SIMULATION_QUIET_PERIOD_CONFLICT.value,
        expected_status=409,
    )

    unchanged = validate_success(api.get_campaign(campaign["id"], ADMIN))
    assert unchanged["state"] == CAMPAIGN_APPROVED
    assert_instant_is_none(unchanged["scheduled_send_at"], "scheduled_send_at")
    assert list_deliveries(api, campaign_id=campaign["id"]) == []


# --------------------------------------------------------------------------- #
# compensating_invariant                                                      #
# --------------------------------------------------------------------------- #


def _report_escalated_to_the_suspension_rung(api) -> dict:
    """Fourteen days overdue: one sweep walks rungs 1, 2 and 3 in a single run."""
    reset_clock(api)
    pair = register_manager_and_report(
        api, department="ENGINEERING", report_role_code="ENGINEER",
        report_hire_date="2016-08-08", manager_hire_date="2011-11-11",
    )
    module = create_published_module(
        api, code="ANNUAL-SEC-F", title="Annual Security Awareness F",
        module_type="ANNUAL",
    )
    assignment = assign_module(api, pair["report"], module, assignment_reason="ANNUAL")
    set_clock(api, "2026-09-14T00:00:00Z")
    run_sweep(api)
    return {"manager": pair["manager"], "employee": pair["report"],
            "assignment": assignment}


def test_void_marks_every_cascade_artefact_as_a_compensated_exit(api):
    """The void unwinds the whole rung-3 cascade with the compensating reason code.

    PRD §3.5: "Every `SENT` escalation notice of the assignment becomes `EXPIRED`.
    Every `ACTIVE` access consequence whose `source_assignment_id` is this
    assignment becomes `VOIDED` with `lift_reason_code` of `ASSIGNMENT_VOIDED`."

    Design: Difficulty/compensating_invariant/suspension_ledger_restored_when_assignment_voided
    """
    ctx = _report_escalated_to_the_suspension_rung(api)
    before = read_assignment(api, ctx["assignment"]["id"])
    assert_assignment(before, state=ASSIGNMENT_ESCALATED, days_overdue=14,
                      escalation_level=3)
    active = list_consequences_for(api, ctx["employee"]["id"], state=CONSEQUENCE_ACTIVE)
    assert sorted(row["severity_rank"] for row in active) == [2, 3]
    assert {row["consequence_type"] for row in active} == {
        CONSEQUENCE_MFA_REVIEW, CONSEQUENCE_SUSPENSION}
    assert read_employee(api, ctx["employee"]["id"])["access_posture"] == POSTURE_SUSPENDED

    voided = validate_success(
        api.void_assignment(ctx["assignment"]["id"],
                            {"void_reason_code": "ASSIGNED_IN_ERROR"}, ADMIN)
    )
    assert voided["state"] == ASSIGNMENT_VOIDED
    assert voided["void_reason_code"] == "ASSIGNED_IN_ERROR"
    assert_instant_is_none(voided["next_reminder_due_at"], "next_reminder_due_at")

    for row in active:
        after = validate_success(api.get_access_consequence(row["id"], ADMIN))
        assert_consequence(after, state=CONSEQUENCE_VOIDED,
                           lift_reason_code=LIFT_REASON_ASSIGNMENT_VOIDED)
        assert_instant_equals(after["lifted_at"], "2026-09-14T00:00:00Z", "lifted_at")

    assert list_consequences_for(
        api, ctx["employee"]["id"], state=CONSEQUENCE_ACTIVE) == []


def test_void_restores_the_suspension_ledger_to_its_pre_escalation_value(api):
    """The ledger obligation is exact, and the notices go with it.

    PRD §3.5: "The obligation on the void action is exact:
    `active_suspension_count` must come back to the value it held before
    escalation created the consequence in the first place."

    Design: Difficulty/compensating_invariant/suspension_ledger_restored_when_assignment_voided
    """
    ctx = _report_escalated_to_the_suspension_rung(api)
    escalated = read_employee(api, ctx["employee"]["id"])
    assert escalated["active_suspension_count"] == 1

    validate_success(
        api.void_assignment(ctx["assignment"]["id"],
                            {"void_reason_code": "ASSIGNED_IN_ERROR"}, ADMIN)
    )

    employee = read_employee(api, ctx["employee"]["id"])
    assert employee["active_suspension_count"] == 0
    assert employee["access_posture"] == POSTURE_NONE
    assert employee["compliance_state"] == COMPLIANCE_COMPLIANT
    assert_risk_scores(employee, provisional=0.00)

    notices = list_notices_for(api, ctx["assignment"]["id"])
    assert len(notices) == 3
    assert sorted(notice["level"] for notice in notices) == [1, 2, 3]
    for notice in notices:
        assert_notice(notice, state=NOTICE_EXPIRED)
    assert list_notices_for(
        api, ctx["assignment"]["id"], state=NOTICE_SENT) == []


def _scheduled_executive_wave(api) -> dict:
    """Two EXECUTIVE employees holding one QUEUED delivery each."""
    reset_clock(api)
    first = register_employee(
        api, full_name="Xavier One", department="EXECUTIVE",
        role_code="EXECUTIVE", hire_date="2012-01-01",
    )
    second = register_employee(
        api, full_name="Xena Two", department="EXECUTIVE",
        role_code="EXECUTIVE", hire_date="2013-02-02",
    )
    ctx = scheduled_campaign(
        api, scheduled_send_at="2026-08-20T09:00:00Z",
        name="EXEC Board Wave", difficulty_tier=TIER_2,
        target_departments=["EXECUTIVE"],
        template_overrides={
            "name": "Board Deck Review",
            "pretext_category": "SHARED_DOCUMENT",
            "difficulty_tier": TIER_2,
            "theme_tags": ["AUTHORITY"],
            "credential_capture_enabled": False,
        },
    )
    ctx["employees"] = [first, second]
    return ctx


def test_cancel_excludes_the_queued_deliveries_it_reserved(api):
    """Cancellation is the release half of the reservation without a re-reservation.

    PRD §3.8: "**Cancelling a scheduled campaign** performs the release half
    without the re-reservation half: `cancelled_at` is stamped, every `QUEUED`
    delivery becomes `EXCLUDED` with `excluded_reason` of `CAMPAIGN_CANCELLED`,
    each affected employee's `reserved_simulation_slots` is decremented by one and
    their `version` bumped, `evaluable_count` falls to 0, and the campaign's
    `version` is bumped."

    Design: Difficulty/compensating_invariant/reservation_ledger_restored_when_campaign_cancelled
    """
    ctx = _scheduled_executive_wave(api)
    campaign = ctx["campaign"]
    assert campaign["target_count"] == 2
    assert campaign["evaluable_count"] == 2
    queued = list_deliveries(api, campaign_id=campaign["id"])
    assert len(queued) == 2
    for delivery in queued:
        assert_delivery(delivery, state=DELIVERY_QUEUED)
    for employee in ctx["employees"]:
        assert read_employee(api, employee["id"])["reserved_simulation_slots"] == 1

    cancelled = validate_success(api.cancel_campaign(campaign["id"], AUTHOR))
    assert cancelled["state"] == CAMPAIGN_CANCELLED
    assert_instant_equals(cancelled["cancelled_at"], "2026-08-01T00:00:00Z",
                          "cancelled_at")
    assert cancelled["evaluable_count"] == 0

    for delivery in queued:
        after = read_delivery(api, delivery["id"])
        assert_delivery(after, state=DELIVERY_EXCLUDED,
                        excluded_reason=EXCLUDED_REASON_CAMPAIGN_CANCELLED)


def test_cancel_restores_the_reservation_ledger_on_both_employees(api):
    """The global reservation invariant holds after the compensating release.

    PRD §2.9: "The invariant is global: the sum of `reserved_simulation_slots`
    across all employees always equals the number of `SimulationDelivery` rows in
    state `QUEUED`, both before and after every operation."

    Design: Difficulty/compensating_invariant/reservation_ledger_restored_when_campaign_cancelled
    """
    ctx = _scheduled_executive_wave(api)
    validate_success(api.cancel_campaign(ctx["campaign"]["id"], AUTHOR))

    total_reserved = 0
    for employee in ctx["employees"]:
        row = read_employee(api, employee["id"])
        assert row["reserved_simulation_slots"] == 0
        assert row["repeat_clicker_tier"] == 0
        assert_risk_scores(row, provisional=0.00, settled=0.00)
        total_reserved += row["reserved_simulation_slots"]

    still_queued = list_deliveries(api, state=DELIVERY_QUEUED)
    assert still_queued == []
    assert total_reserved == len(still_queued)
