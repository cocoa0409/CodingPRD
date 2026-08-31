"""Booking jurisdiction inspections: half-open slots and daily capacity."""
from test_helpers import (
    ApiErrorId, validate_success, validate_error, validate_paginated,
    assert_inspection_appointment, assert_availability,
    inspection_appointment_payload,
    setup_permitted_project, setup_scheduled_phase,
    register_inspector, book_inspection, availability,
    PROJECT_MANAGER,
)


def test_back_to_back_inspection_slots_are_accepted(api):
    """PRD §2.10: "An inspection appointment's slot is a **half-open** interval of instants:
    `slot_start` is inside the slot and `slot_end` is not, and no buffer is applied.
    Back-to-back bookings, where one appointment starts at precisely the instant another ends,
    are therefore accepted rather than rejected."
    PRD §3.8: "Third comes the slot conflict: the booking is rejected with
    `ERR_INSPECTOR_SLOT_CONFLICT` (HTTP 409) when any other appointment held by the same
    inspector with status `SCHEDULED` or `PARTIAL` overlaps the requested interval —
    concretely, when the requested `slot_start` is strictly earlier than that appointment's
    `slot_end` and that appointment's `slot_start` is strictly earlier than the requested
    `slot_end`. Because both comparisons are strict, an appointment starting at precisely the
    instant another ends is accepted."

    Design: Difficulty/resource_temporal_overlap/inspector_slot_half_open_and_daily_capacity
    """
    ctx = setup_permitted_project(api)
    inspector = register_inspector(api, ctx["jurisdiction"]["id"],
                                   full_name="T. Alvarez", daily_capacity=2)
    phase = setup_scheduled_phase(api, ctx, "2026-09-01", "2026-09-05")

    first = validate_success(api.create_inspection_appointment(
        phase["id"], inspection_appointment_payload(
            inspector["id"], inspection_type="FOUNDATION", slot_date="2026-09-02",
            slot_start="2026-09-02T09:00:00Z", slot_end="2026-09-02T10:00:00Z"),
        PROJECT_MANAGER), 201)
    second = validate_success(api.create_inspection_appointment(
        phase["id"], inspection_appointment_payload(
            inspector["id"], inspection_type="FRAMING", slot_date="2026-09-02",
            slot_start="2026-09-02T10:00:00Z", slot_end="2026-09-02T11:00:00Z"),
        PROJECT_MANAGER), 201)

    assert_inspection_appointment(first)
    assert_inspection_appointment(second)
    assert first["status"] == "SCHEDULED"
    assert second["status"] == "SCHEDULED"


def test_third_booking_on_a_full_day_is_refused_on_capacity(api):
    """PRD §3.8: "Fourth comes the day's aggregate load: the count of appointments already
    held by that inspector on the same `slot_date` with status `SCHEDULED` or `PARTIAL` must
    be strictly less than the inspector's `daily_capacity` before the new row is written; at
    or beyond capacity the booking is rejected with `ERR_INSPECTOR_DAILY_CAPACITY_EXCEEDED`
    (HTTP 409). Note that these two checks measure different things — a day can be free of
    interval overlaps and still be full."

    Design: Difficulty/resource_temporal_overlap/inspector_slot_half_open_and_daily_capacity
    """
    ctx = setup_permitted_project(api)
    inspector = register_inspector(api, ctx["jurisdiction"]["id"],
                                   full_name="T. Alvarez", daily_capacity=2)
    phase = setup_scheduled_phase(api, ctx, "2026-09-01", "2026-09-05")
    book_inspection(api, phase["id"], inspector["id"], inspection_type="FOUNDATION",
                    slot_date="2026-09-02", slot_start="2026-09-02T09:00:00Z",
                    slot_end="2026-09-02T10:00:00Z")
    book_inspection(api, phase["id"], inspector["id"], inspection_type="FRAMING",
                    slot_date="2026-09-02", slot_start="2026-09-02T10:00:00Z",
                    slot_end="2026-09-02T11:00:00Z")

    error = validate_error(api.create_inspection_appointment(
        phase["id"], inspection_appointment_payload(
            inspector["id"], inspection_type="ROUGH_MEP", slot_date="2026-09-02",
            slot_start="2026-09-02T11:00:00Z", slot_end="2026-09-02T12:00:00Z"),
        PROJECT_MANAGER),
        ApiErrorId.ERR_INSPECTOR_DAILY_CAPACITY_EXCEEDED)
    assert error["error_id"] != ApiErrorId.ERR_INSPECTOR_SLOT_CONFLICT.value, (
        "the third window overlaps nothing; only the aggregate day count is full")

    day = availability(api, inspector["id"], "2026-09-02")
    assert_availability(day, inspector["id"], "2026-09-02", daily_capacity=2, booked_count=2)


def test_cancelling_an_inspection_returns_the_slot_to_the_day(api):
    """PRD §3.8: "A `ProjectManager` may cancel a booked inspection that is still in
    `SCHEDULED` or `PARTIAL`, moving it to `CANCELLED` and returning the slot to the
    inspector's day so that the day's booked count falls back to exactly what it was before
    the booking."
    PRD §3.8: "New appointments are created in `SCHEDULED` with `result_notes` and
    `recorded_by_inspector_id` both null, and the booking consumes one of that inspector's
    slots on `slot_date`."

    Design: Difficulty/compensating_invariant/inspector_slot_capacity_conserved_on_cancel
    """
    ctx = setup_permitted_project(api)
    inspector = register_inspector(api, ctx["jurisdiction"]["id"],
                                   full_name="T. Alvarez", daily_capacity=2)
    phase = setup_scheduled_phase(api, ctx, "2026-09-01", "2026-09-05")

    before = availability(api, inspector["id"], "2026-09-02")
    assert before["remaining_slots"] == 2

    appointment = book_inspection(api, phase["id"], inspector["id"],
                                  inspection_type="FOUNDATION", slot_date="2026-09-02",
                                  slot_start="2026-09-02T09:00:00Z",
                                  slot_end="2026-09-02T10:00:00Z")
    assert appointment["result_notes"] is None
    assert appointment["recorded_by_inspector_id"] is None
    booked = availability(api, inspector["id"], "2026-09-02")
    assert booked["remaining_slots"] == 1

    cancelled = validate_success(
        api.cancel_inspection_appointment(appointment["id"], PROJECT_MANAGER))

    assert cancelled["status"] == "CANCELLED"
    after = availability(api, inspector["id"], "2026-09-02")
    assert_availability(after, inspector["id"], "2026-09-02", daily_capacity=2, booked_count=0)
    assert after["remaining_slots"] == before["remaining_slots"], "no slot may leak"


def test_cancelled_appointment_drops_out_of_the_scheduled_listing(api):
    """PRD §3.8: "Appointment listings may be narrowed by `adu_project_id`,
    `construction_phase_id`, `inspector_id`, `recorded_by_inspector_id`, `slot_date`, and
    `status`."
    PRD §3.1: "a `booked_count` counting only appointments still in `SCHEDULED` or `PARTIAL`,
    and the `remaining_slots` left over."

    Design: Difficulty/compensating_invariant/inspector_slot_capacity_conserved_on_cancel
    """
    ctx = setup_permitted_project(api)
    inspector = register_inspector(api, ctx["jurisdiction"]["id"],
                                   full_name="T. Alvarez", daily_capacity=2)
    phase = setup_scheduled_phase(api, ctx, "2026-09-01", "2026-09-05")
    appointment = book_inspection(api, phase["id"], inspector["id"],
                                  inspection_type="FOUNDATION", slot_date="2026-09-02",
                                  slot_start="2026-09-02T09:00:00Z",
                                  slot_end="2026-09-02T10:00:00Z")

    validate_success(api.cancel_inspection_appointment(appointment["id"], PROJECT_MANAGER))

    rows, meta = validate_paginated(api.list_inspection_appointments(
        PROJECT_MANAGER, {"inspector_id": inspector["id"], "slot_date": "2026-09-02",
                          "status": "SCHEDULED"}))
    assert meta["total_count"] == 0
    assert rows == []

    day = availability(api, inspector["id"], "2026-09-02")
    assert day["booked_count"] == 0
    assert day["remaining_slots"] == 2


def test_booking_against_an_inactive_inspector_is_rejected(api):
    """PRD §3.8: "Second, the inspector's `status` must be `ACTIVE`; booking against an
    `INACTIVE` inspector is rejected with `ERR_INSPECTOR_INACTIVE` (HTTP 409)."

    Design: Corner/errors/book_inspection_with_inactive_inspector_returns_inspector_inactive
    """
    ctx = setup_permitted_project(api)
    inspector = register_inspector(api, ctx["jurisdiction"]["id"],
                                   full_name="L. Petrov", status="INACTIVE")
    phase = setup_scheduled_phase(api, ctx, "2026-09-01", "2026-09-05")

    validate_error(api.create_inspection_appointment(
        phase["id"], inspection_appointment_payload(inspector["id"]), PROJECT_MANAGER),
        ApiErrorId.ERR_INSPECTOR_INACTIVE)

    rows, meta = validate_paginated(api.list_inspection_appointments(
        PROJECT_MANAGER, {"construction_phase_id": phase["id"]}))
    assert meta["total_count"] == 0
    assert availability(api, inspector["id"], "2026-09-03")["booked_count"] == 0


def test_final_slot_requires_the_final_certification(api):
    """PRD §3.8: "First, the inspector's `certifications` array must cover the requested
    `inspection_type`: a `FOUNDATION` or `FRAMING` inspection requires `STRUCTURAL`; a
    `ROUGH_MEP` inspection requires **both** `ELECTRICAL` and `PLUMBING`; an `INSULATION`
    inspection requires `ENVELOPE`; and a `FINAL` inspection requires `FINAL`. A gap is
    rejected with `ERR_INSPECTOR_NOT_CERTIFIED` (HTTP 409)."

    Design: Corner/errors/book_final_inspection_with_uncertified_inspector_rejected
    """
    ctx = setup_permitted_project(api)
    inspector = register_inspector(api, ctx["jurisdiction"]["id"], full_name="K. Ibarra",
                                   certifications=["STRUCTURAL"])
    phase = setup_scheduled_phase(api, ctx, "2026-09-01", "2026-09-05")

    structural = book_inspection(api, phase["id"], inspector["id"],
                                 inspection_type="FOUNDATION", slot_date="2026-09-03",
                                 slot_start="2026-09-03T09:00:00Z",
                                 slot_end="2026-09-03T10:00:00Z")
    assert structural["status"] == "SCHEDULED"

    validate_error(api.create_inspection_appointment(
        phase["id"], inspection_appointment_payload(
            inspector["id"], inspection_type="FINAL", slot_date="2026-09-04",
            slot_start="2026-09-04T09:00:00Z", slot_end="2026-09-04T10:00:00Z"),
        PROJECT_MANAGER),
        ApiErrorId.ERR_INSPECTOR_NOT_CERTIFIED)

    assert availability(api, inspector["id"], "2026-09-04")["booked_count"] == 0


def test_overlapping_slot_on_the_same_inspector_is_rejected(api):
    """PRD §3.8: "Third comes the slot conflict: the booking is rejected with
    `ERR_INSPECTOR_SLOT_CONFLICT` (HTTP 409) when any other appointment held by the same
    inspector with status `SCHEDULED` or `PARTIAL` overlaps the requested interval —
    concretely, when the requested `slot_start` is strictly earlier than that appointment's
    `slot_end` and that appointment's `slot_start` is strictly earlier than the requested
    `slot_end`."

    Design: Corner/errors/overlapping_inspector_slot_returns_slot_conflict
    """
    ctx = setup_permitted_project(api)
    inspector = register_inspector(api, ctx["jurisdiction"]["id"])
    phase = setup_scheduled_phase(api, ctx, "2026-09-01", "2026-09-05")
    held = book_inspection(api, phase["id"], inspector["id"], inspection_type="FOUNDATION",
                           slot_date="2026-09-03", slot_start="2026-09-03T09:00:00Z",
                           slot_end="2026-09-03T10:00:00Z")

    error = validate_error(api.create_inspection_appointment(
        phase["id"], inspection_appointment_payload(
            inspector["id"], inspection_type="FRAMING", slot_date="2026-09-03",
            slot_start="2026-09-03T09:30:00Z", slot_end="2026-09-03T10:30:00Z"),
        PROJECT_MANAGER),
        ApiErrorId.ERR_INSPECTOR_SLOT_CONFLICT)
    assert error["error_id"] != ApiErrorId.ERR_INSPECTOR_DAILY_CAPACITY_EXCEEDED.value, (
        "the inspector still has spare daily capacity; the intervals overlap")

    day = availability(api, inspector["id"], "2026-09-03")
    assert_availability(day, inspector["id"], "2026-09-03", daily_capacity=4, booked_count=1)
    assert validate_success(api.get_inspection_appointment(
        held["id"], PROJECT_MANAGER))["status"] == "SCHEDULED"
