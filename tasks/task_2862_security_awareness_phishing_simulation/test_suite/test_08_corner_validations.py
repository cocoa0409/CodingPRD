"""Domain validations: uniqueness, referential gates, budgets and windows.

Every test in this module translates exactly one non-stub instance of the
`validations` section of the §1.9 breadth index.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    ASSIGNMENT_ASSIGNED,
    CAMPAIGN_APPROVED,
    CAMPAIGN_DRAFT,
    DELIVERY_CLICKED,
    DELIVERY_DELIVERED,
    DELIVERY_REPORTED,
    EMPLOYMENT_OFFBOARDED,
    MODULE_DRAFT,
    MODULE_RETIRED,
    OUTCOME_CLICKED_NO_REPORT,
    OUTCOME_PENDING,
    TIER_1,
    TIER_2,
    TIER_3,
)
from test_helpers.assertions import (
    assert_assignment,
    assert_delivery,
    assert_instant_equals,
    assert_instant_is_none,
    assert_ledgers,
    assert_risk_scores,
    ids_of,
)
from test_helpers.factories import (
    campaign_payload,
    employee_payload,
    module_payload,
    schedule_payload,
)
from test_helpers.fixtures import (
    approved_campaign,
    approved_template,
    click,
    create_module,
    create_published_module,
    create_retired_module,
    delivery_for,
    managed_assignment,
    offboard,
    read_assignment,
    read_delivery,
    read_employee,
    register_employee,
    repeat_clicker_at_tier_two,
    reset_clock,
    running_campaign,
    set_clock,
)
from test_helpers.test_users import ADMIN, AUTHOR


def test_a_second_employee_cannot_reuse_an_existing_email(api):
    """Email uniqueness spans every row regardless of department or role.

    PRD §2.8: "Uniqueness: `email` on `Employee` and `code` on `TrainingModule` must
    be unique across all rows, producing `ERR_DUPLICATE_EMAIL` or
    `ERR_DUPLICATE_MODULE_CODE` (HTTP 409)."

    Design: Corner/validations/duplicate_employee_email_rejected_with_409
    """
    reset_clock(api)
    first = register_employee(
        api, email="dup@corp.example", full_name="First Dup",
        department="HR", role_code="IC", hire_date="2020-01-01",
    )

    validate_error(
        api.create_employee(
            employee_payload(email="dup@corp.example", full_name="Second Dup",
                             department="SALES", role_code="IC",
                             hire_date="2024-01-01"),
            ADMIN,
        ),
        ApiErrorId.DUPLICATE_EMAIL.value,
        expected_status=409,
    )

    rows = validate_success(api.list_employees({}, ADMIN))
    assert ids_of(rows) == [first["id"]]
    assert rows[0]["full_name"] == "First Dup"


def test_retiring_a_module_does_not_free_its_code(api):
    """Code uniqueness spans every row, live or retired.

    PRD §2.8: "Uniqueness: `email` on `Employee` and `code` on `TrainingModule` must
    be unique across all rows, producing `ERR_DUPLICATE_EMAIL` or
    `ERR_DUPLICATE_MODULE_CODE` (HTTP 409)."

    Design: Corner/validations/duplicate_module_code_rejected_even_after_the_first_is_retired
    """
    reset_clock(api)
    retired = create_retired_module(
        api, code="SEC-101", title="Security Basics", module_type="ANNUAL")
    assert retired["status"] == MODULE_RETIRED

    validate_error(
        api.create_module(
            module_payload(code="SEC-101", title="Security Basics v2",
                           module_type="ANNUAL"),
            ADMIN,
        ),
        ApiErrorId.DUPLICATE_MODULE_CODE.value,
        expected_status=409,
    )

    unchanged = validate_success(api.get_module(retired["id"], ADMIN))
    assert unchanged["status"] == MODULE_RETIRED
    assert unchanged["title"] == "Security Basics"

    # Only the code collided, so a different code still creates.
    fresh = validate_success(
        api.create_module(
            module_payload(code="SEC-102", title="Security Basics v2",
                           module_type="ANNUAL"),
            ADMIN,
        ),
        expected_status=201,
    )
    assert fresh["code"] == "SEC-102"


def test_a_campaign_may_not_outrank_the_template_it_sends(api):
    """A TIER_3 campaign on a TIER_1 template is refused at creation.

    PRD §3.7: "One referential check applies at creation: the rank of the campaign's
    `difficulty_tier` may not exceed the rank of its template's `difficulty_tier`,
    where `TIER_1_BASIC` ranks 1, `TIER_2_TARGETED` ranks 2 and `TIER_3_SPEAR` ranks
    3. A `TIER_3_SPEAR` campaign on a `TIER_2_TARGETED` template is refused with
    `ERR_CAMPAIGN_TIER_EXCEEDS_TEMPLATE` (HTTP 422)."

    Design: Corner/validations/campaign_tier_exceeding_template_tier_returns_422
    """
    reset_clock(api)
    register_employee(
        api, email="tier.probe@corp.example", full_name="Tia Tier",
        department="ENGINEERING", role_code="ENGINEER", hire_date="2019-09-09",
    )
    template = approved_template(
        api, name="Basic Tier Template", pretext_category="PACKAGE_DELIVERY",
        difficulty_tier=TIER_1, theme_tags=["CURIOSITY"],
        credential_capture_enabled=False,
    )

    validate_error(
        api.create_campaign(
            campaign_payload(template["id"], name="Spear On Basic",
                             difficulty_tier=TIER_3,
                             target_departments=["ENGINEERING"]),
            AUTHOR,
        ),
        ApiErrorId.CAMPAIGN_TIER_EXCEEDS_TEMPLATE.value,
        expected_status=422,
    )
    assert validate_success(api.list_campaigns({}, ADMIN)) == []


def test_a_campaign_tier_equal_to_the_template_tier_is_accepted(api):
    """The ceiling comparison is "may not exceed", so equality is legal.

    PRD §3.7: "the rank of the campaign's `difficulty_tier` may not exceed the rank
    of its template's `difficulty_tier`, where `TIER_1_BASIC` ranks 1,
    `TIER_2_TARGETED` ranks 2 and `TIER_3_SPEAR` ranks 3."

    Design: Corner/validations/campaign_tier_equal_to_template_tier_is_accepted
    """
    reset_clock(api)
    template = approved_template(
        api, name="Targeted Tier Template", pretext_category="SHARED_DOCUMENT",
        difficulty_tier=TIER_2, theme_tags=["AUTHORITY"],
        credential_capture_enabled=False,
    )

    campaign = validate_success(
        api.create_campaign(
            campaign_payload(template["id"], name="Equal Tier Wave",
                             difficulty_tier=TIER_2),
            AUTHOR,
        ),
        expected_status=201,
    )
    assert campaign["state"] == CAMPAIGN_DRAFT
    assert campaign["difficulty_tier"] == TIER_2
    assert campaign["template_id"] == template["id"]


def test_role_eligibility_only_bites_when_the_module_names_role_codes(api):
    """A FINANCE-only module refuses an ENGINEER; the unrestricted module does not.

    PRD §3.2: "The module's `applies_to_role_codes` must either be empty or contain
    the employee's current `role_code`, or the create is refused with
    `ERR_ROLE_NOT_ELIGIBLE_FOR_MODULE`."

    Design: Corner/validations/role_eligibility_rejects_assignment_for_an_uncovered_role_code
    """
    reset_clock(api)
    employee = register_employee(
        api, email="rita.role@corp.example", full_name="Rita Role",
        department="ENGINEERING", role_code="ENGINEER", hire_date="2019-01-01",
    )
    restricted = create_published_module(
        api, code="FIN-WIRE", title="Wire Fraud For Approvers",
        module_type="ROLE_SPECIFIC", applies_to_role_codes=["FINANCE_APPROVER"],
    )
    unrestricted = create_published_module(
        api, code="ALL-ANNUAL", title="Annual Awareness", module_type="ANNUAL")
    assert unrestricted["applies_to_role_codes"] == []

    validate_error(
        api.create_assignment(
            {"employee_id": employee["id"], "module_id": restricted["id"],
             "assignment_reason": "ROLE_CHANGE",
             "expected_employee_version": employee["version"]},
            ADMIN,
        ),
        ApiErrorId.ROLE_NOT_ELIGIBLE_FOR_MODULE.value,
        expected_status=422,
    )

    # The refused create bumped nothing, so the same version still matches.
    accepted = validate_success(
        api.create_assignment(
            {"employee_id": employee["id"], "module_id": unrestricted["id"],
             "assignment_reason": "ANNUAL",
             "expected_employee_version": employee["version"]},
            ADMIN,
        ),
        expected_status=201,
    )
    assert accepted["module_id"] == unrestricted["id"]
    assert_assignment(accepted, state=ASSIGNMENT_ASSIGNED)


def test_coaching_demands_a_remedial_module_that_is_also_published(api):
    """Two independent gates on one module_id, each with its own identifier.

    PRD §3.10: "The named module's `module_type` must be exactly `REMEDIAL`, or the
    request is refused with `ERR_COACHING_MODULE_TYPE_INVALID` (HTTP 422), and its
    `status` must be `PUBLISHED`, or the request is refused with
    `ERR_MODULE_NOT_PUBLISHED` (HTTP 409)."

    Design: Corner/validations/coaching_module_must_be_remedial_and_published
    """
    reset_clock(api)
    annual_published = create_published_module(
        api, code="COACH-ANNUAL", title="Annual Not Remedial",
        module_type="ANNUAL",
    )
    remedial_draft = create_module(
        api, code="COACH-DRAFT", title="Draft Remedial Coaching",
        module_type="REMEDIAL",
    )
    assert remedial_draft["status"] == MODULE_DRAFT

    ctx = repeat_clicker_at_tier_two(api, department="SALES",
                                     hire_date="2017-07-07")
    intervention = ctx["intervention"]
    assert intervention is not None

    validate_error(
        api.assign_coaching(
            intervention["id"], {"module_id": annual_published["id"]}, ADMIN),
        ApiErrorId.COACHING_MODULE_TYPE_INVALID.value,
        expected_status=422,
    )
    validate_error(
        api.assign_coaching(
            intervention["id"], {"module_id": remedial_draft["id"]}, ADMIN),
        ApiErrorId.MODULE_NOT_PUBLISHED.value,
        expected_status=409,
    )

    unchanged = validate_success(api.get_intervention(intervention["id"], ADMIN))
    assert unchanged["state"] == "OPEN"
    assert unchanged["coaching_assignment_id"] is None

    assignments = validate_success(
        api.list_assignments({"employee_id": ctx["employee"]["id"]}, ADMIN))
    assert assignments == [], "no remedial assignment was created"


def test_a_credential_submit_needs_the_template_capture_flag(api):
    """A CLICKED delivery on a capture-disabled template stays CLICKED.

    PRD §3.9: "The template behind the campaign must have
    `credential_capture_enabled` set to true, and there must be a prior `CLICK` on
    this delivery. ... while a `CREDENTIAL_SUBMIT` against a `CLICKED` delivery whose
    template has capture disabled is refused with `ERR_CREDENTIAL_CAPTURE_DISABLED`
    (HTTP 422)"

    Design: Corner/validations/credential_submit_on_capture_disabled_template_returns_422
    """
    reset_clock(api)
    employee = register_employee(
        api, email="carl.cap@corp.example", full_name="Carl Cap",
        department="IT", role_code="IT_ADMIN", hire_date="2018-08-08",
    )
    ctx = running_campaign(
        api, scheduled_send_at="2026-08-02T09:00:00Z",
        name="IT No Capture Wave", difficulty_tier=TIER_1,
        target_departments=["IT"],
        template_overrides={
            "name": "No Capture Template",
            "pretext_category": "IT_PASSWORD_RESET",
            "difficulty_tier": TIER_1,
            "theme_tags": ["URGENCY"],
            "credential_capture_enabled": False,
        },
    )
    delivery = delivery_for(api, ctx["campaign"]["id"], employee["id"])
    click(api, delivery["id"], "2026-08-02T09:30:00Z")

    validate_error(
        api.append_interaction(
            delivery["id"],
            {"event_type": "CREDENTIAL_SUBMIT",
             "occurred_at": "2026-08-02T09:31:00Z", "source": "LANDING_PAGE"},
            ADMIN,
        ),
        ApiErrorId.CREDENTIAL_CAPTURE_DISABLED.value,
        expected_status=422,
    )

    after = read_delivery(api, delivery["id"])
    assert_delivery(after, state=DELIVERY_CLICKED,
                    outcome_class=OUTCOME_CLICKED_NO_REPORT)
    assert_instant_is_none(after["credential_submitted_at"],
                           "credential_submitted_at")

    events = validate_success(
        api.list_interaction_events(delivery["id"], {}, ADMIN))
    assert len(events) == 1, "the rejected event was not appended"
    assert events[0]["event_type"] == "CLICK"

    employee_after = read_employee(api, employee["id"])
    assert employee_after["repeat_clicker_tier"] == 1
    assert_risk_scores(employee_after, provisional=11.00)


def test_a_credential_submit_needs_a_prior_click_on_that_delivery(api):
    """With capture enabled, a DELIVERED delivery still refuses the submit.

    PRD §3.9: "The two failures are distinct: a `CREDENTIAL_SUBMIT` against a
    `DELIVERED` or `REPORTED` delivery has no prior click and is refused with
    `ERR_CREDENTIAL_WITHOUT_CLICK` (HTTP 422)"

    PRD §3.9: "a delivery that is still `QUEUED` or that has reached one of the
    terminal states `CREDENTIAL_SUBMITTED`, `NO_INTERACTION` or `EXCLUDED` refuses
    the append with `ERR_DELIVERY_NOT_INTERACTABLE` (HTTP 409)."

    Design: Corner/validations/credential_submit_before_any_click_returns_422
    """
    reset_clock(api)
    employee = register_employee(
        api, email="nora.noclick@corp.example", full_name="Nora Noclick",
        department="FINANCE", role_code="FINANCE_APPROVER", hire_date="2018-05-05",
    )
    template = approved_template(
        api, name="Capture Enabled Template",
        pretext_category="IT_PASSWORD_RESET", difficulty_tier=TIER_2,
        theme_tags=["URGENCY"], credential_capture_enabled=True,
    )
    ctx = running_campaign(
        api, scheduled_send_at="2026-08-02T09:00:00Z", template=template,
        name="FIN Capture Wave", difficulty_tier=TIER_2,
        target_departments=["FINANCE"],
    )
    delivery = delivery_for(api, ctx["campaign"]["id"], employee["id"])

    set_clock(api, "2026-08-02T09:20:00Z")
    validate_error(
        api.append_interaction(
            delivery["id"],
            {"event_type": "CREDENTIAL_SUBMIT",
             "occurred_at": "2026-08-02T09:20:00Z", "source": "LANDING_PAGE"},
            ADMIN,
        ),
        ApiErrorId.CREDENTIAL_WITHOUT_CLICK.value,
        expected_status=422,
    )

    after = read_delivery(api, delivery["id"])
    assert_delivery(after, state=DELIVERY_DELIVERED, outcome_class=OUTCOME_PENDING)
    employee_after = read_employee(api, employee["id"])
    assert employee_after["repeat_clicker_tier"] == 0
    assert employee_after["consecutive_clean_simulations"] == 0

    # A QUEUED delivery is not interactable at all, which is a different refusal.
    later = approved_campaign(
        api, template=template, name="FIN Capture Wave 2",
        difficulty_tier=TIER_2, target_departments=["FINANCE"],
    )
    validate_success(
        api.schedule_campaign(
            later["campaign"]["id"],
            schedule_payload("2026-08-20T09:00:00Z",
                             later["campaign"]["version"]),
            AUTHOR,
        )
    )
    queued = delivery_for(api, later["campaign"]["id"], employee["id"])
    validate_error(
        api.append_interaction(
            queued["id"],
            {"event_type": "CREDENTIAL_SUBMIT",
             "occurred_at": "2026-08-02T09:20:00Z", "source": "LANDING_PAGE"},
            ADMIN,
        ),
        ApiErrorId.DELIVERY_NOT_INTERACTABLE.value,
        expected_status=409,
    )


def test_an_event_must_land_inside_the_delivery_to_clock_window(api):
    """Both ends of the window are refused; the lower bound itself is inclusive.

    PRD §3.9: "And the event may be neither backdated before its delivery nor
    postdated past the clock: `occurred_at` must be at or after the delivery's
    `delivered_at` and at or before the current logical clock, with any violation
    refused as `ERR_EVENT_OUT_OF_ORDER` (HTTP 422)."

    Design: Corner/validations/interaction_event_backdated_before_delivery_returns_422
    """
    reset_clock(api)
    employee = register_employee(
        api, email="otto.order@corp.example", full_name="Otto Order",
        department="HR", role_code="IC", hire_date="2019-02-02",
    )
    ctx = running_campaign(
        api, scheduled_send_at="2026-08-02T09:00:00Z",
        name="HR Order Wave", difficulty_tier=TIER_1,
        target_departments=["HR"],
        template_overrides={
            "name": "Order Probe Template",
            "pretext_category": "HR_BENEFITS_ENROLLMENT",
            "difficulty_tier": TIER_1,
            "theme_tags": ["AUTHORITY"],
            "credential_capture_enabled": False,
        },
    )
    delivery = delivery_for(api, ctx["campaign"]["id"], employee["id"])
    assert_instant_equals(delivery["delivered_at"], "2026-08-02T09:00:00Z",
                          "delivered_at")

    set_clock(api, "2026-08-02T09:30:00Z")
    validate_error(
        api.append_interaction(
            delivery["id"],
            {"event_type": "REPORT", "occurred_at": "2026-08-02T08:00:00Z",
             "source": "REPORT_BUTTON"},
            ADMIN,
        ),
        ApiErrorId.EVENT_OUT_OF_ORDER.value,
        expected_status=422,
    )
    validate_error(
        api.append_interaction(
            delivery["id"],
            {"event_type": "REPORT", "occurred_at": "2026-08-02T09:31:00Z",
             "source": "REPORT_BUTTON"},
            ADMIN,
        ),
        ApiErrorId.EVENT_OUT_OF_ORDER.value,
        expected_status=422,
    )

    # Exactly at delivered_at is inside the window because the bound is inclusive.
    accepted = validate_success(
        api.append_interaction(
            delivery["id"],
            {"event_type": "REPORT", "occurred_at": "2026-08-02T09:00:00Z",
             "source": "REPORT_BUTTON"},
            ADMIN,
        ),
        expected_status=201,
    )
    assert accepted["sequence_index"] == 1, "neither refusal consumed an index"

    after = read_delivery(api, delivery["id"])
    assert_delivery(after, state=DELIVERY_REPORTED)
    assert_instant_equals(after["first_report_at"], "2026-08-02T09:00:00Z",
                          "first_report_at")
    assert after["time_to_report_minutes"] == 0


def test_the_extension_budget_is_an_aggregate_not_a_per_grant_cap(api):
    """Two grants of 6 exceed a maximum of 10 that 6 then 4 does not.

    PRD §3.5: "First the budget: the assignment's existing
    `granted_extension_days` plus the requested `extension_days` must not exceed the
    module's `max_extension_days`, or the request is refused with
    `ERR_EXTENSION_LIMIT_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/extension_budget_aggregate_exceeds_module_maximum
    """
    reset_clock(api)
    ctx = managed_assignment(
        api, assignment_reason="ANNUAL",
        module_overrides={"code": "BUD-ANNUAL", "title": "Budget Probe Module",
                          "module_type": "ANNUAL"},
    )
    assert ctx["module"]["max_extension_days"] == 10
    assignment_id = ctx["assignment"]["id"]
    manager_headers = ctx["manager_headers"]
    assert_instant_equals(ctx["assignment"]["due_at"], "2026-08-31T00:00:00Z",
                          "due_at")

    first = validate_success(
        api.extend_assignment(assignment_id, {"extension_days": 6}, manager_headers))
    assert first["granted_extension_days"] == 6
    assert_instant_equals(first["effective_due_at"], "2026-09-06T00:00:00Z",
                          "effective_due_at")

    validate_error(
        api.extend_assignment(assignment_id, {"extension_days": 6}, manager_headers),
        ApiErrorId.EXTENSION_LIMIT_EXCEEDED.value,
        expected_status=422,
    )
    held = read_assignment(api, assignment_id)
    assert held["granted_extension_days"] == 6
    assert_instant_equals(held["effective_due_at"], "2026-09-06T00:00:00Z",
                          "effective_due_at")

    # Four days is exactly the remaining budget, so it lands on the ceiling.
    second = validate_success(
        api.extend_assignment(assignment_id, {"extension_days": 4}, manager_headers))
    assert second["granted_extension_days"] == 10
    assert_instant_equals(second["effective_due_at"], "2026-09-10T00:00:00Z",
                          "effective_due_at")
    assert_assignment(second, state=ASSIGNMENT_ASSIGNED)
    assert second["attempt_count"] == 0


def test_the_extension_window_demands_the_grant_move_the_deadline_forward(api):
    """A one-day grant twelve days after the deadline cannot reach the clock.

    PRD §3.5: "and the grant must actually move the deadline into the future,
    meaning the current clock must be at or before `due_at` advanced by the sum of
    `granted_extension_days` and the new `extension_days`. Failing either clause is
    refused with `ERR_EXTENSION_WINDOW_CLOSED` (HTTP 409)."

    Design: Corner/validations/extension_window_closed_when_the_grant_lands_in_the_past
    """
    reset_clock(api)
    ctx = managed_assignment(
        api, assignment_reason="REMEDIAL",
        module_overrides={"code": "WIN-REM", "title": "Window Probe Module",
                          "module_type": "REMEDIAL", "max_extension_days": 20},
    )
    assignment_id = ctx["assignment"]["id"]
    manager_headers = ctx["manager_headers"]
    assert_instant_equals(ctx["assignment"]["due_at"], "2026-08-08T00:00:00Z",
                          "due_at")

    set_clock(api, "2026-08-20T00:00:00Z")
    validate_error(
        api.extend_assignment(assignment_id, {"extension_days": 1}, manager_headers),
        ApiErrorId.EXTENSION_WINDOW_CLOSED.value,
        expected_status=409,
    )

    granted = validate_success(
        api.extend_assignment(assignment_id, {"extension_days": 13}, manager_headers))
    assert granted["granted_extension_days"] == 13
    assert_instant_equals(granted["effective_due_at"], "2026-08-21T00:00:00Z",
                          "effective_due_at")
    assert granted["escalation_level"] == 0
    # Offset 7 sits at position reminders_sent == 0, so the instant is due 7 days
    # before the new effective deadline.
    assert_instant_equals(granted["next_reminder_due_at"], "2026-08-14T00:00:00Z",
                          "next_reminder_due_at")


def test_submitting_a_campaign_for_review_needs_the_policy_acknowledgement(api):
    """A DRAFT campaign created without the flag cannot leave DRAFT.

    PRD §3.7: "Both require that `communication_policy_ack` is true, refusing
    otherwise with `ERR_COMMUNICATION_POLICY_NOT_ACKNOWLEDGED`, and both bump the
    campaign's `version`."

    Design: Corner/validations/submit_for_review_without_policy_acknowledgement_returns_422
    """
    reset_clock(api)
    template = approved_template(
        api, name="Policy Probe Template", pretext_category="SHARED_DOCUMENT",
        difficulty_tier=TIER_1, theme_tags=["CURIOSITY"],
        credential_capture_enabled=False,
    )

    campaign = validate_success(
        api.create_campaign(
            campaign_payload(template["id"], name="Unacknowledged Wave",
                             difficulty_tier=TIER_1,
                             communication_policy_ack=None),
            AUTHOR,
        ),
        expected_status=201,
    )
    assert campaign["state"] == CAMPAIGN_DRAFT

    validate_error(
        api.submit_campaign_for_review(campaign["id"], AUTHOR),
        ApiErrorId.COMMUNICATION_POLICY_NOT_ACKNOWLEDGED.value,
        expected_status=422,
    )

    unchanged = validate_success(api.get_campaign(campaign["id"], ADMIN))
    assert unchanged["state"] == CAMPAIGN_DRAFT
    assert unchanged["version"] == campaign["version"], "the refused submit bumped nothing"


def test_an_offboarded_employee_can_receive_nothing_further(api):
    """The employment axis closes both the assignment door and the offboard door.

    PRD §3.2: "The target employee's `employment_status` must be `ACTIVE`, or it is
    refused with `ERR_EMPLOYEE_OFFBOARDED`."

    PRD §3.1: "`employment_status` is either `ACTIVE` or `OFFBOARDED`, moves only
    forward, and moves only when a `ProgramAdmin` offboards the person. Offboarding
    an employee who is already `OFFBOARDED` is refused with
    `ERR_EMPLOYEE_OFFBOARDED`."

    Design: Corner/validations/offboarded_employee_cannot_receive_a_new_assignment_returns_409
    """
    reset_clock(api)
    employee = register_employee(
        api, email="olly.off@corp.example", full_name="Olly Off",
        department="HR", role_code="IC", hire_date="2017-03-03",
    )
    module = create_published_module(
        api, code="OFF-ANNUAL", title="Offboard Probe Module",
        module_type="ANNUAL",
    )

    gone = offboard(api, employee["id"])
    assert gone["employment_status"] == EMPLOYMENT_OFFBOARDED

    validate_error(
        api.create_assignment(
            {"employee_id": employee["id"], "module_id": module["id"],
             "assignment_reason": "ANNUAL",
             "expected_employee_version": gone["version"]},
            ADMIN,
        ),
        ApiErrorId.EMPLOYEE_OFFBOARDED.value,
        expected_status=409,
    )
    validate_error(
        api.offboard_employee(employee["id"], ADMIN),
        ApiErrorId.EMPLOYEE_OFFBOARDED.value,
        expected_status=409,
    )

    after = read_employee(api, employee["id"])
    assert after["employment_status"] == EMPLOYMENT_OFFBOARDED
    assert after["version"] == gone["version"], "neither refusal bumped the employee"
    assert validate_success(
        api.list_assignments({"employee_id": employee["id"]}, ADMIN)) == []


def test_scheduling_needs_at_least_one_evaluable_cohort_member(api):
    """A department with no ACTIVE members resolves to nothing and is refused.

    PRD §3.8: "Fourth, the resolved cohort must contain at least one evaluable
    member, or the schedule is refused with `ERR_EMPTY_TARGET_COHORT` (HTTP 422)."

    Design: Corner/validations/schedule_with_an_empty_target_cohort_returns_422
    """
    reset_clock(api)
    employee = register_employee(
        api, email="eng.only@corp.example", full_name="Ella Eng",
        department="ENGINEERING", role_code="ENGINEER", hire_date="2018-04-04",
    )
    template = approved_template(
        api, name="Cohort Probe Template", pretext_category="PACKAGE_DELIVERY",
        difficulty_tier=TIER_1, theme_tags=["CURIOSITY"],
        credential_capture_enabled=False,
    )

    empty = approved_campaign(
        api, template=template, name="Empty Cohort Wave",
        difficulty_tier=TIER_1, target_departments=["EXECUTIVE"],
    )
    empty_campaign = empty["campaign"]
    validate_error(
        api.schedule_campaign(
            empty_campaign["id"],
            schedule_payload("2026-08-05T09:00:00Z", empty_campaign["version"]),
            AUTHOR,
        ),
        ApiErrorId.EMPTY_TARGET_COHORT.value,
        expected_status=422,
    )

    unchanged = validate_success(api.get_campaign(empty_campaign["id"], ADMIN))
    assert unchanged["state"] == CAMPAIGN_APPROVED
    assert_instant_is_none(unchanged["scheduled_send_at"], "scheduled_send_at")
    assert validate_success(
        api.list_deliveries({"campaign_id": empty_campaign["id"]}, ADMIN)) == []
    assert_ledgers(read_employee(api, employee["id"]), reserved_simulation_slots=0)

    # The same schedule against a populated department resolves one member.
    populated = approved_campaign(
        api, template=template, name="Engineering Cohort Wave",
        difficulty_tier=TIER_1, target_departments=["ENGINEERING"],
    )
    scheduled = validate_success(
        api.schedule_campaign(
            populated["campaign"]["id"],
            schedule_payload("2026-08-05T09:00:00Z",
                             populated["campaign"]["version"]),
            AUTHOR,
        )
    )
    assert_instant_equals(scheduled["scheduled_send_at"], "2026-08-05T09:00:00Z",
                          "scheduled_send_at")
    rows = validate_success(
        api.list_deliveries({"campaign_id": populated["campaign"]["id"]}, ADMIN))
    assert len(rows) == 1
    assert rows[0]["employee_id"] == employee["id"]
