"""Loops that re-enter a state the row already occupied, and the rows they read.

A retest walks a screening back into `FINDINGS_RECORDED`; a recovery report walks
a rotation back into `ACTIVE`.  Neither hop is a fresh arrival, and the contract
pins exactly what each one rewrites and what it leaves standing.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_FTO_NOT_CERTIFIED,
    ERR_INVALID_STATE,
    ERR_LESSON_PLAN_NOT_APPROVED,
)
from test_helpers.assertions import assert_hours_equals, assert_instant_equals, assert_score_equals
from test_helpers.test_users import (
    COORDINATOR_ALT_USER_ID,
    COORDINATOR_USER_ID,
    coordinator_alt_headers,
    coordinator_headers,
    director_headers,
)

PATROL = "PATROL"
FITNESS = "PHYSICAL_FITNESS"


def _screening_awaiting_retest(world):
    """A fitness screening whose first attempt scored 59 and was sent to retest."""
    standard = world.create_standard(
        min_total_hours=6.0,
        topic_requirements=[f.topic_requirement(PATROL, 6.0, False)],
        fitness_event_floor_points=10, fitness_pass_score=60)
    cohort = world.create_cohort(standard["id"])
    recruit = world.create_recruit(cohort["id"], full_name="Alba Reyes",
                                   age_bracket="AGE_20_29")
    record = world.order_screening(recruit["id"], FITNESS)
    first = world.record_findings(record["id"], FITNESS,
                                  raw_metrics=f.FITNESS_FLOOR_CAPPED_METRICS)
    assert first["composite_score"] == 59
    sent_back = world.adjudicate(record["id"], FITNESS, "RETEST")
    assert sent_back["status"] == "RETEST_REQUIRED"
    return {"standard": standard, "cohort": cohort, "recruit": recruit,
            "record": record}


def test_a_retest_reenters_the_same_row_and_replaces_its_score(world):
    """Attempt two overwrites the 59 with a 77 on the row the loop left.

    PRD: "A record at `RETEST_REQUIRED` accepts a fresh findings submission,
    which returns it to `FINDINGS_RECORDED`, increments `attempt_number` by one,
    replaces `raw_metrics` and `disqualifier_codes` wholesale, recomputes
    `composite_score`, records the new `findings_recorded_by_user_id` and
    `findings_recorded_at`, and resets `adjudicated_by_user_id` to null -
    re-arming the segregation-of-duties comparison against whoever recorded the
    retest."

    Design: Difficulty/non_linear_state_machine/screening_retest_loop_reenters_findings_recorded_and_resets_adjudicator
    """
    built = _screening_awaiting_retest(world)

    retested = world.record_findings(built["record"]["id"], FITNESS,
                                     raw_metrics=f.FITNESS_PASSING_METRICS)
    assert retested["status"] == "FINDINGS_RECORDED"
    assert retested["attempt_number"] == 2
    assert retested["composite_score"] == 77
    assert retested["raw_metrics"] == f.FITNESS_PASSING_METRICS
    assert retested["findings_recorded_by_user_id"] == COORDINATOR_USER_ID
    assert retested["adjudicated_by_user_id"] is None

    stored = validate_success(world.client.get_screening_record(
        built["record"]["id"], coordinator_headers()))
    assert stored["attempt_number"] == 2
    assert stored["composite_score"] == 77


def test_the_reentered_row_accepts_the_adjudicator_the_loop_cleared(world):
    """The retest adjudicator may clear the row the retest re-armed.

    PRD: "The `decision` field selects one of four outcomes, and each writes
    `adjudicated_by_user_id` from the acting `X-User-ID` and increments the
    recruit's `version` by one:"

    Design: Difficulty/non_linear_state_machine/screening_retest_loop_reenters_findings_recorded_and_resets_adjudicator
    """
    built = _screening_awaiting_retest(world)

    world.record_findings(built["record"]["id"], FITNESS,
                          raw_metrics=f.FITNESS_PASSING_METRICS)
    cleared = world.adjudicate(built["record"]["id"], FITNESS, "CLEAR")
    assert cleared["status"] == "CLEARED"
    assert cleared["adjudicated_by_user_id"] == COORDINATOR_ALT_USER_ID

    trainee = world.read_recruit(built["recruit"]["id"])
    assert trainee["clearance_status"] == "PARTIAL"
    assert trainee["pipeline_stage"] == "SCREENING"


def test_adjudication_is_refused_while_the_row_waits_for_its_retest(world):
    """RETEST_REQUIRED declares findings as its only trigger, not adjudication.

    PRD: "Adjudication is legal only from `FINDINGS_RECORDED`; against a record
    already at `CLEARED`, `WAIVED` or `DISQUALIFIED` - all three terminal - both
    findings and adjudication answer `ERR_SCREENING_ALREADY_ADJUDICATED`."

    Design: Difficulty/non_linear_state_machine/screening_retest_loop_reenters_findings_recorded_and_resets_adjudicator
    """
    built = _screening_awaiting_retest(world)

    refused = world.client.adjudicate_screening(
        built["record"]["id"], f.adjudicate_payload("CLEAR"),
        coordinator_alt_headers())
    validate_error(refused, ERR_INVALID_STATE, 409)

    unchanged = validate_success(world.client.get_screening_record(
        built["record"]["id"], coordinator_headers()))
    assert unchanged["status"] == "RETEST_REQUIRED"
    assert unchanged["attempt_number"] == 1
    assert unchanged["composite_score"] == 59
    assert world.read_recruit(built["recruit"]["id"])["clearance_status"] == "PENDING"


def _probation_with_remedial_phase_two(world):
    """A probationary trainee whose second phase has just flipped REMEDIAL."""
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

    recruit = world.advance(recruit["id"], "PROBATION",
                            probation_start="2027-04-01",
                            probation_base_days=365)
    phase_two = world.plan_rotation(
        world.read_recruit(recruit["id"]), second_fto["id"], phase_number=2,
        start_date="2027-04-05", end_date="2027-05-05",
        prior_rotation_id=phase_one["id"])
    world.activate_rotation(phase_two["id"])
    world.set_clock("2027-04-20T12:00:00Z")
    world.file_report(phase_two["id"], second_fto["id"], "2027-04-10",
                      f.dimension_ratings(3))
    return {"curriculum": curriculum, "recruit": recruit,
            "first_fto": first_fto, "second_fto": second_fto,
            "phase_one": phase_one, "phase_two": phase_two}


def test_a_slumping_report_flips_the_rotation_remedial_and_pushes_probation(world):
    """A single rating sum of 15 scores 3.00, flips REMEDIAL and extends by 60 days.

    PRD: "A rotation at `ACTIVE` whose recomputed score is **strictly less than**
    4.00 moves to `REMEDIAL` - level 2 of the cascade. Because the rotation
    became `REMEDIAL`, level 3 moves the trainee's `probation_status` from
    `ACTIVE` to `EXTENSION_REQUIRED` (only when it was `ACTIVE`)."

    Design: Difficulty/non_linear_state_machine/rotation_remedial_loop_returns_to_active_but_probation_stays_extension_required
    """
    built = _probation_with_remedial_phase_two(world)

    flipped = world.read_rotation(built["phase_two"]["id"])
    assert flipped["status"] == "REMEDIAL"
    assert_score_equals(flipped["competency_score"], "3.00", "competency_score")

    trainee = world.read_recruit(built["recruit"]["id"])
    assert trainee["probation_status"] == "EXTENSION_REQUIRED"
    assert trainee["probation_milestone_due_date"] == "2027-09-30"
    assert_score_equals(trainee["probation_milestone_score"], "3.00",
                        "probation_milestone_score")
    assert trainee["probation_extension_days"] == 60
    assert trainee["probation_scheduled_end"] == "2028-05-30"


def test_a_recovery_report_closes_the_loop_back_to_active(world):
    """Rating sums 15 and 35 weight to 5.00 and return the rotation to ACTIVE.

    PRD: "In the other direction, a rotation at `REMEDIAL` whose recomputed score
    reaches 4.00 or above returns to `ACTIVE`, closing the loop - but this
    direction does **not** restore the trainee's `probation_status`: only an
    explicit extension decision or the abort path closes that loop."

    Design: Difficulty/non_linear_state_machine/rotation_remedial_loop_returns_to_active_but_probation_stays_extension_required
    """
    built = _probation_with_remedial_phase_two(world)

    recovery = world.file_report(built["phase_two"]["id"],
                                built["second_fto"]["id"], "2027-04-11",
                                f.dimension_ratings(7))
    assert_score_equals(recovery["dor_mean"], "7.00", "dor_mean")

    reopened = world.read_rotation(built["phase_two"]["id"])
    assert reopened["status"] == "ACTIVE"
    assert reopened["dor_count"] == 2
    assert reopened["remedial_flag_count"] == 0
    assert_score_equals(reopened["competency_score"], "5.00", "competency_score")
    assert_score_equals(reopened["rolling_mean_score"], "5.00",
                        "rolling_mean_score")


def test_the_upward_flip_leaves_the_probation_schedule_where_the_slump_put_it(world):
    """The trainee stays EXTENSION_REQUIRED on a 60-day extension after recovery.

    PRD: "Four derived fields - `probation_milestone_due_date`,
    `probation_milestone_score`, `probation_extension_days` and
    `probation_scheduled_end` - are re-derived whenever a recruit enters
    probation, on every `probation_status` transition, and on every rotation
    transition into `COMPLETED`, `REMEDIAL` or `ABORTED`."

    Design: Difficulty/non_linear_state_machine/rotation_remedial_loop_returns_to_active_but_probation_stays_extension_required
    """
    built = _probation_with_remedial_phase_two(world)

    world.file_report(built["phase_two"]["id"], built["second_fto"]["id"],
                      "2027-04-11", f.dimension_ratings(7))

    trainee = world.read_recruit(built["recruit"]["id"])
    assert trainee["pipeline_stage"] == "PROBATION"
    assert trainee["probation_status"] == "EXTENSION_REQUIRED"
    assert_score_equals(trainee["probation_milestone_score"], "3.00",
                        "probation_milestone_score")
    assert trainee["probation_extension_days"] == 60
    assert trainee["probation_scheduled_end"] == "2028-05-30"
    assert trainee["probation_milestone_due_date"] == "2027-09-30"


def _session_pinned_to_a_superseded_plan(world):
    """A scheduled session whose plan has since been revised past its pin."""
    standard = world.create_standard(
        min_total_hours=6.0,
        topic_requirements=[f.topic_requirement(PATROL, 6.0, False)])
    cohort = world.create_cohort(standard["id"])
    instructor = world.create_certified_instructor(topics=[PATROL])
    plan = world.create_approved_lesson_plan(instructor["id"], PATROL,
                                             contact_hours=2.0)
    session = world.schedule_session(cohort["id"], plan["id"], instructor["id"],
                                     room_code="R1",
                                     starts_at="2026-08-10T09:00:00Z",
                                     ends_at="2026-08-10T11:00:00Z",
                                     min_enrollment=1)
    approved = validate_success(world.client.get_lesson_plan(plan["id"],
                                                            director_headers()))
    assert approved["approved_revision_number"] == 1
    revised = validate_success(world.client.create_lesson_plan_revision(
        plan["id"],
        f.lesson_plan_revision_payload(approved["version"], contact_hours=2.5,
                                       revision_notes="added de-escalation block"),
        coordinator_headers()))
    world.set_clock("2026-08-10T12:00:00Z")
    return {"standard": standard, "cohort": cohort, "instructor": instructor,
            "plan": revised, "session": session}


def test_a_session_cannot_be_closed_out_while_its_plan_sits_outside_approved(world):
    """A revision drops the plan back to SUBMITTED and blocks the delivery.

    PRD: "Sessions already scheduled against a plan that has been sent back keep
    their `SCHEDULED` posture, but cannot be delivered while the plan sits
    outside `APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/session_delivery_requires_pinned_plan_revision_still_approved
    """
    built = _session_pinned_to_a_superseded_plan(world)

    assert built["plan"]["status"] == "SUBMITTED"
    assert built["plan"]["revision_number"] == 2
    assert built["plan"]["approved_revision_number"] == 1

    refused = world.client.deliver_course_session(built["session"]["id"],
                                                 coordinator_headers())
    validate_error(refused, ERR_LESSON_PLAN_NOT_APPROVED, 422)

    stored = validate_success(world.client.get_course_session(
        built["session"]["id"], coordinator_headers()))
    assert stored["status"] == "SCHEDULED"
    assert stored["pinned_lesson_plan_revision"] == 1


def test_re_approving_the_plan_does_not_rescue_the_stale_pin(world):
    """The pin of 1 no longer matches an approved revision number of 2.

    PRD: "The referenced lesson plan's `status` is `APPROVED` and the session's
    `pinned_lesson_plan_revision` still equals that plan's
    `approved_revision_number` - otherwise `ERR_LESSON_PLAN_NOT_APPROVED`, 422."

    Design: Difficulty/cross_entity_state_dependency/session_delivery_requires_pinned_plan_revision_still_approved
    """
    built = _session_pinned_to_a_superseded_plan(world)

    reapproved = world.approve_lesson_plan(built["plan"]["id"])
    assert reapproved["status"] == "APPROVED"
    assert reapproved["revision_number"] == 2
    assert reapproved["approved_revision_number"] == 2
    assert_hours_equals(reapproved["contact_hours"], "2.50", "contact_hours")

    refused = world.client.deliver_course_session(built["session"]["id"],
                                                 coordinator_headers())
    validate_error(refused, ERR_LESSON_PLAN_NOT_APPROVED, 422)

    stored = validate_success(world.client.get_course_session(
        built["session"]["id"], coordinator_headers()))
    assert stored["status"] == "SCHEDULED"
    assert stored["pinned_lesson_plan_revision"] == 1


def test_a_session_pinned_at_the_newly_approved_revision_closes_out(world):
    """A session created after the re-approval pins revision 2 and delivers.

    PRD: "`pinned_lesson_plan_revision` captures the plan's
    `approved_revision_number` at this instant, and it is this pin that delivery
    will later insist still matches."

    Design: Difficulty/cross_entity_state_dependency/session_delivery_requires_pinned_plan_revision_still_approved
    """
    built = _session_pinned_to_a_superseded_plan(world)
    world.approve_lesson_plan(built["plan"]["id"])

    replacement = world.schedule_session(
        built["cohort"]["id"], built["plan"]["id"], built["instructor"]["id"],
        room_code="R1", starts_at="2026-08-11T09:00:00Z",
        ends_at="2026-08-11T11:00:00Z", min_enrollment=0)
    assert replacement["pinned_lesson_plan_revision"] == 2

    world.set_clock("2026-08-11T12:00:00Z")
    delivered = world.deliver_session(replacement["id"])
    assert delivered["status"] == "DELIVERED"

    cohort = validate_success(world.client.get_academy_class(
        built["cohort"]["id"], director_headers()))
    assert cohort["status"] == "IN_SESSION"
    assert_hours_equals(cohort["credited_topic_hours_total"], "0.00",
                        "credited_topic_hours_total")


def _rotation_under_a_lapsed_officer(world):
    """A PLANNED rotation whose officer was expired by a clock advance."""
    standard = world.create_standard(
        min_total_hours=2.0,
        topic_requirements=[f.topic_requirement(PATROL, 2.0, False)])
    cohort = world.create_cohort(standard["id"])
    officer = world.create_certified_instructor(
        topics=[PATROL], expires_at="2027-01-01T00:00:00Z", fto_certified=True)
    plan = world.create_approved_lesson_plan(officer["id"], PATROL,
                                             contact_hours=2.0)
    academy = {
        "standard": standard, "cohort": cohort, "instructor": officer,
        "lesson_plan": plan, "topic_code": PATROL,
        "session_starts_at": "2026-08-10T09:00:00Z",
        "session_ends_at": "2026-08-10T11:00:00Z",
        "after_session": "2026-08-10T12:00:00Z",
    }
    recruit = world.recruit_in_field_training(academy)
    rotation = world.plan_rotation(recruit, officer["id"], phase_number=1,
                                  start_date="2027-02-05",
                                  end_date="2027-03-05")
    world.set_clock("2027-02-01T00:00:00Z")
    return {"cohort": cohort, "officer": officer, "plan": plan,
            "recruit": recruit, "rotation": rotation}


def _only_session_of(world, cohort_id):
    sessions, _meta = validate_paginated(world.client.list_course_sessions(
        coordinator_headers(), {"academy_class_id": cohort_id, "limit": 50}))
    assert len(sessions) == 1
    return sessions[0]


def test_the_clock_sweep_lapses_the_credential_and_touches_nothing_else(world):
    """Advancing the clock past the expiry moves only the instructor row.

    PRD: "Advancing the clock performs exactly one sweep and no other work: every
    `Instructor` whose `certification_status` is `CERTIFIED` and whose
    `certification_expires_at` is strictly earlier than the new instant moves to
    `EXPIRED`."

    Design: Difficulty/cross_entity_state_dependency/rotation_activation_blocked_by_clock_driven_fto_certification_expiry
    """
    built = _rotation_under_a_lapsed_officer(world)

    swept = validate_success(world.client.get_instructor(built["officer"]["id"],
                                                        director_headers()))
    assert swept["certification_status"] == "EXPIRED"

    plan = validate_success(world.client.get_lesson_plan(built["plan"]["id"],
                                                        director_headers()))
    assert plan["status"] == "APPROVED"
    assert _only_session_of(world, built["cohort"]["id"])["status"] == "DELIVERED"
    assert world.read_rotation(built["rotation"]["id"])["status"] == "PLANNED"


def test_activation_is_refused_while_the_officers_credential_has_lapsed(world):
    """A rotation planned under a live credential will not activate under a dead one.

    PRD: "The assigned FTO has `certification_status` equal to `CERTIFIED` and
    `fto_certified` true - otherwise `ERR_FTO_NOT_CERTIFIED`, 422."

    Design: Difficulty/cross_entity_state_dependency/rotation_activation_blocked_by_clock_driven_fto_certification_expiry
    """
    built = _rotation_under_a_lapsed_officer(world)

    refused = world.client.activate_rotation(built["rotation"]["id"],
                                            coordinator_headers())
    validate_error(refused, ERR_FTO_NOT_CERTIFIED, 422)

    assert world.read_rotation(built["rotation"]["id"])["status"] == "PLANNED"
    officer = validate_success(world.client.get_instructor(
        built["officer"]["id"], director_headers()))
    assert officer["active_trainee_count"] == 0


def test_renewing_the_credential_reopens_the_activation(world):
    """The EXPIRED to CERTIFIED renewal lets the same rotation go into service.

    PRD: "The rotation moves `PLANNED` -> `ACTIVE` and the officer's
    `active_trainee_count` rises by one. `PLANNED` never counted toward that
    load; activation is the reservation."

    Design: Difficulty/cross_entity_state_dependency/rotation_activation_blocked_by_clock_driven_fto_certification_expiry
    """
    built = _rotation_under_a_lapsed_officer(world)

    renewed = world.certify_instructor(
        built["officer"]["id"],
        certification_expires_at="2028-01-01T00:00:00Z",
        authorized_topic_codes=[PATROL], fto_certified=True)
    assert renewed["certification_status"] == "CERTIFIED"
    assert_instant_equals(renewed["certification_expires_at"],
                          "2028-01-01T00:00:00Z", "certification_expires_at")

    activated = world.activate_rotation(built["rotation"]["id"])
    assert activated["status"] == "ACTIVE"

    officer = validate_success(world.client.get_instructor(
        built["officer"]["id"], director_headers()))
    assert officer["active_trainee_count"] == 1
    assert world.read_recruit(built["recruit"]["id"])["pipeline_stage"] == "FIELD_TRAINING"
