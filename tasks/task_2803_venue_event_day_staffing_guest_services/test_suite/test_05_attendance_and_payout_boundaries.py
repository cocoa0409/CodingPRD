"""Worked-minute pricing around the eight-hour overtime threshold.

Every worker in this module is paid 2600 cents an hour, which is the rate the
contract itself uses to state the expected answers on both sides of the split.
"""

from test_helpers import (
    assert_cents,
    assert_fields,
    assert_payout_totals,
    assert_slot_fill,
    attendance,
    create_assignment,
    create_member,
    event_in_progress_with_slot,
    read_assignment,
    read_member,
    read_slot,
    set_clock,
)
from test_helpers.factories import ticket_taker_payload

CLOCK = "2026-09-12T07:45:00Z"
SHIFT_START = "2026-09-12T08:00:00Z"
SHIFT_END = "2026-09-12T16:00:00Z"
RATE = 2600


def _three_head_block(client):
    """An IN_PROGRESS event whose single 08:00-16:00 block needs three heads."""
    set_clock(client, CLOCK)
    return event_in_progress_with_slot(
        client,
        position_type_payload=ticket_taker_payload(required_certifications=[]),
        slot_overrides={
            "zone_code": "Z810",
            "shift_start": SHIFT_START,
            "shift_end": SHIFT_END,
            "required_headcount_override": 3,
        },
        name="Overtime Boundary Fixture",
        doors_open_at="2026-09-12T07:30:00Z",
        doors_close_at="2026-09-12T17:00:00Z",
        expected_attendance=20000,
    )


def _worker(client, name, seniority):
    return create_member(
        client,
        full_name=name,
        employment_type="PART_TIME_EMPLOYEE",
        seniority_date=seniority,
        hourly_rate_cents=RATE,
    )


def test_worked_minutes_priced_below_at_and_above_the_eight_hour_threshold(client):
    """479, 480 and 481 worked minutes on one block are priced from three separate splits.

    "Minutes are split at an eight-hour threshold: the regular portion is the
    worked minutes or 480, whichever is smaller, and the overtime portion is
    whatever the worked minutes exceed 480 by, or nothing when they do not
    exceed it."

    Design: Difficulty/boundary_precision_check/overtime_threshold_exact_480_worked_minutes
    """
    context = _three_head_block(client)
    slot_id = context["slot"]["id"]

    m1 = _worker(client, "Tam Ellis", "2024-01-01T00:00:00Z")
    m2 = _worker(client, "Uma Deng", "2024-02-01T00:00:00Z")
    m3 = _worker(client, "Vic Roan", "2024-03-01T00:00:00Z")

    a1 = create_assignment(client, slot_id, m1["id"])
    a2 = create_assignment(client, slot_id, m2["id"])
    a3 = create_assignment(client, slot_id, m3["id"])

    for assignment in (a1, a2, a3):
        attendance(client, assignment["id"], "CHECK_IN", at=SHIFT_START)

    # One minute short of the threshold: 479 * 2600 / 60 = 20756.6667 -> 20757.
    short = attendance(client, a3["id"], "CHECK_OUT", at="2026-09-12T15:59:00Z")
    assert_fields(short, worked_minutes=479)
    assert_cents(short["base_pay_cents"], 20757, "base_pay_cents at 479 minutes")

    # Exactly at the threshold: no overtime component at all.
    exact = attendance(client, a1["id"], "CHECK_OUT", at="2026-09-12T16:00:00Z")
    assert_fields(exact, worked_minutes=480)
    assert_cents(exact["base_pay_cents"], 20800, "base_pay_cents at 480 minutes")

    # One minute past it: 20800 regular plus a separately rounded 65 overtime.
    over = attendance(client, a2["id"], "CHECK_OUT", at="2026-09-12T16:01:00Z")
    assert_fields(over, worked_minutes=481)
    assert_cents(over["base_pay_cents"], 20865, "base_pay_cents at 481 minutes")


def test_overtime_component_is_quantized_separately_from_the_regular_component(client):
    """The two pay components are rounded on their own, never as one blended total.

    "`base_pay_cents` is the sum of those two already-rounded components — the
    blended total is never rounded once — and `total_payout_cents` is
    `base_pay_cents` plus `gratuity_cents`, which is still zero at this point."

    Design: Difficulty/boundary_precision_check/overtime_threshold_exact_480_worked_minutes
    """
    context = _three_head_block(client)
    slot_id = context["slot"]["id"]

    m1 = _worker(client, "Tam Ellis", "2024-01-01T00:00:00Z")
    m2 = _worker(client, "Uma Deng", "2024-02-01T00:00:00Z")

    a1 = create_assignment(client, slot_id, m1["id"])
    a2 = create_assignment(client, slot_id, m2["id"])
    attendance(client, a1["id"], "CHECK_IN", at=SHIFT_START)
    attendance(client, a2["id"], "CHECK_IN", at=SHIFT_START)

    at_threshold = attendance(client, a1["id"], "CHECK_OUT", at="2026-09-12T16:00:00Z")
    past_threshold = attendance(client, a2["id"], "CHECK_OUT", at="2026-09-12T16:01:00Z")

    # 481 minutes blended in one quantization would round 20864.9999... to 20865
    # only by accident; the contract's arithmetic is 20800 + 65.
    assert_cents(at_threshold["base_pay_cents"], 20800, "480 minutes")
    assert_cents(past_threshold["base_pay_cents"], 20865, "481 minutes")
    assert past_threshold["base_pay_cents"] - at_threshold["base_pay_cents"] == 65, (
        "the single overtime minute must be worth its own separately rounded 65 cents"
    )
    assert_payout_totals(past_threshold, base=20865, gratuity=0, total=20865)
    assert_payout_totals(at_threshold, base=20800, gratuity=0, total=20800)


def test_completed_shifts_still_count_as_filled_and_accrue_without_penalty(client):
    """Checking out accrues the money, credits the worker and leaves the block full.

    "In the same request the `payout_status` moves `PENDING → ACCRUED`, freezing
    `base_pay_cents` and `total_payout_cents` at their computed values, the
    worker's `completed_assignment_count` is incremented by 1, and both of the
    worker's reliability figures are recomputed."

    Design: Difficulty/boundary_precision_check/overtime_threshold_exact_480_worked_minutes
    """
    context = _three_head_block(client)
    slot_id = context["slot"]["id"]

    members = [
        _worker(client, "Tam Ellis", "2024-01-01T00:00:00Z"),
        _worker(client, "Uma Deng", "2024-02-01T00:00:00Z"),
        _worker(client, "Vic Roan", "2024-03-01T00:00:00Z"),
    ]
    assignments = [create_assignment(client, slot_id, m["id"]) for m in members]
    for assignment in assignments:
        attendance(client, assignment["id"], "CHECK_IN", at=SHIFT_START)

    attendance(client, assignments[2]["id"], "CHECK_OUT", at="2026-09-12T15:59:00Z")
    attendance(client, assignments[0]["id"], "CHECK_OUT", at="2026-09-12T16:00:00Z")
    attendance(client, assignments[1]["id"], "CHECK_OUT", at="2026-09-12T16:01:00Z")

    for assignment in assignments:
        row = read_assignment(client, assignment["id"])
        assert_fields(
            row,
            attendance_status="COMPLETED",
            payout_status="ACCRUED",
            late_check_in=False,
        )
        assert_payout_totals(
            row,
            base=row["base_pay_cents"],
            gratuity=0,
            total=row["base_pay_cents"],
        )

    # A completed shift is still a filled head, so the block stays FILLED.
    assert_slot_fill(read_slot(client, slot_id), filled=3, required=3, status="FILLED")

    for member in members:
        row = read_member(client, member["id"])
        assert_fields(
            row,
            completed_assignment_count=1,
            reliability_score=100,
            season_reliability_score=100,
            no_show_strikes=0,
        )
