"""The two reliability figures and the automatic probation cascade they gate."""

from test_helpers import (
    COORDINATOR_HEADERS,
    ERR_STAFF_MEMBER_NOT_ACTIVE,
    activate_plan,
    advance_event,
    assert_cents,
    assert_fields,
    assert_slot_fill,
    attendance,
    backfill_requests_for_assignment,
    certify,
    create_assignment,
    create_elevator_operator,
    create_event,
    create_member,
    create_plan,
    create_slot,
    create_ticket_taker,
    err,
    read_assignment,
    read_member,
    read_slot,
    set_clock,
)
from test_helpers.factories import staff_assignment_payload

SIX_WINDOWS = [
    ("Z101", "2026-09-08T10:00:00Z", "2026-09-08T12:00:00Z"),
    ("Z101", "2026-09-08T14:00:00Z", "2026-09-08T16:00:00Z"),
    ("Z101", "2026-09-09T10:00:00Z", "2026-09-09T12:00:00Z"),
    ("Z101", "2026-09-10T10:00:00Z", "2026-09-10T12:00:00Z"),
    ("Z101", "2026-09-11T10:00:00Z", "2026-09-11T12:00:00Z"),
    ("Z101", "2026-09-12T10:00:00Z", "2026-09-12T12:00:00Z"),
]


def _six_blocks_and_one_worker(client):
    """Six single-head blocks on five consecutive days, and one worker to fill them."""
    set_clock(client, "2026-09-07T08:00:00Z")
    event = create_event(
        client,
        name="Reliability Fixture",
        doors_open_at="2026-09-12T17:00:00Z",
        doors_close_at="2026-09-12T23:00:00Z",
        expected_attendance=20000,
    )
    position_type = create_ticket_taker(
        client,
        base_hourly_rate_cents=2000,
        attendance_ratio_per_1000=0.8,
        min_headcount=3,
        required_certifications=[],
    )
    plan = create_plan(client, event["id"])
    blocks = []
    for zone_code, shift_start, shift_end in SIX_WINDOWS:
        blocks.append(
            create_slot(
                client,
                plan["id"],
                position_type["id"],
                zone_code=zone_code,
                shift_start=shift_start,
                shift_end=shift_end,
                required_headcount_override=1,
            )
        )
    member = create_member(
        client,
        full_name="Mia Vance",
        employment_type="PART_TIME_EMPLOYEE",
        seniority_date="2024-03-01T00:00:00Z",
        hourly_rate_cents=2000,
        in_backfill_pool=True,
    )
    activate_plan(client, plan["id"], event["id"])
    advance_event(client, event["id"], "IN_PROGRESS")
    return {"event": event, "plan": plan, "blocks": blocks, "member": member}


def _work_a_block(client, member_id, block, check_in_at, checked_out_at):
    assignment = create_assignment(client, block["id"], member_id)
    attendance(client, assignment["id"], "CHECK_IN", at=check_in_at)
    attendance(client, assignment["id"], "CHECK_OUT", at=checked_out_at)
    return assignment


def _no_show_a_block(client, member_id, block):
    assignment = create_assignment(client, block["id"], member_id)
    attendance(client, assignment["id"], "NO_SHOW")
    return assignment


def _five_rows_then_a_sixth(client):
    """Three completions and two no-shows in place, with the earliest block still open."""
    context = _six_blocks_and_one_worker(client)
    member_id = context["member"]["id"]
    blocks = context["blocks"]

    context["worked_last"] = _work_a_block(
        client, member_id, blocks[5], "2026-09-07T08:00:00Z", "2026-09-07T10:00:00Z"
    )
    _work_a_block(client, member_id, blocks[4], "2026-09-07T10:00:00Z", "2026-09-07T12:00:00Z")
    _work_a_block(client, member_id, blocks[2], "2026-09-07T12:00:00Z", "2026-09-07T14:00:00Z")
    _no_show_a_block(client, member_id, blocks[3])
    _no_show_a_block(client, member_id, blocks[1])
    return context


def test_the_rolling_and_season_reliability_figures_diverge_on_identical_rows(client):
    """Six qualifying rows give 81 on the window and 34 across the season.

    "The two diverge on identical data: a worker whose three most recent rows are a
    no-show and two completions, and whose three older rows are two no-shows and a
    completion, scores 81 on the rolling figure and 34 on the season figure."

    Design: Difficulty/dual_variant_calc/reliability_rolling_window_vs_season_to_date
    """
    context = _five_rows_then_a_sixth(client)
    member_id = context["member"]["id"]

    _no_show_a_block(client, member_id, context["blocks"][0])

    member = read_member(client, member_id)
    assert_fields(
        member,
        reliability_score=81,
        season_reliability_score=34,
        no_show_strikes=3,
        completed_assignment_count=3,
    )
    assert member["reliability_score"] - member["season_reliability_score"] == 47, (
        "the window and the season figures must differ by exactly 47 points here"
    )


def test_only_the_rolling_figure_gates_probation_so_the_worker_stays_active(client):
    """The season figure sits 31 points under the floor and demotes nobody.

    "The `season_reliability_score` is not consulted for this gate, which is why the
    worker in the example above stays `ACTIVE` despite a season figure far below the
    floor."

    Design: Difficulty/dual_variant_calc/reliability_rolling_window_vs_season_to_date
    """
    context = _five_rows_then_a_sixth(client)
    member_id = context["member"]["id"]

    _no_show_a_block(client, member_id, context["blocks"][0])

    member = read_member(client, member_id)
    assert_fields(
        member,
        status="ACTIVE",
        in_backfill_pool=True,
        last_status_reason=None,
        season_reliability_score=34,
    )
    assert member["reliability_score"] >= 65, (
        "the rolling figure never fell below the probation floor, so no demotion is due"
    )


def test_older_no_shows_fall_out_of_the_window_but_never_out_of_the_season(client):
    """Three successive no-shows leave the window pinned at 81 while the season falls twice.

    "`reliability_score` applies that rule to the three most recent qualifying rows
    only, so older no-shows fall out of the window and stop hurting the worker."

    Design: Difficulty/dual_variant_calc/reliability_rolling_window_vs_season_to_date
    """
    context = _six_blocks_and_one_worker(client)
    member_id = context["member"]["id"]
    blocks = context["blocks"]

    worked_last = _work_a_block(
        client, member_id, blocks[5], "2026-09-07T08:00:00Z", "2026-09-07T10:00:00Z"
    )
    _work_a_block(client, member_id, blocks[4], "2026-09-07T10:00:00Z", "2026-09-07T12:00:00Z")
    _work_a_block(client, member_id, blocks[2], "2026-09-07T12:00:00Z", "2026-09-07T14:00:00Z")

    _no_show_a_block(client, member_id, blocks[3])
    assert_fields(
        read_member(client, member_id), reliability_score=81, season_reliability_score=84
    )
    _no_show_a_block(client, member_id, blocks[1])
    assert_fields(
        read_member(client, member_id), reliability_score=81, season_reliability_score=59
    )
    last = _no_show_a_block(client, member_id, blocks[0])
    assert_fields(
        read_member(client, member_id), reliability_score=81, season_reliability_score=34
    )

    worked = read_assignment(client, worked_last["id"])
    assert_fields(worked, late_check_in=False, worked_minutes=120, payout_status="ACCRUED")
    assert_cents(worked["base_pay_cents"], 4000, "base_pay_cents")
    assert_fields(
        read_assignment(client, last["id"]),
        attendance_status="NO_SHOW",
        payout_status="VOIDED",
    )


ELEVATOR_WINDOWS = [
    ("E101", "2026-09-12T10:00:00Z", "2026-09-12T12:00:00Z"),
    ("E102", "2026-09-12T13:00:00Z", "2026-09-12T15:00:00Z"),
    ("E103", "2026-09-12T16:00:00Z", "2026-09-12T18:00:00Z"),
]


def _one_strike_from_probation(client):
    """One elevator operator booked on three blocks, already carrying one strike."""
    set_clock(client, "2026-09-12T09:00:00Z")
    event = create_event(
        client,
        name="Cascade Depth Fixture",
        doors_open_at="2026-09-12T09:30:00Z",
        doors_close_at="2026-09-12T19:00:00Z",
        expected_attendance=40000,
    )
    position_type = create_elevator_operator(
        client,
        base_hourly_rate_cents=2600,
        attendance_ratio_per_1000=0.2,
        min_headcount=2,
        required_certifications=["ELEVATOR_OPERATION", "EVACUATION_PROCEDURES"],
    )
    plan = create_plan(client, event["id"])
    blocks = [
        create_slot(
            client,
            plan["id"],
            position_type["id"],
            zone_code=zone_code,
            shift_start=shift_start,
            shift_end=shift_end,
            required_headcount_override=1,
        )
        for zone_code, shift_start, shift_end in ELEVATOR_WINDOWS
    ]
    member = create_member(
        client,
        full_name="Mo Vance",
        employment_type="PART_TIME_EMPLOYEE",
        seniority_date="2023-05-01T00:00:00Z",
        hourly_rate_cents=2600,
        in_backfill_pool=True,
    )
    certify(client, member["id"], "ELEVATOR_OPERATION", "EVACUATION_PROCEDURES")
    activate_plan(client, plan["id"], event["id"])
    advance_event(client, event["id"], "IN_PROGRESS")
    assignments = [create_assignment(client, block["id"], member["id"]) for block in blocks]

    attendance(client, assignments[0]["id"], "NO_SHOW")
    assert_fields(
        read_member(client, member["id"]),
        status="ACTIVE",
        reliability_score=75,
        season_reliability_score=75,
    )
    return {
        "event": event,
        "plan": plan,
        "blocks": blocks,
        "member": member,
        "assignments": assignments,
    }


def test_a_second_no_show_voids_the_row_opens_a_backfill_and_moves_both_scores(client):
    """Links one to three of the no-show chain, in order.

    "The assignment moves `SCHEDULED → NO_SHOW`, its `payout_status` is driven
    `PENDING → VOIDED` and `total_payout_cents` is set to 0."

    Design: Difficulty/transitive_cascade/no_show_five_link_probation_cascade
    """
    context = _one_strike_from_probation(client)
    second = context["assignments"][1]

    row = attendance(client, second["id"], "NO_SHOW")
    assert_fields(row, attendance_status="NO_SHOW", payout_status="VOIDED")
    assert_cents(row["total_payout_cents"], 0, "total_payout_cents")

    assert_slot_fill(
        read_slot(client, context["blocks"][1]["id"]), filled=0, required=1, status="OPEN"
    )
    requests = backfill_requests_for_assignment(client, second["id"])
    assert len(requests) == 1, "one backfill request is opened against the emptied block"
    assert_fields(
        requests[0],
        status="OPEN",
        position_slot_id=context["blocks"][1]["id"],
        triggering_assignment_id=second["id"],
        attempt_count=0,
    )

    assert_fields(
        read_member(client, context["member"]["id"]),
        no_show_strikes=2,
        reliability_score=50,
        season_reliability_score=50,
    )


def test_the_demotion_cascades_into_the_workers_other_elevator_shift(client):
    """Links four and five: probation lands, and it cancels an untouched third block.

    "And finally, caused by that demotion, every *other* assignment of the same
    worker whose `attendance_status` is `SCHEDULED` and whose block belongs to a
    position family whose `required_certifications` include `ELEVATOR_OPERATION`
    moves to `CANCELLED` with `payout_status` driven to `VOIDED`, and each block
    touched by those cancellations has its `filled_headcount` decremented and its
    `status` re-derived."

    Design: Difficulty/transitive_cascade/no_show_five_link_probation_cascade
    """
    context = _one_strike_from_probation(client)

    attendance(client, context["assignments"][1]["id"], "NO_SHOW")

    assert_fields(
        read_member(client, context["member"]["id"]),
        status="PROBATION",
        in_backfill_pool=False,
        last_status_reason="AUTO_PROBATION_RELIABILITY",
    )
    third = read_assignment(client, context["assignments"][2]["id"])
    assert_fields(third, attendance_status="CANCELLED", payout_status="VOIDED")
    assert_slot_fill(
        read_slot(client, context["blocks"][2]["id"]), filled=0, required=1, status="OPEN"
    )


def test_the_cascaded_cancellation_opens_no_backfill_request_of_its_own(client):
    """The fifth link is quieter than the first: no request, and terminal rows are left alone.

    "From `SCHEDULED` it drives `payout_status` to `VOIDED`, decrements the block's
    `filled_headcount` and re-derives its `status`, and — unlike a no-show — opens no
    backfill request at all."

    Design: Difficulty/transitive_cascade/no_show_five_link_probation_cascade
    """
    context = _one_strike_from_probation(client)
    first, second, third = context["assignments"]

    attendance(client, second["id"], "NO_SHOW")

    assert backfill_requests_for_assignment(client, third["id"]) == [], (
        "a cascaded cancellation must not open a backfill request"
    )
    assert_fields(read_assignment(client, first["id"]), attendance_status="NO_SHOW")
    assert_slot_fill(
        read_slot(client, context["blocks"][0]["id"]), filled=0, required=1, status="OPEN"
    )

    err(
        client.create_staff_assignment(
            staff_assignment_payload(context["blocks"][2]["id"], context["member"]["id"]),
            COORDINATOR_HEADERS,
        ),
        ERR_STAFF_MEMBER_NOT_ACTIVE,
    )
