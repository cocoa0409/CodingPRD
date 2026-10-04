"""Consult booking: start-to-start geometry, weekly capacity and slot reuse.

Covers the two independent timeline constraints on a clinician's calendar — the
pairwise start-to-start buffer and the weekly aggregate minute cap — plus the
release of a cancelled slot, and the clinician-state guard that blocks a booking
against a clinician who is no longer live.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    CLINICAL_OPS,
    ENROLLMENT_OPS,
    book_appointment,
    get_success_data,
    setup_scenario,
    validate_error,
    validate_success,
)

APPOINTMENT_DAY = "2026-09-08T00:00:00Z"
NEXT_DAY = "2026-09-09T00:00:00Z"


def _active_with_clinicians(**kwargs):
    return setup_scenario(acute_fee=9000, activate=True, add_clinicians=True, **kwargs)


# ══════════════════════════════════════════════════════════════════
# Start-to-start geometry
# ══════════════════════════════════════════════════════════════════

def test_booking_inside_the_start_to_start_buffer_is_refused(api, clinical_ops_headers):
    """PRD §3.4: "Geometry works on a 60-minute grid and is a start-to-start rule:
    two slots occupied on one clinician's day may not start less than 60 minutes
    apart, and no single complete 60-minute block may be occupied twice in one day."
    PRD §3.4: "A consult that violates either limb is refused with
    `ERR_APPOINTMENT_OVERLAP` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/appointment_start_to_start_buffer_rejects_adjacent_booking
    """
    scenario = _active_with_clinicians()
    enrollment_id = scenario["enrollment_id"]
    dana_id = scenario["dana_id"]

    first = book_appointment(enrollment_id, dana_id, appointment_date=APPOINTMENT_DAY,
                             start_minute=540, duration_minutes=30,
                             slot_type="INITIAL_CONSULT")
    assert first["start_minute"] == 540
    assert first["duration_minutes"] == 30

    refused = api.create_appointment({
        "enrollment_id": enrollment_id,
        "clinician_id": dana_id,
        "appointment_date": APPOINTMENT_DAY,
        "start_minute": 585,
        "duration_minutes": 60,
        "slot_type": "FOLLOW_UP",
    }, ENROLLMENT_OPS)
    validate_error(refused, ApiErrorId.ERR_APPOINTMENT_OVERLAP, expected_status=422)

    scheduled = get_success_data(api.list_appointments(
        ENROLLMENT_OPS, {"clinician_id": dana_id}))
    assert len(scheduled) == 1, (
        "the 09:00 consult runs 540 to 570 and the refused one was to start at 585, "
        "so the intervals are disjoint: the rejection came from the 45-minute "
        "start-to-start gap, not from intersection"
    )

    accepted = api.create_appointment({
        "enrollment_id": enrollment_id,
        "clinician_id": dana_id,
        "appointment_date": APPOINTMENT_DAY,
        "start_minute": 600,
        "duration_minutes": 60,
        "slot_type": "FOLLOW_UP",
    }, ENROLLMENT_OPS)
    assert accepted.status_code == 201, "the buffer boundary sits at exactly 60 minutes"


def test_a_booking_exactly_sixty_minutes_after_is_accepted(api, clinical_ops_headers):
    """PRD §3.4: "two slots occupied on one clinician's day may not start less than
    60 minutes apart".
    PRD §3.4: "its `appointment_status` tracks the consult's own lifecycle
    independently of the clinician's availability".

    Design: Difficulty/resource_temporal_overlap/appointment_start_to_start_buffer_rejects_adjacent_booking
    """
    scenario = _active_with_clinicians()
    enrollment_id = scenario["enrollment_id"]
    dana_id = scenario["dana_id"]

    first = book_appointment(enrollment_id, dana_id, appointment_date=APPOINTMENT_DAY,
                             start_minute=540, duration_minutes=30,
                             slot_type="INITIAL_CONSULT")
    second = validate_success(api.create_appointment({
        "enrollment_id": enrollment_id,
        "clinician_id": dana_id,
        "appointment_date": APPOINTMENT_DAY,
        "start_minute": 600,
        "duration_minutes": 30,
        "slot_type": "FOLLOW_UP",
    }, ENROLLMENT_OPS), expected_status=201)

    assert second["start_minute"] - first["start_minute"] == 60, (
        "a gap of exactly 60 minutes clears the buffer"
    )
    assert second["appointment_status"] == "SCHEDULED"
    assert second["cancelled_at"] is None

    scheduled = get_success_data(api.list_appointments(
        ENROLLMENT_OPS, {"clinician_id": dana_id}))
    assert len(scheduled) == 2


def test_a_cancelled_consult_releases_both_its_slot_and_its_buffer(api, clinical_ops_headers):
    """PRD §3.4: "A consult may instead be cancelled, either by the conducting
    `Clinician` or by an `EnrollmentOps` operator, from `SCHEDULED` only;
    cancellation stamps `cancelled_at`, increments the affected enrollment's
    `consult_cancellation_count`, and advances both versions."
    PRD §3.4: "two slots occupied on one clinician's day may not start less than
    60 minutes apart".

    Design: Corner/endpoints/dismissing_the_review_seats_are_reusable_the_next_day
    """
    scenario = _active_with_clinicians()
    enrollment_id = scenario["enrollment_id"]
    dana_id = scenario["dana_id"]

    held = book_appointment(enrollment_id, dana_id, appointment_date=APPOINTMENT_DAY,
                            start_minute=540, duration_minutes=30,
                            slot_type="INITIAL_CONSULT")

    refused = api.create_appointment({
        "enrollment_id": enrollment_id,
        "clinician_id": dana_id,
        "appointment_date": APPOINTMENT_DAY,
        "start_minute": 585,
        "duration_minutes": 30,
        "slot_type": "FOLLOW_UP",
    }, ENROLLMENT_OPS)
    validate_error(refused, ApiErrorId.ERR_APPOINTMENT_OVERLAP, expected_status=422)

    cancelled = validate_success(api.cancel_appointment(held["id"], ENROLLMENT_OPS))
    assert cancelled["appointment_status"] == "CANCELLED"
    assert cancelled["cancelled_at"] is not None

    rebooked = api.create_appointment({
        "enrollment_id": enrollment_id,
        "clinician_id": dana_id,
        "appointment_date": APPOINTMENT_DAY,
        "start_minute": 540,
        "duration_minutes": 30,
        "slot_type": "FOLLOW_UP",
    }, ENROLLMENT_OPS)
    assert rebooked.status_code == 201, (
        "cancelling released both the slot and the buffer"
    )

    enrollment = get_success_data(api.get_enrollment(enrollment_id, ENROLLMENT_OPS))
    assert enrollment["consult_cancellation_count"] == 1


def test_a_consult_and_its_clinician_hold_separate_state_fields(api, clinical_ops_headers):
    """PRD §3.4: "a consult and the clinician who conducts it hold separate state
    fields with separate version counters, and a consult is not reverted when its
    clinician is merely limited."
    PRD §3.4: "a clinician may be limited and restored freely".
    PRD §3.4: "A newly registered clinician is `AVAILABLE` with
    `weekly_completed_minutes` at zero".

    Design: Corner/entities/program_track_carries_only_identity_and_created_at
    """
    scenario = _active_with_clinicians()
    enrollment_id = scenario["enrollment_id"]
    dana_id = scenario["dana_id"]

    appointment = book_appointment(enrollment_id, dana_id, appointment_date=APPOINTMENT_DAY,
                                   start_minute=540, duration_minutes=60,
                                   slot_type="INITIAL_CONSULT")

    limited = validate_success(api.limit_clinician(dana_id, clinical_ops_headers))
    assert limited["clinician_status"] == "LIMITED"

    unaffected = get_success_data(api.get_appointment(appointment["id"], ENROLLMENT_OPS))
    assert unaffected["appointment_status"] == "SCHEDULED", (
        "a consult is not reverted when its clinician is merely limited"
    )

    restored = validate_success(api.restore_clinician(dana_id, clinical_ops_headers))
    assert restored["clinician_status"] == "AVAILABLE"
    assert restored["weekly_completed_minutes"] == 0


# ══════════════════════════════════════════════════════════════════
# Weekly aggregate capacity
# ══════════════════════════════════════════════════════════════════

def test_the_weekly_minute_cap_rejects_the_consult_past_the_cap(api, clinical_ops_headers):
    """PRD §3.4: "Capacity is a weekly aggregate: the sum of `duration_minutes`
    over the clinician's `SCHEDULED` and `COMPLETED` consults in one ISO week may
    not exceed `weekly_capacity_slots` multiplied by 60 minutes, and a booking
    that lands exactly on that cap is permitted rather than refused."
    PRD §3.4: "A booking that would push the clinician past the cap is refused with
    `ERR_CLINICIAN_CAPACITY_EXCEEDED` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/clinician_weekly_capacity_aggregate_cap_rejects_excess_minutes
    """
    scenario = _active_with_clinicians(leo_capacity_slots=2)
    enrollment_id = scenario["enrollment_id"]
    leo_id = scenario["leo_id"]

    accepted = [
        book_appointment(enrollment_id, leo_id, appointment_date=APPOINTMENT_DAY,
                         start_minute=start, duration_minutes=40,
                         slot_type="INITIAL_CONSULT" if start == 540 else "FOLLOW_UP")
        for start in (540, 600, 660)
    ]
    assert len(accepted) == 3
    assert sum(a["duration_minutes"] for a in accepted) == 120, (
        "three 40-minute consults land exactly on the cap of weekly_capacity_slots 2 "
        "times 60 minutes, which is permitted"
    )

    refused = api.create_appointment({
        "enrollment_id": enrollment_id,
        "clinician_id": leo_id,
        "appointment_date": APPOINTMENT_DAY,
        "start_minute": 720,
        "duration_minutes": 40,
        "slot_type": "FOLLOW_UP",
    }, ENROLLMENT_OPS)
    validate_error(refused, ApiErrorId.ERR_CLINICIAN_CAPACITY_EXCEEDED, expected_status=422)


def test_the_capacity_cap_is_a_weekly_aggregate_not_a_daily_one(api, clinical_ops_headers):
    """PRD §3.4: "Capacity is a weekly aggregate: the sum of `duration_minutes`
    over the clinician's `SCHEDULED` and `COMPLETED` consults in one ISO week may
    not exceed `weekly_capacity_slots` multiplied by 60 minutes".
    PRD §3.4: "`weekly_completed_minutes` is the sum of `duration_minutes` over
    completed consults in the current ISO week, and `weekly_scheduled_minutes` is
    the sum over both scheduled and completed consults in the current ISO week."

    Design: Difficulty/resource_temporal_overlap/clinician_weekly_capacity_aggregate_cap_rejects_excess_minutes
    """
    scenario = _active_with_clinicians(leo_capacity_slots=2)
    enrollment_id = scenario["enrollment_id"]
    leo_id = scenario["leo_id"]

    accepted = [
        book_appointment(enrollment_id, leo_id, appointment_date=APPOINTMENT_DAY,
                         start_minute=start, duration_minutes=40,
                         slot_type="INITIAL_CONSULT" if start == 540 else "FOLLOW_UP")
        for start in (540, 600, 660)
    ]

    # The next day is inside the same ISO week, so the aggregate is unchanged.
    refused_next_day = api.create_appointment({
        "enrollment_id": enrollment_id,
        "clinician_id": leo_id,
        "appointment_date": NEXT_DAY,
        "start_minute": 540,
        "duration_minutes": 40,
        "slot_type": "FOLLOW_UP",
    }, ENROLLMENT_OPS)
    validate_error(refused_next_day, ApiErrorId.ERR_CLINICIAN_CAPACITY_EXCEEDED,
                   expected_status=422)

    clinician = get_success_data(api.get_clinician(leo_id, CLINICAL_OPS))
    assert clinician["weekly_scheduled_minutes"] == 120, (
        "the aggregate is what blocked the refusal: no two of the accepted consults "
        "intersect geometrically, since each pair is separated by 60 minutes"
    )

    for appointment in accepted:
        validate_success(api.cancel_appointment(appointment["id"], ENROLLMENT_OPS))

    deactivated = validate_success(api.deactivate_clinician(leo_id, clinical_ops_headers))
    assert deactivated["clinician_status"] == "DEACTIVATED"
    assert get_success_data(api.get_clinician(leo_id, CLINICAL_OPS))["clinician_status"] == (
        "DEACTIVATED"
    )


def test_completing_a_consult_requires_its_start_to_have_arrived(api, clinical_ops_headers):
    """PRD §3.4: "completion requires the consult to be `SCHEDULED` and requires
    the appointment's start instant to be at or before the current logical clock
    instant — a consult whose start has not yet arrived cannot be marked complete."

    Design: Difficulty/resource_temporal_overlap/appointment_start_to_start_buffer_rejects_adjacent_booking
    """
    # Second translation of the same instance: the start-to-start geometry that
    # governs which consults exist also governs when one may be closed out.
    scenario = _active_with_clinicians()
    enrollment_id = scenario["enrollment_id"]
    dana_id = scenario["dana_id"]

    appointment = book_appointment(enrollment_id, dana_id, appointment_date=APPOINTMENT_DAY,
                                   start_minute=540, duration_minutes=30,
                                   slot_type="INITIAL_CONSULT")

    from test_helpers import make_clinician_headers
    refused = api.complete_appointment(appointment["id"], make_clinician_headers(dana_id))
    assert refused.status_code >= 400, (
        "the clock sits at 2026-09-01, before the 2026-09-08 start instant"
    )
    assert refused.json()["response_type"] == "error"

    unchanged = get_success_data(api.get_appointment(appointment["id"], ENROLLMENT_OPS))
    assert unchanged["appointment_status"] == "SCHEDULED"