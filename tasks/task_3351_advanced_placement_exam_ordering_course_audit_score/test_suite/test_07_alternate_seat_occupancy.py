"""Alternate administrations: buffer-interval occupancy and the same-day cap."""
from test_helpers import (
    ALTERNATE_PLANNING_CLOCK_UTC,
    ApiErrorId,
    api_client,
    create_alternate,
    create_registration,
    create_student,
    get_registration,
    host_headers,
    setup_open_order,
    transition_alternate,
    transition_registration,
    validate_error,
    validate_success,
)


def _prepare(school_overrides, subjects):
    """One approved school, one order and `len(subjects)` confirmed registrations."""
    bundle = setup_open_order(
        clock=ALTERNATE_PLANNING_CLOCK_UTC, school_overrides=school_overrides
    )
    school, order = bundle["school"], bundle["order"]
    students = [bundle["student"]]
    while len(students) < len(subjects):
        students.append(create_student(school))
    registrations = []
    for index, subject in enumerate(subjects):
        registration = create_registration(
            order, students[index], school, exam_subject=subject, registration_tier="REGULAR"
        )
        registration = transition_registration(registration, "CONFIRMED", school=school)
        registrations.append(registration)
    bundle["registrations"] = registrations
    return bundle


def _approve(alternate, school):
    # `_file()` already moved the row FILED -> UNDER_REVIEW; the PRD machine is
    # "A filed request moves to `UNDER_REVIEW` only when ...", with no self-edge,
    # so approval is the single UNDER_REVIEW -> APPROVED step.
    return transition_alternate(alternate, "APPROVED", school=school)


def _file(bundle, index, alternate_date, form_code, reason_code):
    alternate = create_alternate(
        bundle["registrations"][index],
        bundle["school"],
        alternate_date_utc=alternate_date,
        reason_code=reason_code,
        form_code=form_code,
    )
    return transition_alternate(alternate, "UNDER_REVIEW", school=bundle["school"])


def _attempt_approval(alternate, school):
    return api_client.transition_alternate_exam_request(
        alternate["id"],
        {
            "to_status": "APPROVED",
            "expected_alternate_exam_request_version": alternate["version"],
        },
        host_headers(school),
    )


# --------------------------------------------------------------------------
# Buffered intervals: touching blocks merge, and the seat-minute budget bites
# --------------------------------------------------------------------------

def test_touching_buffered_intervals_overflow_a_two_seat_centre():
    """PRD §3.6: "Each such request occupies a buffered interval that begins 30 minutes before its `alternate_date_utc` and ends 195 minutes after it plus a further 30 minutes, so each block spans 255 minutes."
    PRD §3.6: "the center's capacity is its `seat_capacity` multiplied by the 30-minute buffer-before allowance"
    PRD §3.6: "If the requesting request's own interval overlaps any existing block, or the merged total exceeds the available seat-minutes, the request overflows and is denied with `ERR_ALT_SEAT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/alternate_buffer_interval_touching_merge_occupancy
    """
    bundle = _prepare({"seat_capacity": 2}, ["AP-MUSIC", "AP-MUSIC"])
    _approve(
        _file(bundle, 0, "2027-05-10T09:00:00Z", "ALT-A-1", "SCHEDULE_CONFLICT"), bundle["school"]
    )
    second = _file(bundle, 1, "2027-05-10T13:15:00Z", "ALT-B-1", "ILLNESS")

    response = _attempt_approval(second, bundle["school"])
    validate_error(response, ApiErrorId.ERR_ALT_SEAT_CONFLICT)

    # 2 * 30 seat-minutes = 60, far below the 510 merged minutes.
    assert get_registration(bundle["registrations"][1]["id"])["status"] == "CONFIRMED"


def test_touching_buffered_intervals_are_admitted_by_a_generous_centre():
    """PRD §3.6: "Blocks whose gap is zero — that is, where one block's end equals the next block's start — merge into a single block, because the buffer must remain unoccupied; a gap of one minute or more keeps them separate."
    PRD §3.6: "If the requesting request's own interval overlaps any existing block, or the merged total exceeds the available seat-minutes, the request overflows and is denied with `ERR_ALT_SEAT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/alternate_buffer_interval_touching_merge_occupancy
    """
    bundle = _prepare({"seat_capacity": 20}, ["AP-MUSIC", "AP-MUSIC"])
    _approve(
        _file(bundle, 0, "2027-05-10T09:00:00Z", "ALT-A-1", "SCHEDULE_CONFLICT"), bundle["school"]
    )
    second = _file(bundle, 1, "2027-05-10T13:15:00Z", "ALT-B-1", "ILLNESS")

    approved = validate_success(_attempt_approval(second, bundle["school"]))

    assert approved["status"] == "APPROVED", (
        "touching intervals merge into one 510-minute block, which fits 20 * 30 seat-minutes"
    )


# --------------------------------------------------------------------------
# The independent same-calendar-day cap
# --------------------------------------------------------------------------

def test_third_alternate_on_one_calendar_day_is_refused_by_the_concurrent_cap():
    """PRD §3.6: "A separate, stricter rule applies independently of the buffer arithmetic: no more than two alternate administrations for the same school may share one calendar day."
    PRD §3.6: "A request denied for either reason ends in `DENIED`."

    Design: Difficulty/resource_temporal_overlap/alternate_same_day_concurrent_count_cap
    """
    bundle = _prepare({"seat_capacity": 30}, ["AP-ART-HIST", "AP-ART-HIST", "AP-ART-HIST"])
    _approve(
        _file(bundle, 0, "2027-05-11T09:00:00Z", "ALT-K-1", "RELIGIOUS_OBSERVANCE"),
        bundle["school"],
    )
    _approve(_file(bundle, 1, "2027-05-11T14:00:00Z", "ALT-K-2", "ILLNESS"), bundle["school"])
    third = _file(bundle, 2, "2027-05-11T19:00:00Z", "ALT-K-3", "EMERGENCY")

    response = _attempt_approval(third, bundle["school"])
    validate_error(response, ApiErrorId.ERR_ALT_SEAT_CONFLICT)


def test_third_alternate_on_a_different_calendar_day_is_admitted():
    """PRD §3.6: "no more than two alternate administrations for the same school may share one calendar day"
    PRD §3.6: "The merged blocks are summed into a total occupied minutes figure, and the center's capacity is its `seat_capacity` multiplied by the 30-minute buffer-before allowance."

    Design: Difficulty/resource_temporal_overlap/alternate_same_day_concurrent_count_cap
    """
    bundle = _prepare({"seat_capacity": 30}, ["AP-ART-HIST", "AP-ART-HIST", "AP-ART-HIST"])
    _approve(
        _file(bundle, 0, "2027-05-11T09:00:00Z", "ALT-K-1", "RELIGIOUS_OBSERVANCE"),
        bundle["school"],
    )
    _approve(_file(bundle, 1, "2027-05-11T14:00:00Z", "ALT-K-2", "ILLNESS"), bundle["school"])
    third = _file(bundle, 2, "2027-05-12T19:00:00Z", "ALT-K-3", "EMERGENCY")

    approved = validate_success(_attempt_approval(third, bundle["school"]))
    assert approved["status"] == "APPROVED", (
        "the cap is per calendar day, and 2027-05-12 carries no alternate administration yet"
    )
