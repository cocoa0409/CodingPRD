"""Which rung answers when one request breaks two rules, and where the limits sit.

The ladder's ordering is observable: satisfy the higher rung and the lower one
starts answering. The comparisons are just as exact - at the limit is not past it.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_INSTRUCTOR_NOT_AUTHORIZED,
    ERR_INSTRUCTOR_SCHEDULE_CONFLICT,
    ERR_RECRUIT_NOT_IN_ACADEMY,
    ERR_SAME_ACTOR_ADJUDICATION,
    ERR_SCREENING_ALREADY_ADJUDICATED,
    ERR_TOPIC_NOT_IN_STANDARD,
)
from test_helpers.assertions import assert_hours_equals, assert_score_equals
from test_helpers.test_users import (
    EXAMINER_USER_ID,
    INVESTIGATOR_ALT_USER_ID,
    INVESTIGATOR_USER_ID,
    coordinator_headers,
    director_headers,
    examiner_headers,
    investigator_headers,
)

PATROL = "PATROL"
FIREARMS = "FIREARMS"


def _one_applicant_and_one_academy_recruit(world):
    """Two recruits of one cohort, only one of whom has reached the academy."""
    standard = world.create_standard(
        min_total_hours=6.0,
        topic_requirements=[f.topic_requirement(PATROL, 6.0, True)])
    cohort = world.create_cohort(standard["id"])
    applicant = world.create_recruit(cohort["id"], full_name="Alba Reyes")
    enrolled = world.recruit_in_academy(cohort["id"], full_name="Boyd Chen")
    return {"standard": standard, "cohort": cohort, "applicant": applicant,
            "enrolled": enrolled}


def test_the_academy_standing_gate_answers_before_the_topic_gate(world):
    """An applicant asking for an off-curriculum exam hears about the academy first.

    PRD: "Checks are evaluated in the fixed ascending order below; the **first**
    check that fails determines the response, and no later check is consulted."

    Design: Difficulty/priority_pair_validation_conflict/exam_state_gate_outranks_topic_referential_gate
    """
    built = _one_applicant_and_one_academy_recruit(world)

    refused = world.client.create_examination(
        f.examination_payload(built["applicant"]["id"], FIREARMS),
        coordinator_headers())
    validate_error(refused, ERR_RECRUIT_NOT_IN_ACADEMY, 409)

    rows, meta = validate_paginated(world.client.list_examinations(
        coordinator_headers(), {"recruit_id": built["applicant"]["id"]}))
    assert meta["total_count"] == 0
    assert rows == []
    assert world.read_recruit(built["applicant"]["id"])["academy_status"] == "NOT_STARTED"


def test_the_topic_gate_answers_once_the_academy_standing_holds(world):
    """The same off-curriculum topic is refused on its own terms for an enrolled recruit.

    PRD: "The `topic_code` exists as a `topic_requirements` entry on the
    certification standard of the relevant cohort - otherwise
    `ERR_TOPIC_NOT_IN_STANDARD`, 422."

    Design: Difficulty/priority_pair_validation_conflict/exam_state_gate_outranks_topic_referential_gate
    """
    built = _one_applicant_and_one_academy_recruit(world)

    refused = world.client.create_examination(
        f.examination_payload(built["enrolled"]["id"], FIREARMS),
        coordinator_headers())
    validate_error(refused, ERR_TOPIC_NOT_IN_STANDARD, 422)

    _rows, meta = validate_paginated(world.client.list_examinations(
        coordinator_headers(), {"recruit_id": built["enrolled"]["id"]}))
    assert meta["total_count"] == 0
    assert world.read_recruit(built["enrolled"]["id"])["academy_status"] == "IN_PROGRESS"


def _two_topics_two_instructors(world):
    """A cohort with two curriculum topics, each taught by a different instructor."""
    standard = world.create_standard(
        min_total_hours=10.0,
        topic_requirements=[f.topic_requirement(PATROL, 6.0, False),
                            f.topic_requirement(FIREARMS, 4.0, True)])
    cohort = world.create_cohort(standard["id"])
    patrol_instructor = world.create_certified_instructor(topics=[PATROL])
    firearms_instructor = world.create_certified_instructor(topics=[FIREARMS])
    patrol_plan = world.create_approved_lesson_plan(patrol_instructor["id"],
                                                    PATROL, contact_hours=2.0)
    firearms_plan = world.create_approved_lesson_plan(firearms_instructor["id"],
                                                      FIREARMS, contact_hours=2.0)
    booked = world.schedule_session(cohort["id"], patrol_plan["id"],
                                    patrol_instructor["id"], room_code="R1",
                                    starts_at="2026-08-10T09:00:00Z",
                                    ends_at="2026-08-10T11:00:00Z",
                                    min_enrollment=1)
    return {"cohort": cohort, "patrol_instructor": patrol_instructor,
            "firearms_instructor": firearms_instructor,
            "patrol_plan": patrol_plan, "firearms_plan": firearms_plan,
            "booked": booked}


def _clashing_session(world, built, lesson_plan_id):
    return world.client.create_course_session(
        f.course_session_payload(built["cohort"]["id"], lesson_plan_id,
                                 built["patrol_instructor"]["id"],
                                 room_code="R1",
                                 starts_at="2026-08-10T09:00:00Z",
                                 ends_at="2026-08-10T11:00:00Z",
                                 min_enrollment=1),
        coordinator_headers())


def test_the_authorization_gate_answers_before_the_schedule_gate(world):
    """An unauthorized topic outranks the instructor's own double booking.

    PRD: "The instructor of record has `certification_status` equal to `CERTIFIED`
    and the relevant `topic_code` present in their `authorized_topic_codes` -
    otherwise `ERR_INSTRUCTOR_NOT_AUTHORIZED`, 422."

    Design: Difficulty/priority_pair_validation_conflict/instructor_authorization_outranks_schedule_conflict
    """
    built = _two_topics_two_instructors(world)

    refused = _clashing_session(world, built, built["firearms_plan"]["id"])
    validate_error(refused, ERR_INSTRUCTOR_NOT_AUTHORIZED, 422)

    _rows, meta = validate_paginated(world.client.list_course_sessions(
        coordinator_headers(), {"academy_class_id": built["cohort"]["id"]}))
    assert meta["total_count"] == 1


def test_the_schedule_gate_answers_once_the_authorization_holds(world):
    """The identical window on an authorized topic is refused as a conflict.

    PRD: "The candidate session's half-open instant interval does not conflict
    with another live session of the same instructor - otherwise
    `ERR_INSTRUCTOR_SCHEDULE_CONFLICT`, 409."

    Design: Difficulty/priority_pair_validation_conflict/instructor_authorization_outranks_schedule_conflict
    """
    built = _two_topics_two_instructors(world)

    refused = _clashing_session(world, built, built["patrol_plan"]["id"])
    validate_error(refused, ERR_INSTRUCTOR_SCHEDULE_CONFLICT, 409)

    _rows, meta = validate_paginated(world.client.list_course_sessions(
        coordinator_headers(), {"academy_class_id": built["cohort"]["id"]}))
    assert meta["total_count"] == 1

    stored = validate_success(world.client.get_course_session(
        built["booked"]["id"], coordinator_headers()))
    assert stored["status"] == "SCHEDULED"
    assert stored["topic_code"] == PATROL


def _one_cleared_and_one_pending_screening(world):
    """One terminal BACKGROUND record and one MEDICAL record awaiting adjudication."""
    standard = world.create_standard(
        min_total_hours=6.0,
        topic_requirements=[f.topic_requirement(PATROL, 6.0, False)])
    cohort = world.create_cohort(standard["id"])
    recruit = world.create_recruit(cohort["id"], full_name="Alba Reyes")
    background = world.order_screening(recruit["id"], "BACKGROUND")
    world.record_findings(background["id"], "BACKGROUND")
    world.adjudicate(background["id"], "BACKGROUND", "CLEAR")
    medical = world.order_screening(recruit["id"], "MEDICAL")
    world.record_findings(medical["id"], "MEDICAL")
    return {"recruit": recruit, "background": background, "medical": medical}


def test_the_terminal_state_gate_answers_before_the_same_actor_guard(world):
    """Re-adjudicating a cleared record hears about the terminal state, not the actor.

    PRD: "Adjudication is legal only from `FINDINGS_RECORDED`; against a record
    already at `CLEARED`, `WAIVED` or `DISQUALIFIED` - all three terminal - both
    findings and adjudication answer `ERR_SCREENING_ALREADY_ADJUDICATED`."

    Design: Difficulty/priority_pair_validation_conflict/screening_terminal_state_outranks_same_actor_guard
    """
    built = _one_cleared_and_one_pending_screening(world)

    refused = world.client.adjudicate_screening(
        built["background"]["id"], f.adjudicate_payload("CLEAR"),
        investigator_headers(INVESTIGATOR_USER_ID))
    validate_error(refused, ERR_SCREENING_ALREADY_ADJUDICATED, 409)

    stored = validate_success(world.client.get_screening_record(
        built["background"]["id"], coordinator_headers()))
    assert stored["status"] == "CLEARED"
    assert stored["adjudicated_by_user_id"] == INVESTIGATOR_ALT_USER_ID


def test_the_same_actor_guard_answers_once_the_state_gate_holds(world):
    """The recorder of findings may not adjudicate the record they wrote.

    PRD: "Segregation of duties: the `X-User-ID` adjudicating a screening differs
    from that screening's `findings_recorded_by_user_id`, and the `X-User-ID`
    approving a lesson plan differs from the authoring instructor's identifier -
    otherwise `ERR_SAME_ACTOR_ADJUDICATION`, 422."

    Design: Difficulty/priority_pair_validation_conflict/screening_terminal_state_outranks_same_actor_guard
    """
    built = _one_cleared_and_one_pending_screening(world)

    refused = world.client.adjudicate_screening(
        built["medical"]["id"], f.adjudicate_payload("CLEAR"),
        examiner_headers(EXAMINER_USER_ID))
    validate_error(refused, ERR_SAME_ACTOR_ADJUDICATION, 422)

    stored = validate_success(world.client.get_screening_record(
        built["medical"]["id"], coordinator_headers()))
    assert stored["status"] == "FINDINGS_RECORDED"
    assert stored["adjudicated_by_user_id"] is None
    assert world.read_recruit(built["recruit"]["id"])["clearance_status"] == "PARTIAL"


def _absence_accrued_to_the_limit(world):
    """A recruit sitting on exactly the four-hour unexcused absence limit."""
    standard = world.create_standard(
        min_total_hours=6.0, max_absence_hours=4.0,
        topic_requirements=[f.topic_requirement(PATROL, 6.0, False)])
    cohort = world.create_cohort(standard["id"])
    instructor = world.create_certified_instructor(topics=[PATROL])
    plan = world.create_approved_lesson_plan(instructor["id"], PATROL,
                                             contact_hours=2.0)
    recruit = world.recruit_in_academy(cohort["id"])

    rows = []
    for day in ("2026-08-10", "2026-08-11"):
        session = world.schedule_session(
            cohort["id"], plan["id"], instructor["id"], room_code="R1",
            starts_at=f"{day}T09:00:00Z", ends_at=f"{day}T11:00:00Z",
            min_enrollment=1)
        rows.append(world.record_attendance(session["id"], recruit["id"],
                                            "ABSENT_UNEXCUSED", 0.0))
        world.set_clock(f"{day}T12:00:00Z")
        world.deliver_session(session["id"])

    half_hour = world.schedule_session(
        cohort["id"], plan["id"], instructor["id"], room_code="R1",
        starts_at="2026-08-12T09:00:00Z", ends_at="2026-08-12T09:30:00Z",
        min_enrollment=1)
    return {"cohort": cohort, "recruit": recruit, "rows": rows,
            "half_hour": half_hour}


def test_absence_hours_landing_exactly_on_the_limit_leave_the_recruit_alone(world):
    """Four accrued hours against a four-hour limit is not a dismissal trigger.

    PRD: "Mandatory dismissal review is triggered when that accrual is **strictly
    greater than** the standard's `max_absence_hours`; landing exactly on the limit
    does not trigger it."

    Design: Difficulty/boundary_precision_check/absence_hours_exactly_at_limit_does_not_trigger_dismissal_review
    """
    built = _absence_accrued_to_the_limit(world)

    at_limit = world.read_recruit(built["recruit"]["id"])
    assert_hours_equals(at_limit["unexcused_absence_hours"], "4.00",
                        "unexcused_absence_hours")
    assert at_limit["academy_status"] == "IN_PROGRESS"

    for row in built["rows"]:
        stored = validate_success(world.client.get_attendance_record(
            row["id"], coordinator_headers()))
        assert_hours_equals(stored["counted_absence_hours"], "2.00",
                            "counted_absence_hours")


def test_half_an_hour_past_the_limit_pends_the_dismissal(world):
    """A four-and-a-half-hour accrual is strictly greater and does trigger review.

    PRD: "a third delivered half-hour session marked the same way reaches four and
    a half hours and moves `academy_status` to `DISMISSAL_PENDING`, carrying its
    own void cascade over the recruit's `PROVISIONAL` attendance rows."

    Design: Difficulty/boundary_precision_check/absence_hours_exactly_at_limit_does_not_trigger_dismissal_review
    """
    built = _absence_accrued_to_the_limit(world)

    third = world.record_attendance(built["half_hour"]["id"],
                                    built["recruit"]["id"],
                                    "ABSENT_UNEXCUSED", 0.0)
    world.set_clock("2026-08-12T12:00:00Z")
    delivered = world.deliver_session(built["half_hour"]["id"])
    assert delivered["status"] == "DELIVERED"
    assert_hours_equals(delivered["scheduled_hours"], "0.50", "scheduled_hours")

    trainee = world.read_recruit(built["recruit"]["id"])
    assert_hours_equals(trainee["unexcused_absence_hours"], "4.50",
                        "unexcused_absence_hours")
    assert trainee["academy_status"] == "DISMISSAL_PENDING"
    assert trainee["pipeline_stage"] == "ACADEMY"
    assert_hours_equals(trainee["credited_hours_total"], "0.00",
                        "credited_hours_total")
    assert_hours_equals(trainee["scheduled_basis_hours_total"], "0.00",
                        "scheduled_basis_hours_total")

    stored = validate_success(world.client.get_attendance_record(
        third["id"], coordinator_headers()))
    assert stored["ledger_status"] == "CREDITED"
    assert_hours_equals(stored["counted_absence_hours"], "0.50",
                        "counted_absence_hours")


def _rotation_scoring_exactly_four(world):
    """A live rotation whose single report puts its competency score on 4.00."""
    curriculum = world.curriculum(topic_code=PATROL, required_hours=2.0,
                                  exam_required=False, min_total_hours=2.0,
                                  session_ends_at="2026-08-03T11:00:00Z",
                                  after_session="2026-08-03T11:00:00Z")
    recruit = world.recruit_in_field_training(curriculum)
    fto = world.create_certified_fto()
    rotation = world.plan_rotation(recruit, fto["id"], phase_number=1,
                                   start_date="2027-03-01",
                                   end_date="2027-03-31")
    world.activate_rotation(rotation["id"])
    world.set_clock("2027-03-13T12:00:00Z")
    first = world.file_report(rotation["id"], fto["id"], "2027-03-10",
                             f.dimension_ratings(4))
    return {"recruit": recruit, "fto": fto, "rotation": rotation,
            "first": first}


def test_a_competency_score_exactly_on_the_threshold_holds_the_rotation_active(world):
    """Five acceptable ratings score 4.00, and 4.00 is not below 4.00.

    PRD: "A rotation at `ACTIVE` whose recomputed score is **strictly less than**
    4.00 moves to `REMEDIAL` - level 2 of the cascade."

    Design: Difficulty/boundary_precision_check/terminal_weighted_exactly_at_fto_threshold_does_not_flip_remedial
    """
    built = _rotation_scoring_exactly_four(world)

    assert_score_equals(built["first"]["dor_mean"], "4.00", "dor_mean")
    at_threshold = world.read_rotation(built["rotation"]["id"])
    assert_score_equals(at_threshold["competency_score"], "4.00",
                        "competency_score")
    assert at_threshold["status"] == "ACTIVE"
    assert world.read_recruit(built["recruit"]["id"])["probation_status"] == "NOT_APPLICABLE"


def test_one_dimension_slipping_takes_the_score_below_the_threshold(world):
    """A second report of 19 rating points pulls the pair to 3.90 and flips REMEDIAL.

    PRD: "Each report stores its own `dor_mean` - the arithmetic mean of its five
    ratings, rounded half up to 2 decimal places - and starts with `voided` false."

    Design: Difficulty/boundary_precision_check/terminal_weighted_exactly_at_fto_threshold_does_not_flip_remedial
    """
    built = _rotation_scoring_exactly_four(world)

    second = world.file_report(built["rotation"]["id"], built["fto"]["id"],
                              "2027-03-11", f.dimension_ratings(4, demeanor=3))
    assert_score_equals(second["dor_mean"], "3.80", "dor_mean")

    flipped = world.read_rotation(built["rotation"]["id"])
    assert flipped["dor_count"] == 2
    assert_score_equals(flipped["competency_score"], "3.90", "competency_score")
    assert_score_equals(flipped["rolling_mean_score"], "3.90",
                        "rolling_mean_score")
    assert flipped["status"] == "REMEDIAL"
    assert flipped["remedial_flag_count"] == 0

    trainee = world.read_recruit(built["recruit"]["id"])
    assert trainee["probation_status"] == "NOT_APPLICABLE"
    assert trainee["probation_extension_days"] == 0

    officer = validate_success(world.client.get_instructor(built["fto"]["id"],
                                                         director_headers()))
    assert officer["active_trainee_count"] == 1


def _three_quarter_hour_partials(world):
    """Three two-hour sessions each attended PARTIAL for half an hour."""
    standard = world.create_standard(
        min_total_hours=6.0,
        topic_requirements=[f.topic_requirement(PATROL, 6.0, False)])
    cohort = world.create_cohort(standard["id"])
    instructor = world.create_certified_instructor(topics=[PATROL])
    plan = world.create_approved_lesson_plan(instructor["id"], PATROL,
                                             contact_hours=2.0)
    recruit = world.recruit_in_academy(cohort["id"])

    rows = []
    for day in ("2026-08-10", "2026-08-11", "2026-08-12"):
        session = world.schedule_session(
            cohort["id"], plan["id"], instructor["id"], room_code="R1",
            starts_at=f"{day}T09:00:00Z", ends_at=f"{day}T11:00:00Z",
            min_enrollment=1)
        rows.append(world.record_attendance(session["id"], recruit["id"],
                                            "PARTIAL", 0.5))
        world.set_clock(f"{day}T12:00:00Z")
        world.deliver_session(session["id"])
    return {"cohort": cohort, "recruit": recruit, "rows": rows}


def test_each_row_is_rounded_at_the_row_before_anything_is_summed(world):
    """Half an hour at the partial factor is 0.375, stored as 0.38 per row.

    PRD: "That row's credited hours are its `present_hours` multiplied by its
    attendance factor, **rounded half up to 2 decimal places at the row**."

    Design: Difficulty/boundary_precision_check/per_session_rounding_before_summation_pins_1_14_not_1_13
    """
    built = _three_quarter_hour_partials(world)

    for row in built["rows"]:
        stored = validate_success(world.client.get_attendance_record(
            row["id"], coordinator_headers()))
        assert_hours_equals(stored["credited_hours"], "0.38", "credited_hours")

    trainee = world.read_recruit(built["recruit"]["id"])
    assert_hours_equals(trainee["per_topic_credited_hours"][PATROL], "1.14",
                        f"per_topic_credited_hours[{PATROL}]")
    assert_hours_equals(trainee["credited_hours_total"], "1.14",
                        "credited_hours_total")
    assert_hours_equals(trainee["scheduled_basis_hours_total"], "6.00",
                        "scheduled_basis_hours_total")


def test_the_progress_report_and_the_class_ledger_read_the_same_1_14(world):
    """Every reader of those rows reports 1.14, never the 1.13 of summing first.

    PRD: "A recruit's `per_topic_credited_hours` for a topic is then the sum of
    those already-rounded per-row values across every attendance row of that
    recruit whose `ledger_status` is `CREDITED`, whose session's `status` is
    `DELIVERED`, and whose session's `topic_code` is that topic."

    Design: Difficulty/boundary_precision_check/per_session_rounding_before_summation_pins_1_14_not_1_13
    """
    built = _three_quarter_hour_partials(world)

    progress = validate_success(world.client.get_certification_progress(
        built["recruit"]["id"], coordinator_headers()))
    assert_hours_equals(progress["total_hours"], "1.14", "total_hours")
    assert_hours_equals(progress["per_topic_hours"][PATROL], "1.14",
                        f"per_topic_hours[{PATROL}]")

    cohort = validate_success(world.client.get_academy_class(
        built["cohort"]["id"], director_headers()))
    assert_hours_equals(cohort["credited_topic_hours_total"], "1.14",
                        "credited_topic_hours_total")

    trainee = world.read_recruit(built["recruit"]["id"])
    assert trainee["academy_status"] == "IN_PROGRESS"
    assert_hours_equals(trainee["unexcused_absence_hours"], "0.00",
                        "unexcused_absence_hours")
