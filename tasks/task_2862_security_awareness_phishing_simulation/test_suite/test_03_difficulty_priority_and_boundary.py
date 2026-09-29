"""Validation-priority conflicts and inclusive/exclusive boundaries.

Every test in this module translates exactly one instance of the §1.8 depth
index: the two `priority_pair_validation_conflict` instances and the two
`boundary_precision_check` instances.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    ASSIGNMENT_ASSIGNED,
    ASSIGNMENT_OVERDUE,
    CAMPAIGN_APPROVED,
    CAMPAIGN_IN_REVIEW,
    COMPLIANCE_AT_RISK,
    NOTICE_SENT,
    POSTURE_NONE,
    TEMPLATE_DRAFT,
    TIER_2,
    WINDOW_SIMULATION_BLACKOUT,
)
from test_helpers.assertions import (
    assert_assignment,
    assert_instant_equals,
    assert_instant_is_none,
    assert_notice,
    assert_sweep_counters,
)
from test_helpers.factories import schedule_payload
from test_helpers.fixtures import (
    approved_campaign,
    assign_module,
    create_campaign,
    create_published_module,
    create_template,
    declare_window,
    list_deliveries,
    list_notices_for,
    read_assignment,
    read_employee,
    register_employee,
    register_manager_and_report,
    reset_clock,
    run_sweep,
    set_clock,
)
from test_helpers.test_users import (
    ADMIN,
    AUTHOR,
    AUTHOR_1_ID,
    make_campaign_approver_headers,
)


# --------------------------------------------------------------------------- #
# priority_pair_validation_conflict                                           #
# --------------------------------------------------------------------------- #


def _harmful_campaign_in_review(api) -> dict:
    """An IN_REVIEW campaign whose template carries a prohibited theme tag."""
    reset_clock(api)
    register_employee(
        api, full_name="Hank HR", department="HR", role_code="IC",
        hire_date="2018-08-08",
    )
    template = create_template(
        api, name="Workforce Reduction Notice",
        pretext_category="HR_BENEFITS_ENROLLMENT", difficulty_tier=TIER_2,
        theme_tags=["URGENCY", "LAYOFF_NOTICE"], credential_capture_enabled=False,
    )
    campaign = create_campaign(
        api, template["id"], AUTHOR, name="HR Restructure Wave",
        difficulty_tier=TIER_2, target_departments=["HR"],
    )
    validate_success(api.submit_campaign_for_review(campaign["id"], AUTHOR))
    return {"template": template, "campaign": campaign}


def test_safety_screen_outranks_segregation_of_duties_on_approval(api):
    """Approving a harmful-theme campaign as its own author answers the safety error.

    PRD §3.7: "Because safety is checked before authorship, a harmful-theme
    campaign is refused with the safety error even when the person asking is also
    its author."

    Design: Difficulty/priority_pair_validation_conflict/campaign_approve_harmful_theme_outranks_sod_returns_422
    """
    ctx = _harmful_campaign_in_review(api)

    error = validate_error(
        api.approve_campaign(
            ctx["campaign"]["id"], make_campaign_approver_headers(AUTHOR_1_ID)),
        ApiErrorId.HARMFUL_PRETEXT_THEME.value,
        expected_status=422,
    )
    assert error["error_id"] != ApiErrorId.SEGREGATION_OF_DUTIES_VIOLATION.value
    assert error["error_id"] != ApiErrorId.TEMPLATE_NOT_APPROVED.value


def test_rejected_approval_leaves_the_campaign_and_template_untouched(api):
    """The refused approval writes nothing on either entity.

    PRD §3.7: "A new template's `review_state` is `DRAFT`, its `blocked_reason`
    is empty, and its `harmful_flag_hits` is computed at creation time by the
    screen of §2.10 — recorded, not rejected, so that the safety gate bites at
    approval time where a human decision is being made."

    Design: Difficulty/priority_pair_validation_conflict/campaign_approve_harmful_theme_outranks_sod_returns_422
    """
    ctx = _harmful_campaign_in_review(api)
    validate_error(
        api.approve_campaign(
            ctx["campaign"]["id"], make_campaign_approver_headers(AUTHOR_1_ID)),
        ApiErrorId.HARMFUL_PRETEXT_THEME.value,
    )

    campaign = validate_success(api.get_campaign(ctx["campaign"]["id"], ADMIN))
    assert campaign["state"] == CAMPAIGN_IN_REVIEW
    assert campaign["reviewer_user_id"] is None
    assert campaign["rejection_reason"] is None
    assert campaign["author_user_id"] == AUTHOR_1_ID

    template = validate_success(api.get_template(ctx["template"]["id"], ADMIN))
    assert "LAYOFF_NOTICE" in template["harmful_flag_hits"]
    assert template["review_state"] == TEMPLATE_DRAFT

    assert list_deliveries(api, campaign_id=ctx["campaign"]["id"]) == []


def _approved_campaign_inside_a_blackout(api) -> dict:
    """An APPROVED campaign whose only legal send window is blacked out."""
    reset_clock(api)
    employee = register_employee(
        api, full_name="Eve Exec", department="EXECUTIVE",
        role_code="EXECUTIVE", hire_date="2013-03-03",
    )
    declare_window(
        api, "2026-08-10T00:00:00Z", "2026-08-12T00:00:00Z",
        window_type=WINDOW_SIMULATION_BLACKOUT, reason="Quarter-end close",
    )
    ctx = approved_campaign(
        api, name="EXEC Doc Wave", difficulty_tier=TIER_2,
        target_departments=["EXECUTIVE"],
        template_overrides={
            "name": "Shared Document Review",
            "pretext_category": "SHARED_DOCUMENT",
            "difficulty_tier": TIER_2,
            "theme_tags": ["CURIOSITY"],
            "credential_capture_enabled": False,
        },
    )
    ctx["employee"] = employee
    return ctx


def test_stale_campaign_version_outranks_the_blackout_conflict(api):
    """The optimistic-concurrency guard answers 412 before the calendar check.

    PRD §2.7: "A mismatch with the campaign's current `version` is rejected with
    `ERR_STALE_CAMPAIGN_VERSION` (HTTP 412)."

    PRD §2.8 lists optimistic concurrency as step 10 of the fixed order —
    "Optimistic-concurrency comparison of `expected_employee_version` or
    `expected_campaign_version` against the named parent
    (`ERR_STALE_EMPLOYEE_VERSION`, `ERR_STALE_CAMPAIGN_VERSION`)." — while
    "Everything after step 12 is domain-specific" and the domain order runs
    "schedule-in-the-future; blackout conflict; quiet-period conflict".

    Design: Difficulty/priority_pair_validation_conflict/campaign_schedule_stale_version_outranks_blackout_returns_412
    """
    ctx = _approved_campaign_inside_a_blackout(api)
    campaign = ctx["campaign"]

    error = validate_error(
        api.schedule_campaign(
            campaign["id"],
            schedule_payload("2026-08-11T09:00:00Z", campaign["version"] - 1),
            AUTHOR,
        ),
        ApiErrorId.STALE_CAMPAIGN_VERSION.value,
        expected_status=412,
    )
    assert error["error_id"] != ApiErrorId.COMMUNICATION_BLACKOUT_CONFLICT.value

    unchanged = validate_success(api.get_campaign(campaign["id"], ADMIN))
    assert unchanged["state"] == CAMPAIGN_APPROVED
    assert_instant_is_none(unchanged["scheduled_send_at"], "scheduled_send_at")
    assert unchanged["version"] == campaign["version"]
    assert list_deliveries(api, campaign_id=campaign["id"]) == []
    assert read_employee(api, ctx["employee"]["id"])["reserved_simulation_slots"] == 0


def test_blackout_conflict_surfaces_once_the_version_is_current(api):
    """Both rules were live: the calendar check answers 409 on the fresh version.

    PRD §3.8: "the schedule is refused when `scheduled_send_at` is at or after
    the window's `start_at` and at or before its `end_at`. Both endpoints are
    therefore blocking, and the refusal is `ERR_COMMUNICATION_BLACKOUT_CONFLICT`
    (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/campaign_schedule_stale_version_outranks_blackout_returns_412
    """
    ctx = _approved_campaign_inside_a_blackout(api)
    campaign = ctx["campaign"]

    validate_error(
        api.schedule_campaign(
            campaign["id"],
            schedule_payload("2026-08-11T09:00:00Z", campaign["version"] - 1),
            AUTHOR,
        ),
        ApiErrorId.STALE_CAMPAIGN_VERSION.value,
    )
    validate_error(
        api.schedule_campaign(
            campaign["id"],
            schedule_payload("2026-08-11T09:00:00Z", campaign["version"]),
            AUTHOR,
        ),
        ApiErrorId.COMMUNICATION_BLACKOUT_CONFLICT.value,
        expected_status=409,
    )

    still_approved = validate_success(api.get_campaign(campaign["id"], ADMIN))
    assert still_approved["state"] == CAMPAIGN_APPROVED
    assert still_approved["version"] == campaign["version"]


# --------------------------------------------------------------------------- #
# boundary_precision_check                                                    #
# --------------------------------------------------------------------------- #


def _annual_assignment_with_explicit_cadence(api) -> dict:
    """One annual assignment due 2026-08-31 with the 7/3/1/-2 reminder ladder."""
    reset_clock(api)
    employee = register_employee(
        api, full_name="Boris Boundary", department="ENGINEERING",
        role_code="ENGINEER", hire_date="2017-01-09",
    )
    module = create_published_module(
        api, code="ANNUAL-SEC-D", title="Annual Security Awareness D",
        module_type="ANNUAL", reminder_offsets_days=[7, 3, 1, -2],
    )
    assignment = assign_module(api, employee, module, assignment_reason="ANNUAL")
    return {"employee": employee, "module": module, "assignment": assignment}


def test_sweep_one_second_before_the_reminder_instant_sends_nothing(api):
    """The exclusive side of the inclusive bound: strictly-before is not yet due.

    PRD §3.4: "The instant at which the next unsent reminder falls due is the
    assignment's `effective_due_at` moved *backwards* by the offset sitting at the
    position given by `reminders_sent`, counting positions from zero — so with the
    default list of 7, 3, 1 and −2, the first reminder is due seven days before
    the effective deadline"

    Design: Difficulty/boundary_precision_check/reminder_cadence_inclusive_boundary_exact_instant_sends
    """
    ctx = _annual_assignment_with_explicit_cadence(api)
    assert_instant_equals(ctx["assignment"]["effective_due_at"],
                          "2026-08-31T00:00:00Z", "effective_due_at")
    assert_instant_equals(ctx["assignment"]["next_reminder_due_at"],
                          "2026-08-24T00:00:00Z", "next_reminder_due_at")
    assert ctx["assignment"]["reminders_sent"] == 0

    set_clock(api, "2026-08-23T23:59:59Z")
    sweep = run_sweep(api)
    assert_sweep_counters(sweep, assignments_scanned=1, reminders_sent_count=0,
                          overdue_count=0, escalations_created_count=0,
                          consequences_applied_count=0)

    assignment = read_assignment(api, ctx["assignment"]["id"])
    assert_assignment(assignment, state=ASSIGNMENT_ASSIGNED, reminders_sent=0,
                      escalation_level=0)
    assert_instant_is_none(assignment["last_reminder_at"], "last_reminder_at")
    assert_instant_equals(assignment["next_reminder_due_at"],
                          "2026-08-24T00:00:00Z", "next_reminder_due_at")


def test_sweep_at_exactly_the_reminder_instant_sends_the_reminder(api):
    """The bound is inclusive, and the recomputation walks to the next offset.

    PRD §3.4: "When the sweep finds an assignment whose `next_reminder_due_at` is
    set and is at or before the current clock — the boundary is inclusive, so a
    sweep run at exactly that instant does send the reminder — it increments
    `reminders_sent` by one, stamps `last_reminder_at` with the clock, and
    recomputes `next_reminder_due_at` from the new count."

    Design: Difficulty/boundary_precision_check/reminder_cadence_inclusive_boundary_exact_instant_sends
    """
    ctx = _annual_assignment_with_explicit_cadence(api)

    set_clock(api, "2026-08-23T23:59:59Z")
    run_sweep(api)

    set_clock(api, "2026-08-24T00:00:00Z")
    sweep = run_sweep(api)
    assert_sweep_counters(sweep, assignments_scanned=1, reminders_sent_count=1,
                          overdue_count=0, escalations_created_count=0,
                          consequences_applied_count=0)

    assignment = read_assignment(api, ctx["assignment"]["id"])
    assert_assignment(assignment, state=ASSIGNMENT_ASSIGNED, reminders_sent=1,
                      escalation_level=0)
    assert_instant_equals(assignment["last_reminder_at"], "2026-08-24T00:00:00Z",
                          "last_reminder_at")
    assert_instant_equals(assignment["next_reminder_due_at"],
                          "2026-08-28T00:00:00Z", "next_reminder_due_at")


def _report_with_an_annual_deadline(api) -> dict:
    """A SALES manager and report holding one annual assignment due 2026-08-31."""
    reset_clock(api)
    pair = register_manager_and_report(
        api, department="SALES", report_role_code="IC",
        report_hire_date="2019-09-09", manager_hire_date="2012-12-12",
    )
    module = create_published_module(
        api, code="ANNUAL-SEC-E", title="Annual Security Awareness E",
        module_type="ANNUAL",
    )
    assignment = assign_module(api, pair["report"], module, assignment_reason="ANNUAL")
    return {"manager": pair["manager"], "employee": pair["report"],
            "assignment": assignment}


def test_first_overdue_second_floors_days_overdue_to_zero_and_fires_no_rung(api):
    """One second past the deadline the assignment is OVERDUE but at rung 0.

    PRD §3.4: "Because `days_overdue` is floored, it remains 0 for the first
    twenty-three hours, fifty-nine minutes and fifty-nine seconds after the
    effective deadline."

    Design: Difficulty/boundary_precision_check/escalation_ladder_first_overdue_day_floor_boundary
    """
    ctx = _report_with_an_annual_deadline(api)

    set_clock(api, "2026-08-31T23:59:59Z")
    sweep = run_sweep(api)
    assert_sweep_counters(sweep, assignments_scanned=1, overdue_count=1,
                          escalations_created_count=0, consequences_applied_count=0)

    assignment = read_assignment(api, ctx["assignment"]["id"])
    assert_assignment(assignment, state=ASSIGNMENT_OVERDUE, days_overdue=0,
                      escalation_level=0)
    assert list_notices_for(api, ctx["assignment"]["id"]) == []


def test_the_next_second_crosses_the_floor_and_fires_the_notify_only_rung(api):
    """At exactly one day overdue the ladder targets rung 1 and stops there.

    PRD §3.4: "The target rung follows from that count: 14 or more days overdue
    targets rung 3, at least 7 but fewer than 14 targets rung 2, at least 1 but
    fewer than 7 targets rung 1, and anything less targets rung 0."

    Design: Difficulty/boundary_precision_check/escalation_ladder_first_overdue_day_floor_boundary
    """
    ctx = _report_with_an_annual_deadline(api)
    set_clock(api, "2026-08-31T23:59:59Z")
    run_sweep(api)

    set_clock(api, "2026-09-01T00:00:00Z")
    sweep = run_sweep(api)
    assert_sweep_counters(sweep, assignments_scanned=1,
                          escalations_created_count=1,
                          consequences_applied_count=0)

    assignment = read_assignment(api, ctx["assignment"]["id"])
    assert_assignment(assignment, state=ASSIGNMENT_OVERDUE, days_overdue=1,
                      escalation_level=1)

    notices = list_notices_for(api, ctx["assignment"]["id"])
    assert len(notices) == 1
    assert_notice(notices[0], state=NOTICE_SENT, level=1)
    assert notices[0]["manager_id"] == ctx["manager"]["id"]
    assert_instant_equals(notices[0]["sent_at"], "2026-09-01T00:00:00Z", "sent_at")

    employee = read_employee(api, ctx["employee"]["id"])
    assert employee["access_posture"] == POSTURE_NONE
    assert employee["active_suspension_count"] == 0
    assert employee["compliance_state"] == COMPLIANCE_AT_RISK
