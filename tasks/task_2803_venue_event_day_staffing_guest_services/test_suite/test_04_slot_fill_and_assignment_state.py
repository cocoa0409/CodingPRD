"""Derived block fill state and the two independent dimensions of an assignment."""

from test_helpers import (
    COORDINATOR_HEADERS,
    ERR_CERTIFICATION_MISSING,
    ERR_DUPLICATE_ASSIGNMENT,
    ERR_SHIFT_REST_CONFLICT,
    ERR_SLOT_CAPACITY_FULL,
    activate_plan,
    assert_cents,
    assert_fields,
    assert_instant,
    assert_payout_totals,
    assert_slot_fill,
    attendance,
    advance_event,
    certified_member,
    certify,
    create_assignment,
    create_event,
    create_member,
    create_plan,
    create_slot,
    create_ticket_taker,
    create_usher,
    err,
    event_in_progress_with_slot,
    page,
    read_assignment,
    read_event,
    read_member,
    read_slot,
    run_payout,
    set_clock,
)
from test_helpers.factories import (
    guest_services_rep_payload,
    staff_assignment_payload,
    ticket_taker_payload,
)


def _two_head_block_and_three_workers(client):
    """An empty two-head block with three unbooked workers standing by."""
    set_clock(client, "2026-09-12T17:30:00Z")
    context = event_in_progress_with_slot(
        client,
        position_type_payload=ticket_taker_payload(
            base_hourly_rate_cents=2000,
            attendance_ratio_per_1000=0.8,
            min_headcount=3,
            required_certifications=[],
        ),
        slot_overrides={
            "zone_code": "Z140",
            "shift_start": "2026-09-12T18:00:00Z",
            "shift_end": "2026-09-12T22:00:00Z",
            "required_headcount_override": 2,
        },
        name="Slot Cycle Fixture",
        doors_open_at="2026-09-12T17:00:00Z",
        doors_close_at="2026-09-12T23:00:00Z",
        expected_attendance=20000,
    )
    context["members"] = [
        create_member(
            client,
            full_name=full_name,
            employment_type="PART_TIME_EMPLOYEE",
            seniority_date=seniority_date,
            hourly_rate_cents=2000,
        )
        for full_name, seniority_date in (
            ("Ana One", "2024-01-10T00:00:00Z"),
            ("Bo Two", "2024-02-10T00:00:00Z"),
            ("Cy Three", "2024-03-10T00:00:00Z"),
        )
    ]
    return context


def test_the_block_walks_open_to_partially_filled_to_filled_as_heads_arrive(client):
    """Fill state is a pure function of the head count, not a latched pipeline stage.

    "Outside the two explicit states `CLOSED` and `UNDERSTAFFED_ESCALATED`, a shift
    block's `status` is a pure function of `filled_headcount` against
    `required_headcount`: zero filled is `OPEN`, more than zero but fewer than
    required is `PARTIALLY_FILLED`, and at or above required is `FILLED`."

    Design: Difficulty/non_linear_state_machine/position_slot_fill_release_cycle
    """
    context = _two_head_block_and_three_workers(client)
    slot_id = context["slot"]["id"]
    first, second, _third = context["members"]

    assert_slot_fill(read_slot(client, slot_id), filled=0, required=2, status="OPEN")

    create_assignment(client, slot_id, first["id"])
    assert_slot_fill(
        read_slot(client, slot_id), filled=1, required=2, status="PARTIALLY_FILLED"
    )

    create_assignment(client, slot_id, second["id"])
    assert_slot_fill(read_slot(client, slot_id), filled=2, required=2, status="FILLED")


def test_releases_drive_the_block_backwards_through_partially_filled_to_open(client):
    """Two backward arcs the derivation reaches and a forward-only pipeline cannot.

    "Releasing a worker from a shift is the deliberate counterpart and is far
    quieter. The assignment moves `SCHEDULED → RELEASED`, its `payout_status` is
    driven to `VOIDED` and `total_payout_cents` is set to 0, and the block's
    `filled_headcount` is decremented and its `status` re-derived, restoring the
    invariant that `filled_headcount` equals the count of assignments in
    `SCHEDULED`, `CHECKED_IN` or `COMPLETED`."

    Design: Difficulty/non_linear_state_machine/position_slot_fill_release_cycle
    """
    context = _two_head_block_and_three_workers(client)
    slot_id = context["slot"]["id"]
    first, second, _third = context["members"]

    first_assignment = create_assignment(client, slot_id, first["id"])
    second_assignment = create_assignment(client, slot_id, second["id"])

    released = attendance(client, second_assignment["id"], "RELEASE")
    assert_fields(released, attendance_status="RELEASED", payout_status="VOIDED")
    assert_cents(released["total_payout_cents"], 0, "total_payout_cents")
    assert_slot_fill(
        read_slot(client, slot_id), filled=1, required=2, status="PARTIALLY_FILLED"
    )

    attendance(client, first_assignment["id"], "RELEASE")
    assert_slot_fill(read_slot(client, slot_id), filled=0, required=2, status="OPEN")

    assert_fields(
        read_member(client, first["id"]),
        reliability_score=100,
        season_reliability_score=100,
        no_show_strikes=0,
    )


def test_the_block_re_enters_partially_filled_a_third_time_without_resizing(client):
    """A fresh head after two releases reopens the same derived state as at the start.

    "Wherever a rule below says a slot's status is \"re-derived\", it means exactly
    this function is re-applied."

    Design: Difficulty/non_linear_state_machine/position_slot_fill_release_cycle
    """
    context = _two_head_block_and_three_workers(client)
    slot_id = context["slot"]["id"]
    first, second, third = context["members"]

    first_assignment = create_assignment(client, slot_id, first["id"])
    second_assignment = create_assignment(client, slot_id, second["id"])
    attendance(client, second_assignment["id"], "RELEASE")
    attendance(client, first_assignment["id"], "RELEASE")

    create_assignment(client, slot_id, third["id"])

    slot = read_slot(client, slot_id)
    assert_slot_fill(slot, filled=1, required=2, status="PARTIALLY_FILLED")
    assert_fields(slot, required_headcount=2, ratio_derived_headcount=18)


def _tip_eligible_completed_shift(client):
    """One contracted worker who has clocked a full four-hour tip-eligible shift."""
    set_clock(client, "2026-09-12T17:00:00Z")
    context = event_in_progress_with_slot(
        client,
        position_type_payload=guest_services_rep_payload(
            base_hourly_rate_cents=2400,
            attendance_ratio_per_1000=0.35,
            min_headcount=2,
            required_certifications=["CODE_OF_CONDUCT"],
            is_tip_eligible=True,
            is_contracted_position=True,
        ),
        slot_overrides={
            "zone_code": "Z150",
            "shift_start": "2026-09-12T18:00:00Z",
            "shift_end": "2026-09-12T22:00:00Z",
            "required_headcount_override": 1,
        },
        name="Payout Dimension Fixture",
        doors_open_at="2026-09-12T17:00:00Z",
        doors_close_at="2026-09-12T23:00:00Z",
        expected_attendance=20000,
        gratuity_pool_cents=50000,
    )
    member = certified_member(
        client,
        "CODE_OF_CONDUCT",
        full_name="Dot Reyes",
        employment_type="CONTRACTED",
        seniority_date="2022-11-01T00:00:00Z",
        hourly_rate_cents=2400,
    )
    context["member"] = member
    context["assignment"] = create_assignment(client, context["slot"]["id"], member["id"])
    return context


def test_checking_in_moves_attendance_alone_and_checking_out_moves_both(client):
    """One row, two dimensions: the payout side does not stir until the shift ends.

    "In the same request the `payout_status` moves `PENDING → ACCRUED`, freezing
    `base_pay_cents` and `total_payout_cents` at their computed values, the worker's
    `completed_assignment_count` is incremented by 1, and both of the worker's
    reliability figures are recomputed."

    Design: Difficulty/non_linear_state_machine/assignment_attendance_and_payout_dimensions_independent
    """
    context = _tip_eligible_completed_shift(client)
    assignment_id = context["assignment"]["id"]

    checked_in = attendance(client, assignment_id, "CHECK_IN", at="2026-09-12T18:00:00Z")
    assert_fields(
        checked_in,
        attendance_status="CHECKED_IN",
        payout_status="PENDING",
        late_check_in=False,
    )
    assert_cents(checked_in["base_pay_cents"], 0, "base_pay_cents before check-out")
    assert_instant(checked_in["check_in_at"], "2026-09-12T18:00:00.000Z", "check_in_at")

    completed = attendance(client, assignment_id, "CHECK_OUT", at="2026-09-12T22:00:00Z")
    assert_fields(
        completed, attendance_status="COMPLETED", payout_status="ACCRUED", worked_minutes=240
    )
    assert_payout_totals(completed, base=9600, gratuity=0, total=9600)

    assert_fields(
        read_member(client, context["member"]["id"]),
        completed_assignment_count=1,
        reliability_score=100,
    )


def test_the_two_payout_phases_advance_the_money_while_attendance_stands_still(client):
    """ACCRUED to GRATUITY_ALLOCATED to PAID, all with attendance pinned at COMPLETED.

    "Each allocated row then has `gratuity_cents` set to its share, has
    `total_payout_cents` recomputed as `base_pay_cents` plus `gratuity_cents`, and
    moves `payout_status` `ACCRUED → GRATUITY_ALLOCATED`; the event's
    `gratuity_allocated_cents` rises by the whole distributed pool."

    Design: Difficulty/non_linear_state_machine/assignment_attendance_and_payout_dimensions_independent
    """
    context = _tip_eligible_completed_shift(client)
    assignment_id = context["assignment"]["id"]
    event_id = context["event"]["id"]

    attendance(client, assignment_id, "CHECK_IN", at="2026-09-12T18:00:00Z")
    attendance(client, assignment_id, "CHECK_OUT", at="2026-09-12T22:00:00Z")
    advance_event(client, event_id, "CLOSED")

    settled = read_assignment(client, assignment_id)
    assert_fields(settled, attendance_status="COMPLETED", payout_status="ACCRUED")

    run_payout(client, event_id, "GRATUITY_ALLOCATION")
    tipped = read_assignment(client, assignment_id)
    assert_fields(
        tipped, attendance_status="COMPLETED", payout_status="GRATUITY_ALLOCATED"
    )
    assert_payout_totals(tipped, base=9600, gratuity=50000, total=59600)
    assert_cents(
        read_event(client, event_id)["gratuity_allocated_cents"],
        50000,
        "gratuity_allocated_cents",
    )

    run_payout(client, event_id, "PAYROLL")
    paid = read_assignment(client, assignment_id)
    assert_fields(paid, attendance_status="COMPLETED", payout_status="PAID")
    assert_payout_totals(paid, base=9600, gratuity=50000, total=59600)


def _full_single_head_block_needing_a_credential(client):
    """A one-head usher block already filled, plus an uncertified and a certified spare."""
    set_clock(client, "2026-09-12T17:00:00Z")
    event = create_event(
        client,
        name="Ladder Order Fixture",
        doors_open_at="2026-09-12T17:00:00Z",
        doors_close_at="2026-09-12T23:00:00Z",
        expected_attendance=20000,
    )
    usher = create_usher(
        client,
        base_hourly_rate_cents=2200,
        attendance_ratio_per_1000=1.5,
        min_headcount=4,
        required_certifications=["EVACUATION_PROCEDURES"],
    )
    plan = create_plan(client, event["id"])
    slot = create_slot(
        client,
        plan["id"],
        usher["id"],
        zone_code="Z510",
        shift_start="2026-09-12T18:00:00Z",
        shift_end="2026-09-12T22:00:00Z",
        required_headcount_override=1,
    )
    holder = create_member(
        client,
        full_name="Ora Kelly",
        employment_type="PART_TIME_EMPLOYEE",
        seniority_date="2023-01-10T00:00:00Z",
        hourly_rate_cents=2200,
    )
    uncertified = create_member(
        client,
        full_name="Pia Rowe",
        employment_type="PART_TIME_EMPLOYEE",
        seniority_date="2023-02-10T00:00:00Z",
        hourly_rate_cents=2200,
    )
    certified_spare = create_member(
        client,
        full_name="Rex Ulloa",
        employment_type="PART_TIME_EMPLOYEE",
        seniority_date="2023-03-10T00:00:00Z",
        hourly_rate_cents=2200,
    )
    certify(client, holder["id"], "EVACUATION_PROCEDURES")
    certify(client, certified_spare["id"], "EVACUATION_PROCEDURES")
    activate_plan(client, plan["id"], event["id"])
    advance_event(client, event["id"], "IN_PROGRESS")
    create_assignment(client, slot["id"], holder["id"])
    return {
        "event": event,
        "plan": plan,
        "slot": slot,
        "holder": holder,
        "uncertified": uncertified,
        "certified_spare": certified_spare,
    }


def test_the_missing_credential_is_reported_even_though_the_block_is_also_full(client):
    """Both rung 12 and rung 17 are violated at once, and the credential rung answers.

    "Credential compliance (`ERR_CERTIFICATION_MISSING`). Compliance outranks every
    capacity, temporal and fiscal check below it — an uncertified worker is reported
    as uncertified even when the shift block is also full."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_uncertified_full_slot
    """
    context = _full_single_head_block_needing_a_credential(client)
    slot_id = context["slot"]["id"]

    assert_slot_fill(read_slot(client, slot_id), filled=1, required=1, status="FILLED")

    err(
        client.create_staff_assignment(
            staff_assignment_payload(slot_id, context["uncertified"]["id"]),
            COORDINATOR_HEADERS,
        ),
        ERR_CERTIFICATION_MISSING,
    )

    assert_slot_fill(read_slot(client, slot_id), filled=1, required=1, status="FILLED")
    rows, _meta = page(
        client.list_staff_member_certifications(
            context["uncertified"]["id"], COORDINATOR_HEADERS
        )
    )
    assert rows == [], "the refused attempt must not conjure a credential for the worker"


def test_the_capacity_rung_fires_once_the_credential_rung_is_satisfied(client):
    """The same full block reports itself full as soon as the worker is certified.

    "Finally the block must have room — `filled_headcount` strictly below
    `required_headcount` — or the attempt is refused with `ERR_SLOT_CAPACITY_FULL`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_uncertified_full_slot
    """
    context = _full_single_head_block_needing_a_credential(client)
    slot_id = context["slot"]["id"]

    err(
        client.create_staff_assignment(
            staff_assignment_payload(slot_id, context["certified_spare"]["id"]),
            COORDINATOR_HEADERS,
        ),
        ERR_SLOT_CAPACITY_FULL,
    )

    assert_slot_fill(read_slot(client, slot_id), filled=1, required=1, status="FILLED")
    rows, _meta = page(
        client.list_staff_assignments(COORDINATOR_HEADERS, {"position_slot_id": slot_id})
    )
    assert len(rows) == 1, "neither refused attempt may leave an assignment behind"
    assert_fields(rows[0], staff_member_id=context["holder"]["id"])


def _one_worker_and_two_adjacent_blocks(client):
    """A worker booked on an 18:00-22:00 block, with a 22:15 block fifteen minutes later."""
    set_clock(client, "2026-09-12T17:00:00Z")
    event = create_event(
        client,
        name="Rest Buffer Order Fixture",
        doors_open_at="2026-09-12T17:00:00Z",
        doors_close_at="2026-09-12T23:30:00Z",
        expected_attendance=20000,
    )
    ticket_taker = create_ticket_taker(
        client,
        base_hourly_rate_cents=2000,
        attendance_ratio_per_1000=0.8,
        min_headcount=3,
        required_certifications=[],
    )
    plan = create_plan(client, event["id"])
    early = create_slot(
        client,
        plan["id"],
        ticket_taker["id"],
        zone_code="Z610",
        shift_start="2026-09-12T18:00:00Z",
        shift_end="2026-09-12T22:00:00Z",
        required_headcount_override=2,
    )
    late = create_slot(
        client,
        plan["id"],
        ticket_taker["id"],
        zone_code="Z611",
        shift_start="2026-09-12T22:15:00Z",
        shift_end="2026-09-12T23:00:00Z",
        required_headcount_override=2,
    )
    member = create_member(
        client,
        full_name="Sol Vega",
        employment_type="PART_TIME_EMPLOYEE",
        seniority_date="2023-06-01T00:00:00Z",
        hourly_rate_cents=2000,
    )
    activate_plan(client, plan["id"], event["id"])
    advance_event(client, event["id"], "IN_PROGRESS")
    create_assignment(client, early["id"], member["id"])
    return {
        "event": event,
        "plan": plan,
        "early": early,
        "late": late,
        "member": member,
    }


def test_a_second_booking_on_the_same_block_reports_the_duplicate_not_the_rest_gap(client):
    """Rung 13 answers first, even though a zero-minute gap also breaks rung 14.

    "The rest buffer between shifts (`ERR_SHIFT_REST_CONFLICT`). Because this rung
    sits below uniqueness, a second assignment on the very same shift block reports
    the duplicate rather than the rest conflict it also implies."

    Design: Difficulty/priority_pair_validation_conflict/constraint_beats_temporal_on_duplicate_assignment
    """
    context = _one_worker_and_two_adjacent_blocks(client)
    early_id = context["early"]["id"]

    err(
        client.create_staff_assignment(
            staff_assignment_payload(early_id, context["member"]["id"]),
            COORDINATOR_HEADERS,
        ),
        ERR_DUPLICATE_ASSIGNMENT,
    )

    assert_slot_fill(
        read_slot(client, early_id), filled=1, required=2, status="PARTIALLY_FILLED"
    )
    rows, _meta = page(
        client.list_staff_assignments(
            COORDINATOR_HEADERS, {"staff_member_id": context["member"]["id"]}
        )
    )
    assert len(rows) == 1, "the refused duplicate must not become a second booking"


def test_the_rest_rung_fires_on_a_different_block_fifteen_minutes_away(client):
    """A distinct block clears uniqueness, and the fifteen-minute gap then bites.

    "The worker must observe the rest buffer: no other non-terminal assignment of
    theirs may have a shift window that comes within 30 minutes of the target block's
    window, where a gap of exactly 30 minutes is accepted and a gap of 29 minutes is
    refused with `ERR_SHIFT_REST_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/constraint_beats_temporal_on_duplicate_assignment
    """
    context = _one_worker_and_two_adjacent_blocks(client)
    late_id = context["late"]["id"]

    err(
        client.create_staff_assignment(
            staff_assignment_payload(late_id, context["member"]["id"]),
            COORDINATOR_HEADERS,
        ),
        ERR_SHIFT_REST_CONFLICT,
    )

    assert_slot_fill(read_slot(client, late_id), filled=0, required=2, status="OPEN")
    assert_slot_fill(
        read_slot(client, context["early"]["id"]),
        filled=1,
        required=2,
        status="PARTIALLY_FILLED",
    )
    rows, _meta = page(
        client.list_staff_assignments(
            COORDINATOR_HEADERS, {"staff_member_id": context["member"]["id"]}
        )
    )
    assert len(rows) == 1, "the worker still holds exactly one booking"
    assert_fields(rows[0], position_slot_id=context["early"]["id"])
