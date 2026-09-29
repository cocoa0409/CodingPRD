"""Where each state machine opens, where it locks, and what a hop drags with it.

A recruit carries four independent dimensions on one row, a session and a
rotation each carry their own lifecycle, and the contract pins exactly which of
them a single request is allowed to move.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_CLEARANCE_INCOMPLETE,
    ERR_MILESTONE_NOT_REACHED,
    ERR_PROBATION_NOT_ACTIVE,
    ERR_RECRUIT_NOT_IN_ACADEMY,
    ERR_RECRUIT_TERMINAL,
    ERR_ROTATION_NOT_ACTIVE,
    ERR_SESSION_NOT_DELIVERABLE,
    ERR_SESSION_NOT_VOIDABLE,
    ERR_STAGE_TRANSITION_NOT_ALLOWED,
)
from test_helpers.assertions import (
    assert_hours_equals,
    assert_instant_equals,
    assert_ladder_precedence,
    assert_score_equals,
    count_entries,
    find_entry,
)
from test_helpers.test_users import (
    coordinator_headers,
    custodian_headers,
    director_headers,
    make_fto_headers,
)
from test_helpers.types import ALL_SCREENING_TYPES

PATROL = "PATROL"
MORNING_ENDS = "2026-08-10T11:00:00Z"
AFTER_MORNING = "2026-08-10T12:00:00Z"


def _patrol_curriculum(world, exam_required=False, **standard_kwargs):
    """A two-hour PATROL requirement taught in one morning block."""
    return world.curriculum(topic_code=PATROL, required_hours=2.0,
                            exam_required=exam_required, min_total_hours=2.0,
                            session_starts_at="2026-08-10T09:00:00Z",
                            session_ends_at=MORNING_ENDS,
                            after_session=AFTER_MORNING, **standard_kwargs)


def _morning_session(world, built, day="2026-08-10", min_enrollment=1):
    """One two-hour PATROL block on the named day in room R1."""
    return world.schedule_session(built["cohort"]["id"],
                                  built["lesson_plan"]["id"],
                                  built["instructor"]["id"], room_code="R1",
                                  starts_at=f"{day}T09:00:00Z",
                                  ends_at=f"{day}T11:00:00Z",
                                  min_enrollment=min_enrollment)


def _entries(world, **params):
    """The training record, read through the custodian's listing."""
    params.setdefault("limit", 100)
    rows, meta = validate_paginated(
        world.client.list_training_record_entries(custodian_headers(), params))
    return rows, meta


def test_every_lifecycle_opens_at_its_own_declared_start(world):
    """A screening, an examination, a rotation and an attendance row all open empty.

    PRD: "A new rotation starts at `status` `PLANNED` with `competency_score`
    and `rolling_mean_score` both null, `final_narrative` and `abort_reason`
    null, and `dor_count` and `remedial_flag_count` at zero."

    Design: Corner/state_machines/initial_state_screening_examination_and_rotation_each_open_at_their_own_start
    """
    built = _patrol_curriculum(world, exam_required=True)

    fresh = world.create_recruit(built["cohort"]["id"])
    screening = validate_success(world.client.order_screening(
        fresh["id"], f.screening_payload("BACKGROUND"), coordinator_headers()),
        201)
    assert screening["status"] == "ORDERED"
    assert screening["attempt_number"] == 1
    assert screening["composite_score"] is None
    assert screening["findings_recorded_by_user_id"] is None

    studying = world.recruit_in_academy(built["cohort"]["id"])
    examination = world.schedule_examination(studying["id"], PATROL)
    assert examination["status"] == "SCHEDULED"
    assert examination["attempt_number"] == 1
    assert examination["raw_score"] is None
    assert_hours_equals(examination["remediation_hours"], "0.00",
                        "remediation_hours")

    trainee = world.recruit_in_field_training(built)
    officer = world.create_certified_fto()
    rotation = world.plan_rotation(trainee, officer["id"], phase_number=1,
                                   start_date="2026-08-20",
                                   end_date="2026-09-02")
    assert rotation["status"] == "PLANNED"
    assert rotation["dor_count"] == 0
    assert rotation["remedial_flag_count"] == 0
    assert rotation["competency_score"] is None
    assert rotation["rolling_mean_score"] is None

    later = _morning_session(world, built, day="2026-08-12")
    row = world.record_attendance(later["id"], studying["id"], "PRESENT", 2.0)
    assert row["ledger_status"] == "PROVISIONAL"
    assert_hours_equals(row["credited_hours"], "0.00", "credited_hours")
    assert_hours_equals(row["counted_absence_hours"], "0.00",
                        "counted_absence_hours")
    assert row["void_reason"] is None

    # Planning never reserves the officer; activation is the reservation.
    reserved = validate_success(world.client.get_instructor(officer["id"],
                                                           director_headers()))
    assert reserved["active_trainee_count"] == 0


def test_a_dismissed_recruit_answers_the_terminal_code_to_every_mutation(world):
    """Five different mutations all report the terminal code, not their own.

    PRD: "This rung sits deliberately **above** the per-entity state family on
    rung 40: once a recruit is terminal, every mutation naming that recruit
    answers `ERR_RECRUIT_TERMINAL` rather than the narrower
    `ERR_STAGE_TRANSITION_NOT_ALLOWED`, `ERR_PROBATION_NOT_ACTIVE` or
    `ERR_INVALID_STATE` that the same request would also have violated."

    Design: Corner/state_machines/terminal_state_lockdown_dismissed_recruit_rejects_every_further_mutation
    """
    built = _patrol_curriculum(world, exam_required=True)
    recruit = world.recruit_in_academy(built["cohort"]["id"])

    dismissed = world.dismiss(recruit["id"], "INTEGRITY",
                              "falsified application")
    assert dismissed["pipeline_stage"] == "DISMISSED"
    assert dismissed["dismissal_reason_code"] == "INTEGRITY"
    frozen_version = dismissed["version"]

    hop = validate_error(world.client.advance_stage(
        recruit["id"], f.advance_stage_payload("FIELD_TRAINING"),
        coordinator_headers()), ERR_RECRUIT_TERMINAL, 409)
    assert_ladder_precedence(hop["error_id"], ERR_RECRUIT_TERMINAL,
                             ERR_STAGE_TRANSITION_NOT_ALLOWED)

    validate_error(world.client.order_screening(
        recruit["id"], f.screening_payload("MEDICAL"), coordinator_headers()),
        ERR_RECRUIT_TERMINAL, 409)

    validate_error(world.client.dismiss_recruit(
        recruit["id"], f.dismiss_payload("MEDICAL", "second attempt"),
        director_headers()), ERR_RECRUIT_TERMINAL, 409)

    decision = validate_error(world.client.create_probation_decision(
        recruit["id"], f.probation_decision_payload("PASS", "premature"),
        director_headers()), ERR_RECRUIT_TERMINAL, 409)
    assert_ladder_precedence(decision["error_id"], ERR_RECRUIT_TERMINAL,
                             ERR_PROBATION_NOT_ACTIVE)

    sitting = validate_error(world.client.create_examination(
        f.examination_payload(recruit["id"], PATROL), coordinator_headers()),
        ERR_RECRUIT_TERMINAL, 409)
    assert_ladder_precedence(sitting["error_id"], ERR_RECRUIT_TERMINAL,
                             ERR_RECRUIT_NOT_IN_ACADEMY)

    final = world.read_recruit(recruit["id"])
    assert final["pipeline_stage"] == "DISMISSED"
    assert final["dismissal_reason_code"] == "INTEGRITY"
    assert final["version"] == frozen_version


def test_hops_that_skip_a_stage_are_refused_by_the_transition_rule(world):
    """Screening to probation and applicant to academy are both illegal hops.

    PRD: "Exactly one successor is legal from each stage, and naming anything
    else - including a stage the recruit has already passed, or a hop that skips
    one - answers `ERR_STAGE_TRANSITION_NOT_ALLOWED`."

    Design: Corner/state_machines/invalid_transitions_illegal_stage_hops_are_rejected_with_the_narrow_code
    """
    built = _patrol_curriculum(world)
    screening = world.recruit_in_screening(built["cohort"]["id"])
    applicant = world.create_recruit(built["cohort"]["id"])

    skipped = validate_error(world.client.advance_stage(
        screening["id"],
        f.advance_stage_payload("PROBATION", probation_start="2026-09-05"),
        coordinator_headers()), ERR_STAGE_TRANSITION_NOT_ALLOWED, 409)
    assert_ladder_precedence(skipped["error_id"],
                             ERR_STAGE_TRANSITION_NOT_ALLOWED,
                             ERR_CLEARANCE_INCOMPLETE)

    # The APPLICANT -> SCREENING hop is reached by ordering work, never here.
    validate_error(world.client.advance_stage(
        applicant["id"], f.advance_stage_payload("ACADEMY"),
        coordinator_headers()), ERR_STAGE_TRANSITION_NOT_ALLOWED, 409)

    # An exit is legal from SCREENING, ACADEMY, FIELD_TRAINING or PROBATION
    # only, so an applicant cannot be dismissed: a state-family conflict.
    exit_attempt = world.client.dismiss_recruit(
        applicant["id"], f.dismiss_payload("INTEGRITY", "no exit edge here"),
        director_headers())
    assert exit_attempt.status_code == 409

    untouched = world.read_recruit(applicant["id"])
    assert untouched["pipeline_stage"] == "APPLICANT"
    assert untouched["dismissal_reason_code"] is None


def test_a_replayed_delivery_and_a_replayed_void_are_both_refused(world):
    """The second deliver and the second void are conflicts, not replays.

    PRD: "The session moves `DELIVERED` -> `VOIDED`, which is terminal, with
    `void_reason` recording the supplied reason and `delivered_at` cleared back
    to null."

    Design: Corner/state_machines/idempotency_repeat_deliver_and_repeat_void_are_rejected_never_replayed
    """
    built = _patrol_curriculum(world)
    recruit = world.recruit_in_academy(built["cohort"]["id"])
    session = _morning_session(world, built)
    world.record_attendance(session["id"], recruit["id"], "PRESENT", 2.0)
    world.set_clock(AFTER_MORNING)

    delivered = world.deliver_session(session["id"])
    assert delivered["status"] == "DELIVERED"
    assert_hours_equals(delivered["credited_hours_total"], "2.00",
                        "credited_hours_total")

    validate_error(world.client.deliver_course_session(
        session["id"], coordinator_headers()), ERR_SESSION_NOT_DELIVERABLE, 409)
    after_replay = validate_success(world.client.get_academy_class(
        built["cohort"]["id"], director_headers()))
    assert_hours_equals(after_replay["credited_topic_hours_total"], "2.00",
                        "credited_topic_hours_total")

    voided = world.void_delivery(session["id"], "instructor recalled to duty")
    assert voided["status"] == "VOIDED"
    assert_hours_equals(voided["credited_hours_total"], "0.00",
                        "credited_hours_total")

    validate_error(world.client.void_course_session_delivery(
        session["id"], f.void_delivery_payload("second attempt"),
        director_headers()), ERR_SESSION_NOT_VOIDABLE, 409)
    after_second_void = validate_success(world.client.get_academy_class(
        built["cohort"]["id"], director_headers()))
    assert_hours_equals(after_second_void["credited_topic_hours_total"], "0.00",
                        "credited_topic_hours_total")

    rows, _meta = _entries(world, academy_class_id=built["cohort"]["id"])
    assert count_entries(rows, kind="HOURS_CREDIT") == 1
    assert count_entries(rows, kind="HOURS_REVERSAL") == 1


def _planned_and_aborted_phase_one(world, built):
    """One aborted phase one and one still-planned phase one for the same trainee."""
    trainee = world.recruit_in_field_training(built)
    keeper_officer = world.create_certified_fto()
    scrapped_officer = world.create_certified_fto()

    scrapped = world.plan_rotation(world.read_recruit(trainee["id"]),
                                   scrapped_officer["id"], phase_number=1,
                                   start_date="2026-08-20",
                                   end_date="2026-09-02")
    world.abort_rotation(scrapped["id"], "trainee reassigned")
    keeper = world.plan_rotation(world.read_recruit(trainee["id"]),
                                 keeper_officer["id"], phase_number=1,
                                 start_date="2026-08-20",
                                 end_date="2026-09-02")
    return {"trainee": trainee, "officer": keeper_officer,
            "keeper": keeper, "scrapped": scrapped}


def test_closing_a_rotation_needs_one_in_service(world):
    """A planned phase and an aborted phase both refuse completion and reports.

    PRD: "A `FieldTrainingOfficer` or a `TrainingCoordinator` completes a
    rotation from `ACTIVE` **or** `REMEDIAL`, supplying the `final_narrative`."

    Design: Corner/state_machines/precondition_enforcement_rotation_completion_requires_a_live_rotation
    """
    built = _patrol_curriculum(world)
    phases = _planned_and_aborted_phase_one(world, built)
    world.set_clock("2026-09-20T08:00:00Z")

    validate_error(world.client.complete_rotation(
        phases["keeper"]["id"], f.complete_rotation_payload("phase closed"),
        coordinator_headers()), ERR_ROTATION_NOT_ACTIVE, 409)

    validate_error(world.client.complete_rotation(
        phases["scrapped"]["id"], f.complete_rotation_payload("phase closed"),
        coordinator_headers()), ERR_ROTATION_NOT_ACTIVE, 409)

    validate_error(world.client.create_observation_report(
        phases["keeper"]["id"],
        f.observation_report_payload(phases["officer"]["id"], "2026-08-21",
                                    f.dimension_ratings(5),
                                    "filed against a planned rotation"),
        make_fto_headers(phases["officer"]["id"])),
        ERR_ROTATION_NOT_ACTIVE, 409)

    still_planned = world.read_rotation(phases["keeper"]["id"])
    assert still_planned["status"] == "PLANNED"
    assert still_planned["dor_count"] == 0
    assert still_planned["final_narrative"] is None

    unreserved = validate_success(world.client.get_instructor(
        phases["officer"]["id"], director_headers()))
    assert unreserved["active_trainee_count"] == 0


def test_a_probation_decision_needs_a_probation_to_decide(world):
    """A trainee still in field training has no probation to pass or separate.

    PRD: "The recruit's `probation_status` must be `ACTIVE` or
    `EXTENSION_REQUIRED`, or the answer is `ERR_PROBATION_NOT_ACTIVE`."

    Design: Corner/state_machines/precondition_enforcement_probation_decision_requires_an_open_probation
    """
    built = _patrol_curriculum(world)
    trainee = world.recruit_in_field_training(built)

    passing = validate_error(world.client.create_probation_decision(
        trainee["id"], f.probation_decision_payload("PASS", "too early"),
        director_headers()), ERR_PROBATION_NOT_ACTIVE, 409)
    # The milestone gate sits at a later priority than the posture gate.
    assert_ladder_precedence(passing["error_id"], ERR_PROBATION_NOT_ACTIVE,
                             ERR_MILESTONE_NOT_REACHED)

    validate_error(world.client.create_probation_decision(
        trainee["id"], f.probation_decision_payload("SEPARATE", "too early"),
        director_headers()), ERR_PROBATION_NOT_ACTIVE, 409)

    untouched = world.read_recruit(trainee["id"])
    assert untouched["probation_status"] == "NOT_APPLICABLE"
    assert untouched["probation_start"] is None
    assert untouched["probation_milestone_due_date"] is None
    assert untouched["pipeline_stage"] == "FIELD_TRAINING"


def test_the_academy_hop_needs_a_finished_clearance(world):
    """A partial clearance and a pending one are both refused entry to the academy.

    PRD: "`SCREENING` -> `ACADEMY` requires `clearance_status` to be exactly
    `CLEARED`, answering `ERR_CLEARANCE_INCOMPLETE` while it is `PENDING` or
    `PARTIAL`"

    Design: Corner/state_machines/precondition_enforcement_academy_advance_requires_completed_clearance
    """
    built = _patrol_curriculum(world)
    partial = world.create_recruit(built["cohort"]["id"])
    world.clear_screening(partial["id"], "BACKGROUND")
    pending = world.recruit_in_screening(built["cohort"]["id"])

    validate_error(world.client.advance_stage(
        partial["id"], f.advance_stage_payload("ACADEMY"),
        coordinator_headers()), ERR_CLEARANCE_INCOMPLETE, 422)
    validate_error(world.client.advance_stage(
        pending["id"], f.advance_stage_payload("ACADEMY"),
        coordinator_headers()), ERR_CLEARANCE_INCOMPLETE, 422)

    held = world.read_recruit(partial["id"])
    assert held["clearance_status"] == "PARTIAL"
    assert held["pipeline_stage"] == "SCREENING"
    assert held["academy_status"] == "NOT_STARTED"

    waiting = world.read_recruit(pending["id"])
    assert waiting["clearance_status"] == "PENDING"
    assert waiting["pipeline_stage"] == "SCREENING"

    for recruit_id in (partial["id"], pending["id"]):
        rows, _meta = _entries(world, recruit_id=recruit_id, kind="STAGE_ENTRY")
        assert count_entries(rows, stage_code="ACADEMY") == 0


def test_the_clearance_dimension_walks_pending_partial_then_cleared(world):
    """Four adjudications move the aggregate PENDING, PARTIAL, PARTIAL, CLEARED.

    PRD: "From `PARTIAL` it becomes `CLEARED` when all four screening types -
    `BACKGROUND`, `MEDICAL`, `PSYCHOLOGICAL` and `PHYSICAL_FITNESS` - each have
    a record of this recruit at `CLEARED` or `WAIVED`."

    Design: Corner/state_machines/valid_transition_clearance_walks_pending_partial_cleared_as_adjudications_land
    """
    built = _patrol_curriculum(world, fitness_event_floor_points=10,
                               fitness_pass_score=60)
    recruit = world.create_recruit(built["cohort"]["id"])
    ordered = {screening_type: world.order_screening(recruit["id"], screening_type)
               for screening_type in ALL_SCREENING_TYPES}
    assert world.read_recruit(recruit["id"])["clearance_status"] == "PENDING"

    walk = []
    for screening_type in ALL_SCREENING_TYPES:
        recorded = world.record_findings(ordered[screening_type]["id"],
                                         screening_type)
        if screening_type == "PHYSICAL_FITNESS":
            assert recorded["composite_score"] == 77
        adjudicated = world.adjudicate(ordered[screening_type]["id"],
                                       screening_type, "CLEAR")
        assert adjudicated["status"] == "CLEARED"
        assert adjudicated["adjudicated_by_user_id"] is not None
        walk.append(world.read_recruit(recruit["id"])["clearance_status"])

    assert walk == ["PARTIAL", "PARTIAL", "PARTIAL", "CLEARED"]
    # Clearance never advances the pipeline on its own.
    assert world.read_recruit(recruit["id"])["pipeline_stage"] == "SCREENING"


def test_closing_out_a_session_writes_the_row_the_ledger_and_the_audit_together(world):
    """One deliver credits the roster row and appends exactly one ledger entry.

    PRD: "Every attendance row of the session at `PROVISIONAL` moves to
    `CREDITED`, with `credited_hours` and `counted_absence_hours` computed as
    described below. For each credited row the system appends a training record
    entry of `kind` `HOURS_CREDIT` with `stage_code` `ACADEMY`, the session's
    `topic_code`, and a `hours_delta` equal to that row's positive
    `credited_hours`."

    Design: Corner/state_machines/side_effect_execution_deliver_writes_attendance_ledger_and_audit_rows_together
    """
    built = _patrol_curriculum(world)
    recruit = world.recruit_in_academy(built["cohort"]["id"])
    session = _morning_session(world, built)
    row = world.record_attendance(session["id"], recruit["id"], "PRESENT", 2.0)
    world.set_clock(AFTER_MORNING)

    delivered = world.deliver_session(session["id"])
    assert delivered["status"] == "DELIVERED"
    assert_hours_equals(delivered["credited_hours_total"], "2.00",
                        "credited_hours_total")
    assert_instant_equals(delivered["delivered_at"], AFTER_MORNING,
                          "delivered_at")

    credited = validate_success(world.client.get_attendance_record(
        row["id"], coordinator_headers()))
    # The row was credited in place, not re-created.
    assert credited["id"] == row["id"]
    assert credited["ledger_status"] == "CREDITED"
    assert_hours_equals(credited["credited_hours"], "2.00", "credited_hours")
    assert_hours_equals(credited["counted_absence_hours"], "0.00",
                        "counted_absence_hours")
    assert credited["void_reason"] is None

    rows, meta = _entries(world, recruit_id=recruit["id"], kind="HOURS_CREDIT")
    assert meta["total_count"] == 1
    assert rows[0]["kind"] == "HOURS_CREDIT"
    assert_hours_equals(rows[0]["hours_delta"], "2.00", "hours_delta")
    assert rows[0]["topic_code"] == PATROL
    assert rows[0]["stage_code"] == "ACADEMY"
    assert rows[0]["subject_entity_id"] is not None

    roster, roster_meta = validate_paginated(world.client.list_attendance_records(
        coordinator_headers(), {"course_session_id": session["id"],
                               "recruit_id": recruit["id"]}))
    assert roster_meta["total_count"] == 1
    assert roster[0]["id"] == row["id"]


def test_a_replacement_session_pulls_an_at_risk_cohort_back_into_session(world):
    """Voiding drops the cohort to AT_RISK and a fresh session restores it.

    PRD: "An `AT_RISK` cohort climbs back to `IN_SESSION` as soon as a
    replacement session restores every topic's projected hours to at least its
    `required_hours`, closing the `IN_SESSION` <-> `AT_RISK` posture loop."

    Design: Corner/state_machines/cyclic_class_returns_from_at_risk_once_a_replacement_session_restores_projection
    """
    built = _patrol_curriculum(world)
    recruit = world.recruit_in_academy(built["cohort"]["id"])
    session = _morning_session(world, built)
    world.record_attendance(session["id"], recruit["id"], "PRESENT", 2.0)
    world.set_clock(AFTER_MORNING)
    world.deliver_session(session["id"])

    def read_cohort():
        return validate_success(world.client.get_academy_class(
            built["cohort"]["id"], director_headers()))

    teaching = read_cohort()
    assert teaching["status"] == "IN_SESSION"
    assert_hours_equals(teaching["projected_topic_hours"][PATROL], "2.00",
                        "projected_topic_hours")
    assert_hours_equals(teaching["unmet_topic_hours"][PATROL], "0.00",
                        "unmet_topic_hours")

    voided = world.void_delivery(session["id"], "instructor recalled to duty")
    assert voided["status"] == "VOIDED"

    exposed = read_cohort()
    assert exposed["status"] == "AT_RISK"
    assert_hours_equals(exposed["projected_topic_hours"][PATROL], "0.00",
                        "projected_topic_hours")
    assert_hours_equals(exposed["unmet_topic_hours"][PATROL], "2.00",
                        "unmet_topic_hours")

    replacement = _morning_session(world, built, day="2026-08-12")
    assert replacement["status"] == "SCHEDULED"

    restored = read_cohort()
    assert restored["status"] == "IN_SESSION"
    assert_hours_equals(restored["projected_topic_hours"][PATROL], "2.00",
                        "projected_topic_hours")
    # The return is driven by projected hours, not by credited ones.
    assert_hours_equals(restored["credited_topic_hours_total"], "0.00",
                        "credited_topic_hours_total")


def test_the_four_recruit_dimensions_advance_independently_of_one_another(world):
    """Five checkpoints show the academy substate moving while the pipeline holds.

    PRD: "A recruit carries **four independent state dimensions on the same
    row**, and understanding that they move independently is essential."

    Design: Corner/state_machines/parallel_four_recruit_dimensions_advance_independently_of_one_another
    """
    built = _patrol_curriculum(world)
    recruit = world.create_recruit(built["cohort"]["id"])

    def snapshot():
        read = world.read_recruit(recruit["id"])
        return (read["pipeline_stage"], read["clearance_status"],
                read["academy_status"], read["probation_status"],
                read["probation_start"])

    checkpoints = [snapshot()]
    world.clear_all_four_screenings(recruit["id"])
    checkpoints.append(snapshot())
    world.advance(recruit["id"], "ACADEMY")
    checkpoints.append(snapshot())

    session = _morning_session(world, built)
    world.record_attendance(session["id"], recruit["id"], "PRESENT", 2.0)
    world.set_clock(AFTER_MORNING)
    world.deliver_session(session["id"])
    checkpoints.append(snapshot())

    world.advance(recruit["id"], "FIELD_TRAINING")
    checkpoints.append(snapshot())

    assert [point[:4] for point in checkpoints] == [
        ("APPLICANT", "PENDING", "NOT_STARTED", "NOT_APPLICABLE"),
        ("SCREENING", "CLEARED", "NOT_STARTED", "NOT_APPLICABLE"),
        ("ACADEMY", "CLEARED", "IN_PROGRESS", "NOT_APPLICABLE"),
        ("ACADEMY", "CLEARED", "COMPLETE", "NOT_APPLICABLE"),
        ("FIELD_TRAINING", "CLEARED", "COMPLETE", "NOT_APPLICABLE"),
    ]
    assert all(point[4] is None for point in checkpoints)


def test_leaving_the_academy_freezes_its_substate_while_probation_opens(world):
    """The probation hop opens one substate and leaves the academy one at COMPLETE.

    PRD: "The hop sets `probation_status` to `ACTIVE` from `NOT_APPLICABLE` and
    runs the probation schedule."

    Design: Corner/state_machines/compound_academy_and_probation_substates_freeze_outside_their_parent_stage
    """
    built = _patrol_curriculum(world)
    trainee = world.recruit_in_field_training(built)
    officer = world.create_certified_fto()
    rotation = world.plan_rotation(trainee, officer["id"], phase_number=1,
                                   start_date="2026-08-20",
                                   end_date="2026-09-02")
    world.set_clock("2026-08-20T08:00:00Z")
    world.activate_rotation(rotation["id"])
    world.set_clock("2026-08-21T18:00:00Z")
    world.file_report(rotation["id"], officer["id"], "2026-08-21",
                      f.dimension_ratings(5), not_responding_to_training=False)
    world.set_clock("2026-09-03T08:00:00Z")
    world.complete_rotation(rotation["id"])

    before = world.read_recruit(trainee["id"])
    assert before["pipeline_stage"] == "FIELD_TRAINING"
    assert before["academy_status"] == "COMPLETE"
    assert before["probation_status"] == "NOT_APPLICABLE"
    assert before["probation_milestone_due_date"] is None

    probationary = world.advance(trainee["id"], "PROBATION",
                                 probation_start="2026-09-05")
    assert probationary["pipeline_stage"] == "PROBATION"
    assert probationary["probation_status"] == "ACTIVE"
    assert probationary["probation_start"] == "2026-09-05"
    assert probationary["probation_base_days"] == 365
    # Step 1: 2026-09-05 plus the floor of 365 halved, or 182 days.
    assert probationary["probation_milestone_due_date"] == "2027-03-06"
    assert_score_equals(probationary["probation_milestone_score"], "5.00",
                        "probation_milestone_score")
    assert probationary["probation_extension_days"] == 0
    assert probationary["probation_scheduled_end"] == "2027-09-05"
    # Leaving ACADEMY neither reset nor advanced the academy substate.
    assert probationary["academy_status"] == "COMPLETE"

    rows, _meta = _entries(world, recruit_id=trainee["id"], kind="STAGE_ENTRY")
    assert find_entry(rows, stage_code="PROBATION") is not None


def test_dismissing_an_academy_recruit_voids_the_row_and_starves_the_session(world):
    """The exit voids the provisional row and drops the session below its floor.

    PRD: "From `ACADEMY`, every attendance row of the recruit at `PROVISIONAL`
    is set to `VOIDED` with `void_reason` recording that the recruit exited the
    pipeline, each affected session re-derives `enrolled_count`, and a
    `SCHEDULED` session that falls below `min_enrollment` moves to
    `UNDER_MIN_ENROLLMENT`."

    Design: Corner/state_machines/cascade_down_dismissing_an_academy_recruit_voids_rows_and_starves_the_session
    """
    built = _patrol_curriculum(world)
    recruit = world.recruit_in_academy(built["cohort"]["id"])
    session = _morning_session(world, built)
    row = world.record_attendance(session["id"], recruit["id"], "PRESENT", 2.0)

    dismissed = world.dismiss(recruit["id"], "ABSENCE_LIMIT",
                              "failed to report")
    assert dismissed["pipeline_stage"] == "DISMISSED"
    assert dismissed["dismissal_reason_code"] == "ABSENCE_LIMIT"

    orphaned = validate_success(world.client.get_attendance_record(
        row["id"], coordinator_headers()))
    assert orphaned["ledger_status"] == "VOIDED"
    assert isinstance(orphaned["void_reason"], str) and orphaned["void_reason"]
    assert_hours_equals(orphaned["credited_hours"], "0.00", "credited_hours")

    starved = validate_success(world.client.get_course_session(
        session["id"], coordinator_headers()))
    assert starved["enrolled_count"] == 0
    assert starved["status"] == "UNDER_MIN_ENROLLMENT"
    # The session was never delivered, so no reversal was needed.
    assert_hours_equals(starved["credited_hours_total"], "0.00",
                        "credited_hours_total")

    rows, _meta = _entries(world, recruit_id=recruit["id"], kind="ADVERSE_EXIT")
    assert len(rows) == 1
    assert rows[0]["stage_code"] == "ACADEMY"

    cohort = validate_success(world.client.get_academy_class(
        built["cohort"]["id"], director_headers()))
    assert_hours_equals(cohort["credited_topic_hours_total"], "0.00",
                        "credited_topic_hours_total")


def test_crediting_one_attendance_row_moves_both_of_its_parents(world):
    """One delivery moves the cohort posture and the recruit's academy substate.

    PRD: "The cohort's `credited_topic_hours_total` rises by that amount and its
    `unmet_topic_hours` and `projected_topic_hours` are re-derived, and a cohort
    at `FORMING` moves to `IN_SESSION` on its first delivered session."

    Design: Corner/state_machines/bubble_up_crediting_a_child_attendance_row_moves_both_parent_entities
    """
    built = _patrol_curriculum(world)
    recruit = world.recruit_in_academy(built["cohort"]["id"])
    session = _morning_session(world, built)
    world.record_attendance(session["id"], recruit["id"], "PRESENT", 2.0)
    world.set_clock(AFTER_MORNING)

    forming = validate_success(world.client.get_academy_class(
        built["cohort"]["id"], director_headers()))
    assert forming["status"] == "FORMING"
    assert_hours_equals(forming["credited_topic_hours_total"], "0.00",
                        "credited_topic_hours_total")

    world.deliver_session(session["id"])

    teaching = validate_success(world.client.get_academy_class(
        built["cohort"]["id"], director_headers()))
    assert teaching["status"] == "IN_SESSION"
    assert_hours_equals(teaching["credited_topic_hours_total"], "2.00",
                        "credited_topic_hours_total")
    assert_hours_equals(teaching["unmet_topic_hours"][PATROL], "0.00",
                        "unmet_topic_hours")

    graduated_curriculum = world.read_recruit(recruit["id"])
    assert graduated_curriculum["academy_status"] == "COMPLETE"
    assert_hours_equals(graduated_curriculum["credited_hours_total"], "2.00",
                        "credited_hours_total")
    assert_hours_equals(graduated_curriculum["per_topic_credited_hours"][PATROL],
                        "2.00", "per_topic_credited_hours")
    # The substate bubbled up without moving the pipeline.
    assert graduated_curriculum["pipeline_stage"] == "ACADEMY"

    hopped = world.advance(recruit["id"], "FIELD_TRAINING")
    assert hopped["pipeline_stage"] == "FIELD_TRAINING"


def test_exiting_from_screening_leaves_the_open_screenings_alone(world):
    """Three unfinished screenings survive the exit untouched.

    PRD: "From `SCREENING`, screening rows at `ORDERED`, `FINDINGS_RECORDED` or
    `RETEST_REQUIRED` are **left untouched** - this cascade only ever reaches
    terminal-bound work."

    Design: Corner/state_machines/conditional_cascade_screening_stage_exit_leaves_open_screenings_untouched
    """
    built = _patrol_curriculum(world, fitness_event_floor_points=10,
                               fitness_pass_score=60)
    recruit = world.create_recruit(built["cohort"]["id"])
    background = world.order_screening(recruit["id"], "BACKGROUND")
    psychological = world.screening_at_findings_recorded(recruit["id"],
                                                        "PSYCHOLOGICAL")
    fitness = world.order_screening(recruit["id"], "PHYSICAL_FITNESS")
    world.record_findings(fitness["id"], "PHYSICAL_FITNESS",
                          raw_metrics=f.FITNESS_FLOOR_CAPPED_METRICS)
    world.adjudicate(fitness["id"], "PHYSICAL_FITNESS", "RETEST")
    world.clear_screening(recruit["id"], "MEDICAL")

    dismissed = world.dismiss(recruit["id"], "INTEGRITY",
                              "falsified application")
    assert dismissed["pipeline_stage"] == "DISMISSED"

    def read_screening(screening_id):
        return validate_success(world.client.get_screening_record(
            screening_id, custodian_headers()))

    assert read_screening(background["id"])["status"] == "ORDERED"
    assert read_screening(psychological["id"])["status"] == "FINDINGS_RECORDED"
    assert read_screening(fitness["id"])["status"] == "RETEST_REQUIRED"

    # The cleared leg still reads PARTIAL; nothing forced DISQUALIFIED.
    assert world.read_recruit(recruit["id"])["clearance_status"] == "PARTIAL"

    _rotations, rotation_meta = validate_paginated(
        world.client.list_field_training_rotations(
            coordinator_headers(), {"recruit_id": recruit["id"]}))
    assert rotation_meta["total_count"] == 0

    rows, _meta = _entries(world, recruit_id=recruit["id"])
    assert count_entries(rows, kind="ADVERSE_EXIT", stage_code="SCREENING") == 1
    assert count_entries(rows, kind="HOURS_REVERSAL") == 0
