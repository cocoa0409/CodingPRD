"""What each rule refuses, and which refusal wins when several apply at once.

Every rejection here is paired with the repaired call that succeeds, and with a
listing that proves the refused call wrote nothing.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_ACADEMY_CLASS_NOT_FOUND,
    ERR_ATTENDANCE_ALREADY_RECORDED,
    ERR_CLOCK_NOT_MONOTONIC,
    ERR_COURSE_SESSION_NOT_FOUND,
    ERR_DISQUALIFIER_UNWAIVED,
    ERR_DOR_AUTHOR_NOT_ASSIGNED_FTO,
    ERR_DOR_OUTSIDE_ROTATION_WINDOW,
    ERR_DUPLICATE_DOR,
    ERR_DUPLICATE_IDENTIFIER,
    ERR_DUPLICATE_SCREENING_TYPE,
    ERR_EXAM_NOT_REQUIRED_FOR_TOPIC,
    ERR_INSTRUCTOR_CERT_EXPIRED,
    ERR_INSTRUCTOR_NOT_AUTHORIZED,
    ERR_INVALID_INTERVAL,
    ERR_INVALID_PAGINATION,
    ERR_INVALID_REQUEST,
    ERR_PRESENT_HOURS_INCONSISTENT,
    ERR_RECRUIT_NOT_FOUND,
    ERR_REMEDIATION_ATTEMPTS_EXHAUSTED,
    ERR_ROLE_NOT_PERMITTED,
    ERR_STALE_RECRUIT_VERSION,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import (
    assert_hours_equals,
    assert_instant_equals,
    assert_ladder_precedence,
    assert_score_equals,
)
from test_helpers.test_users import (
    coordinator_alt_headers,
    coordinator_headers,
    custodian_headers,
    director_headers,
    headers_empty_role,
    headers_unknown_role,
    investigator_alt_headers,
    make_fto_headers,
    make_recruit_headers,
)

PATROL = "PATROL"
MISSING_ID = "00000000-0000-4000-8000-000000000000"


def _patrol_curriculum(world, exam_required=False, **standard_kwargs):
    return world.curriculum(topic_code=PATROL, required_hours=2.0,
                            exam_required=exam_required, min_total_hours=2.0,
                            session_starts_at="2026-08-10T09:00:00Z",
                            session_ends_at="2026-08-10T11:00:00Z",
                            after_session="2026-08-10T12:00:00Z",
                            **standard_kwargs)


def _block(world, built, day="2026-08-10", starts="09:00:00", ends="11:00:00",
           min_enrollment=1):
    return world.schedule_session(built["cohort"]["id"],
                                  built["lesson_plan"]["id"],
                                  built["instructor"]["id"], room_code="R1",
                                  starts_at=f"{day}T{starts}Z",
                                  ends_at=f"{day}T{ends}Z",
                                  min_enrollment=min_enrollment)


def test_a_repeated_identifier_is_refused_on_each_of_the_four_unique_columns(world):
    """A standard code, class code, applicant number and badge number are each unique.

    PRD: "Uniqueness of `code` on a certification standard, `class_code` on a
    cohort, `applicant_number` on a recruit and `badge_number` on an instructor -
    otherwise `ERR_DUPLICATE_IDENTIFIER`, 409."

    Design: Corner/validations/violation_to_error_duplicate_identifier_fires_on_all_four_unique_columns
    """
    standard = world.create_standard(
        code="TCOLE-FT", min_total_hours=2.0,
        topic_requirements=[f.topic_requirement(PATROL, 2.0, False)])
    cohort = world.create_cohort(standard["id"], class_code="CLS-FT")
    world.create_recruit(cohort["id"], applicant_number="A-001",
                         full_name="Rae Ortiz")
    world.create_instructor(badge_number="B-100", full_name="Ivy Nash")

    # Every other field of each retry differs; only the identifier repeats.
    repeat_standard = world.client.create_certification_standard(
        f.certification_standard_payload(
            code="TCOLE-FT", state_code="NM", min_total_hours=99.0,
            min_passing_score=80.0, max_remediation_attempts=3,
            max_absence_hours=8.0,
            topic_requirements=[f.topic_requirement("ETHICS", 9.0, True)]),
        director_headers())
    validate_error(repeat_standard, ERR_DUPLICATE_IDENTIFIER, 409)

    repeat_cohort = world.client.create_academy_class(
        f.academy_class_payload(standard["id"], class_code="CLS-FT",
                                start_date="2027-01-04", planned_seats=12),
        director_headers())
    validate_error(repeat_cohort, ERR_DUPLICATE_IDENTIFIER, 409)

    repeat_recruit = world.client.create_recruit(
        f.recruit_payload(cohort["id"], applicant_number="A-001",
                          full_name="Someone Else", date_of_birth="1990-06-06",
                          age_bracket="AGE_30_39"),
        coordinator_headers())
    validate_error(repeat_recruit, ERR_DUPLICATE_IDENTIFIER, 409)

    repeat_instructor = world.client.create_instructor(
        f.instructor_payload(badge_number="B-100", full_name="Other Person"),
        director_headers())
    validate_error(repeat_instructor, ERR_DUPLICATE_IDENTIFIER, 409)

    _standards, standards_meta = validate_paginated(
        world.client.list_certification_standards(director_headers()))
    assert standards_meta["total_count"] == 1
    _cohorts, cohorts_meta = validate_paginated(
        world.client.list_academy_classes(director_headers()))
    assert cohorts_meta["total_count"] == 1

    recruits, recruits_meta = validate_paginated(
        world.client.list_recruits(coordinator_headers()))
    assert recruits_meta["total_count"] == 1
    assert recruits[0]["full_name"] == "Rae Ortiz"

    instructors, instructors_meta = validate_paginated(
        world.client.list_instructors(director_headers()))
    assert instructors_meta["total_count"] == 1
    assert instructors[0]["full_name"] == "Ivy Nash"


def test_a_zero_length_or_reversed_window_is_refused_but_one_day_is_not(world):
    """Sessions need a strictly later end; a rotation may open and close on one day.

    PRD: "A course session's `ends_at` is strictly after its `starts_at`, and a
    rotation's `end_date` is not earlier than its `start_date` - otherwise
    `ERR_INVALID_INTERVAL`, 400."

    Design: Corner/validations/violation_to_error_invalid_interval_guards_both_session_and_rotation_windows
    """
    built = _patrol_curriculum(world)
    recruit = world.recruit_in_field_training(built)
    fto = world.create_certified_fto()

    def session(starts, ends):
        return world.client.create_course_session(
            f.course_session_payload(built["cohort"]["id"],
                                     built["lesson_plan"]["id"],
                                     built["instructor"]["id"], room_code="R1",
                                     starts_at=starts, ends_at=ends,
                                     min_enrollment=1),
            coordinator_headers())

    validate_error(session("2026-08-20T09:00:00Z", "2026-08-20T09:00:00Z"),
                   ERR_INVALID_INTERVAL, 400)
    validate_error(session("2026-08-20T11:00:00Z", "2026-08-20T09:00:00Z"),
                   ERR_INVALID_INTERVAL, 400)

    reversed_rotation = world.client.create_field_training_rotation(
        f.rotation_payload(recruit["id"], fto["id"], recruit["version"],
                           phase_number=1, start_date="2026-09-02",
                           end_date="2026-08-20"),
        coordinator_headers())
    validate_error(reversed_rotation, ERR_INVALID_INTERVAL, 400)

    # The rotation rule is "not earlier", so a single-day phase is legal.
    single_day = world.plan_rotation(recruit, fto["id"], phase_number=1,
                                    start_date="2026-08-20",
                                    end_date="2026-08-20")
    assert single_day["status"] == "PLANNED"

    rotations, meta = validate_paginated(
        world.client.list_field_training_rotations(coordinator_headers()))
    assert meta["total_count"] == 1
    assert rotations[0]["id"] == single_day["id"]


def test_pagination_arguments_out_of_band_are_refused_on_every_listing(world):
    """Zero, 101 and a negative offset are rejected rather than clamped.

    PRD: "A `limit` that is not an integer in the range 1 through 100 inclusive,
    or an `offset` that is not an integer of at least 0, is rejected with
    `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/validations/violation_to_error_invalid_pagination_rejects_limit_and_offset_out_of_band
    """
    standard = world.create_standard(
        min_total_hours=2.0,
        topic_requirements=[f.topic_requirement(PATROL, 2.0, False)])
    cohort = world.create_cohort(standard["id"])
    world.create_recruit(cohort["id"])

    validate_error(world.client.list_recruits(coordinator_headers(), {"limit": 0}),
                   ERR_INVALID_PAGINATION, 400)
    validate_error(world.client.list_recruits(coordinator_headers(), {"limit": 101}),
                   ERR_INVALID_PAGINATION, 400)
    validate_error(world.client.list_recruits(coordinator_headers(), {"offset": -1}),
                   ERR_INVALID_PAGINATION, 400)
    # The bound is a global pagination rule, not a per-endpoint one.
    validate_error(
        world.client.list_course_sessions(coordinator_headers(), {"limit": 101}),
        ERR_INVALID_PAGINATION, 400)

    rows, meta = validate_paginated(world.client.list_recruits(
        coordinator_headers(), {"limit": 1, "offset": 0}))
    assert len(rows) == 1
    assert meta["total_count"] == 1
    assert meta["has_more"] is False

    _rows, upper = validate_paginated(world.client.list_recruits(
        coordinator_headers(), {"limit": 100}))
    assert upper["limit"] == 100


def test_the_clock_refuses_to_run_backwards_but_accepts_standing_still(world):
    """An earlier instant is refused; the very same instant is accepted.

    PRD: "The clock is monotonic: a target instant earlier than the clock's
    current value is rejected with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 400); an
    instant equal to the current value is accepted."

    Design: Corner/validations/violation_to_error_clock_must_not_run_backwards_but_may_stand_still
    """
    world.set_clock("2026-08-10T12:00:00Z")

    validate_error(world.client.set_clock("2026-08-05T00:00:00Z",
                                         coordinator_headers()),
                   ERR_CLOCK_NOT_MONOTONIC, 400)
    validate_error(world.client.set_clock("2026-08-10T11:59:59Z",
                                         coordinator_headers()),
                   ERR_CLOCK_NOT_MONOTONIC, 400)

    standing_still = validate_success(
        world.client.set_clock("2026-08-10T12:00:00Z", coordinator_headers()))
    # The accepted equal-instant call is also the proof that neither rejected
    # call moved the clock.
    assert_instant_equals(standing_still["current_utc"], "2026-08-10T12:00:00Z",
                          "current_utc")

    forward = validate_success(
        world.client.set_clock("2026-08-10T12:00:01Z", coordinator_headers()))
    assert_instant_equals(forward["current_utc"], "2026-08-10T12:00:01Z",
                          "current_utc")


def _active_rotation_with_two_officers(world):
    """An ACTIVE phase-one rotation under one officer, with a second one idle."""
    built = _patrol_curriculum(world)
    recruit = world.recruit_in_field_training(built)
    assigned = world.create_certified_fto()
    bystander = world.create_certified_fto()
    rotation = world.plan_rotation(recruit, assigned["id"], phase_number=1,
                                  start_date="2026-08-20",
                                  end_date="2026-09-02")
    world.set_clock("2026-08-20T08:00:00Z")
    rotation = world.activate_rotation(rotation["id"])
    world.set_clock("2026-08-21T18:00:00Z")
    return built, recruit, assigned, bystander, rotation


def test_a_report_outside_the_window_by_a_stranger_or_twice_a_day_is_refused(world):
    """The window is closed, the author is pinned, and one shift takes one report.

    PRD: "At most one non-voided report may exist per rotation and `observed_on`
    date, or the answer is `ERR_DUPLICATE_DOR`."

    Design: Corner/validations/violation_to_error_observation_report_window_author_and_duplicate_guards
    """
    _built, _recruit, assigned, bystander, rotation = (
        _active_rotation_with_two_officers(world))

    before_the_window = world.client.create_observation_report(
        rotation["id"],
        f.observation_report_payload(assigned["id"], "2026-08-19",
                                     f.dimension_ratings(5),
                                     narrative="day before the window opens"),
        make_fto_headers(assigned["id"]))
    validate_error(before_the_window, ERR_DOR_OUTSIDE_ROTATION_WINDOW, 422)

    # The acting officer IS the assigned FTO, so the resource-owner rung passes
    # and only the body's author field is wrong.
    wrong_author = world.client.create_observation_report(
        rotation["id"],
        f.observation_report_payload(bystander["id"], "2026-08-21",
                                     f.dimension_ratings(5),
                                     narrative="authored by the wrong officer"),
        make_fto_headers(assigned["id"]))
    validate_error(wrong_author, ERR_DOR_AUTHOR_NOT_ASSIGNED_FTO, 422)

    filed = world.file_report(rotation["id"], assigned["id"], "2026-08-21",
                              f.dimension_ratings(5))
    assert_score_equals(filed["dor_mean"], "5.00", "dor_mean")
    assert filed["voided"] is False

    same_shift_again = world.client.create_observation_report(
        rotation["id"],
        f.observation_report_payload(assigned["id"], "2026-08-21",
                                     f.dimension_ratings(3),
                                     narrative="second report for one shift"),
        make_fto_headers(assigned["id"]))
    validate_error(same_shift_again, ERR_DUPLICATE_DOR, 409)

    # A dor_count of 2, or a score of 4.00, would mean the duplicate was stored.
    read = world.read_rotation(rotation["id"])
    assert read["dor_count"] == 1
    assert_score_equals(read["competency_score"], "5.00", "competency_score")
    assert_score_equals(read["rolling_mean_score"], "5.00", "rolling_mean_score")
    assert read["status"] == "ACTIVE"


def test_a_second_attendance_row_or_a_second_screening_of_a_type_is_refused(world):
    """One row per session and recruit, and one screening row per type ever.

    PRD: "At most one attendance record exists per course session and recruit,
    whatever its `ledger_status` - otherwise `ERR_ATTENDANCE_ALREADY_RECORDED`,
    409."

    Design: Corner/validations/violation_to_error_child_row_uniqueness_on_attendance_and_screening_type
    """
    built = _patrol_curriculum(world)
    cleared = world.recruit_in_academy(built["cohort"]["id"],
                                      applicant_number="A-001")
    ordered_only = world.create_recruit(built["cohort"]["id"],
                                        applicant_number="A-002")
    world.order_screening(ordered_only["id"], "MEDICAL")

    session = _block(world, built)
    world.record_attendance(session["id"], cleared["id"], "PRESENT", 2.0)

    # A different status and different hours do not make it a different row.
    second_row = world.client.record_attendance(
        session["id"], f.attendance_payload(cleared["id"], "ABSENT_EXCUSED", 0.0),
        coordinator_headers())
    validate_error(second_row, ERR_ATTENDANCE_ALREADY_RECORDED, 409)

    # A second row of a type is never legitimate: not after the first cleared,
    # and not while the first is still merely ordered.
    after_cleared = world.client.order_screening(
        cleared["id"], f.screening_payload("MEDICAL"), coordinator_headers())
    validate_error(after_cleared, ERR_DUPLICATE_SCREENING_TYPE, 409)
    while_ordered = world.client.order_screening(
        ordered_only["id"], f.screening_payload("MEDICAL"), coordinator_headers())
    validate_error(while_ordered, ERR_DUPLICATE_SCREENING_TYPE, 409)

    rows, rows_meta = validate_paginated(world.client.list_attendance_records(
        coordinator_headers(), {"course_session_id": session["id"]}))
    assert rows_meta["total_count"] == 1
    assert rows[0]["status"] == "PRESENT"
    assert_hours_equals(rows[0]["present_hours"], "2.00", "present_hours")

    screenings, screenings_meta = validate_paginated(
        world.client.list_screening_records(custodian_headers(),
                                           {"recruit_id": cleared["id"]}))
    assert screenings_meta["total_count"] == 4
    assert sorted(row["screening_type"] for row in screenings) == [
        "BACKGROUND", "MEDICAL", "PHYSICAL_FITNESS", "PSYCHOLOGICAL"]
    assert [row["attempt_number"] for row in screenings] == [1, 1, 1, 1]


def test_present_hours_that_disagree_with_the_declared_status_are_refused(world):
    """Both partial bounds are exclusive, presence is exact and absence is zero.

    PRD: "`PRESENT` requires `present_hours` to equal the session's
    `scheduled_hours`; `PARTIAL` requires `present_hours` to be strictly greater
    than zero and strictly less than `scheduled_hours`; and both absence values
    require `present_hours` to be exactly zero."

    Design: Corner/validations/violation_to_error_present_hours_must_agree_with_the_declared_attendance_status
    """
    built = _patrol_curriculum(world)
    recruit = world.recruit_in_academy(built["cohort"]["id"])
    session = _block(world, built)

    def attempt(status, present_hours):
        return world.client.record_attendance(
            session["id"], f.attendance_payload(recruit["id"], status,
                                                present_hours),
            coordinator_headers())

    validate_error(attempt("PRESENT", 1.5), ERR_PRESENT_HOURS_INCONSISTENT, 422)
    validate_error(attempt("ABSENT_EXCUSED", 1.0),
                   ERR_PRESENT_HOURS_INCONSISTENT, 422)
    validate_error(attempt("PARTIAL", 2.0), ERR_PRESENT_HOURS_INCONSISTENT, 422)
    validate_error(attempt("PARTIAL", 0.0), ERR_PRESENT_HOURS_INCONSISTENT, 422)

    accepted = validate_success(attempt("PARTIAL", 1.5), 201)
    assert accepted["ledger_status"] == "PROVISIONAL"
    assert_hours_equals(accepted["present_hours"], "1.50", "present_hours")

    # None of the four rejects wrote a row, or the fifth call would have been
    # refused as a duplicate instead.
    _rows, meta = validate_paginated(world.client.list_attendance_records(
        coordinator_headers(), {"course_session_id": session["id"]}))
    assert meta["total_count"] == 1


def test_an_examination_is_refused_for_a_topic_that_declares_no_exam(world):
    """PATROL is in the standard but requires no exam, so no row may be opened.

    PRD: "That `topic_requirements` entry has `exam_required` true - otherwise
    `ERR_EXAM_NOT_REQUIRED_FOR_TOPIC`, 422."

    Design: Corner/validations/violation_to_error_examination_requires_the_topic_to_declare_an_exam
    """
    built = _patrol_curriculum(world, exam_required=False)
    recruit = world.recruit_in_academy(built["cohort"]["id"])

    refused = world.client.create_examination(
        f.examination_payload(recruit["id"], PATROL), coordinator_headers())
    error = validate_error(refused, ERR_EXAM_NOT_REQUIRED_FOR_TOPIC, 422)
    # PATROL IS a topic_requirements entry, so this is not a topic fault.
    assert error["error_id"] == ERR_EXAM_NOT_REQUIRED_FOR_TOPIC

    _rows, meta = validate_paginated(world.client.list_examinations(
        coordinator_headers(), {"recruit_id": recruit["id"]}))
    assert meta["total_count"] == 0

    progress = validate_success(world.client.get_certification_progress(
        recruit["id"], coordinator_headers()))
    # The exam map carries one entry per exam-required topic, and there are none.
    assert progress["exam_status"] == {}
    assert_hours_equals(progress["unmet_topic_hours"][PATROL], "2.00",
                        "unmet_topic_hours")
    assert progress["eligible_for_certification"] is False


def test_a_disqualifier_blocks_a_clearance_and_a_waiver_needs_its_reasons(world):
    """An adverse finding cannot be cleared, and a waiver without cause is not one.

    PRD: "It requires a non-empty `waiver_justification`, which is stored on the
    record, and it is permitted only when `screening_type` is `BACKGROUND`,
    `MEDICAL` or `PSYCHOLOGICAL`: physical fitness shortfalls are never waivable."

    Design: Corner/validations/violation_to_error_disqualifiers_block_clear_and_are_never_waivable_for_fitness
    """
    built = _patrol_curriculum(world, fitness_event_floor_points=10,
                               fitness_pass_score=60)
    recruit = world.create_recruit(built["cohort"]["id"])
    background = world.screening_at_findings_recorded(
        recruit["id"], "BACKGROUND", disqualifier_codes=["FELONY_CONVICTION"])
    fitness = world.screening_at_findings_recorded(
        recruit["id"], "PHYSICAL_FITNESS", disqualifier_codes=["PRIOR_INJURY"],
        raw_metrics=f.FITNESS_PASSING_METRICS)

    clear_it = world.client.adjudicate_screening(
        background["id"], f.adjudicate_payload("CLEAR"),
        investigator_alt_headers())
    validate_error(clear_it, ERR_DISQUALIFIER_UNWAIVED, 422)

    waive_without_cause = world.client.adjudicate_screening(
        background["id"], f.adjudicate_payload("WAIVE"),
        investigator_alt_headers())
    validate_error(waive_without_cause, ERR_DISQUALIFIER_UNWAIVED, 422)

    # A fitness waiver is refused whoever asks: the subject-scoped authority and
    # the waiver-role narrowing both bear on it, so only the refusal itself is
    # pinned here.
    waive_the_fitness = world.client.adjudicate_screening(
        fitness["id"],
        f.adjudicate_payload("WAIVE", "chief granted an exception"),
        coordinator_alt_headers())
    assert waive_the_fitness.status_code >= 400

    waived = validate_success(world.client.adjudicate_screening(
        background["id"],
        f.adjudicate_payload("WAIVE", "conviction expunged, chief approved"),
        investigator_alt_headers()))
    assert waived["status"] == "WAIVED"
    assert waived["waiver_justification"] == "conviction expunged, chief approved"

    untouched = validate_success(world.client.get_screening_record(
        fitness["id"], custodian_headers()))
    assert untouched["status"] == "FINDINGS_RECORDED"
    assert untouched["composite_score"] == 77

    # One waived leg of four is not a full clearance.
    assert world.read_recruit(recruit["id"])["clearance_status"] == "PARTIAL"


def test_a_credential_that_lapses_on_the_hour_still_blocks_the_next_session(world):
    """At the expiry instant the credential reads CERTIFIED yet schedules nothing.

    PRD: "The session instructor's `certification_expires_at` is strictly after
    the current logical clock - otherwise `ERR_INSTRUCTOR_CERT_EXPIRED`, 422."

    Design: Corner/validations/violation_to_error_instructor_certification_expiring_exactly_now_blocks_scheduling
    """
    standard = world.create_standard(
        min_total_hours=2.0,
        topic_requirements=[f.topic_requirement(PATROL, 2.0, False)])
    cohort = world.create_cohort(standard["id"])
    instructor = world.create_certified_instructor(
        topics=[PATROL], expires_at="2026-09-01T00:00:00Z")
    plan = world.create_approved_lesson_plan(instructor["id"], PATROL)
    world.set_clock("2026-09-01T00:00:00Z")

    def read_instructor():
        return validate_success(world.client.get_instructor(
            instructor["id"], director_headers()))

    def schedule():
        return world.client.create_course_session(
            f.course_session_payload(cohort["id"], plan["id"], instructor["id"],
                                     room_code="R1",
                                     starts_at="2026-09-02T09:00:00Z",
                                     ends_at="2026-09-02T11:00:00Z",
                                     min_enrollment=1),
            coordinator_headers())

    # The sweep expires only what lapsed strictly before the new instant.
    assert read_instructor()["certification_status"] == "CERTIFIED"
    validate_error(schedule(), ERR_INSTRUCTOR_CERT_EXPIRED, 422)

    world.set_clock("2026-09-01T00:00:01Z")
    assert read_instructor()["certification_status"] == "EXPIRED"

    now_unauthorized = validate_error(schedule(), ERR_INSTRUCTOR_NOT_AUTHORIZED,
                                     422)
    assert_ladder_precedence(now_unauthorized["error_id"],
                             ERR_INSTRUCTOR_NOT_AUTHORIZED,
                             ERR_INSTRUCTOR_CERT_EXPIRED)

    _rows, meta = validate_paginated(
        world.client.list_course_sessions(coordinator_headers()))
    assert meta["total_count"] == 0


def test_a_remediation_budget_spent_on_one_topic_blocks_a_first_on_another(world):
    """With one attempt allowed, PATROL's remediation closes ETHICS out.

    PRD: "Because `remediation_attempts_used` is the maximum over all of that
    recruit's examinations of `attempt_number` minus one, a budget spent on one
    topic blocks a *first* remediation on another."

    Design: Corner/validations/violation_to_error_remediation_budget_is_shared_across_topics_per_recruit
    """
    standard = world.create_standard(
        min_total_hours=4.0, max_remediation_attempts=1,
        topic_requirements=[f.topic_requirement(PATROL, 2.0, True),
                            f.topic_requirement(f.TOPIC_ETHICS, 2.0, True)])
    cohort = world.create_cohort(standard["id"])
    recruit = world.recruit_in_academy(cohort["id"])

    patrol_exam = world.failed_examination(recruit["id"], PATROL, 50.0)
    world.assign_remediation(patrol_exam["id"], 6.0)
    ethics_exam = world.failed_examination(recruit["id"], f.TOPIC_ETHICS, 50.0)
    before = world.read_recruit(recruit["id"])

    refused = world.client.assign_remediation(
        ethics_exam["id"], f.assign_remediation_payload(6.0),
        coordinator_headers())
    validate_error(refused, ERR_REMEDIATION_ATTEMPTS_EXHAUSTED, 409)

    held = validate_success(world.client.get_examination(ethics_exam["id"],
                                                        coordinator_headers()))
    assert held["status"] == "FAILED"
    assert held["attempt_number"] == 1
    assert_hours_equals(held["remediation_hours"], "0.00", "remediation_hours")

    after = world.read_recruit(recruit["id"])
    assert after["remediation_attempts_used"] == 1
    assert after["academy_status"] == "REMEDIATION"
    assert after["version"] == before["version"]

    spent = validate_success(world.client.get_examination(patrol_exam["id"],
                                                         coordinator_headers()))
    assert spent["status"] == "REMEDIATION_ASSIGNED"
    assert_hours_equals(spent["remediation_hours"], "6.00", "remediation_hours")


def test_the_role_gate_answers_before_the_path_identifier_is_resolved(world):
    """Two identical calls to a missing cohort differ only in who is asking.

    PRD: "Priority 3 - `ERR_ROLE_NOT_PERMITTED`, 403, when the role is declared
    but not listed for the endpoint. Priority 10 - path-identifier existence."

    Design: Corner/validations/priority_ordering_role_gate_outranks_path_id_existence
    """
    standard = world.create_standard(
        min_total_hours=2.0,
        topic_requirements=[f.topic_requirement(PATROL, 2.0, False)])
    world.create_cohort(standard["id"])

    # The 403 leaks nothing about whether the cohort exists.
    forbidden = validate_error(
        world.client.certify_graduates(MISSING_ID, coordinator_headers()),
        ERR_ROLE_NOT_PERMITTED, 403)
    missing = validate_error(
        world.client.certify_graduates(MISSING_ID, director_headers()),
        ERR_ACADEMY_CLASS_NOT_FOUND, 404)

    assert_ladder_precedence(forbidden["error_id"], ERR_ROLE_NOT_PERMITTED,
                             ERR_ACADEMY_CLASS_NOT_FOUND)
    assert missing["error_id"] == ERR_ACADEMY_CLASS_NOT_FOUND


def test_the_authentication_ladder_answers_before_the_role_and_the_pagination(world):
    """One malformed listing answered four ways as only the headers change.

    PRD: "Priority 1 - `ERR_UNAUTHENTICATED`, 401, when either authentication
    header is missing or blank. Priority 2 - `ERR_UNAUTHENTICATED`, 401, when
    `X-User-Role` is not one of the eight declared roles."

    Design: Corner/validations/priority_ordering_missing_auth_headers_outrank_role_and_pagination_checks
    """
    standard = world.create_standard(
        min_total_hours=2.0,
        topic_requirements=[f.topic_requirement(PATROL, 2.0, False)])
    cohort = world.create_cohort(standard["id"])
    recruit = world.create_recruit(cohort["id"])

    out_of_band = {"limit": 0}

    blank = validate_error(
        world.client.list_recruits(headers_empty_role(""), out_of_band),
        ERR_UNAUTHENTICATED, 401)
    undeclared = validate_error(
        world.client.list_recruits(headers_unknown_role(), out_of_band),
        ERR_UNAUTHENTICATED, 401)
    # Recruit IS a declared role, but it is not listed for this endpoint.
    not_listed = validate_error(
        world.client.list_recruits(make_recruit_headers(recruit["id"]),
                                   out_of_band),
        ERR_ROLE_NOT_PERMITTED, 403)
    # Only once the caller is admitted does the pagination fault surface.
    validate_error(world.client.list_recruits(coordinator_headers(),
                                              out_of_band),
                   ERR_INVALID_PAGINATION, 400)

    assert_ladder_precedence(blank["error_id"], ERR_UNAUTHENTICATED,
                             ERR_ROLE_NOT_PERMITTED)
    assert_ladder_precedence(undeclared["error_id"], ERR_UNAUTHENTICATED,
                             ERR_INVALID_PAGINATION)
    assert_ladder_precedence(not_listed["error_id"], ERR_ROLE_NOT_PERMITTED,
                             ERR_INVALID_PAGINATION)


def test_path_identifiers_resolve_before_body_keys_and_both_before_the_shape(world):
    """Three defects at once are repaired one at a time, each answer naming one id.

    PRD: "Priority 12 - referenced-entity existence for body foreign keys, each
    with its own `ERR_*_NOT_FOUND` and 404."

    Design: Corner/validations/priority_ordering_path_ids_resolve_before_body_fks_and_before_shape
    """
    built = _patrol_curriculum(world)
    recruit = world.recruit_in_academy(built["cohort"]["id"])
    session = _block(world, built)
    shapeless = {"recruit_id": MISSING_ID, "status": "PRESENT"}

    bad_path = validate_error(
        world.client.record_attendance(MISSING_ID, shapeless,
                                       coordinator_headers()),
        ERR_COURSE_SESSION_NOT_FOUND, 404)
    bad_body_fk = validate_error(
        world.client.record_attendance(session["id"], shapeless,
                                       coordinator_headers()),
        ERR_RECRUIT_NOT_FOUND, 404)
    # Both 404s live on the existence tier, so their order is read off the ids.
    assert bad_path["error_id"] == ERR_COURSE_SESSION_NOT_FOUND
    assert bad_body_fk["error_id"] == ERR_RECRUIT_NOT_FOUND

    missing_field = validate_error(
        world.client.record_attendance(
            session["id"], {"recruit_id": recruit["id"], "status": "PRESENT"},
            coordinator_headers()),
        ERR_INVALID_REQUEST, 400)
    assert_ladder_precedence(bad_body_fk["error_id"], ERR_RECRUIT_NOT_FOUND,
                             ERR_INVALID_REQUEST)
    assert missing_field["error_id"] == ERR_INVALID_REQUEST

    recorded = validate_success(world.client.record_attendance(
        session["id"], f.attendance_payload(recruit["id"], "PRESENT", 2.0),
        coordinator_headers()), 201)
    assert recorded["ledger_status"] == "PROVISIONAL"


def test_existence_and_interval_answer_before_the_concurrency_token(world):
    """A stale token is reported only once the body is otherwise sound.

    PRD: "Priority 30 - optimistic-concurrency mismatch: `ERR_STALE_*_VERSION`,
    412, checked only after the referenced entities exist."

    Design: Corner/validations/priority_conflict_existence_and_interval_checks_outrank_the_concurrency_token
    """
    built = _patrol_curriculum(world)
    recruit = world.recruit_in_field_training(built)
    fto = world.create_certified_fto()
    stale = recruit["version"] - 1

    def plan(recruit_id, start_date, end_date, expected_version):
        return world.client.create_field_training_rotation(
            f.rotation_payload(recruit_id, fto["id"], expected_version,
                               phase_number=1, start_date=start_date,
                               end_date=end_date),
            coordinator_headers())

    bogus = validate_error(
        plan(MISSING_ID, "2026-08-20", "2026-09-02", stale),
        ERR_RECRUIT_NOT_FOUND, 404)
    reversed_window = validate_error(
        plan(recruit["id"], "2026-09-02", "2026-08-20", stale),
        ERR_INVALID_INTERVAL, 400)
    token_only = validate_error(
        plan(recruit["id"], "2026-08-20", "2026-09-02", stale),
        ERR_STALE_RECRUIT_VERSION, 412)

    assert_ladder_precedence(bogus["error_id"], ERR_RECRUIT_NOT_FOUND,
                             ERR_STALE_RECRUIT_VERSION)
    assert_ladder_precedence(reversed_window["error_id"], ERR_INVALID_INTERVAL,
                             ERR_STALE_RECRUIT_VERSION)
    assert token_only["error_id"] == ERR_STALE_RECRUIT_VERSION

    planned = validate_success(
        plan(recruit["id"], "2026-08-20", "2026-09-02", recruit["version"]), 201)
    assert planned["status"] == "PLANNED"
    assert planned["phase_number"] == 1

    _rows, meta = validate_paginated(
        world.client.list_field_training_rotations(coordinator_headers()))
    assert meta["total_count"] == 1


def test_a_fully_compliant_session_and_a_chained_second_phase_are_accepted(world):
    """Zero-gap adjacency and a next-day phase two both pass every gate.

    PRD: "Two sessions of the same instructor may not intersect on this
    half-open reading, so a session ending at exactly the instant another begins
    is legal."

    Design: Corner/validations/satisfaction_to_pass_a_fully_compliant_session_and_rotation_are_accepted
    """
    built = _patrol_curriculum(world)
    recruit = world.recruit_in_field_training(built)

    def teach(starts_at, ends_at):
        return world.client.create_course_session(
            f.course_session_payload(built["cohort"]["id"],
                                     built["lesson_plan"]["id"],
                                     built["instructor"]["id"], room_code="R1",
                                     starts_at=starts_at, ends_at=ends_at,
                                     min_enrollment=1),
            coordinator_headers())

    morning = validate_success(teach("2026-08-14T09:00:00Z",
                                     "2026-08-14T11:00:00Z"), 201)
    assert_hours_equals(morning["scheduled_hours"], "2.00", "scheduled_hours")
    assert morning["status"] == "SCHEDULED"

    # Session B begins at exactly session A's ends_at, in the same room and
    # under the same instructor.
    afternoon = validate_success(teach("2026-08-14T11:00:00Z",
                                       "2026-08-14T13:00:00Z"), 201)
    assert afternoon["status"] == "SCHEDULED"
    assert_instant_equals(afternoon["starts_at"], morning["ends_at"],
                          "starts_at")

    cohort = validate_success(world.client.get_academy_class(
        built["cohort"]["id"], director_headers()))
    assert_hours_equals(cohort["projected_topic_hours"][PATROL], "6.00",
                        "projected_topic_hours")

    first_fto = world.create_certified_fto()
    second_fto = world.create_certified_fto()
    phase_one = world.plan_rotation(recruit, first_fto["id"], phase_number=1,
                                    start_date="2026-08-20",
                                    end_date="2026-09-02")
    world.set_clock("2026-08-20T08:00:00Z")
    world.activate_rotation(phase_one["id"])
    world.set_clock("2026-08-21T18:00:00Z")
    world.file_report(phase_one["id"], first_fto["id"], "2026-08-21")
    world.set_clock("2026-09-02T12:00:00Z")
    world.complete_rotation(phase_one["id"])

    # Phase two starts the day after phase one ends, under a different officer.
    phase_two = validate_success(world.client.create_field_training_rotation(
        f.rotation_payload(recruit["id"], second_fto["id"],
                           world.read_recruit(recruit["id"])["version"],
                           phase_number=2, start_date="2026-09-03",
                           end_date="2026-09-16",
                           prior_rotation_id=phase_one["id"]),
        coordinator_headers()), 201)
    assert phase_two["status"] == "PLANNED"
    assert phase_two["phase_number"] == 2
    assert phase_two["prior_rotation_id"] == phase_one["id"]
