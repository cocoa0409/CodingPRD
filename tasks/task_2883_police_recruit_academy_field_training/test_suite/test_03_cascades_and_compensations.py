"""The multi-level cascades and the two compensations that walk them back.

Each cascade lands entirely inside the request that heads it, and each stops at a
declared hard boundary: hours already earned are never taken away by a cascade,
only by the reversal written for that purpose.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import ERR_MILESTONE_NOT_REACHED
from test_helpers.assertions import (
    assert_hours_equals,
    assert_score_equals,
    count_entries,
    find_entry,
)
from test_helpers.test_users import (
    coordinator_headers,
    custodian_headers,
    director_headers,
)

PATROL = "PATROL"
REVOCATION_REASON = "sustained integrity complaint"
VOID_REASON = "instructor documentation deficiency found on audit"


def _class_under_one_instructor(world, exam_required=False, session_days=(
        "2026-08-10", "2026-08-11", "2026-08-12"), attended_days=2):
    """One cohort, one instructor, one recruit and several scheduled sessions.

    The first session is closed out; the rest stay `SCHEDULED` with a provisional
    attendance row apiece, which is what the cascades reach for.
    """
    standard = world.create_standard(
        min_total_hours=6.0,
        topic_requirements=[f.topic_requirement(PATROL, 6.0, exam_required)],
        max_remediation_attempts=1)
    cohort = world.create_cohort(standard["id"])
    instructor = world.create_certified_instructor(topics=[PATROL],
                                                   fto_certified=True)
    plan = world.create_approved_lesson_plan(instructor["id"], PATROL,
                                             contact_hours=2.0)
    recruit = world.recruit_in_academy(cohort["id"])

    sessions = [
        world.schedule_session(cohort["id"], plan["id"], instructor["id"],
                              room_code="R1", starts_at=f"{day}T09:00:00Z",
                              ends_at=f"{day}T11:00:00Z", min_enrollment=1)
        for day in session_days
    ]
    rows = [world.record_attendance(session["id"], recruit["id"], "PRESENT", 2.0)
            for session in sessions[:attended_days]]
    world.set_clock("2026-08-10T12:00:00Z")
    delivered = world.deliver_session(sessions[0]["id"])
    sessions[0] = delivered

    cohort_before = validate_success(world.client.get_academy_class(
        cohort["id"], director_headers()))
    return {"standard": standard, "cohort": cohort, "instructor": instructor,
            "plan": plan, "recruit": recruit, "sessions": sessions,
            "rows": rows, "cohort_before": cohort_before}


def _read_session(world, session_id):
    return validate_success(world.client.get_course_session(
        session_id, coordinator_headers()))


def _read_row(world, row_id):
    return validate_success(world.client.get_attendance_record(
        row_id, coordinator_headers()))


def test_revoking_a_credential_sends_its_approved_plans_back_for_revision(world):
    """Level 1 revokes, level 2 pushes the plan to REVISION_REQUESTED.

    PRD: "**Cascade C, level 2** - because the credential became `REVOKED`, every
    lesson plan authored by this instructor whose `status` is `APPROVED` moves
    `APPROVED` -> `REVISION_REQUESTED`, has its `approved_revision_number` set to
    null, and has `reviewer_notes` set to record that the authoring instructor's
    certification was revoked."

    Design: Difficulty/transitive_cascade/revoke_instructor_cascades_plan_session_projected_hours_class_at_risk
    """
    built = _class_under_one_instructor(world)
    assert built["cohort_before"]["status"] == "IN_SESSION"
    assert_hours_equals(built["cohort_before"]["projected_topic_hours"][PATROL],
                        "6.00", "projected_topic_hours before")

    revoked = validate_success(world.client.revoke_instructor_certification(
        built["instructor"]["id"], f.revoke_certification_payload(REVOCATION_REASON),
        director_headers()))
    assert revoked["certification_status"] == "REVOKED"
    assert revoked["fto_certified"] is False
    assert revoked["revocation_reason"] == REVOCATION_REASON
    assert revoked["active_trainee_count"] == 0

    plan = validate_success(world.client.get_lesson_plan(built["plan"]["id"],
                                                        director_headers()))
    assert plan["status"] == "REVISION_REQUESTED"
    assert plan["approved_revision_number"] is None
    assert plan["revision_number"] == 1
    assert plan["reviewer_notes"]


def test_the_cancelled_sessions_void_only_their_provisional_rows(world):
    """Levels 3 cancels the scheduled sessions and spares the credited row.

    PRD: "**Cascade C, level 3** - because those plans left `APPROVED`, every
    course session referencing one of them whose `status` is `SCHEDULED` or
    `UNDER_MIN_ENROLLMENT` moves to `CANCELLED`, and every attendance row of such
    a session whose `ledger_status` is `PROVISIONAL` moves to `VOIDED` with its
    `void_reason` recording that the session was cancelled."

    Design: Difficulty/transitive_cascade/revoke_instructor_cascades_plan_session_projected_hours_class_at_risk
    """
    built = _class_under_one_instructor(world)

    validate_success(world.client.revoke_instructor_certification(
        built["instructor"]["id"], f.revoke_certification_payload(REVOCATION_REASON),
        director_headers()))

    assert _read_session(world, built["sessions"][0]["id"])["status"] == "DELIVERED"
    for cancelled in built["sessions"][1:]:
        assert _read_session(world, cancelled["id"])["status"] == "CANCELLED"
    assert _read_session(world, built["sessions"][1]["id"])["enrolled_count"] == 0

    credited = _read_row(world, built["rows"][0]["id"])
    assert credited["ledger_status"] == "CREDITED"
    assert_hours_equals(credited["credited_hours"], "2.00", "credited_hours")

    voided = _read_row(world, built["rows"][1]["id"])
    assert voided["ledger_status"] == "VOIDED"
    assert voided["void_reason"]


def test_the_cohort_drops_to_at_risk_while_its_credited_ledger_holds(world):
    """Level 4 re-projects 2.00 hours against a 6.00-hour requirement.

    PRD: "**Cascade C, level 4** - because those sessions were cancelled, every
    affected cohort re-derives `projected_topic_hours`, and a cohort at
    `IN_SESSION` for which any curriculum topic now projects fewer hours than
    that topic's `required_hours` drops `IN_SESSION` -> `AT_RISK`."

    Design: Difficulty/transitive_cascade/revoke_instructor_cascades_plan_session_projected_hours_class_at_risk
    """
    built = _class_under_one_instructor(world)

    validate_success(world.client.revoke_instructor_certification(
        built["instructor"]["id"], f.revoke_certification_payload(REVOCATION_REASON),
        director_headers()))

    cohort = validate_success(world.client.get_academy_class(
        built["cohort"]["id"], director_headers()))
    assert cohort["status"] == "AT_RISK"
    assert_hours_equals(cohort["projected_topic_hours"][PATROL], "2.00",
                        "projected_topic_hours")
    assert_hours_equals(cohort["credited_topic_hours_total"], "2.00",
                        "credited_topic_hours_total")

    trainee = world.read_recruit(built["recruit"]["id"])
    assert_hours_equals(trainee["credited_hours_total"], "2.00",
                        "credited_hours_total")
    assert_hours_equals(trainee["per_topic_credited_hours"][PATROL], "2.00",
                        f"per_topic_credited_hours[{PATROL}]")
    assert trainee["academy_status"] == "IN_PROGRESS"


def _examination_one_failure_from_final(world):
    """A remediated examination sitting one grading away from FAILED_FINAL."""
    built = _class_under_one_instructor(
        world, exam_required=True,
        session_days=("2026-08-10", "2026-08-11"), attended_days=2)
    examination = world.schedule_examination(built["recruit"]["id"], PATROL)
    failed = world.grade_examination(examination["id"], 60.0)
    assert failed["status"] == "FAILED"
    remediated = world.assign_remediation(examination["id"], 6.0)
    assert remediated["status"] == "REMEDIATION_ASSIGNED"
    assert remediated["attempt_number"] == 2
    built["examination"] = remediated
    return built


def test_a_second_failure_below_the_bar_pends_the_recruits_dismissal(world):
    """Attempt 2 of a one-remediation standard fails finally and pends dismissal.

    PRD: "Level 2, because the examination became `FAILED_FINAL`, moves the
    examinee's `academy_status` to `DISMISSAL_PENDING`, from `IN_PROGRESS` or from
    `REMEDIATION` alike."

    Design: Difficulty/transitive_cascade/final_exam_failure_cascades_dismissal_pending_void_attendance_session_under_min
    """
    built = _examination_one_failure_from_final(world)

    final = world.grade_examination(built["examination"]["id"], 60.0)
    assert final["status"] == "FAILED_FINAL"
    assert final["attempt_number"] == 2
    assert_score_equals(final["raw_score"], "60.00", "raw_score")
    assert_hours_equals(final["remediation_hours"], "6.00", "remediation_hours")

    trainee = world.read_recruit(built["recruit"]["id"])
    assert trainee["academy_status"] == "DISMISSAL_PENDING"
    assert trainee["remediation_attempts_used"] == 1


def test_the_pending_dismissal_voids_provisional_rows_and_spares_credited_ones(world):
    """Level 3 stops at the ledger: earned hours survive a pending dismissal.

    PRD: "Note what level 3 does *not* touch: rows already at `CREDITED` are left
    alone, so hours already earned survive a pending dismissal."

    Design: Difficulty/transitive_cascade/final_exam_failure_cascades_dismissal_pending_void_attendance_session_under_min
    """
    built = _examination_one_failure_from_final(world)

    world.grade_examination(built["examination"]["id"], 60.0)

    credited = _read_row(world, built["rows"][0]["id"])
    assert credited["ledger_status"] == "CREDITED"
    assert_hours_equals(credited["credited_hours"], "2.00", "credited_hours")

    voided = _read_row(world, built["rows"][1]["id"])
    assert voided["ledger_status"] == "VOIDED"
    assert voided["void_reason"]
    assert_hours_equals(voided["credited_hours"], "0.00", "credited_hours")

    trainee = world.read_recruit(built["recruit"]["id"])
    assert_hours_equals(trainee["credited_hours_total"], "2.00",
                        "credited_hours_total")
    assert trainee["pipeline_stage"] == "ACADEMY"


def test_the_starved_session_falls_under_its_floor_without_moving_the_cohort(world):
    """Level 4 leaves the cohort IN_SESSION because the hours are still projected.

    PRD: "Level 4, because those counts dropped, moves every affected session
    whose `status` is `SCHEDULED` and whose `enrolled_count` is now below its
    `min_enrollment` to `UNDER_MIN_ENROLLMENT`."

    Design: Difficulty/transitive_cascade/final_exam_failure_cascades_dismissal_pending_void_attendance_session_under_min
    """
    built = _examination_one_failure_from_final(world)

    world.grade_examination(built["examination"]["id"], 60.0)

    starved = _read_session(world, built["sessions"][1]["id"])
    assert starved["enrolled_count"] == 0
    assert starved["status"] == "UNDER_MIN_ENROLLMENT"
    assert _read_session(world, built["sessions"][0]["id"])["status"] == "DELIVERED"

    cohort = validate_success(world.client.get_academy_class(
        built["cohort"]["id"], director_headers()))
    assert cohort["status"] == "IN_SESSION"
    assert_hours_equals(cohort["projected_topic_hours"][PATROL], "4.00",
                        "projected_topic_hours")


def _two_delivered_sessions(world):
    """Two closed-out two-hour sessions crediting 4.00 hours to one recruit."""
    standard = world.create_standard(
        min_total_hours=6.0,
        topic_requirements=[f.topic_requirement(PATROL, 6.0, False)])
    cohort = world.create_cohort(standard["id"])
    instructor = world.create_certified_instructor(topics=[PATROL])
    plan = world.create_approved_lesson_plan(instructor["id"], PATROL,
                                             contact_hours=2.0)
    recruit = world.recruit_in_academy(cohort["id"])

    sessions, rows = [], []
    for day in ("2026-08-10", "2026-08-11"):
        session = world.schedule_session(
            cohort["id"], plan["id"], instructor["id"], room_code="R1",
            starts_at=f"{day}T09:00:00Z", ends_at=f"{day}T11:00:00Z",
            min_enrollment=1)
        rows.append(world.record_attendance(session["id"], recruit["id"],
                                           "PRESENT", 2.0))
        sessions.append(session)
    for index, day in enumerate(("2026-08-10", "2026-08-11")):
        world.set_clock(f"{day}T12:00:00Z")
        sessions[index] = world.deliver_session(sessions[index]["id"])

    cohort_before = validate_success(world.client.get_academy_class(
        cohort["id"], director_headers()))
    return {"cohort": cohort, "recruit": recruit, "sessions": sessions,
            "rows": rows, "cohort_before": cohort_before}


def test_voiding_a_delivery_returns_the_cohort_ledger_to_its_earlier_value(world):
    """A 4.00-hour ledger falls back to exactly the 2.00 it held before.

    PRD: "the cohort's `credited_topic_hours_total` falls by the amount the
    delivery had added - returning to its exact pre-delivery value, which is the
    conserved quantity of this compensation"

    Design: Difficulty/compensating_invariant/void_delivery_restores_class_credited_topic_hours_total_exactly
    """
    built = _two_delivered_sessions(world)
    assert built["cohort_before"]["status"] == "IN_SESSION"
    assert_hours_equals(built["cohort_before"]["credited_topic_hours_total"],
                        "4.00", "credited_topic_hours_total before")

    voided = world.void_delivery(built["sessions"][0]["id"], VOID_REASON)
    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == VOID_REASON
    assert_hours_equals(voided["credited_hours_total"], "0.00",
                        "session credited_hours_total")
    assert voided["enrolled_count"] == 0

    cohort = validate_success(world.client.get_academy_class(
        built["cohort"]["id"], director_headers()))
    assert_hours_equals(cohort["credited_topic_hours_total"], "2.00",
                        "credited_topic_hours_total")
    assert_hours_equals(cohort["projected_topic_hours"][PATROL], "2.00",
                        "projected_topic_hours")
    assert cohort["status"] == "AT_RISK"


def test_the_reversed_rows_lose_their_hours_and_the_other_delivery_stands(world):
    """Only the voided session's rows are reset; the second delivery is untouched.

    PRD: "Every attendance row of the session at `CREDITED` moves to `VOIDED`
    with `credited_hours` and `counted_absence_hours` both reset to `0.00`."

    Design: Difficulty/compensating_invariant/void_delivery_restores_class_credited_topic_hours_total_exactly
    """
    built = _two_delivered_sessions(world)

    world.void_delivery(built["sessions"][0]["id"], VOID_REASON)

    reversed_row = _read_row(world, built["rows"][0]["id"])
    assert reversed_row["ledger_status"] == "VOIDED"
    assert_hours_equals(reversed_row["credited_hours"], "0.00", "credited_hours")
    assert_hours_equals(reversed_row["counted_absence_hours"], "0.00",
                        "counted_absence_hours")

    survivor = _read_row(world, built["rows"][1]["id"])
    assert survivor["ledger_status"] == "CREDITED"
    assert _read_session(world, built["sessions"][1]["id"])["status"] == "DELIVERED"

    trainee = world.read_recruit(built["recruit"]["id"])
    assert_hours_equals(trainee["credited_hours_total"], "2.00",
                        "credited_hours_total")
    assert_hours_equals(trainee["per_topic_credited_hours"][PATROL], "2.00",
                        f"per_topic_credited_hours[{PATROL}]")
    assert_hours_equals(trainee["scheduled_basis_hours_total"], "2.00",
                        "scheduled_basis_hours_total")
    assert trainee["academy_status"] == "IN_PROGRESS"


def test_the_reversal_is_appended_beside_the_credits_it_undoes(world):
    """One negative entry joins the two positive ones; nothing is deleted.

    PRD: "For each reversed row the system appends a training record entry of
    `kind` `HOURS_REVERSAL` with `stage_code` `ACADEMY`, the session's
    `topic_code` and a `hours_delta` equal to the *negative* of that row's
    previous `credited_hours`."

    Design: Difficulty/compensating_invariant/void_delivery_restores_class_credited_topic_hours_total_exactly
    """
    built = _two_delivered_sessions(world)

    world.void_delivery(built["sessions"][0]["id"], VOID_REASON)

    entries, _meta = validate_paginated(world.client.list_training_record_entries(
        custodian_headers(), {"recruit_id": built["recruit"]["id"], "limit": 100}))
    assert count_entries(entries, kind="HOURS_CREDIT") == 2
    assert count_entries(entries, kind="HOURS_REVERSAL") == 1

    reversal = find_entry(entries, kind="HOURS_REVERSAL")
    assert reversal is not None
    assert reversal["topic_code"] == PATROL
    assert reversal["stage_code"] == "ACADEMY"
    assert_hours_equals(reversal["hours_delta"], "-2.00", "hours_delta")


def _probation_pushed_by_a_remedial_phase(world):
    """A probation schedule extended by a phase-two rotation that flipped REMEDIAL."""
    curriculum = world.curriculum(topic_code=PATROL, required_hours=2.0,
                                  exam_required=False, min_total_hours=2.0,
                                  session_ends_at="2026-08-03T11:00:00Z",
                                  after_session="2026-08-03T11:00:00Z")
    recruit = world.recruit_in_field_training(curriculum)
    first_fto = world.create_certified_fto()
    second_fto = world.create_certified_fto()

    phase_one = world.plan_rotation(recruit, first_fto["id"], phase_number=1,
                                    start_date="2027-03-01",
                                    end_date="2027-03-31")
    world.activate_rotation(phase_one["id"])
    world.set_clock("2027-03-13T12:00:00Z")
    world.file_report(phase_one["id"], first_fto["id"], "2027-03-10",
                      f.dimension_ratings(6))
    world.set_clock("2027-03-31T12:00:00Z")
    world.complete_rotation(phase_one["id"])

    before = world.advance(recruit["id"], "PROBATION",
                           probation_start="2027-04-01",
                           probation_base_days=365)
    phase_two = world.plan_rotation(
        world.read_recruit(recruit["id"]), second_fto["id"], phase_number=2,
        start_date="2027-04-05", end_date="2027-05-05",
        prior_rotation_id=phase_one["id"])
    world.activate_rotation(phase_two["id"])
    world.set_clock("2027-04-20T12:00:00Z")
    report = world.file_report(phase_two["id"], second_fto["id"], "2027-04-10",
                               f.dimension_ratings(3))
    after = world.read_recruit(recruit["id"])
    return {"recruit": recruit, "first_fto": first_fto,
            "second_fto": second_fto, "phase_one": phase_one,
            "phase_two": phase_two, "report": report,
            "before": before, "after": after}


def test_aborting_a_remedial_rotation_empties_its_scores_and_voids_its_reports(world):
    """The rotation's two scores return to their empty-set value of null.

    PRD: "Every non-voided report of the rotation is marked `voided` true, and
    `dor_count`, `remedial_flag_count`, `competency_score` and
    `rolling_mean_score` all return to their empty-set values, meaning both scores
    become null."

    Design: Difficulty/compensating_invariant/abort_remedial_rotation_restores_active_trainee_count_and_probation_schedule
    """
    built = _probation_pushed_by_a_remedial_phase(world)
    reason = "assigned FTO reassigned to patrol; phase restarts later"

    aborted = world.abort_rotation(built["phase_two"]["id"], reason)
    assert aborted["status"] == "ABORTED"
    assert aborted["abort_reason"] == reason
    assert aborted["dor_count"] == 0
    assert aborted["competency_score"] is None
    assert aborted["rolling_mean_score"] is None

    report = validate_success(world.client.get_observation_report(
        built["report"]["id"], coordinator_headers()))
    assert report["voided"] is True
    assert_score_equals(report["dor_mean"], "3.00", "dor_mean")


def test_the_abort_restores_the_officers_load_and_the_pre_cascade_schedule(world):
    """The 60-day extension is undone exactly and the milestone score reverts to 6.00.

    PRD: "when the trainee's `probation_status` is `EXTENSION_REQUIRED` and no
    rotation of that trainee remains at `REMEDIAL`, `probation_status` returns to
    `ACTIVE` and the probation schedule is re-derived, restoring
    `probation_extension_days` and `probation_scheduled_end` to their pre-cascade
    values."

    Design: Difficulty/compensating_invariant/abort_remedial_rotation_restores_active_trainee_count_and_probation_schedule
    """
    built = _probation_pushed_by_a_remedial_phase(world)
    assert_score_equals(built["before"]["probation_milestone_score"], "6.00",
                        "probation_milestone_score before")
    assert built["before"]["probation_extension_days"] == 0
    assert built["before"]["probation_scheduled_end"] == "2028-03-31"
    assert built["after"]["probation_extension_days"] == 60
    assert built["after"]["probation_scheduled_end"] == "2028-05-30"

    world.abort_rotation(built["phase_two"]["id"])

    restored = world.read_recruit(built["recruit"]["id"])
    assert restored["probation_status"] == "ACTIVE"
    assert_score_equals(restored["probation_milestone_score"], "6.00",
                        "probation_milestone_score")
    assert restored["probation_extension_days"] == 0
    assert restored["probation_scheduled_end"] == "2028-03-31"
    assert restored["probation_milestone_due_date"] == "2027-09-30"

    for officer in (built["first_fto"], built["second_fto"]):
        loaded = validate_success(world.client.get_instructor(officer["id"],
                                                            director_headers()))
        assert loaded["active_trainee_count"] == 0
    assert world.read_rotation(built["phase_one"]["id"])["status"] == "COMPLETED"


def test_the_restored_probation_still_waits_for_its_milestone_date(world):
    """A restored ACTIVE probation cannot be passed before the milestone date.

    PRD: "`PASS` is legal from `ACTIVE` only and moves `probation_status` to
    `PASSED`, which is terminal; it additionally requires the logical clock's date
    to have reached `probation_milestone_due_date`, or the answer is
    `ERR_MILESTONE_NOT_REACHED`, and requires `probation_milestone_score` not to
    be null, without which the trigger is not declared and the answer is
    `ERR_INVALID_STATE`."

    Design: Difficulty/compensating_invariant/abort_remedial_rotation_restores_active_trainee_count_and_probation_schedule
    """
    built = _probation_pushed_by_a_remedial_phase(world)
    world.abort_rotation(built["phase_two"]["id"])

    refused = world.client.create_probation_decision(
        built["recruit"]["id"],
        f.probation_decision_payload("PASS", "early closure requested"),
        director_headers())
    validate_error(refused, ERR_MILESTONE_NOT_REACHED, 409)

    unchanged = world.read_recruit(built["recruit"]["id"])
    assert unchanged["probation_status"] == "ACTIVE"
    assert unchanged["pipeline_stage"] == "PROBATION"
