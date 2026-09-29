"""Who may occupy the same time twice: rooms, dates and trainee load.

Sessions are half-open instants with a campus-crossing rule bolted on, rotations
are closed date intervals where mere adjacency collides, and an officer's
concurrent load is counted over intersecting intervals rather than over rows.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_FTO_LOAD_EXCEEDED,
    ERR_INSTRUCTOR_SCHEDULE_CONFLICT,
    ERR_ROTATION_DATE_OVERLAP,
)
from test_helpers.assertions import assert_hours_equals
from test_helpers.test_users import coordinator_headers, director_headers

PATROL = "PATROL"


def _one_morning_block(world):
    """One instructor holding a 09:00-11:00 session in room R1."""
    standard = world.create_standard(
        min_total_hours=6.0,
        topic_requirements=[f.topic_requirement(PATROL, 6.0, False)])
    cohort = world.create_cohort(standard["id"])
    instructor = world.create_certified_instructor(topics=[PATROL])
    plan = world.create_approved_lesson_plan(instructor["id"], PATROL,
                                             contact_hours=2.0)
    morning = world.schedule_session(
        cohort["id"], plan["id"], instructor["id"], room_code="R1",
        starts_at="2026-08-10T09:00:00Z", ends_at="2026-08-10T11:00:00Z",
        min_enrollment=1)
    return {"cohort": cohort, "instructor": instructor, "lesson_plan": plan,
            "morning": morning}


def _attempt(world, built, room_code, starts_at, ends_at):
    """Try to schedule one more session for the same instructor."""
    payload = f.course_session_payload(
        built["cohort"]["id"], built["lesson_plan"]["id"],
        built["instructor"]["id"], room_code=room_code, starts_at=starts_at,
        ends_at=ends_at, min_enrollment=1)
    return world.client.create_course_session(payload, coordinator_headers())


def test_a_session_starting_as_another_ends_in_the_same_room_is_scheduled(world):
    """Zero gap in one room is legal, but a genuine interior overlap is not.

    PRD: "A session occupies `[starts_at, ends_at)`, including its start instant
    and excluding its end instant, so a session that begins exactly when another
    ends does *not* intersect it."

    Design: Difficulty/resource_temporal_overlap/instructor_half_open_adjacency_allowed_same_room_but_15_minute_buffer_across_rooms
    """
    built = _one_morning_block(world)

    adjacent = validate_success(
        _attempt(world, built, "R1", "2026-08-10T11:00:00Z",
                 "2026-08-10T13:00:00Z"), 201)
    assert adjacent["status"] == "SCHEDULED"
    assert adjacent["room_code"] == "R1"
    assert_hours_equals(adjacent["scheduled_hours"], "2.00", "scheduled_hours")
    assert_hours_equals(built["morning"]["scheduled_hours"], "2.00",
                        "scheduled_hours")

    overlapping = _attempt(world, built, "R1", "2026-08-10T10:00:00Z",
                           "2026-08-10T12:00:00Z")
    validate_error(overlapping, ERR_INSTRUCTOR_SCHEDULE_CONFLICT, 409)


def test_crossing_rooms_needs_a_full_fifteen_minute_turnaround(world):
    """Zero gap across rooms is a conflict; exactly fifteen minutes is not.

    PRD: "two sessions of the same instructor that sit in the *same* `room_code`
    may be perfectly adjacent with a zero gap, but two sessions in *different*
    `room_code` values separated by a gap of less than fifteen minutes are a
    conflict, because the instructor cannot cross the campus in that time."

    Design: Difficulty/resource_temporal_overlap/instructor_half_open_adjacency_allowed_same_room_but_15_minute_buffer_across_rooms
    """
    built = _one_morning_block(world)
    validate_success(
        _attempt(world, built, "R1", "2026-08-10T11:00:00Z",
                 "2026-08-10T13:00:00Z"), 201)

    no_turnaround = _attempt(world, built, "R2", "2026-08-10T13:00:00Z",
                             "2026-08-10T15:00:00Z")
    validate_error(no_turnaround, ERR_INSTRUCTOR_SCHEDULE_CONFLICT, 409)

    exactly_fifteen = validate_success(
        _attempt(world, built, "R2", "2026-08-10T13:15:00Z",
                 "2026-08-10T15:00:00Z"), 201)
    assert exactly_fifteen["status"] == "SCHEDULED"
    assert exactly_fifteen["room_code"] == "R2"
    assert_hours_equals(exactly_fifteen["scheduled_hours"], "1.75",
                        "scheduled_hours")

    rows, meta = validate_paginated(world.client.list_course_sessions(
        coordinator_headers(), {"instructor_id": built["instructor"]["id"]}))
    assert meta["total_count"] == 3
    assert len(rows) == 3


def _completed_phase_one(world):
    """A trainee whose phase one ran 2027-03-01 to 2027-03-31 and closed."""
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
    world.set_clock("2027-04-01T12:00:00Z")
    world.complete_rotation(phase_one["id"])

    return {"recruit": world.read_recruit(recruit["id"]),
            "first_fto": first_fto, "second_fto": second_fto,
            "phase_one": phase_one}


def _plan_phase_two(world, built, start_date):
    """Try to plan phase two under the second officer from this start date."""
    payload = f.rotation_payload(
        built["recruit"]["id"], built["second_fto"]["id"],
        built["recruit"]["version"], phase_number=2, start_date=start_date,
        end_date="2027-04-30", prior_rotation_id=built["phase_one"]["id"])
    return world.client.create_field_training_rotation(payload,
                                                       coordinator_headers())


def test_a_rotation_beginning_the_day_the_last_one_ended_is_an_overlap(world):
    """Sharing the boundary date with the closed phase one collides.

    PRD: "A rotation occupies `[start_date, end_date]` inclusive of both
    endpoints, so two rotations that merely touch - one ending on the very day the
    next begins - *do* intersect. Adjacency counts as overlap."

    Design: Difficulty/resource_temporal_overlap/rotation_closed_interval_adjacency_counts_as_overlap
    """
    built = _completed_phase_one(world)

    touching = _plan_phase_two(world, built, "2027-03-31")
    validate_error(touching, ERR_ROTATION_DATE_OVERLAP, 409)

    rows, meta = validate_paginated(world.client.list_field_training_rotations(
        coordinator_headers(), {"recruit_id": built["recruit"]["id"]}))
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [built["phase_one"]["id"]]


def test_the_same_request_one_day_later_is_planned(world):
    """A start date clear of the boundary plans, and PLANNED carries no load.

    PRD: "A new rotation starts at `status` `PLANNED` with `competency_score` and
    `rolling_mean_score` both null, `final_narrative` and `abort_reason` null, and
    `dor_count` and `remedial_flag_count` at zero."

    Design: Difficulty/resource_temporal_overlap/rotation_closed_interval_adjacency_counts_as_overlap
    """
    built = _completed_phase_one(world)

    phase_two = validate_success(_plan_phase_two(world, built, "2027-04-01"), 201)
    assert phase_two["status"] == "PLANNED"
    assert phase_two["phase_number"] == 2
    assert phase_two["prior_rotation_id"] == built["phase_one"]["id"]
    assert phase_two["competency_score"] is None
    assert phase_two["rolling_mean_score"] is None
    assert phase_two["dor_count"] == 0

    assert world.read_rotation(built["phase_one"]["id"])["status"] == "COMPLETED"

    _rows, meta = validate_paginated(world.client.list_field_training_rotations(
        coordinator_headers(), {"recruit_id": built["recruit"]["id"]}))
    assert meta["total_count"] == 2

    officer = validate_success(world.client.get_instructor(
        built["second_fto"]["id"], director_headers()))
    assert officer["active_trainee_count"] == 0


def _officer_holding_two_april_rotations(world):
    """One officer already assigned two rotations that cover most of April."""
    standard = world.create_standard(
        min_total_hours=2.0,
        topic_requirements=[f.topic_requirement(PATROL, 2.0, False)])
    cohort = world.create_cohort(standard["id"])
    fto = world.create_certified_fto()

    first = world.create_recruit(cohort["id"], full_name="Sam Ortiz")
    second = world.create_recruit(cohort["id"], full_name="Tess Ruiz")
    third = world.create_recruit(cohort["id"], full_name="Umar Vale")

    first_rotation = world.plan_rotation(first, fto["id"], phase_number=1,
                                         start_date="2027-04-01",
                                         end_date="2027-04-20")
    second_rotation = world.plan_rotation(second, fto["id"], phase_number=1,
                                          start_date="2027-04-10",
                                          end_date="2027-04-30")
    return {"fto": fto, "third": third, "first_rotation": first_rotation,
            "second_rotation": second_rotation}


def _plan_for_the_third(world, built, start_date, end_date):
    """Try to assign the third trainee to the same officer over this window."""
    payload = f.rotation_payload(built["third"]["id"], built["fto"]["id"],
                                 built["third"]["version"], phase_number=1,
                                 start_date=start_date, end_date=end_date)
    return world.client.create_field_training_rotation(payload,
                                                       coordinator_headers())


def test_a_third_intersecting_assignment_exceeds_the_officers_ceiling(world):
    """Two intersecting rotations already fill the concurrent-trainee cap.

    PRD: "Finally the officer's concurrent load is capped at two: if they already
    hold two or more rotations at `PLANNED`, `ACTIVE` or `REMEDIAL` whose closed
    intervals intersect the candidate's, the answer is `ERR_FTO_LOAD_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/fto_aggregate_concurrent_trainee_capacity_exceeded
    """
    built = _officer_holding_two_april_rotations(world)

    refused = _plan_for_the_third(world, built, "2027-04-15", "2027-05-01")
    validate_error(refused, ERR_FTO_LOAD_EXCEEDED, 409)

    _rows, meta = validate_paginated(world.client.list_field_training_rotations(
        coordinator_headers(), {"fto_instructor_id": built["fto"]["id"]}))
    assert meta["total_count"] == 2


def test_a_window_intersecting_neither_rotation_is_planned(world):
    """The ceiling is counted over intersecting intervals, not over rows held.

    PRD: "`active_trainee_count` is a conserved reading rather than a stored
    counter: it is always the number of field training rotations naming this
    instructor as FTO whose `status` is `ACTIVE` or `REMEDIAL`."

    Design: Difficulty/resource_temporal_overlap/fto_aggregate_concurrent_trainee_capacity_exceeded
    """
    built = _officer_holding_two_april_rotations(world)

    planned = validate_success(
        _plan_for_the_third(world, built, "2027-06-01", "2027-06-20"), 201)
    assert planned["status"] == "PLANNED"
    assert world.read_rotation(built["first_rotation"]["id"])["status"] == "PLANNED"
    assert world.read_rotation(built["second_rotation"]["id"])["status"] == "PLANNED"

    _rows, meta = validate_paginated(world.client.list_field_training_rotations(
        coordinator_headers(), {"fto_instructor_id": built["fto"]["id"]}))
    assert meta["total_count"] == 3

    officer = validate_success(world.client.get_instructor(
        built["fto"]["id"], director_headers()))
    assert officer["active_trainee_count"] == 0
    assert world.read_recruit(built["third"]["id"])["pipeline_stage"] == "APPLICANT"
