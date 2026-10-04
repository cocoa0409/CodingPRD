"""In-person verification appointment tests: half-open interval semantics,
the office capacity ceiling, and interval payload validation.

PRD section 3.5.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_verification_appointment,
    book_appointment,
    book_appointment_payload,
    setup_office_with_in_person_case,
    validate_error,
    validate_paginated,
    validate_success,
)

AGENT = TEST_USERS["verification_agent_headers"]


def test_overlapping_booking_beyond_capacity_rejected(api):
    """PRD section 3.5: "The office's `capacity` caps simultaneous bookings:
    a new appointment is rejected with `ERR_APPOINTMENT_CAPACITY_EXCEEDED`
    (HTTP 409) when any instant inside its half-open interval would bring the
    number of overlapping `BOOKED` appointments at that office to the
    office's capacity."

    Design: Difficulty/resource_temporal_overlap/office_capacity_aggregate_overlap
    """
    world = setup_office_with_in_person_case(capacity=2)
    office, case = world["office"], world["case"]
    book_appointment(office["id"], case["id"],
                     "2027-03-02T10:00:00Z", "2027-03-02T11:00:00Z")
    book_appointment(office["id"], case["id"],
                     "2027-03-02T10:30:00Z", "2027-03-02T11:30:00Z")

    # At 10:45 three half-open intervals would overlap in a capacity-2 office.
    resp = api.book_appointment(
        office["id"],
        book_appointment_payload(
            case["id"], "2027-03-02T10:45:00Z", "2027-03-02T11:15:00Z"
        ),
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_APPOINTMENT_CAPACITY_EXCEEDED)


def test_adjacent_booking_succeeds_half_open(api):
    """PRD section 3.5: "the interval is half-open: it occupies every instant
    from `start_at` up to but not including `end_at`, and `end_at` must be
    strictly after `start_at` (else `ERR_INVALID_REQUEST`)."

    Design: Difficulty/resource_temporal_overlap/office_capacity_aggregate_overlap
    """
    world = setup_office_with_in_person_case(capacity=2)
    office, case = world["office"], world["case"]
    book_appointment(office["id"], case["id"],
                     "2027-03-02T10:00:00Z", "2027-03-02T11:00:00Z")
    book_appointment(office["id"], case["id"],
                     "2027-03-02T10:30:00Z", "2027-03-02T11:30:00Z")

    # 11:00 start is adjacent to the first appointment's 11:00 end: half-open
    # semantics keep the overlap count at the capacity of 2, never above.
    resp = api.book_appointment(
        office["id"],
        book_appointment_payload(
            case["id"], "2027-03-02T11:00:00Z", "2027-03-02T12:00:00Z"
        ),
        AGENT,
    )
    created = validate_success(resp, 201)
    assert_verification_appointment(created)
    assert created["status"] == "BOOKED"
    assert created["office_id"] == office["id"]

    rows, meta = validate_paginated(api.list_office_appointments(office["id"], AGENT))
    assert meta["total_count"] == 3
    assert len(rows) == 3
    assert all(r["status"] == "BOOKED" for r in rows)


def test_appointment_end_before_start_invalid_request(api):
    """PRD section 3.5: "the interval is half-open: it occupies every instant
    from `start_at` up to but not including `end_at`, and `end_at` must be
    strictly after `start_at` (else `ERR_INVALID_REQUEST`)."

    Design: Corner/validations/appointment_end_before_start_invalid_request
    """
    world = setup_office_with_in_person_case(capacity=4)
    office, case = world["office"], world["case"]

    resp = api.book_appointment(
        office["id"],
        book_appointment_payload(
            case["id"], "2027-03-02T11:00:00Z", "2027-03-02T10:00:00Z"
        ),
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
