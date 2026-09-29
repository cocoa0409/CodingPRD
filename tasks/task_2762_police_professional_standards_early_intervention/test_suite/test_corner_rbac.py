"""The credential ladder: role exclusivity, the assigned investigator and the plan owner."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    OFFICER_REPRESENTATIVE_HEADERS,
    RECORDS_CUSTODIAN_HEADERS,
    SYSTEM_ADMIN_HEADERS,
    assert_instant,
    headers_without_role,
    headers_without_user_id,
    headers_with_undeclared_role,
    make_investigator_headers,
    make_supervisor_headers,
)
from test_helpers import factories, fixtures

BASE_CLOCK = "2026-08-01T00:00:00Z"
UNKNOWN_ID = "00000000-0000-0000-0000-000000000000"


def test_every_role_is_confined_to_its_own_exclusive_operations(api):
    """Five wrong-role probes, two missing headers and one undeclared role, then the role's own work.

    PRD: The eight roles, spelled exactly as they must appear in `X-User-Role`, are `Complainant`, `Supervisor`, `Investigator`, `IACommander`, `AppealsOfficer`, `OfficerRepresentative`, `RecordsCustodian` and `SystemAdmin`.
    PRD: both `X-User-ID` and `X-User-Role` present and non-empty, on every endpoint. Failure: `ERR_UNAUTHENTICATED` (401).
    PRD: `X-User-Role` names a declared role and that role is authorized on the target endpoint, on every endpoint. Failure: `ERR_UNAUTHORIZED` (403).
    PRD: Validation proceeds strictly in ascending priority tier; **the first violated rule determines the response, and no later rule is evaluated.**
    PRD: `SystemAdmin` seeds the standing reference data — units, hearing rooms and officer records — moves an officer along the employment dimension, may record activity events, may run the early-intervention sweep, may read the public outcome report, and holds the logical clock.
    PRD: `Supervisor` files complaints on behalf of the department, attaches allegations, records officer activity events, creates and closes intervention plans, exclusively activates plans and completes monitoring check-ins, and reads the officer, complaint, allegation, investigation, session, alert and plan resources.
    PRD: `IACommander` exclusively screens and classifies intake, opens investigations, assigns investigators, closes investigations, dispositions allegations, imposes discipline and dismisses alerts; shares intake, allegation creation, tolling, the early-intervention sweep, plan creation and plan closure; and reads every resource other than the hearing rooms.
    PRD: `OfficerRepresentative` exclusively files appeals, shares interview postponement, and reads the officer, session, discipline, appeal, reinstatement and disclosure resources.
    PRD: `RecordsCustodian` exclusively purges retention-expired complaint files and logs credibility-record releases, and reads the complaint, allegation, investigation, session, discipline, appeal and disclosure resources alongside the public outcome report.
    PRD: On acceptance the system derives `base_weight` from the event type's base weight in the scoring table below, and derives `weekday_index` from `occurred_at`: an integer from 0 to 6 where 0 is Monday, computed in UTC.
    Design: Corner/rbac/every_role_is_confined_to_its_own_exclusive_operations
    """
    world = fixtures.world_with_investigation(api)

    # Opening an investigation belongs to the commander alone.
    validate_error(
        api.open_investigation(
            world["c_id"],
            {"opening_note": "A supervisor trying to open an investigation."},
            world["sup_headers"],
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    _, opened = fixtures.rows(
        api.list_investigations(world["cmdr_headers"], {"complaint_id": world["c_id"]})
    )
    assert opened["total_count"] == 1

    # The role rule answers before the assigned-investigator rule and before the state gate.
    validate_error(
        api.submit_findings(
            world["i1_id"],
            factories.findings_payload([factories.finding_entry(world["a1_id"])]),
            world["cmdr_headers"],
        ),
        "ERR_UNAUTHORIZED",
        403,
    )

    # The role rule answers before the purgeability rule.
    validate_error(
        api.purge_complaint(
            world["c_id"],
            {"purge_reason": "A system administrator trying to purge records."},
            SYSTEM_ADMIN_HEADERS,
        ),
        "ERR_UNAUTHORIZED",
        403,
    )

    # The role rule answers before path existence, so an unknown id does not leak through it.
    validate_error(
        api.hear_appeal(
            UNKNOWN_ID,
            {"hearing_notes": "A representative trying to hear their own appeal."},
            OFFICER_REPRESENTATIVE_HEADERS,
        ),
        "ERR_UNAUTHORIZED",
        403,
    )

    # Hearing-room reads are the one read family the records custodian is not granted.
    validate_error(
        api.list_hearing_rooms(RECORDS_CUSTODIAN_HEADERS, {"limit": 10, "offset": 0}),
        "ERR_UNAUTHORIZED",
        403,
    )

    validate_error(
        api.create_activity_event(
            world["subj_id"],
            factories.activity_event_payload(
                event_type="PURSUIT",
                occurred_at="2026-07-25T00:00:00Z",
                severity_code="NA",
                source_reference="PUR-9",
            ),
            headers_without_role(world["sup_id"]),
        ),
        "ERR_UNAUTHENTICATED",
        401,
    )

    validate_error(
        api.dispose_allegation(
            world["a1_id"],
            factories.disposition_payload(
                "NOT_SUSTAINED", rationale="No acting officer id supplied."
            ),
            headers_without_user_id("IACommander"),
        ),
        "ERR_UNAUTHENTICATED",
        401,
    )

    validate_error(
        api.assign_investigation(
            world["i1_id"],
            factories.assignment_payload(world["i1_v0"], world["inv_a_id"]),
            headers_with_undeclared_role(world["cmdr_id"]),
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    unconsumed = fixtures.read_investigation(api, world["i1_id"], world["cmdr_headers"])
    assert unconsumed["version"] == world["i1_v0"]
    assert unconsumed["status"] == "UNASSIGNED"
    assert unconsumed["assigned_investigator_officer_id"] is None

    # The same supervisor identity, refused four other operations, does its own work.
    recorded = validate_success(
        api.create_activity_event(
            world["subj_id"],
            factories.activity_event_payload(
                event_type="PURSUIT",
                occurred_at="2026-07-25T00:00:00Z",
                severity_code="NA",
                source_reference="PUR-10",
            ),
            world["sup_headers"],
        ),
        201,
    )

    assert recorded["event_type"] == "PURSUIT"
    assert recorded["source_reference"] == "PUR-10"
    assert recorded["system_generated"] is False
    assert_instant(recorded["occurred_at"], "2026-07-25T00:00:00Z")
    events, event_meta = fixtures.rows(
        api.list_activity_events(world["subj_id"], world["cmdr_headers"])
    )
    # Attaching the allegation already appended a system_generated
    # COMPLAINT_INTAKE event at the complaint's received_at, so the supervisor's
    # own PURSUIT event is the second row on file. The list is ordered by
    # occurred_at ascending, which puts the 25 July pursuit ahead of the 1 August
    # intake event.
    assert event_meta["total_count"] == 2
    assert [row["event_type"] for row in events] == ["PURSUIT", "COMPLAINT_INTAKE"]
    assert events[0]["source_reference"] == "PUR-10"
    assert events[0]["system_generated"] is False
    assert events[1]["system_generated"] is True


def test_only_the_assigned_investigator_may_work_the_investigation(api):
    """Briggs holds the role but not the case: refused on all three bound operations, allowed to toll.

    PRD: `Investigator` exclusively schedules interview sessions, records that they were held and submits findings, shares the tolling and postponement capabilities, and reads the complaint, allegation, investigation and session resources.
    PRD: the acting user is the right individual, not merely the right role. `ERR_NOT_ASSIGNED_INVESTIGATOR` (403) guards findings submission, interview-session creation and interview hold. `ERR_NOT_PLAN_SUPERVISOR` (403) guards plan activation, plan closure and check-in completion whenever the acting role is `Supervisor`.
    PRD: Validation proceeds strictly in ascending priority tier; **the first violated rule determines the response, and no later rule is evaluated.**
    PRD: Only the officer named in `assigned_investigator_officer_id` may schedule a session; anyone else, even another certified investigator, is refused with `ERR_NOT_ASSIGNED_INVESTIGATOR`.
    PRD: Either the assigned `Investigator` or an `IACommander` may stop and restart the statutory clock by supplying an `action` of `SUSPEND` or `RESUME`, with an optional `tolling_reason` that must be present when suspending. Suspension is legal only from `IN_PROGRESS` and produces `IN_PROGRESS → TOLLED`, stamping `suspended_at` from the logical clock.
    PRD: Resuming from `TOLLED` produces `TOLLED → IN_PROGRESS` and accrues the tolled time: the elapsed duration from `suspended_at` to the logical clock is converted to whole days with any partial day discarded, that figure is added to `tolled_days`, `suspended_at` is cleared, and `due_at` is recomputed.
    Design: Corner/rbac/only_the_assigned_investigator_may_work_the_investigation
    """
    world = fixtures.world_assigned_investigation(api, investigator_officer_id=None)
    assert world["investigation"]["assigned_investigator_officer_id"] == world["inv_a_id"]
    assert world["investigation"]["status"] == "ASSIGNED"
    briggs = fixtures.create_investigator(
        api,
        world["ia_unit_id"],
        badge_number="IA-102",
        full_name="Investigator Briggs",
        certification_level=3,
        max_case_load=8,
    )
    briggs_headers = make_investigator_headers(briggs["id"])
    booking = factories.interview_session_payload(
        world["subj_id"],
        world["room1_id"],
        scheduled_start="2026-08-05T09:00:00Z",
        scheduled_end="2026-08-05T10:00:00Z",
        notice_served_at=BASE_CLOCK,
        representation_status="REP_PRESENT",
    )

    validate_error(
        api.schedule_interview_session(world["i1_id"], booking, briggs_headers),
        "ERR_NOT_ASSIGNED_INVESTIGATOR",
        403,
    )
    _, empty = fixtures.rows(
        api.list_interview_sessions(world["cmdr_headers"], {"investigation_id": world["i1_id"]})
    )
    assert empty["total_count"] == 0

    # The ownership rule answers before the state gate, though ASSIGNED is no state for findings.
    validate_error(
        api.submit_findings(
            world["i1_id"],
            factories.findings_payload([factories.finding_entry(world["a1_id"])]),
            briggs_headers,
        ),
        "ERR_NOT_ASSIGNED_INVESTIGATOR",
        403,
    )

    session = validate_success(
        api.schedule_interview_session(world["i1_id"], booking, world["inv_a_headers"]), 201
    )

    assert session["status"] == "SCHEDULED"
    assert fixtures.read_investigation(api, world["i1_id"], world["cmdr_headers"])["status"] == "IN_PROGRESS"

    # The ownership rule answers before the interview-not-started rule.
    validate_error(
        api.hold_interview_session(
            session["id"],
            factories.hold_payload(
                interview_summary="An uninvolved investigator trying to hold the interview."
            ),
            briggs_headers,
        ),
        "ERR_NOT_ASSIGNED_INVESTIGATOR",
        403,
    )
    untouched = fixtures.read_session(api, session["id"], world["cmdr_headers"])
    assert untouched["status"] == "SCHEDULED"
    assert untouched["held_at"] is None

    # Tolling carries no identity binding, so any investigator may stop the clock.
    suspended = get_success_data(
        api.toll_investigation(
            world["i1_id"],
            factories.tolling_payload("SUSPEND", tolling_reason="Criminal referral pending."),
            briggs_headers,
        )
    )

    assert suspended["status"] == "TOLLED"
    assert_instant(suspended["suspended_at"], BASE_CLOCK)

    resumed = get_success_data(
        api.toll_investigation(
            world["i1_id"],
            factories.tolling_payload("RESUME", tolling_reason="Referral declined."),
            world["inv_a_headers"],
        )
    )

    assert resumed["status"] == "IN_PROGRESS"
    assert resumed["tolled_days"] == 0
    assert resumed["suspended_at"] is None


def a_plan_owned_by_doyle_with_ellis_looking_on(api):
    """The commander drafts a plan naming Doyle, while Sergeant Ellis holds the same role."""
    world = fixtures.world_with_promoted_alert(api)
    ellis = fixtures.create_supervisor(
        api,
        world["patrol_unit_id"],
        badge_number="PN-011",
        full_name="Sergeant Ellis",
        annual_salary_cents=10400000,
        demographic_code="DG_B",
        hire_date="2013-04-04T00:00:00Z",
    )
    plan = validate_success(
        api.create_intervention_plan(
            world["al_id"],
            factories.intervention_plan_payload(
                world["al_v"],
                world["sup_id"],
                required_checkin_count=2,
                duration_days=30,
                interventions=["RETRAINING", "PEER_REVIEW"],
            ),
            world["cmdr_headers"],
        ),
        201,
    )
    world.update(
        {
            "sup2_id": ellis["id"],
            "sup2_headers": make_supervisor_headers(ellis["id"]),
            "p1_id": plan["id"],
            "plan": plan,
        }
    )
    return world


def test_only_the_monitoring_supervisor_may_run_the_plan(api):
    """Ellis is refused on all three plan operations; the commander passes identity and hits the children.

    PRD: A `Supervisor` or an `IACommander` attaches a plan to an alert, pinning `expected_alert_version` as Section 2.6 requires and supplying the `supervisor_officer_id` who will do the monitoring, the `required_checkin_count` between 2 and 6, the `duration_days` of 30, 60 or 90, and the `interventions` to be applied, drawn from `RETRAINING`, `COUNSELING`, `PEER_REVIEW`, `REASSIGNMENT` and `EAP_REFERRAL`.
    PRD: the acting user is the right individual, not merely the right role. `ERR_NOT_ASSIGNED_INVESTIGATOR` (403) guards findings submission, interview-session creation and interview hold. `ERR_NOT_PLAN_SUPERVISOR` (403) guards plan activation, plan closure and check-in completion whenever the acting role is `Supervisor`.
    PRD: Validation proceeds strictly in ascending priority tier; **the first violated rule determines the response, and no later rule is evaluated.**
    PRD: Activation is reserved to the monitoring supervisor: when the acting role is `Supervisor`, the acting `X-User-ID` must equal the plan's `supervisor_officer_id`, and any other supervisor is refused with `ERR_NOT_PLAN_SUPERVISOR`. The plan must be `DRAFT`, otherwise `ERR_PLAN_STATE_INVALID`, and the owning alert must be `PLAN_REQUIRED`. Activation accepts an optional `activation_note`, moves the plan `DRAFT → ACTIVE`, stamps `activated_at` from the logical clock, sets `end_date` to `activated_at` plus `duration_days` whole days, materialises the check-in schedule, and moves the owning alert `PLAN_REQUIRED → PLAN_ACTIVE`.
    PRD: The check-in must be `PENDING` and its owning plan must be `ACTIVE`, otherwise `ERR_CHECKIN_NOT_PENDING`, and the acting supervisor must be the plan's monitoring supervisor, otherwise `ERR_NOT_PLAN_SUPERVISOR`.
    PRD: The plan must be `ACTIVE`, otherwise `ERR_PLAN_STATE_INVALID`, and no check-in of the plan may still be `PENDING`, otherwise `ERR_PENDING_CHECKINS`.
    PRD: `ERR_ALERT_ALREADY_OPEN` (409) on the early-intervention sweep; `ERR_PENDING_CHECKINS` (409) on plan closure; and `ERR_PLAN_EXISTS` (409) on alert dismissal.
    Design: Corner/rbac/only_the_monitoring_supervisor_may_run_the_plan
    """
    world = a_plan_owned_by_doyle_with_ellis_looking_on(api)
    assert world["plan"]["status"] == "DRAFT"
    assert world["plan"]["supervisor_officer_id"] == world["sup_id"]

    validate_error(
        api.activate_intervention_plan(
            world["p1_id"],
            {"activation_note": "A sergeant who does not own the plan trying to start it."},
            world["sup2_headers"],
        ),
        "ERR_NOT_PLAN_SUPERVISOR",
        403,
    )
    still_draft = fixtures.read_plan(api, world["p1_id"], world["sup_headers"])
    assert still_draft["status"] == "DRAFT"
    assert still_draft["activated_at"] is None

    activated = get_success_data(
        api.activate_intervention_plan(
            world["p1_id"],
            {"activation_note": "The monitoring supervisor starts the plan."},
            world["sup_headers"],
        )
    )

    assert activated["status"] == "ACTIVE"
    assert_instant(activated["activated_at"], BASE_CLOCK)
    check_ins, check_in_meta = fixtures.rows(
        api.list_plan_check_ins(world["p1_id"], world["sup_headers"])
    )
    assert check_in_meta["total_count"] == 2
    assert [row["status"] for row in check_ins] == ["PENDING", "PENDING"]

    validate_error(
        api.complete_check_in(
            check_ins[0]["id"],
            factories.check_in_completion_payload(notes="Signed off by the wrong sergeant."),
            world["sup2_headers"],
        ),
        "ERR_NOT_PLAN_SUPERVISOR",
        403,
    )
    pending, _ = fixtures.rows(api.list_plan_check_ins(world["p1_id"], world["sup_headers"]))
    assert pending[0]["status"] == "PENDING"
    assert pending[0]["completed_at"] is None

    # The ownership rule answers before the pending-check-in rule, which is also violated here.
    validate_error(
        api.close_intervention_plan(
            world["p1_id"], {"closing_note": "Closed by the wrong sergeant."}, world["sup2_headers"]
        ),
        "ERR_NOT_PLAN_SUPERVISOR",
        403,
    )

    # The commander is not bound by the ownership rule at all, so the same request reaches it.
    validate_error(
        api.close_intervention_plan(
            world["p1_id"],
            {"closing_note": "Closed by the commander while check-ins are still pending."},
            world["cmdr_headers"],
        ),
        "ERR_PENDING_CHECKINS",
        409,
    )

    unclosed = fixtures.read_plan(api, world["p1_id"], world["sup_headers"])
    assert unclosed["status"] == "ACTIVE"
    assert unclosed["compliance_score"] is None
    assert unclosed["closed_at"] is None
    assert unclosed["completed_checkin_count"] == 0
