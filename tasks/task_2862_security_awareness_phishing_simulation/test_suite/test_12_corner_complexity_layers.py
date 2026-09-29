"""Cross-cutting layers and the consistency model of the whole program.

Every test in this module translates exactly one non-stub instance of either the
`cross-cutting complexity layers` section or the `consistency model` section of
the §1.9 breadth index.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    ASSIGNMENT_ASSIGNED,
    ASSIGNMENT_COMPLETED,
    CAMPAIGN_CLOSED,
    COMPLIANCE_COMPLIANT,
    COMPLIANCE_DELINQUENT,
    CONSEQUENCE_ACTIVE,
    CONSEQUENCE_LIFTED,
    DELIVERY_CREDENTIAL_SUBMITTED,
    EVENT_CREDENTIAL_SUBMIT,
    LIFT_REASON_TRAINING_COMPLETED,
    NOTICE_EXPIRED,
    NOTICE_SENT,
    OUTCOME_CREDENTIAL_SUBMITTED,
    POSTURE_ELEVATED_REVIEW,
    POSTURE_NONE,
    POSTURE_SUSPENDED,
    SOURCE_LANDING_PAGE,
    TIER_2,
)
from test_helpers.assertions import (
    assert_assignment,
    assert_consequence,
    assert_delivery,
    assert_employee_axes,
    assert_instant_equals,
    assert_instant_is_none,
    assert_notice,
    assert_rate,
    assert_risk_scores,
)
from test_helpers.factories import (
    assignment_payload,
    consequence_payload,
    interaction_payload,
)
from test_helpers.fixtures import (
    assign_module,
    click,
    create_published_module,
    delivered_simulation,
    list_consequences_for,
    list_notices_for,
    read_assignment,
    read_delivery,
    read_employee,
    register_employee,
    register_manager,
    reset_clock,
    run_sweep,
    set_clock,
)
from test_helpers.test_users import ADMIN, make_learner_headers


def test_one_behind_employee_tokens_are_refused_on_both_employee_writes(api):
    """The same OCC field guards assignment creation and consequence creation.

    PRD §2.7: "Creating a curriculum assignment requires `expected_employee_version`,
    carrying the client's last observed `version` of the target `Employee`. If that
    value does not equal the employee row's current `version`, the create is rejected
    with `ERR_STALE_EMPLOYEE_VERSION` (HTTP 412)."

    PRD §2.7: "Applying an access consequence to an employee likewise requires
    `expected_employee_version`, matched against the same employee row's current
    `version`, and a mismatch is likewise rejected with `ERR_STALE_EMPLOYEE_VERSION`
    (HTTP 412)."

    Design: Corner/cross-cutting complexity layers/stale_employee_version_rejected_on_both_employee_write_endpoints
    """
    reset_clock(api)
    employee = register_employee(
        api, email="occ.probe@corp.example", full_name="Otto Occ",
        department="FINANCE", role_code="FINANCE_APPROVER", hire_date="2018-09-09",
    )
    module = create_published_module(
        api, code="OCC-ANN", title="OCC Probe Module", module_type="ANNUAL")
    current = employee["version"]
    behind = current - 1

    validate_error(
        api.create_assignment(
            assignment_payload(employee["id"], module["id"], behind,
                               assignment_reason="ANNUAL"),
            ADMIN,
        ),
        ApiErrorId.STALE_EMPLOYEE_VERSION.value,
        expected_status=412,
    )
    validate_error(
        api.apply_access_consequence(
            employee["id"], consequence_payload(behind), ADMIN),
        ApiErrorId.STALE_EMPLOYEE_VERSION.value,
        expected_status=412,
    )
    assert read_employee(api, employee["id"])["version"] == current
    assert validate_success(
        api.list_assignments({"employee_id": employee["id"]}, ADMIN)) == []
    assert list_consequences_for(api, employee["id"]) == []

    assignment = validate_success(
        api.create_assignment(
            assignment_payload(employee["id"], module["id"], current,
                               assignment_reason="ANNUAL"),
            ADMIN,
        ),
        expected_status=201,
    )
    assert read_employee(api, employee["id"])["version"] == current + 1

    # The successful write made the previously-current token stale in turn.
    validate_error(
        api.apply_access_consequence(
            employee["id"], consequence_payload(current), ADMIN),
        ApiErrorId.STALE_EMPLOYEE_VERSION.value,
        expected_status=412,
    )
    assert_assignment(read_assignment(api, assignment["id"]),
                      state=ASSIGNMENT_ASSIGNED)
    assert_employee_axes(read_employee(api, employee["id"]),
                         access_posture=POSTURE_NONE)


def test_two_failure_events_on_one_delivery_are_still_one_failure(api):
    """The tier threshold counts deliveries while the score charges once.

    PRD §3.9: "the employee's `repeat_clicker_tier` is recomputed — with a delivery
    counting as at most one failure no matter how many failure events it carries"

    PRD §3.10: "The penalty side sums three weighted counts: 18 points for each
    in-scope delivery whose `credential_submitted_at` is set, 10 points for each
    in-scope delivery whose `first_click_at` is set but whose `credential_submitted_at`
    is not"

    Design: Corner/cross-cutting complexity layers/repeat_threshold_counts_deliveries_not_failure_events
    """
    reset_clock(api)
    employee = register_employee(
        api, email="cass.cred@corp.example", full_name="Cass Cred",
        department="FINANCE", role_code="FINANCE_APPROVER", hire_date="2014-04-04",
    )
    ctx = delivered_simulation(
        api, employee=employee, difficulty_tier=TIER_2,
        credential_capture_enabled=True, name="FIN Threshold Wave",
    )
    delivery_id = ctx["delivery"]["id"]

    click(api, delivery_id, "2026-08-02T09:30:00Z")
    set_clock(api, "2026-08-02T09:31:00Z")
    submitted = validate_success(
        api.append_interaction(
            delivery_id,
            interaction_payload("2026-08-02T09:31:00Z",
                                event_type=EVENT_CREDENTIAL_SUBMIT,
                                source=SOURCE_LANDING_PAGE),
            ADMIN,
        ),
        expected_status=201,
    )
    assert submitted["sequence_index"] == 2

    delivery = read_delivery(api, delivery_id)
    assert_delivery(delivery, state=DELIVERY_CREDENTIAL_SUBMITTED,
                    outcome_class=OUTCOME_CREDENTIAL_SUBMITTED)
    assert_instant_equals(delivery["first_click_at"], "2026-08-02T09:30:00Z",
                          "first_click_at")
    assert_instant_equals(delivery["credential_submitted_at"],
                          "2026-08-02T09:31:00Z", "credential_submitted_at")

    after = read_employee(api, employee["id"])
    assert after["repeat_clicker_tier"] == 1
    assert validate_success(
        api.list_interventions({"employee_id": employee["id"]}, ADMIN)) == []
    # 18 x 1.10 == 19.80: the click weight is not added on top of the credential.
    assert_risk_scores(after, provisional=19.80, settled=0.00)


def test_finishing_the_training_is_the_earned_unwind_of_the_whole_chain(api):
    """Completion lifts every consequence and expires every open notice.

    PRD §3.3: "Every access consequence whose `source_assignment_id` is this
    assignment and whose state is `ACTIVE` becomes `LIFTED`, with `lifted_at` stamped
    and `lift_reason_code` recorded as `TRAINING_COMPLETED` — this is the earned exit,
    not a compensated one, because the obligation was genuinely discharged."

    PRD §3.3: "Every escalation notice belonging to this assignment whose state is
    `SENT` becomes `EXPIRED`; notices already `ACKNOWLEDGED` are left alone, because
    the compensation cascade only ever touches notices still in `SENT`."

    Design: Corner/cross-cutting complexity layers/training_completion_cascade_lifts_consequences_and_expires_notices
    """
    reset_clock(api)
    manager = register_manager(
        api, email="mgr.cascade@corp.example", full_name="Cara Manager",
        department="IT", hire_date="2011-11-11",
    )
    report = register_employee(
        api, email="rep.cascade@corp.example", full_name="Carl Report",
        department="IT", role_code="IT_ADMIN", hire_date="2019-12-12",
        manager_id=manager["id"],
    )
    module = create_published_module(
        api, code="CAS-REM", title="Cascade Probe Remedial",
        module_type="REMEDIAL")
    assignment = assign_module(api, report, module, assignment_reason="REMEDIAL")

    set_clock(api, "2026-08-22T00:00:00Z")
    run_sweep(api)

    escalated = read_assignment(api, assignment["id"])
    assert_assignment(escalated, escalation_level=3)
    assert len(list_notices_for(api, assignment["id"], state=NOTICE_SENT)) == 3
    active = list_consequences_for(api, report["id"], state=CONSEQUENCE_ACTIVE)
    assert sorted(row["severity_rank"] for row in active) == [2, 3]
    assert_employee_axes(read_employee(api, report["id"]),
                         compliance_state=COMPLIANCE_DELINQUENT,
                         access_posture=POSTURE_SUSPENDED)
    assert read_employee(api, report["id"])["active_suspension_count"] == 1

    learner = make_learner_headers(report["id"])
    validate_success(api.start_assignment(assignment["id"], learner))
    completed = validate_success(
        api.submit_assignment(assignment["id"], {"score_pct": 90}, learner))
    assert_assignment(completed, state=ASSIGNMENT_COMPLETED, attempt_count=1,
                      last_score_pct=90)
    assert_instant_equals(completed["completed_at"], "2026-08-22T00:00:00Z",
                          "completed_at")
    assert_instant_is_none(completed["next_reminder_due_at"],
                           "next_reminder_due_at")

    for row in list_consequences_for(api, report["id"]):
        assert_consequence(row, state=CONSEQUENCE_LIFTED,
                           lift_reason_code=LIFT_REASON_TRAINING_COMPLETED)
        assert_instant_equals(row["lifted_at"], "2026-08-22T00:00:00Z", "lifted_at")
    notices = list_notices_for(api, assignment["id"])
    assert len(notices) == 3
    for notice in notices:
        assert_notice(notice, state=NOTICE_EXPIRED)
        assert_instant_is_none(notice["acknowledged_at"], "acknowledged_at")

    released = read_employee(api, report["id"])
    assert_employee_axes(released, compliance_state=COMPLIANCE_COMPLIANT,
                         access_posture=POSTURE_NONE)
    assert released["active_suspension_count"] == 0
    assert_risk_scores(released, provisional=0.00, settled=0.00)
    # The ladder history itself is not rewritten by the unwind.
    assert_assignment(read_assignment(api, assignment["id"]), escalation_level=3)


def test_closing_the_campaign_is_the_variant_reconciliation_event(api):
    """The same click scores 11.00 twice once its campaign is CLOSED.

    PRD §3.10: "For `risk_score_provisional`, the in-flight view used for operational
    triage, in-scope deliveries are those whose campaign is in state `RUNNING` or
    `CLOSED`, and the count of settled clean deliveries is forced to zero"

    PRD §3.10: "For `risk_score_settled`, the audit view that feeds the effectiveness
    report, in-scope deliveries are only those whose campaign is in state `CLOSED`"

    Design: Corner/cross-cutting complexity layers/risk_score_settled_reconciles_when_the_campaign_closes
    """
    reset_clock(api)
    employee = register_employee(
        api, email="vera.variant@corp.example", full_name="Vera Variant",
        department="ENGINEERING", role_code="ENGINEER", hire_date="2014-02-02",
    )
    ctx = delivered_simulation(api, employee=employee, name="ENG Variant Wave")
    campaign_id = ctx["campaign"]["id"]

    click(api, ctx["delivery"]["id"], "2026-08-02T09:30:00Z")
    before = read_employee(api, employee["id"])
    assert_risk_scores(before, provisional=11.00, settled=0.00)
    assert before["repeat_clicker_tier"] == 1

    set_clock(api, "2026-08-09T12:00:00Z")
    closed = validate_success(
        api.close_campaign(
            campaign_id,
            {"debrief_note": "Single-member wave closed; one click, no reports."},
            ADMIN,
        )
    )
    assert closed["state"] == CAMPAIGN_CLOSED
    assert_rate(closed["click_rate"], 1.0000, "click_rate")
    assert_rate(closed["report_rate"], 0.0000, "report_rate")

    after = read_employee(api, employee["id"])
    assert_risk_scores(after, provisional=11.00, settled=11.00)
    # A CLICKED delivery earns no clean-streak increment at close.
    assert after["consecutive_clean_simulations"] == 0
    assert after["repeat_clicker_tier"] == 1


def test_every_derived_field_is_visible_in_the_very_response_that_wrote_it(api):
    """The sweep counters, the reads and a repeat read all agree immediately.

    PRD §3.4: "A `ProgramAdmin` runs a compliance sweep, which evaluates the whole
    population against the current logical clock in four ordered steps and reports
    what it did: `assignments_scanned`, `reminders_sent_count`, `overdue_count`,
    `escalations_created_count`, `consequences_applied_count`, and the `swept_at`
    instant at which it ran."

    PRD §2.4: "Read-only recomputation is the exception: reads that refresh a derived
    field (an employee's tenure band and risk scores, an assignment's overdue-day
    count and next reminder instant, a campaign's four rates, an intervention's live
    tier and cadence) never bump `version` and never refresh `updated_at`."

    Design: Corner/consistency model/immediate_consistency_every_derived_field_visible_in_the_same_response
    """
    reset_clock(api)
    manager = register_manager(
        api, email="mgr.now@corp.example", full_name="Nina Manager",
        department="SALES", hire_date="2012-12-12",
    )
    report = register_employee(
        api, email="rep.now@corp.example", full_name="Ned Report",
        department="SALES", role_code="IC", hire_date="2020-10-10",
        manager_id=manager["id"],
    )
    module = create_published_module(
        api, code="NOW-REM", title="Immediate Probe Remedial",
        module_type="REMEDIAL")
    assignment = assign_module(api, report, module, assignment_reason="REMEDIAL")

    set_clock(api, "2026-08-15T00:00:00Z")
    sweep = validate_success(api.run_compliance_sweep(ADMIN))
    # Rungs 1 and 2 both fire, but only rung 2 carries a consequence.
    assert sweep["escalations_created_count"] == 2
    assert sweep["consequences_applied_count"] == 1
    assert_instant_equals(sweep["swept_at"], "2026-08-15T00:00:00Z", "swept_at")

    first = read_employee(api, report["id"])
    assert_employee_axes(first, compliance_state=COMPLIANCE_DELINQUENT,
                         access_posture=POSTURE_ELEVATED_REVIEW)
    assert_risk_scores(first, provisional=8.00)

    second = read_employee(api, report["id"])
    assert second["access_posture"] == first["access_posture"]
    assert second["risk_score_provisional"] == first["risk_score_provisional"]
    assert second["version"] == first["version"]

    active = list_consequences_for(api, report["id"], state=CONSEQUENCE_ACTIVE)
    assert len(active) == 1
    assert_consequence(active[0], state=CONSEQUENCE_ACTIVE, severity_rank=2)
    assert active[0]["source_assignment_id"] == assignment["id"]

    # A second sweep at the same instant has nothing left to escalate.
    repeat = validate_success(api.run_compliance_sweep(ADMIN))
    assert repeat["escalations_created_count"] == 0
    assert repeat["consequences_applied_count"] == 0
    assert_assignment(read_assignment(api, assignment["id"]), escalation_level=2)
