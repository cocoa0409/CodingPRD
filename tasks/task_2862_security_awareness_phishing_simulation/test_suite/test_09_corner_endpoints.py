"""Endpoint-surface claims: role change, sweeps, acknowledgement, lift and links.

Every test in this module translates exactly one non-stub instance of the
`endpoints` section of the §1.9 breadth index.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    ASSIGNMENT_ASSIGNED,
    ASSIGNMENT_OVERDUE,
    CAMPAIGN_APPROVED,
    CAMPAIGN_IN_REVIEW,
    CAMPAIGN_REJECTED,
    COMPLIANCE_AT_RISK,
    COMPLIANCE_COMPLIANT,
    CONSEQUENCE_ACTIVE,
    CONSEQUENCE_LIFTED,
    LIFT_REASON_MANUAL,
    NOTICE_ACKNOWLEDGED,
    NOTICE_SENT,
    POSTURE_NONE,
    TEMPLATE_BLOCKED,
    TIER_1,
    TIER_2,
    UNKNOWN_EMPLOYEE_UUID,
    WINDOW_ANNOUNCEMENT_MORATORIUM,
    WINDOW_SIMULATION_BLACKOUT,
)
from test_helpers.assertions import (
    assert_append_only_shape,
    assert_assignment,
    assert_consequence,
    assert_employee_axes,
    assert_instant_equals,
    assert_ledgers,
    assert_notice,
    assert_sweep_counters,
    find_by_id,
    ids_of,
)
from test_helpers.factories import (
    communication_window_payload,
    consequence_payload,
    incident_payload,
)
from test_helpers.fixtures import (
    approved_template,
    assign_module,
    create_campaign,
    create_published_module,
    list_consequences_for,
    list_notices_for,
    managed_assignment,
    read_assignment,
    read_employee,
    register_employee,
    register_manager,
    reset_clock,
    run_sweep,
    set_clock,
    sweep_at,
)
from test_helpers.test_users import (
    ADMIN,
    ANALYST,
    APPROVER,
    APPROVER_1_ID,
    AUTHOR,
)


def test_a_role_change_only_moves_future_eligibility(api):
    """The already-created assignment keeps its module across the role PATCH.

    PRD §3.1: "A `ProgramAdmin` may change an employee's `role_code`, which alters
    eligibility for role-specific modules on *future* assignments only —
    assignments already created are untouched — and bumps `Employee.version` by
    one."

    Design: Corner/endpoints/employee_role_change_leaves_existing_assignments_untouched
    """
    reset_clock(api)
    employee = register_employee(
        api, email="rowan.role@corp.example", full_name="Rowan Role",
        department="FINANCE", role_code="FINANCE_APPROVER", hire_date="2016-06-06",
    )
    finance_only = create_published_module(
        api, code="FIN-ONLY", title="Finance Only Module",
        module_type="ROLE_SPECIFIC", applies_to_role_codes=["FINANCE_APPROVER"],
    )
    it_only = create_published_module(
        api, code="IT-ONLY", title="IT Only Module",
        module_type="ROLE_SPECIFIC", applies_to_role_codes=["IT_ADMIN"],
    )
    assignment = assign_module(api, employee, finance_only,
                              assignment_reason="ROLE_CHANGE")

    before = read_employee(api, employee["id"])
    patched = validate_success(
        api.change_employee_role(employee["id"], {"role_code": "IT_ADMIN"}, ADMIN))
    assert patched["role_code"] == "IT_ADMIN"
    assert patched["version"] == before["version"] + 1

    untouched = read_assignment(api, assignment["id"])
    assert untouched["module_id"] == finance_only["id"]
    assert_assignment(untouched, state=ASSIGNMENT_ASSIGNED)

    # The IT-only module was ineligible a moment ago and is eligible now.
    second = validate_success(
        api.create_assignment(
            {"employee_id": employee["id"], "module_id": it_only["id"],
             "assignment_reason": "ROLE_CHANGE",
             "expected_employee_version": patched["version"]},
            ADMIN,
        ),
        expected_status=201,
    )
    assert second["module_id"] == it_only["id"]
    assert sorted(ids_of(validate_success(
        api.list_assignments({"employee_id": employee["id"]}, ADMIN)))) == sorted(
        [assignment["id"], second["id"]])


def test_a_sweep_over_an_empty_estate_reports_every_counter_at_zero(api):
    """The sweep is a pure scan, so its response shape is pinned without state.

    PRD §3.4: "A `ProgramAdmin` runs a compliance sweep, which evaluates the whole
    population against the current logical clock in four ordered steps and reports
    what it did: `assignments_scanned`, `reminders_sent_count`, `overdue_count`,
    `escalations_created_count`, `consequences_applied_count`, and the `swept_at`
    instant at which it ran."

    Design: Corner/endpoints/compliance_sweep_on_an_empty_estate_reports_all_zero_counters
    """
    reset_clock(api)
    employee = register_employee(
        api, email="zoe.zero@corp.example", full_name="Zoe Zero",
        department="HR", role_code="IC", hire_date="2019-11-11",
    )

    sweep = run_sweep(api)
    assert_sweep_counters(sweep, assignments_scanned=0, reminders_sent_count=0,
                          overdue_count=0, escalations_created_count=0,
                          consequences_applied_count=0)
    assert_instant_equals(sweep["swept_at"], "2026-08-01T00:00:00Z", "swept_at")

    after = read_employee(api, employee["id"])
    assert_employee_axes(after, compliance_state=COMPLIANCE_COMPLIANT,
                         access_posture=POSTURE_NONE)
    assert after["version"] == employee["version"], "a pure scan bumps nothing"
    assert validate_success(api.list_notices({}, ADMIN)) == []
    assert validate_success(api.list_access_consequences({}, ADMIN)) == []


def test_one_sweep_reaches_a_per_assignment_verdict_for_each_row(api):
    """The overdue REMEDIAL row escalates while the far-future ANNUAL row is left.

    PRD §3.4: "Steps A through D run in that order within a single sweep, which is
    why an assignment can become overdue and be escalated by the very same run."

    PRD §3.4: "Any assignment in `ASSIGNED`, `IN_PROGRESS` or `FAILED_ATTEMPT` whose
    `effective_due_at` is *strictly* earlier than the current clock moves to
    `OVERDUE`."

    Design: Corner/endpoints/compliance_sweep_treats_each_assignment_independently
    """
    reset_clock(api)
    manager = register_manager(api, department="IT", hire_date="2010-01-01")
    first = register_employee(
        api, email="abe.bulk@corp.example", full_name="Abe Bulk",
        department="IT", role_code="IT_ADMIN", hire_date="2018-01-01",
        manager_id=manager["id"],
    )
    second = register_employee(
        api, email="bea.bulk@corp.example", full_name="Bea Bulk",
        department="IT", role_code="IT_ADMIN", hire_date="2018-02-02",
        manager_id=manager["id"],
    )
    remedial = create_published_module(api, code="BULK-REM",
                                      title="Bulk Remedial", module_type="REMEDIAL")
    annual = create_published_module(api, code="BULK-ANN",
                                     title="Bulk Annual", module_type="ANNUAL")
    overdue_row = assign_module(api, first, remedial, assignment_reason="REMEDIAL")
    future_row = assign_module(api, second, annual, assignment_reason="ANNUAL")
    assert_instant_equals(overdue_row["due_at"], "2026-08-08T00:00:00Z", "due_at")
    assert_instant_equals(future_row["due_at"], "2026-08-31T00:00:00Z", "due_at")

    sweep = sweep_at(api, "2026-08-09T00:00:00Z")
    assert_sweep_counters(sweep, assignments_scanned=2, reminders_sent_count=1,
                          overdue_count=1, escalations_created_count=1,
                          consequences_applied_count=0)

    notices_for_overdue = list_notices_for(api, overdue_row["id"])
    assert len(notices_for_overdue) == 1
    assert_notice(notices_for_overdue[0], state=NOTICE_SENT, level=1)
    assert list_notices_for(api, future_row["id"]) == []

    assert_employee_axes(read_employee(api, first["id"]),
                         compliance_state=COMPLIANCE_AT_RISK,
                         access_posture=POSTURE_NONE)
    assert_employee_axes(read_employee(api, second["id"]),
                         compliance_state=COMPLIANCE_COMPLIANT)

    untouched = read_assignment(api, future_row["id"])
    assert_assignment(untouched, state=ASSIGNMENT_ASSIGNED, reminders_sent=0)
    assert_instant_equals(untouched["next_reminder_due_at"],
                          "2026-08-24T00:00:00Z", "next_reminder_due_at")


def test_acknowledging_a_notice_records_intent_and_nothing_more(api):
    """The ladder stays where it is and the second acknowledge is refused.

    PRD §3.5: "Acknowledgement bumps the notice's `version` by one and — this is the
    point worth stating twice — **does not lift any access consequence**.
    Acknowledging that a report is late is not the same as the report becoming
    un-late."

    PRD §3.5: "acknowledging a notice that is already `ACKNOWLEDGED` or already
    `EXPIRED` is refused with `ERR_NOTICE_STATE_INVALID`."

    Design: Corner/endpoints/escalation_notice_acknowledgement_is_not_remediation
    """
    reset_clock(api)
    ctx = managed_assignment(
        api, assignment_reason="REMEDIAL",
        module_overrides={"code": "ACK-REM", "title": "Ack Probe Remedial",
                          "module_type": "REMEDIAL"},
    )
    manager_headers = ctx["manager_headers"]
    sweep_at(api, "2026-08-09T00:00:00Z")
    notices = list_notices_for(api, ctx["assignment"]["id"], state=NOTICE_SENT)
    assert len(notices) == 1
    notice = notices[0]

    note = "Booked a 1:1 for 2026-08-10 and set a completion deadline."
    acknowledged = validate_success(
        api.acknowledge_notice(notice["id"], {"action_plan_note": note},
                               manager_headers))
    assert_notice(acknowledged, state=NOTICE_ACKNOWLEDGED, level=1)
    assert_instant_equals(acknowledged["acknowledged_at"], "2026-08-09T00:00:00Z",
                          "acknowledged_at")
    assert acknowledged["action_plan_note"] == note

    validate_error(
        api.acknowledge_notice(notice["id"], {"action_plan_note": "Second attempt."},
                               manager_headers),
        ApiErrorId.NOTICE_STATE_INVALID.value,
        expected_status=409,
    )
    still = validate_success(api.get_notice(notice["id"], ADMIN))
    assert still["action_plan_note"] == note, "the refused call overwrote the note"

    # Acknowledging is not remediating: the assignment is still late.
    assignment = read_assignment(api, ctx["assignment"]["id"])
    assert_assignment(assignment, state=ASSIGNMENT_OVERDUE, escalation_level=1)
    assert_employee_axes(read_employee(api, ctx["employee"]["id"]),
                         compliance_state=COMPLIANCE_AT_RISK,
                         access_posture=POSTURE_NONE)


def test_lifting_a_consequence_twice_is_refused_and_keeps_the_first_stamp(api):
    """LIFTED is terminal, so the second discharge changes nothing.

    PRD §3.6: "It is legal only from `ACTIVE`; attempting it against a row already
    `LIFTED` or already `VOIDED` is refused with `ERR_CONSEQUENCE_ALREADY_LIFTED`.
    On success the row becomes `LIFTED`, `lifted_at` is stamped with the clock, the
    employee's `access_posture` is recomputed as the posture matching the highest
    `severity_rank` among the rows that remain `ACTIVE`, `active_suspension_count`
    is recomputed, and both the consequence's `version` and the employee's `version`
    are bumped by one."

    Design: Corner/endpoints/access_consequence_lifted_twice_returns_409_already_lifted
    """
    reset_clock(api)
    employee = register_employee(
        api, email="lena.lift@corp.example", full_name="Lena Lift",
        department="SALES", role_code="IC", hire_date="2019-04-04",
    )
    consequence = validate_success(
        api.apply_access_consequence(
            employee["id"],
            consequence_payload(employee["version"],
                                reason_code="POLICY_BREACH_INVESTIGATION"),
            ADMIN,
        ),
        expected_status=201,
    )
    assert_consequence(consequence, state=CONSEQUENCE_ACTIVE)

    set_clock(api, "2026-08-03T00:00:00Z")
    lifted = validate_success(
        api.lift_access_consequence(
            consequence["id"], {"lift_reason_code": LIFT_REASON_MANUAL}, ADMIN))
    assert_consequence(lifted, state=CONSEQUENCE_LIFTED,
                       lift_reason_code=LIFT_REASON_MANUAL)
    assert_instant_equals(lifted["lifted_at"], "2026-08-03T00:00:00Z", "lifted_at")

    validate_error(
        api.lift_access_consequence(
            consequence["id"], {"lift_reason_code": LIFT_REASON_MANUAL}, ADMIN),
        ApiErrorId.CONSEQUENCE_ALREADY_LIFTED.value,
        expected_status=409,
    )

    final = validate_success(api.get_access_consequence(consequence["id"], ADMIN))
    assert_instant_equals(final["lifted_at"], "2026-08-03T00:00:00Z", "lifted_at")
    assert final["version"] == consequence["version"] + 1, "version advanced once"

    after = read_employee(api, employee["id"])
    assert_employee_axes(after, access_posture=POSTURE_NONE)
    assert_ledgers(after, active_suspension_count=0)
    rows = list_consequences_for(api, employee["id"])
    assert ids_of(rows) == [consequence["id"]]


def test_blocking_a_template_shuts_the_approve_path_but_not_the_reject_path(api):
    """The pending approve fails on the template while the reject still lands.

    PRD §3.7: "third, the template's `review_state` must be exactly
    `APPROVED_FOR_USE`, or the request is refused with `ERR_TEMPLATE_NOT_APPROVED`
    (HTTP 409) — which is what a `DRAFT` or `BLOCKED` template yields."

    PRD §3.7: "It enforces segregation of duties in exactly the same way — an
    approver may not reject their own campaign either, and the refusal is again
    `ERR_SEGREGATION_OF_DUTIES_VIOLATION` — but it runs **no template checks
    whatsoever**."

    Design: Corner/endpoints/blocked_template_prevents_campaign_approval
    """
    reset_clock(api)
    template = approved_template(
        api, name="Block Probe Template", pretext_category="INVOICE_APPROVAL",
        difficulty_tier=TIER_2, theme_tags=["AUTHORITY"],
        credential_capture_enabled=False,
    )
    campaign = create_campaign(api, template["id"], AUTHOR,
                              name="Blocked Template Wave", difficulty_tier=TIER_1)
    in_review = validate_success(
        api.submit_campaign_for_review(campaign["id"], AUTHOR))
    assert in_review["state"] == CAMPAIGN_IN_REVIEW

    reason = "Pretext retired after a real BEC wave used the same invoice lure."
    blocked = validate_success(
        api.block_template(template["id"], {"blocked_reason": reason}, ADMIN))
    assert blocked["review_state"] == TEMPLATE_BLOCKED
    assert blocked["blocked_reason"] == reason

    validate_error(
        api.approve_campaign(campaign["id"], APPROVER),
        ApiErrorId.TEMPLATE_NOT_APPROVED.value,
        expected_status=409,
    )
    held = validate_success(api.get_campaign(campaign["id"], APPROVER))
    assert held["state"] == CAMPAIGN_IN_REVIEW
    assert held["reviewer_user_id"] is None

    # Rejection runs no template checks at all, so it is still available.
    rejected = validate_success(
        api.reject_campaign(
            campaign["id"],
            {"rejection_reason": "Template was blocked; rebuild on another lure."},
            APPROVER,
        )
    )
    assert rejected["state"] == CAMPAIGN_REJECTED
    assert rejected["reviewer_user_id"] == APPROVER_1_ID


def test_rejection_is_a_re_enterable_waypoint_not_a_terminus(api):
    """The same campaign walks IN_REVIEW → REJECTED → IN_REVIEW → APPROVED.

    PRD §3.7: "**Rejection** moves `IN_REVIEW → REJECTED` and requires a
    `rejection_reason`. ... On success `reviewer_user_id` is set to the rejecting
    `X-User-ID`, `rejection_reason` is stored, and `version` is bumped."

    PRD §3.7: "`REJECTED → IN_REVIEW` for a resubmission after feedback. ... The
    resubmission path additionally clears `rejection_reason` back to empty. The
    `IN_REVIEW → REJECTED → IN_REVIEW` cycle may repeat without bound."

    Design: Corner/endpoints/campaign_reject_then_resubmit_returns_to_review
    """
    reset_clock(api)
    template = approved_template(
        api, name="Reject Probe Template", pretext_category="SHARED_DOCUMENT",
        difficulty_tier=TIER_2, theme_tags=["CURIOSITY"],
        credential_capture_enabled=False,
    )
    campaign = create_campaign(api, template["id"], AUTHOR,
                              name="Reject Cycle Wave", difficulty_tier=TIER_2)
    in_review = validate_success(
        api.submit_campaign_for_review(campaign["id"], AUTHOR))
    assert in_review["state"] == CAMPAIGN_IN_REVIEW

    reason = "Send window overlaps the quarterly close; pick another week."
    rejected = validate_success(
        api.reject_campaign(campaign["id"], {"rejection_reason": reason}, APPROVER))
    assert rejected["state"] == CAMPAIGN_REJECTED
    assert rejected["reviewer_user_id"] == APPROVER_1_ID
    assert rejected["rejection_reason"] == reason

    back = validate_success(api.submit_campaign_for_review(campaign["id"], AUTHOR))
    assert back["state"] == CAMPAIGN_IN_REVIEW
    assert not back["rejection_reason"], "resubmission clears the rejection reason"

    approved = validate_success(api.approve_campaign(campaign["id"], APPROVER))
    assert approved["state"] == CAMPAIGN_APPROVED
    assert approved["version"] == in_review["version"] + 3, (
        "reject, resubmit and approve each bump the campaign version once"
    )


def test_both_communication_window_types_coexist_on_the_register(api):
    """A department-scoped blackout and an org-wide moratorium are both stored.

    PRD §2.10: "a `CommunicationWindow` of `window_type` `SIMULATION_BLACKOUT` or
    `ANNOUNCEMENT_MORATORIUM`, carrying a `start_at`, an `end_at` strictly after it,
    a free-text `reason` and an optional `scope_department` (where the absence of a
    department means every department), declares an interval in which simulation
    traffic is restricted."

    PRD §2.8: "Request well-formedness (`ERR_INVALID_REQUEST`): required body fields
    present, enum members recognised, arrays free of duplicate entries, integers
    inside their declared ranges, `score_pct` between 0 and 100 inclusive,
    `extension_days` at least 1, `limit` between 1 and 100 inclusive, `offset` at
    least 0, `end_at` strictly after `start_at`, and `period_end` strictly after
    `period_start`."

    Design: Corner/endpoints/communication_windows_created_and_listed_by_type
    """
    reset_clock(api)
    blackout = validate_success(
        api.create_communication_window(
            communication_window_payload(
                "2026-09-28T00:00:00Z", "2026-10-02T23:59:59Z",
                window_type=WINDOW_SIMULATION_BLACKOUT,
                reason="Quarterly close for the finance organisation.",
                scope_department="FINANCE",
            ),
            ADMIN,
        ),
        expected_status=201,
    )
    moratorium = validate_success(
        api.create_communication_window(
            communication_window_payload(
                "2026-12-24T00:00:00Z", "2026-12-26T00:00:00Z",
                window_type=WINDOW_ANNOUNCEMENT_MORATORIUM,
                reason="Company-wide holiday shutdown.",
            ),
            ADMIN,
        ),
        expected_status=201,
    )

    assert blackout["window_type"] == WINDOW_SIMULATION_BLACKOUT
    assert blackout["scope_department"] == "FINANCE"
    assert_instant_equals(blackout["start_at"], "2026-09-28T00:00:00Z", "start_at")
    assert_instant_equals(blackout["end_at"], "2026-10-02T23:59:59Z", "end_at")
    assert moratorium["window_type"] == WINDOW_ANNOUNCEMENT_MORATORIUM
    assert moratorium["scope_department"] is None, "no department means every one"
    assert_append_only_shape(blackout, "communication window")
    assert_append_only_shape(moratorium, "communication window")

    rows = validate_success(api.list_communication_windows({}, AUTHOR))
    assert ids_of(rows) == [blackout["id"], moratorium["id"]], (
        "list results are ordered by created_at ascending"
    )
    assert find_by_id(rows, blackout["id"])["reason"] == (
        "Quarterly close for the finance organisation."
    )

    # end_at must be strictly after start_at, so an equal pair is malformed.
    validate_error(
        api.create_communication_window(
            communication_window_payload(
                "2026-11-01T00:00:00Z", "2026-11-01T00:00:00Z",
                window_type=WINDOW_SIMULATION_BLACKOUT,
                reason="Zero-length window.",
            ),
            ADMIN,
        ),
        ApiErrorId.INVALID_REQUEST.value,
        expected_status=400,
    )
    assert len(validate_success(api.list_communication_windows({}, ADMIN))) == 2


def test_an_incident_may_name_a_root_cause_employee_and_be_found_by_it(api):
    """The optional cross-reference is resolved when supplied and filterable after.

    PRD §3.10: "optionally a `root_cause_employee_id` naming the employee who was
    the initial access vector. ... They may be read individually or listed with
    filters on `department`, `incident_type`, `root_cause_employee_id`,
    `occurred_from` and `occurred_to`, plus `limit` and `offset`."

    PRD §2.8: "an unknown `employee_id`, `manager_id` or `root_cause_employee_id`
    yields `ERR_EMPLOYEE_NOT_FOUND`"

    Design: Corner/endpoints/incident_links_root_cause_employee_and_filters_by_it
    """
    reset_clock(api)
    employee = register_employee(
        api, email="ivan.incident@corp.example", full_name="Ivan Incident",
        department="ENGINEERING", role_code="ENGINEER", hire_date="2017-01-01",
    )

    linked = validate_success(
        api.create_incident(
            incident_payload(
                incident_type="CREDENTIAL_PHISH", severity="HIGH",
                department="ENGINEERING", occurred_at="2026-07-30T14:00:00Z",
                summary="Reused password harvested by a real lure.",
                root_cause_employee_id=employee["id"],
            ),
            ANALYST,
        ),
        expected_status=201,
    )
    unlinked = validate_success(
        api.create_incident(
            incident_payload(
                incident_type="CREDENTIAL_PHISH", severity="LOW",
                department="ENGINEERING", occurred_at="2026-07-31T14:00:00Z",
                summary="Unattributed credential harvesting attempt.",
            ),
            ANALYST,
        ),
        expected_status=201,
    )
    assert linked["root_cause_employee_id"] == employee["id"]
    assert unlinked["root_cause_employee_id"] is None
    assert linked["phish_related"] is True
    assert unlinked["phish_related"] is True

    filtered = validate_success(
        api.list_incidents({"root_cause_employee_id": employee["id"]}, ANALYST))
    assert ids_of(filtered) == [linked["id"]]

    validate_error(
        api.create_incident(
            incident_payload(
                incident_type="BEC", severity="MEDIUM", department="ENGINEERING",
                occurred_at="2026-08-01T00:00:00Z",
                summary="Unknown root cause reference.",
                root_cause_employee_id=UNKNOWN_EMPLOYEE_UUID,
            ),
            ANALYST,
        ),
        ApiErrorId.EMPLOYEE_NOT_FOUND.value,
        expected_status=404,
    )
    assert len(validate_success(api.list_incidents({}, ANALYST))) == 2
