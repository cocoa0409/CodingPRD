"""Depth coverage: gates that read another entity, and the three interval geometries."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_second_applicant,
    book_road_test,
    carrier_version,
    complete_negative_drug_test,
    create_application,
    create_open_session,
    fetch_carrier,
    make_safety_director_headers,
    pass_road_test,
    reserve_seat,
    setup_draft_application,
    setup_road_test_passed_application,
    setup_submitted_application,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)

RECRUITER = TEST_USERS["recruiter_headers"]
SAFETY_DIRECTOR = TEST_USERS["safety_director_headers"]


def _draft_application_at_a_frozen_office(dot_number: str):
    ctx = setup_draft_application(carrier_overrides={"dot_number": dot_number})
    from test_helpers import api_client

    validate_success(
        api_client.update_carrier(
            ctx["carrier_id"],
            {
                "safety_rating": "UNSATISFACTORY",
                "expected_carrier_version": carrier_version(ctx["carrier_id"]),
            },
            SAFETY_DIRECTOR,
        )
    )
    return ctx


def _road_test_passed_sibling(ctx, index: int, examiner_user_id: str, scheduled_at: str):
    """A second application at the same office, also driven to ROAD_TEST_PASSED."""
    applicant = add_second_applicant(ctx["carrier_id"], index=index)
    application = create_application(applicant["id"], position_type="LOCAL")
    submit_application(application["id"], "rec-001")
    complete_negative_drug_test(application["id"])
    pass_road_test(
        application["id"], examiner_user_id=examiner_user_id, scheduled_at=scheduled_at
    )
    return {"applicant": applicant, "application": application}


# ─── cross_entity_state_dependency ────────────────────────────────────────────

def test_a_frozen_office_cannot_accept_a_submission(api):
    """PRD §3.2: "It is accepted only while `screening_status` is `DRAFT`, only while the owning
    carrier's `posture` is `OPEN` or `RESTRICTED` — a `FROZEN` office is refused with
    `ERR_CARRIER_POSTURE_BLOCKED` — and only while the applicant's `rehire_eligibility` reads
    `ELIGIBLE`, otherwise `ERR_REHIRE_INELIGIBLE`."
    PRD §3.1: "the posture is `FROZEN` when the carrier's `safety_rating` is `UNSATISFACTORY`"

    Design: Difficulty/cross_entity_state_dependency/submit_blocked_by_frozen_carrier_posture
    """
    ctx = _draft_application_at_a_frozen_office("DOT-2166-R")

    response = api.submit_application(
        ctx["application_id"], TEST_USERS["recruiter_headers"]
    )

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_CARRIER_POSTURE_BLOCKED.value, 409)
    assert fetch_carrier(ctx["carrier_id"])["posture"] == "FROZEN"


def test_the_refused_submission_mints_no_qualification_file(api):
    """PRD §3.2: "A fresh application opens at `DRAFT` on the first axis and `NOT_STARTED` on the
    second."
    PRD §3.2: "Submission is also the sole producer of the qualification file and its documents:
    it creates the one-to-one file in `OPEN` status with `review_state` at `NOT_DUE`, `opened_on`
    set to the current logical-clock calendar date and `total_weight` at 33, then seeds twelve
    document rows, one per artifact type, all in `MISSING` status."
    PRD §3.2: "There is no way to create a qualification file or a qualification document by any
    other route."

    Design: Difficulty/cross_entity_state_dependency/submit_blocked_by_frozen_carrier_posture
    """
    ctx = _draft_application_at_a_frozen_office("DOT-2166-R")

    api.submit_application(ctx["application_id"], TEST_USERS["recruiter_headers"])

    application = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )
    assert application["screening_status"] == "DRAFT"
    assert application["qualification_status"] == "NOT_STARTED"

    rows, _ = validate_paginated(
        api.list_dq_files(RECRUITER, params={"application_id": ctx["application_id"]})
    )
    assert rows == [], "no qualification file may exist for an unsubmitted application"


def test_a_seat_cannot_be_reserved_before_the_road_test_is_passed(api):
    """PRD §3.6: "The application must have reached `ROAD_TEST_PASSED` on its qualification axis
    — anything earlier or later, and anything disqualified, reports
    `ERR_APPLICATION_NOT_QUALIFIED`."
    PRD §3.6: "A `Recruiter` reserves one by supplying `session_id`, `application_id` and
    `expected_session_version` matching the session's current `version`, and the reservation is
    only accepted while the session is `OPEN`."

    Design: Difficulty/cross_entity_state_dependency/enrollment_blocked_until_application_road_test_passed
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-2166-S"})
    session = create_open_session(ctx["carrier_id"])

    response = api.create_orientation_enrollment(
        {
            "session_id": session["id"],
            "application_id": ctx["application_id"],
            "expected_session_version": session["version"],
        },
        RECRUITER,
    )

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_APPLICATION_NOT_QUALIFIED.value, 409)


def test_the_refused_reservation_consumes_no_seat(api):
    """PRD §3.6: "On success the enrollment is minted in `RESERVED`, the session's
    `enrolled_count` increments by one and the session's `version` increments by one."
    PRD §3.6: "Classes open in `PLANNED` with `enrolled_count` at zero, and may be listed and
    narrowed by `carrier_id` or by `status`."

    Design: Difficulty/cross_entity_state_dependency/enrollment_blocked_until_application_road_test_passed
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-2166-S"})
    session = create_open_session(ctx["carrier_id"])
    version_after_open = session["version"]

    api.create_orientation_enrollment(
        {
            "session_id": session["id"],
            "application_id": ctx["application_id"],
            "expected_session_version": version_after_open,
        },
        RECRUITER,
    )

    refreshed = validate_success(api.get_orientation_session(session["id"], RECRUITER))
    assert refreshed["enrolled_count"] == 0
    assert refreshed["version"] == version_after_open


def test_a_pass_is_refused_without_a_verified_negative_specimen(api):
    """PRD §3.5: "Creating a hire record and recording a passing road-test result both require
    that some drug test order of the application with `test_type` `PRE_EMPLOYMENT` sits in
    `MRO_VERIFIED_NEGATIVE`; the absence of one reports `ERR_DRUG_TEST_NOT_NEGATIVE`."
    PRD §3.6: "A pass also requires the safety prerequisites of §3.5 — an unblocked Clearinghouse
    picture and a verified-negative pre-employment specimen — and both are evaluated only on the
    pass branch."

    Design: Difficulty/cross_entity_state_dependency/road_test_pass_blocked_without_negative_mro_result
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-2166-T"})
    road_test = book_road_test(ctx["application_id"])

    response = api.record_road_test_result(
        road_test["id"],
        {"outcome": "PASSED", "score_pretrip": 90, "score_skills": 86, "score_road": 78},
        make_safety_director_headers("exam-501"),
    )

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_DRUG_TEST_NOT_NEGATIVE.value, 409)


def test_the_refused_pass_leaves_the_test_scheduled_and_unscored(api):
    """PRD §3.6: "The test opens in `SCHEDULED` with `attempt_number` at 1 and all four score
    fields null."
    PRD §3.6: "On success the test moves `SCHEDULED → PASSED`, which is its terminal state; the
    application's `qualification_status` advances `IN_PROGRESS → ROAD_TEST_PASSED`; the
    `ROAD_TEST_CERT` document of the application's qualification file becomes `PRESENT` with
    `effective_on` at the current logical-clock date; and the file's `completeness_pct`,
    `deficiency_count` and status are recomputed with its `version` incremented by one."

    Design: Difficulty/cross_entity_state_dependency/road_test_pass_blocked_without_negative_mro_result
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-2166-T"})
    road_test = book_road_test(ctx["application_id"])

    api.record_road_test_result(
        road_test["id"],
        {"outcome": "PASSED", "score_pretrip": 90, "score_skills": 86, "score_road": 78},
        make_safety_director_headers("exam-501"),
    )

    row = validate_success(api.get_road_test(road_test["id"], RECRUITER))
    assert row["status"] == "SCHEDULED"
    assert row["composite_score"] is None

    application = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )
    assert application["qualification_status"] == "IN_PROGRESS"


# ─── resource_temporal_overlap ────────────────────────────────────────────────

def test_a_class_starting_inside_the_twelve_hour_buffer_is_refused(api):
    """PRD §3.6: "The **buffered overlap** rule protects the driver: the candidate session's
    interval is widened by twelve hours on each side, forming the half-open span from `starts_at`
    less twelve hours up to but not including `ends_at` plus twelve hours, and if that widened
    span intersects the plain half-open interval of any other session the same application already
    occupies through a `RESERVED` or `ATTENDED` enrollment, the reservation is refused with
    `ERR_ORIENTATION_OVERLAP`."
    PRD §3.6: "A `Recruiter` creates a class by supplying `carrier_id`, the `starts_at` inclusive
    start and the `ends_at` exclusive end of its interval — `ends_at` must fall strictly after
    `starts_at`, and an inverted interval reports `ERR_VALIDATION` at HTTP 422 — a `capacity` of at
    least one seat, and a `location_code` naming the terminal or classroom."

    Design: Difficulty/resource_temporal_overlap/orientation_buffered_half_open_overlap_on_application
    """
    ctx = setup_road_test_passed_application(carrier_overrides={"dot_number": "DOT-2166-U"})
    first = create_open_session(ctx["carrier_id"])
    reserve_seat(first["id"], ctx["application_id"], first["version"])
    overlapping = create_open_session(
        ctx["carrier_id"],
        starts_at="2026-08-13T06:00:00Z",
        ends_at="2026-08-15T18:00:00Z",
        location_code="DAL-2",
    )

    response = api.create_orientation_enrollment(
        {
            "session_id": overlapping["id"],
            "application_id": ctx["application_id"],
            "expected_session_version": overlapping["version"],
        },
        RECRUITER,
    )

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_ORIENTATION_OVERLAP.value, 409)
    refreshed = validate_success(api.get_orientation_session(overlapping["id"], RECRUITER))
    assert refreshed["enrolled_count"] == 0


def test_a_buffered_span_that_merely_touches_the_first_class_is_accepted(api):
    """PRD §3.6: "The **buffered overlap** rule protects the driver: the candidate session's
    interval is widened by twelve hours on each side, forming the half-open span from `starts_at`
    less twelve hours up to but not including `ends_at` plus twelve hours, and if that widened span
    intersects the plain half-open interval of any other session the same application already
    occupies through a `RESERVED` or `ATTENDED` enrollment, the reservation is refused with
    `ERR_ORIENTATION_OVERLAP`."
    PRD §3.6: "On success the enrollment is minted in `RESERVED`, the session's `enrolled_count`
    increments by one and the session's `version` increments by one."

    Design: Difficulty/resource_temporal_overlap/orientation_buffered_half_open_overlap_on_application
    """
    ctx = setup_road_test_passed_application(carrier_overrides={"dot_number": "DOT-2166-U"})
    first = create_open_session(ctx["carrier_id"])
    reserve_seat(first["id"], ctx["application_id"], first["version"])
    touching = create_open_session(
        ctx["carrier_id"],
        starts_at="2026-08-13T09:00:00Z",
        ends_at="2026-08-15T21:00:00Z",
        location_code="DAL-3",
    )

    enrollment = validate_success(
        api.create_orientation_enrollment(
            {
                "session_id": touching["id"],
                "application_id": ctx["application_id"],
                "expected_session_version": touching["version"],
            },
            RECRUITER,
        ),
        201,
    )

    assert enrollment["status"] == "RESERVED", (
        "a buffered start equal to the first class's exclusive end does not intersect it"
    )
    assert validate_success(
        api.get_orientation_session(touching["id"], RECRUITER)
    )["enrolled_count"] == 1
    assert validate_success(
        api.get_orientation_session(first["id"], RECRUITER)
    )["enrolled_count"] == 1


def test_an_examiner_slot_that_touches_endpoint_to_endpoint_collides(api):
    """PRD §3.6: "Each booking consumes three hours of examiner time: the slot runs from
    `scheduled_at` to `scheduled_at` advanced by 180 minutes, and that interval is **closed at both
    ends**. A new or rescheduled test is refused with `ERR_EXAMINER_SLOT_CONFLICT` when its closed
    slot intersects the identically-constructed closed slot of any other road test that is still
    `SCHEDULED` and carries the same `examiner_user_id` — because the interval is closed, two slots
    that merely touch endpoint-to-endpoint already collide."

    Design: Difficulty/resource_temporal_overlap/examiner_closed_slot_touching_endpoints_collide
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-2166-V"})
    book_road_test(
        ctx["application_id"], examiner_user_id="exam-777", scheduled_at="2026-08-05T14:00:00Z"
    )
    other_applicant = add_second_applicant(ctx["carrier_id"], index=2)
    other_application = create_application(other_applicant["id"], position_type="LOCAL")
    submit_application(other_application["id"], "rec-001")

    response = api.create_road_test(
        {
            "application_id": other_application["id"],
            "examiner_user_id": "exam-777",
            "scheduled_at": "2026-08-05T17:00:00Z",
            "vehicle_class": "CLASS_A",
        },
        RECRUITER,
    )

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_EXAMINER_SLOT_CONFLICT.value, 409)


def test_an_examiner_slot_one_minute_clear_of_the_endpoint_is_accepted(api):
    """PRD §3.6: "Each booking consumes three hours of examiner time: the slot runs from
    `scheduled_at` to `scheduled_at` advanced by 180 minutes, and that interval is **closed at both
    ends**. A new or rescheduled test is refused with `ERR_EXAMINER_SLOT_CONFLICT` when its closed
    slot intersects the identically-constructed closed slot of any other road test that is still
    `SCHEDULED` and carries the same `examiner_user_id` — because the interval is closed, two slots
    that merely touch endpoint-to-endpoint already collide."
    PRD §3.6: "The test opens in `SCHEDULED` with `attempt_number` at 1 and all four score fields
    null."

    Design: Difficulty/resource_temporal_overlap/examiner_closed_slot_touching_endpoints_collide
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-2166-V"})
    first = book_road_test(
        ctx["application_id"], examiner_user_id="exam-777", scheduled_at="2026-08-05T14:00:00Z"
    )
    other_applicant = add_second_applicant(ctx["carrier_id"], index=2)
    other_application = create_application(other_applicant["id"], position_type="LOCAL")
    submit_application(other_application["id"], "rec-001")

    accepted = validate_success(
        api.create_road_test(
            {
                "application_id": other_application["id"],
                "examiner_user_id": "exam-777",
                "scheduled_at": "2026-08-05T17:01:00Z",
                "vehicle_class": "CLASS_A",
            },
            RECRUITER,
        ),
        201,
    )

    assert accepted["status"] == "SCHEDULED"
    assert accepted["attempt_number"] == 1
    assert accepted["scheduled_at"] == "2026-08-05T17:01:00.000Z"
    assert validate_success(api.get_road_test(first["id"], RECRUITER))["status"] == "SCHEDULED"


def test_a_full_class_refuses_the_next_reservation(api):
    """PRD §3.6: "The **capacity** rule protects the classroom: the session's `enrolled_count`
    must be strictly below its `capacity`, and a full class reports `ERR_SESSION_AT_CAPACITY`."

    Design: Difficulty/resource_temporal_overlap/orientation_session_aggregate_capacity_exhausted
    """
    ctx = setup_road_test_passed_application(carrier_overrides={"dot_number": "DOT-2166-W"})
    session = create_open_session(ctx["carrier_id"], capacity=1)
    reserve_seat(session["id"], ctx["application_id"], session["version"])
    sibling = _road_test_passed_sibling(
        ctx, index=2, examiner_user_id="exam-502", scheduled_at="2026-08-06T14:00:00Z"
    )

    response = api.create_orientation_enrollment(
        {
            "session_id": session["id"],
            "application_id": sibling["application"]["id"],
            "expected_session_version": validate_success(
                api.get_orientation_session(session["id"], RECRUITER)
            )["version"],
        },
        RECRUITER,
    )

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_SESSION_AT_CAPACITY.value, 409)


def test_the_full_class_keeps_its_single_occupied_seat(api):
    """PRD §3.6: "The `enrolled_count` figure counts every enrollment of the session in
    `RESERVED`, `ATTENDED` or `ABSENT`, so an absent driver still occupies the seat they consumed;
    only a cancellation gives a seat back."
    PRD §3.6: "Each attendance, by contrast, advances the linked application's
    `qualification_status` from `ROAD_TEST_PASSED` to `ORIENTATION_COMPLETE`."

    Design: Difficulty/resource_temporal_overlap/orientation_session_aggregate_capacity_exhausted
    """
    ctx = setup_road_test_passed_application(carrier_overrides={"dot_number": "DOT-2166-W"})
    session = create_open_session(ctx["carrier_id"], capacity=1)
    enrollment = reserve_seat(session["id"], ctx["application_id"], session["version"])
    sibling = _road_test_passed_sibling(
        ctx, index=2, examiner_user_id="exam-502", scheduled_at="2026-08-06T14:00:00Z"
    )

    api.create_orientation_enrollment(
        {
            "session_id": session["id"],
            "application_id": sibling["application"]["id"],
            "expected_session_version": validate_success(
                api.get_orientation_session(session["id"], RECRUITER)
            )["version"],
        },
        RECRUITER,
    )

    refreshed = validate_success(api.get_orientation_session(session["id"], RECRUITER))
    assert refreshed["enrolled_count"] == 1
    assert refreshed["capacity"] == 1
    assert validate_success(
        api.get_orientation_enrollment(enrollment["id"], RECRUITER)
    )["status"] == "RESERVED"
    assert validate_success(
        api.get_driver_application(sibling["application"]["id"], RECRUITER)
    )["qualification_status"] == "ROAD_TEST_PASSED"
