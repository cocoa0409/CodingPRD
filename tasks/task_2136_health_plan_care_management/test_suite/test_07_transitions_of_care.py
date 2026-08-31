"""The discharge obligation: escalation, its ledger consequences and its release."""
import pytest

from test_helpers import (
    ApiErrorId, PROGRAM_ADMIN, activate, assert_caseload_points, complete_touch,
    create_care_manager, create_enrollment_payload, create_member, create_program,
    create_transition_event_payload, enroll, read_care_manager, read_enrollment,
    record_event, schedule_touch, set_clock, setup_discharge_escalated_enrollment,
    stratify, validate_error, validate_paginated, validate_success,
)


def _toc_cascade_setting():
    program = create_program(name="TOC Cascade Program", min_risk_tier="MODERATE",
                             toc_outreach_hours=48)
    care_manager = create_care_manager(full_name="Rita Nolan", capacity_points=6.0)

    escalating_member = create_member(external_member_id="MBR-8001",
                                      full_name="Ivy Chen", birth_date="1955-06-06",
                                      chronic_condition_count=10)
    waiting_member = create_member(external_member_id="MBR-8002",
                                   full_name="Otto Lang", birth_date="1963-09-21",
                                   chronic_condition_count=6)
    assert stratify(escalating_member["id"], "CONCURRENT")["tier"] == "RISING"
    assert stratify(waiting_member["id"], "CONCURRENT")["tier"] == "MODERATE"

    enrollment = enroll(escalating_member["id"], program["id"], care_manager["id"])
    enrollment = activate(enrollment["id"])
    assert_caseload_points(enrollment["acuity_weight_points"], 4.0)
    assert enrollment["cadence_tier"] == "STANDARD"

    ledger = read_care_manager(care_manager["id"])
    assert_caseload_points(ledger["assigned_caseload_points"], 4.0)
    assert ledger["capacity_status"] == "OPEN"

    admission = record_event(escalating_member["id"],
                             event_type="INPATIENT_ADMISSION",
                             occurred_at="2026-07-28T00:00:00Z",
                             episode_cost_cents=900000,
                             adjudication_status="CLOSED")
    return {"program": program, "care_manager": care_manager,
            "member": escalating_member, "waiting_member": waiting_member,
            "enrollment": enrollment, "admission": admission}


def test_discharge_escalates_cadence_and_doubles_the_acuity_weight(api):
    """PRD §3.7: "Hop one sets the deadline and raises the intensity: `toc_due_at`
    becomes the discharge event's `occurred_at` advanced by the program's
    `toc_outreach_hours` hours, the enrollment's current `cadence_tier` is stashed
    in `pre_toc_cadence_tier` so it can be restored later, and both `cadence_tier`
    and `cadence_tier_snapshot` are set to `TOC_INTENSIVE`."
    PRD §3.7: "Hop two is caused by that tier change: `acuity_weight_points` is
    recomputed as the enrollment's tier points multiplied by the
    transitions-of-care cadence multiplier of 2.0, rounded to one decimal place —
    so a `RISING` enrollment that weighed 4.0 now weighs 8.0."
    PRD §3.7: "Alongside the four hops, `next_touch_due_at` is reprojected — and
    because the transitions-of-care clamp is applied last in that projection, the
    resulting interval is at most 2 days."

    Design: Difficulty/transitive_cascade/discharge_toc_escalation_depth_four_closes_auto_assign_pool
    """
    setting = _toc_cascade_setting()

    discharge = validate_success(
        api.create_transition_event(
            create_transition_event_payload(
                setting["member"]["id"], event_type="DISCHARGE",
                occurred_at="2026-08-01T00:00:00Z", episode_cost_cents=0,
                adjudication_status="CLOSED", discharge_disposition="HOME",
                index_admission_event_id=setting["admission"]["id"],
            ),
            PROGRAM_ADMIN,
        ),
        201,
    )
    assert discharge["toc_triggered_enrollment_count"] == 1
    assert discharge["index_admission_event_id"] == setting["admission"]["id"]

    enrollment = read_enrollment(setting["enrollment"]["id"])
    assert enrollment["toc_due_at"] == "2026-08-03T00:00:00.000Z"
    assert enrollment["cadence_tier"] == "TOC_INTENSIVE"
    assert enrollment["cadence_tier_snapshot"] == "TOC_INTENSIVE"
    assert enrollment["pre_toc_cadence_tier"] == "STANDARD"
    assert_caseload_points(enrollment["acuity_weight_points"], 8.0)
    assert enrollment["next_touch_due_at"] == "2026-08-03T00:00:00.000Z"
    assert enrollment["enrollment_status"] == "ACTIVE", (
        "the escalation is a self-loop that never changes the lifecycle dimension"
    )


def test_escalated_caseload_empties_the_auto_assignment_pool(api):
    """PRD §3.7: "Hop three is caused by hop two: the owning care manager's
    `assigned_caseload_points` is recomputed as the full sum over their `PENDING`
    and `ACTIVE` enrollments. Hop four is caused by hop three: the manager's
    `capacity_status` becomes `OVER_CAPACITY` when that new sum is strictly
    greater than their `capacity_points`, which as a side consequence removes them
    from the auto-assignment candidate pool for any subsequent enrollment."
    PRD §3.3: "If the filter leaves no candidate at all, nothing is created and
    the request is refused with `ERR_NO_ELIGIBLE_CARE_MANAGER`."

    Design: Difficulty/transitive_cascade/discharge_toc_escalation_depth_four_closes_auto_assign_pool
    """
    setting = _toc_cascade_setting()

    record_event(setting["member"]["id"], event_type="DISCHARGE",
                 occurred_at="2026-08-01T00:00:00Z", episode_cost_cents=0,
                 adjudication_status="CLOSED", discharge_disposition="HOME",
                 index_admission_event_id=setting["admission"]["id"])

    ledger = read_care_manager(setting["care_manager"]["id"])
    assert_caseload_points(ledger["assigned_caseload_points"], 8.0)
    assert ledger["capacity_status"] == "OVER_CAPACITY"

    response = api.create_enrollment(
        create_enrollment_payload(setting["waiting_member"]["id"],
                                  setting["program"]["id"]),
        PROGRAM_ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_CARE_MANAGER.value)
    assert response.status_code == 409

    _, meta = validate_paginated(
        api.list_enrollments(
            PROGRAM_ADMIN, params={"member_id": setting["waiting_member"]["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_toc_touch_completion_restores_the_pre_escalation_cadence(api):
    """PRD §3.7: "When a touch whose `touch_type` is `TOC` is completed with an
    `outcome` of `REACHED`, and the enrollment has an open `toc_due_at`, and the
    touch's `completed_at` is at or before that `toc_due_at`, the obligation is
    satisfied: the touch's `satisfied_toc_obligation` flag — false on every other
    touch — is set to true, `toc_due_at` is cleared to null, `cadence_tier` and
    `cadence_tier_snapshot` are both restored to the value stashed in
    `pre_toc_cadence_tier`, and `pre_toc_cadence_tier` returns to null."
    PRD §3.7: "The restoration lowers `acuity_weight_points` again, which
    recomputes the owning manager's `assigned_caseload_points` and refreshes their
    `capacity_status`."

    Design: Corner/state_machines/toc_touch_completion_compensates_escalation_and_restores_cadence
    """
    scenario = setup_discharge_escalated_enrollment(
        program_overrides={"name": "TOC Compensation Program",
                           "toc_outreach_hours": 48},
        member_overrides={"external_member_id": "MBR-4801", "full_name": "Toc Tess",
                          "birth_date": "1962-02-12", "chronic_condition_count": 0},
        goal_specs=[{"domain": "CLINICAL",
                     "description": "Post-discharge follow-up"}],
        plan_title="TOC plan",
    )
    escalated = scenario["enrollment"]
    assert escalated["cadence_tier"] == "TOC_INTENSIVE"
    assert_caseload_points(escalated["acuity_weight_points"], 2.0)
    assert escalated["toc_due_at"] == "2026-08-03T00:00:00.000Z"

    care_manager_id = scenario["care_manager"]["id"]
    touch = schedule_touch(escalated["id"], care_manager_id, touch_type="TOC",
                           scheduled_start_at="2026-08-02T09:00:00Z",
                           scheduled_end_at="2026-08-02T09:30:00Z")
    set_clock("2026-08-02T09:00:00Z")

    completed = complete_touch(
        touch["id"], care_manager_id, "REACHED",
        "Post-discharge call completed; meds reconciled.",
    )
    assert completed["satisfied_toc_obligation"] is True

    enrollment = read_enrollment(escalated["id"])
    assert enrollment.get("toc_due_at") is None
    assert enrollment["cadence_tier"] == "STANDARD"
    assert enrollment["cadence_tier_snapshot"] == "STANDARD"
    assert enrollment.get("pre_toc_cadence_tier") is None
    assert_caseload_points(enrollment["acuity_weight_points"], 1.0)
    assert enrollment["engagement_score"] == 33
    assert enrollment["engagement_status"] == "AT_RISK"
    assert enrollment["next_touch_due_at"] == "2026-09-01T09:00:00.000Z"
    assert_caseload_points(
        read_care_manager(care_manager_id)["assigned_caseload_points"], 1.0
    )
