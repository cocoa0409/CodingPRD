"""Lifecycle transitions: the legal hops, the refused hops and their side effects.

Every test in this module translates exactly one non-stub instance of the
`state_machines` section of the §1.9 breadth index.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    ASSIGNMENT_VOIDED,
    CAMPAIGN_CANCELLED,
    CAMPAIGN_CLOSED,
    CAMPAIGN_DRAFT,
    CAMPAIGN_RUNNING,
    CAMPAIGN_SCHEDULED,
    COMPLIANCE_COMPLIANT,
    DELIVERY_CLICKED,
    DELIVERY_EXCLUDED,
    DELIVERY_NO_INTERACTION,
    DELIVERY_QUEUED,
    EMPLOYMENT_OFFBOARDED,
    EXCLUDED_REASON_EMPLOYEE_OFFBOARDED,
    MODULE_DRAFT,
    MODULE_PUBLISHED,
    OUTCOME_CLICKED_THEN_REPORTED,
    OUTCOME_NO_INTERACTION,
    POSTURE_NONE,
    TIER_1,
    TIER_2,
    VOID_REASON_EMPLOYEE_OFFBOARDED,
)
from test_helpers.assertions import (
    assert_assignment,
    assert_delivery,
    assert_instant_equals,
    assert_instant_is_none,
    assert_ledgers,
    assert_rate,
    assert_risk_scores,
    assert_version_is,
)
from test_helpers.factories import module_payload
from test_helpers.fixtures import (
    approved_template,
    assign_module,
    create_campaign,
    create_module,
    create_published_module,
    delivery_for,
    read_assignment,
    read_delivery,
    read_employee,
    register_employee,
    reset_clock,
    running_campaign,
    scheduled_campaign,
    set_clock,
)
from test_helpers.test_users import ADMIN, AUTHOR, AUTHOR_1_ID


# --------------------------------------------------------------------------- #
# TrainingModule lifecycle                                                    #
# --------------------------------------------------------------------------- #


def test_publishing_a_draft_module_stamps_published_at_and_bumps_version(api):
    """DRAFT -> PUBLISHED is the declared hop and it leaves retired_at empty.

    PRD §3.2: "Publishing it requires that its `status` is still `DRAFT` and that
    it is not a `ROLE_SPECIFIC` module with an empty `applies_to_role_codes`; on
    success the `status` becomes `PUBLISHED`, `published_at` is stamped with the
    logical clock, and the module's `version` is bumped."

    Design: Corner/state_machines/module_publish_valid_transition_draft_to_published
    """
    reset_clock(api)
    module = create_module(api, code="PUB-1", title="New Hire Security Basics",
                           module_type="NEW_HIRE")
    assert module["status"] == MODULE_DRAFT
    assert_instant_is_none(module["published_at"], "published_at")

    published = validate_success(api.publish_module(module["id"], ADMIN))
    assert published["status"] == MODULE_PUBLISHED
    assert_instant_equals(published["published_at"], "2026-08-01T00:00:00Z",
                          "published_at")
    assert_instant_is_none(published["retired_at"], "retired_at")
    assert_version_is(published, 2, "module")

    fetched = validate_success(api.get_module(module["id"], ADMIN))
    assert fetched["status"] == MODULE_PUBLISHED
    assert_version_is(fetched, 2, "module")


def test_publishing_an_already_published_module_is_refused_and_changes_nothing(api):
    """The guard is on the current status, so the second publish is a 409.

    PRD §3.2: "Publishing anything that is not `DRAFT`, or retiring anything that
    is not `PUBLISHED`, is refused with `ERR_MODULE_STATE_INVALID`."

    Design: Corner/state_machines/module_publish_twice_returns_409_module_state_invalid
    """
    reset_clock(api)
    module = create_module(api, code="PUB-2", title="Annual Refresher",
                           module_type="ANNUAL")
    published = validate_success(api.publish_module(module["id"], ADMIN))

    set_clock(api, "2026-08-05T00:00:00Z")
    validate_error(
        api.publish_module(module["id"], ADMIN),
        ApiErrorId.MODULE_STATE_INVALID.value,
        expected_status=409,
    )

    unchanged = validate_success(api.get_module(module["id"], ADMIN))
    assert unchanged["status"] == MODULE_PUBLISHED
    # The first stamp is not overwritten by the refused second publish.
    assert_instant_equals(unchanged["published_at"], "2026-08-01T00:00:00Z",
                          "published_at")
    assert unchanged["version"] == published["version"]


def test_retiring_a_draft_module_is_refused_because_retirement_needs_published(api):
    """RETIRED is reachable only from PUBLISHED, never straight from DRAFT.

    PRD §3.2: "Retiring requires that the `status` is `PUBLISHED`; it stamps
    `retired_at` and bumps `version`. Publishing anything that is not `DRAFT`, or
    retiring anything that is not `PUBLISHED`, is refused with
    `ERR_MODULE_STATE_INVALID`."

    Design: Corner/state_machines/module_retire_from_draft_returns_409_module_state_invalid
    """
    reset_clock(api)
    module = validate_success(
        api.create_module(
            module_payload(code="RET-1", title="Admin Console Hygiene",
                           module_type="ROLE_SPECIFIC",
                           applies_to_role_codes=["IT_ADMIN"]),
            ADMIN,
        ),
        expected_status=201,
    )
    assert module["status"] == MODULE_DRAFT

    validate_error(
        api.retire_module(module["id"], ADMIN),
        ApiErrorId.MODULE_STATE_INVALID.value,
        expected_status=409,
    )

    unchanged = validate_success(api.get_module(module["id"], ADMIN))
    assert unchanged["status"] == MODULE_DRAFT
    assert_instant_is_none(unchanged["retired_at"], "retired_at")
    assert unchanged["version"] == module["version"]


# --------------------------------------------------------------------------- #
# SimulationCampaign lifecycle                                                #
# --------------------------------------------------------------------------- #


def test_a_new_campaign_starts_in_draft_with_no_reviewer_and_no_cohort(api):
    """Creation is the entry hop: DRAFT, author stamped, every later stamp empty.

    PRD §3.7: "Creation stamps `author_user_id` with the acting `X-User-ID`,
    leaves `reviewer_user_id` empty, and puts the campaign in `DRAFT`."

    Design: Corner/state_machines/campaign_initial_state_is_draft_on_create
    """
    reset_clock(api)
    template = approved_template(
        api, name="Initial State Probe", pretext_category="SHARED_DOCUMENT",
        difficulty_tier=TIER_2, theme_tags=["CURIOSITY"],
        credential_capture_enabled=False,
    )

    campaign = create_campaign(
        api, template["id"], AUTHOR, name="Draft State Wave",
        difficulty_tier=TIER_1, target_departments=["HR"],
    )

    assert campaign["state"] == CAMPAIGN_DRAFT
    assert campaign["author_user_id"] == AUTHOR_1_ID
    assert campaign["reviewer_user_id"] is None
    assert_instant_is_none(campaign["scheduled_send_at"], "scheduled_send_at")
    assert_instant_is_none(campaign["launched_at"], "launched_at")
    assert_instant_is_none(campaign["closed_at"], "closed_at")
    assert_instant_is_none(campaign["cancelled_at"], "cancelled_at")
    assert campaign["target_count"] == 0, "no cohort is resolved before scheduling"
    assert campaign["evaluable_count"] == 0
    assert campaign["click_rate"] is None, "an empty denominator yields null rates"
    assert campaign["report_rate"] is None


def test_closing_a_scheduled_campaign_is_refused_and_the_cohort_stays_reserved(api):
    """Close is declared only from RUNNING, so SCHEDULED -> CLOSED is undeclared.

    PRD §3.7: "Requesting any campaign transition the lifecycle does not declare —
    launching from `APPROVED`, closing from `SCHEDULED`, cancelling something
    already `CLOSED` — is refused with `ERR_CAMPAIGN_STATE_INVALID`."

    Design: Corner/state_machines/campaign_close_from_scheduled_returns_409_campaign_state_invalid
    """
    reset_clock(api)
    employee = register_employee(
        api, email="hal.hr@corp.example", full_name="Hal HR",
        department="HR", role_code="IC", hire_date="2018-03-03",
    )
    ctx = scheduled_campaign(
        api, scheduled_send_at="2026-08-20T09:00:00Z",
        name="HR Benefits Wave", difficulty_tier=TIER_1,
        target_departments=["HR"],
        template_overrides={
            "name": "Benefits Notice",
            "pretext_category": "HR_BENEFITS_ENROLLMENT",
            "difficulty_tier": TIER_1,
            "theme_tags": ["REWARD"],
            "credential_capture_enabled": False,
        },
    )
    campaign = ctx["campaign"]
    assert campaign["state"] == CAMPAIGN_SCHEDULED

    validate_error(
        api.close_campaign(
            campaign["id"], {"debrief_note": "Closing early."}, ADMIN),
        ApiErrorId.CAMPAIGN_STATE_INVALID.value,
        expected_status=409,
    )

    unchanged = validate_success(api.get_campaign(campaign["id"], ADMIN))
    assert unchanged["state"] == CAMPAIGN_SCHEDULED
    assert_instant_is_none(unchanged["closed_at"], "closed_at")
    assert unchanged["debrief_note"] is None
    assert unchanged["version"] == campaign["version"]

    delivery = delivery_for(api, campaign["id"], employee["id"])
    assert_delivery(delivery, state=DELIVERY_QUEUED)
    assert_ledgers(read_employee(api, employee["id"]), reserved_simulation_slots=1)


def test_a_cancelled_campaign_refuses_every_further_trigger(api):
    """CANCELLED is terminal, so review, approval, schedule, launch and close all fail.

    PRD §3.7: "Cancellation is the author's own withdrawal and lands the campaign
    in the terminal `CANCELLED` state, stamping `cancelled_at` with the logical
    clock and bumping `version`."

    Design: Corner/state_machines/campaign_terminal_cancelled_rejects_further_triggers
    """
    reset_clock(api)
    register_employee(
        api, email="tess.sales@corp.example", full_name="Tess Sales",
        department="SALES", role_code="IC", hire_date="2018-04-04",
    )
    ctx = scheduled_campaign(
        api, scheduled_send_at="2026-08-20T09:00:00Z",
        name="Deal Doc Wave", difficulty_tier=TIER_1,
        target_departments=["SALES"],
        template_overrides={
            "name": "Deal Doc Probe",
            "pretext_category": "SHARED_DOCUMENT",
            "difficulty_tier": TIER_1,
            "theme_tags": ["CURIOSITY"],
            "credential_capture_enabled": False,
        },
    )
    campaign_id = ctx["campaign"]["id"]

    cancelled = validate_success(api.cancel_campaign(campaign_id, AUTHOR))
    assert cancelled["state"] == CAMPAIGN_CANCELLED
    assert_instant_equals(cancelled["cancelled_at"], "2026-08-01T00:00:00Z",
                          "cancelled_at")

    validate_error(
        api.submit_campaign_for_review(campaign_id, AUTHOR),
        ApiErrorId.CAMPAIGN_STATE_INVALID.value,
        expected_status=409,
    )
    validate_error(
        api.launch_campaign(campaign_id, ADMIN),
        ApiErrorId.CAMPAIGN_STATE_INVALID.value,
        expected_status=409,
    )
    validate_error(
        api.close_campaign(campaign_id, {"debrief_note": "Too late."}, ADMIN),
        ApiErrorId.CAMPAIGN_STATE_INVALID.value,
        expected_status=409,
    )
    validate_error(
        api.cancel_campaign(campaign_id, AUTHOR),
        ApiErrorId.CAMPAIGN_STATE_INVALID.value,
        expected_status=409,
    )

    still_cancelled = validate_success(api.get_campaign(campaign_id, ADMIN))
    assert still_cancelled["state"] == CAMPAIGN_CANCELLED
    assert still_cancelled["version"] == cancelled["version"]


def test_launching_before_the_send_instant_is_refused_and_allowed_at_it(api):
    """The launch gate is a clock comparison whose boundary is inclusive.

    PRD §3.8: "A `ProgramAdmin` launches a `SCHEDULED` campaign, moving
    `SCHEDULED → RUNNING`, but only once the logical clock has reached
    `scheduled_send_at`; a launch attempted while the clock is still strictly
    earlier is refused with `ERR_LAUNCH_BEFORE_SCHEDULE` (HTTP 409)."

    Design: Corner/state_machines/campaign_launch_before_scheduled_send_at_returns_409
    """
    reset_clock(api)
    employee = register_employee(
        api, email="ida.it@corp.example", full_name="Ida IT",
        department="IT", role_code="IT_ADMIN", hire_date="2018-05-05",
    )
    ctx = scheduled_campaign(
        api, scheduled_send_at="2026-08-20T09:00:00Z",
        name="IT Password Wave", difficulty_tier=TIER_1,
        target_departments=["IT"],
        template_overrides={
            "name": "Password Expiry Probe",
            "pretext_category": "IT_PASSWORD_RESET",
            "difficulty_tier": TIER_1,
            "theme_tags": ["URGENCY"],
            "credential_capture_enabled": False,
        },
    )
    campaign = ctx["campaign"]

    set_clock(api, "2026-08-19T09:00:00Z")
    validate_error(
        api.launch_campaign(campaign["id"], ADMIN),
        ApiErrorId.LAUNCH_BEFORE_SCHEDULE.value,
        expected_status=409,
    )

    held = validate_success(api.get_campaign(campaign["id"], ADMIN))
    assert held["state"] == CAMPAIGN_SCHEDULED
    assert_instant_is_none(held["launched_at"], "launched_at")
    delivery = delivery_for(api, campaign["id"], employee["id"])
    assert_delivery(delivery, state=DELIVERY_QUEUED)
    assert_instant_is_none(delivery["delivered_at"], "delivered_at")
    assert_ledgers(read_employee(api, employee["id"]), reserved_simulation_slots=1)

    set_clock(api, "2026-08-20T09:00:00Z")
    launched = validate_success(api.launch_campaign(campaign["id"], ADMIN))
    assert launched["state"] == CAMPAIGN_RUNNING
    assert_instant_equals(launched["launched_at"], "2026-08-20T09:00:00Z",
                          "launched_at")
    assert_ledgers(read_employee(api, employee["id"]), reserved_simulation_slots=0)


def test_closing_a_running_campaign_settles_the_cohort_and_freezes_the_rates(api):
    """RUNNING -> CLOSED converts an untouched delivery and freezes four zeroes.

    PRD §3.9: "On success `closed_at` is stamped with the logical clock, the
    `debrief_note` is stored, and every delivery still in `DELIVERED` moves
    `DELIVERED → NO_INTERACTION` with `outcome_class` of `NO_INTERACTION`, each
    such transition incrementing that employee's `consecutive_clean_simulations`
    by one and bumping both the delivery's `version` and the employee's
    `version`."

    Design: Corner/state_machines/campaign_close_side_effects_settle_cohort_and_freeze_rates
    """
    reset_clock(api)
    employee = register_employee(
        api, email="cleo.clean@corp.example", full_name="Cleo Clean",
        department="FINANCE", role_code="FINANCE_APPROVER", hire_date="2015-06-06",
    )
    ctx = running_campaign(
        api, scheduled_send_at="2026-08-02T09:00:00Z",
        name="FIN Invoice Wave", difficulty_tier=TIER_1,
        target_departments=["FINANCE"],
        template_overrides={
            "name": "Invoice Probe",
            "pretext_category": "INVOICE_APPROVAL",
            "difficulty_tier": TIER_1,
            "theme_tags": ["AUTHORITY"],
            "credential_capture_enabled": False,
        },
    )
    campaign_id = ctx["campaign"]["id"]
    delivery = delivery_for(api, campaign_id, employee["id"])

    set_clock(api, "2026-08-02T18:00:00Z")
    closed = validate_success(
        api.close_campaign(
            campaign_id, {"debrief_note": "No interactions; debrief circulated."},
            ADMIN),
    )

    assert closed["state"] == CAMPAIGN_CLOSED
    assert_instant_equals(closed["closed_at"], "2026-08-02T18:00:00Z", "closed_at")
    assert closed["debrief_note"] == "No interactions; debrief circulated."
    assert_rate(closed["click_rate"], 0.0000, "click_rate")
    assert_rate(closed["report_rate"], 0.0000, "report_rate")
    assert_rate(closed["credential_rate"], 0.0000, "credential_rate")
    assert_rate(closed["resilience_ratio"], 0.0000, "resilience_ratio")

    settled = read_delivery(api, delivery["id"])
    assert_delivery(settled, state=DELIVERY_NO_INTERACTION,
                    outcome_class=OUTCOME_NO_INTERACTION)

    after = read_employee(api, employee["id"])
    assert after["consecutive_clean_simulations"] == 1
    assert after["repeat_clicker_tier"] == 0
    assert_risk_scores(after, provisional=0.00, settled=0.00)
    assert_ledgers(after, reserved_simulation_slots=0)


def test_offboarding_voids_the_assignment_and_excludes_the_queued_delivery(api):
    """One employment hop drives the assignment, the delivery and both ledgers.

    PRD §3.1: "every curriculum assignment of that employee whose state is
    `ASSIGNED`, `IN_PROGRESS`, `FAILED_ATTEMPT`, `OVERDUE` or `ESCALATED` becomes
    `VOIDED` with a `void_reason_code` of `EMPLOYEE_OFFBOARDED`; ... every
    simulation delivery of that employee still in state `QUEUED` becomes
    `EXCLUDED` with `excluded_reason` of `EMPLOYEE_OFFBOARDED`, decrementing
    `reserved_simulation_slots` once for each; and the derived fields are then
    recomputed, which drives `access_posture` to `NONE`, `active_suspension_count`
    to 0, `compliance_state` to `COMPLIANT`, and both risk scores to their new
    values."

    Design: Corner/state_machines/offboard_cascade_voids_assignments_and_releases_reservations
    """
    reset_clock(api)
    employee = register_employee(
        api, email="otto.off@corp.example", full_name="Otto Off",
        department="ENGINEERING", role_code="ENGINEER", hire_date="2016-07-07",
    )
    module = create_published_module(
        api, code="OFF-ANNUAL", title="Annual Awareness For Leavers",
        module_type="ANNUAL",
    )
    assignment = assign_module(api, employee, module, assignment_reason="ANNUAL")
    ctx = scheduled_campaign(
        api, scheduled_send_at="2026-08-20T09:00:00Z",
        name="ENG Offboard Wave", difficulty_tier=TIER_1,
        target_departments=["ENGINEERING"],
        template_overrides={
            "name": "Offboard Probe Template",
            "pretext_category": "PACKAGE_DELIVERY",
            "difficulty_tier": TIER_1,
            "theme_tags": ["CURIOSITY"],
            "credential_capture_enabled": False,
        },
    )
    delivery = delivery_for(api, ctx["campaign"]["id"], employee["id"])
    assert_delivery(delivery, state=DELIVERY_QUEUED)

    offboarded = validate_success(api.offboard_employee(employee["id"], ADMIN))
    assert offboarded["employment_status"] == EMPLOYMENT_OFFBOARDED

    voided = read_assignment(api, assignment["id"])
    assert_assignment(voided, state=ASSIGNMENT_VOIDED)
    assert voided["void_reason_code"] == VOID_REASON_EMPLOYEE_OFFBOARDED
    assert_instant_is_none(voided["next_reminder_due_at"], "next_reminder_due_at")

    excluded = read_delivery(api, delivery["id"])
    assert_delivery(excluded, state=DELIVERY_EXCLUDED, outcome_class="EXCLUDED")
    assert excluded["excluded_reason"] == EXCLUDED_REASON_EMPLOYEE_OFFBOARDED

    after = read_employee(api, employee["id"])
    assert_ledgers(after, reserved_simulation_slots=0, active_suspension_count=0)
    assert after["access_posture"] == POSTURE_NONE
    assert after["compliance_state"] == COMPLIANCE_COMPLIANT
    assert_risk_scores(after, provisional=0.00)


def test_a_report_after_a_click_is_a_self_loop_that_reclassifies_the_delivery(api):
    """The state stays CLICKED while the outcome class and the timings both move.

    PRD §3.9: "A `REPORT` that arrives *after* a click is the self-loop
    `CLICKED → CLICKED`. It sets `first_report_at` to the event's `occurred_at` if
    that field is still empty, computes `time_to_report_minutes`, and sets
    `outcome_class` to `CLICKED_THEN_REPORTED`; because the delivery's state does
    not move, the event's `superseding_effect` is `NONE`."

    Design: Corner/state_machines/delivery_report_after_click_sets_clicked_then_reported
    """
    reset_clock(api)
    employee = register_employee(
        api, email="rob.report@corp.example", full_name="Rob Report",
        department="SALES", role_code="IC", hire_date="2018-09-09",
    )
    ctx = running_campaign(
        api, scheduled_send_at="2026-08-02T09:00:00Z",
        name="SALES Report Wave", difficulty_tier=TIER_1,
        target_departments=["SALES"],
        template_overrides={
            "name": "Report After Click Probe",
            "pretext_category": "PACKAGE_DELIVERY",
            "difficulty_tier": TIER_1,
            "theme_tags": ["CURIOSITY"],
            "credential_capture_enabled": False,
        },
    )
    delivery = delivery_for(api, ctx["campaign"]["id"], employee["id"])

    set_clock(api, "2026-08-02T09:40:00Z")
    validate_success(
        api.append_interaction(
            delivery["id"],
            {"event_type": "CLICK", "occurred_at": "2026-08-02T09:10:00Z",
             "source": "LANDING_PAGE"},
            ADMIN,
        ),
        expected_status=201,
    )
    reported = validate_success(
        api.append_interaction(
            delivery["id"],
            {"event_type": "REPORT", "occurred_at": "2026-08-02T09:40:00Z",
             "source": "REPORT_BUTTON"},
            ADMIN,
        ),
        expected_status=201,
    )

    assert reported["superseding_effect"] == "NONE"
    assert reported["sequence_index"] == 2

    after = read_delivery(api, delivery["id"])
    assert_delivery(after, state=DELIVERY_CLICKED,
                    outcome_class=OUTCOME_CLICKED_THEN_REPORTED)
    assert_instant_equals(after["first_click_at"], "2026-08-02T09:10:00Z",
                          "first_click_at")
    assert_instant_equals(after["first_report_at"], "2026-08-02T09:40:00Z",
                          "first_report_at")
    assert after["time_to_report_minutes"] == 40
