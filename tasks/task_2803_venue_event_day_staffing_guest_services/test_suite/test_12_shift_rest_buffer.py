"""The rest gap a worker must be given between two shift windows."""

from test_helpers import (
    COORDINATOR_HEADERS,
    ERR_SHIFT_REST_CONFLICT,
    advance_event,
    assert_fields,
    assert_slot_fill,
    activate_plan,
    create_assignment,
    create_event,
    create_member,
    create_plan,
    create_slot,
    create_ticket_taker,
    err,
    page,
    read_slot,
    set_clock,
)
from test_helpers.factories import staff_assignment_payload

WINDOWS = {
    # The existing shift.
    "a": ("A100", "2026-09-12T16:00:00Z", "2026-09-12T20:00:00Z"),
    # 29 minutes after the existing shift ends.
    "b": ("A200", "2026-09-12T20:29:00Z", "2026-09-12T23:00:00Z"),
    # Exactly 30 minutes after the existing shift ends.
    "c": ("A300", "2026-09-12T20:30:00Z", "2026-09-12T23:00:00Z"),
    # Ends 29 minutes before the existing shift starts.
    "d": ("A400", "2026-09-12T12:00:00Z", "2026-09-12T15:31:00Z"),
}


def _four_windows_and_one_worker(client):
    """One worker already booked on block A, with B, C and D standing empty."""
    set_clock(client, "2026-09-12T15:00:00Z")
    event = create_event(
        client,
        name="Rest Buffer Fixture",
        doors_open_at="2026-09-12T11:30:00Z",
        doors_close_at="2026-09-12T23:30:00Z",
        expected_attendance=20000,
    )
    position_type = create_ticket_taker(client, required_certifications=[])
    plan = create_plan(client, event["id"])
    slots = {}
    for key, (zone_code, shift_start, shift_end) in WINDOWS.items():
        slots[key] = create_slot(
            client,
            plan["id"],
            position_type["id"],
            zone_code=zone_code,
            shift_start=shift_start,
            shift_end=shift_end,
            required_headcount_override=1,
        )
    activate_plan(client, plan["id"], event["id"])
    advance_event(client, event["id"], "IN_PROGRESS")
    member = create_member(
        client,
        full_name="Eve Marsh",
        employment_type="PART_TIME_EMPLOYEE",
        seniority_date="2024-01-01T00:00:00Z",
        hourly_rate_cents=2000,
    )
    booked = create_assignment(client, slots["a"]["id"], member["id"])
    return {"event": event, "slots": slots, "member": member, "assignment": booked}


def _try_assign(client, slot_id, member_id):
    return client.create_staff_assignment(
        staff_assignment_payload(slot_id, member_id), COORDINATOR_HEADERS
    )


def test_a_trailing_gap_of_twenty_nine_minutes_is_refused(client):
    """A block starting 29 minutes after the worker's shift ends breaks the buffer.

    "The worker must observe the rest buffer: no other non-terminal assignment of
    theirs may have a shift window that comes within 30 minutes of the target
    block's window, where a gap of exactly 30 minutes is accepted and a gap of 29
    minutes is refused with `ERR_SHIFT_REST_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/shift_rest_buffer_exact_30_minute_gap
    """
    context = _four_windows_and_one_worker(client)

    err(
        _try_assign(client, context["slots"]["b"]["id"], context["member"]["id"]),
        ERR_SHIFT_REST_CONFLICT,
    )

    # The refusal is temporal: block B is empty and holds no row for this worker.
    assert_slot_fill(
        read_slot(client, context["slots"]["b"]["id"]),
        filled=0,
        required=1,
        status="OPEN",
    )


def test_a_leading_gap_of_twenty_nine_minutes_is_refused_too(client):
    """The buffer is symmetric: a block ending 29 minutes before the shift also breaks it.

    "The worker must observe the rest buffer: no other non-terminal assignment of
    theirs may have a shift window that comes within 30 minutes of the target
    block's window, where a gap of exactly 30 minutes is accepted and a gap of 29
    minutes is refused with `ERR_SHIFT_REST_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/shift_rest_buffer_exact_30_minute_gap
    """
    context = _four_windows_and_one_worker(client)

    err(
        _try_assign(client, context["slots"]["d"]["id"], context["member"]["id"]),
        ERR_SHIFT_REST_CONFLICT,
    )

    assert_slot_fill(
        read_slot(client, context["slots"]["d"]["id"]),
        filled=0,
        required=1,
        status="OPEN",
    )


def test_a_gap_of_exactly_thirty_minutes_is_accepted(client):
    """The buffer boundary is inclusive, so the 20:30 block is bookable.

    "The worker must observe the rest buffer: no other non-terminal assignment of
    theirs may have a shift window that comes within 30 minutes of the target
    block's window, where a gap of exactly 30 minutes is accepted and a gap of 29
    minutes is refused with `ERR_SHIFT_REST_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/shift_rest_buffer_exact_30_minute_gap
    """
    context = _four_windows_and_one_worker(client)
    member_id = context["member"]["id"]

    err(_try_assign(client, context["slots"]["b"]["id"], member_id), ERR_SHIFT_REST_CONFLICT)
    err(_try_assign(client, context["slots"]["d"]["id"], member_id), ERR_SHIFT_REST_CONFLICT)

    accepted = create_assignment(client, context["slots"]["c"]["id"], member_id)
    assert_fields(accepted, attendance_status="SCHEDULED", source="MANUAL")

    assert_slot_fill(
        read_slot(client, context["slots"]["c"]["id"]),
        filled=1,
        required=1,
        status="FILLED",
    )
    assert_slot_fill(
        read_slot(client, context["slots"]["a"]["id"]),
        filled=1,
        required=1,
        status="FILLED",
    )

    rows, meta = page(
        client.list_staff_assignments(COORDINATOR_HEADERS, {"staff_member_id": member_id})
    )
    assert meta["total_count"] == 2, "only the 16:00 and the 20:30 blocks were booked"
    assert {row["position_slot_id"] for row in rows} == {
        context["slots"]["a"]["id"],
        context["slots"]["c"]["id"],
    }
    for row in rows:
        assert_fields(row, attendance_status="SCHEDULED", source="MANUAL")
