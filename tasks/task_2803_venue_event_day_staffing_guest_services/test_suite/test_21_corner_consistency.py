"""Immediate consistency: every cascade and every derived total is readable on the next call."""

from test_helpers import (
    COORDINATOR_HEADERS,
    DIRECTOR_HEADERS,
    activate_plan,
    advance_event,
    assert_cents,
    assert_fields,
    assert_ledger,
    assert_slot_fill,
    assign_issue,
    attendance,
    backfill_requests_for_assignment,
    certify,
    create_assignment,
    create_event,
    create_member,
    create_plan,
    create_position_type,
    create_slot,
    created,
    decide_refund,
    file_refund,
    make_supervisor_headers,
    only,
    page,
    read_assignment,
    read_event,
    read_member,
    read_plan,
    read_slot,
    set_clock,
)
from test_helpers.factories import guest_issue_payload

TICKET_TAKER = {
    "code": "TICKET_TAKER",
    "display_name": "Ticket Taker",
    "base_hourly_rate_cents": 2000,
    "attendance_ratio_per_1000": 0.8,
    "min_headcount": 1,
    "required_certifications": [],
}


def _absent(entity, *fields):
    """A field the PRD calls absent reads as missing or null, never as a value."""
    for field in fields:
        assert entity.get(field) is None, (
            f"{field} must be absent, got {entity.get(field)!r}"
        )


def _fixture_event(client, name, **overrides):
    """The gate-day event these consistency recipes hang their rows from."""
    return create_event(
        client,
        name=name,
        event_date="2026-09-12T00:00:00Z",
        doors_open_at="2026-09-12T17:00:00Z",
        doors_close_at="2026-09-12T23:00:00Z",
        expected_attendance=6000,
        **overrides,
    )


def test_immediate_cascade_visible_in_the_same_response(client):
    """The no-show response is already final, and every row its cascade touched reads current at once.

    "The assignment moves `SCHEDULED → NO_SHOW`, its `payout_status` is driven `PENDING → VOIDED` and `total_payout_cents` is set to 0. The block's `filled_headcount` is decremented by 1 and its `status` re-derived, and a backfill request is opened against that block in `OPEN` with `triggering_assignment_id` pointing at the assignment that just failed. The worker's `no_show_strikes` is incremented by 1 and both reliability figures are recomputed."

    "It records the `position_slot_id` of the block left short, the `triggering_assignment_id` of the failure that opened it, and an `attempt_count` starting at 0, with `selected_staff_member_id`, `filled_assignment_id` and `cancel_reason` all absent, in status `OPEN`."

    "For any set of rows the score starts at 100, subtracts 25 for each row in `NO_SHOW`, subtracts a further 8 for each row in `COMPLETED` whose `late_check_in` flag is set, adds 3 for each row in `COMPLETED`, and is then clamped into the range 0 through 100."

    "Whenever a recomputation triggered by a completion or a no-show leaves an `ACTIVE` worker's `reliability_score` below 65, the system moves that worker `ACTIVE → PROBATION`, sets `in_backfill_pool` to false, and records `last_status_reason` as `AUTO_PROBATION_RELIABILITY`."

    "Conversely, an assignment leaving the filled set takes a block `FILLED → PARTIALLY_FILLED` when at least one head remains and `PARTIALLY_FILLED → OPEN` when none does, and in both directions no other entity is mutated by the block's own re-derivation."

    Design: Corner/consistency_model/immediate_cascade_visible_in_the_same_response
    """
    set_clock(client, "2026-09-12T18:10:00Z")
    event = _fixture_event(client, "Immediate Cascade Fixture")
    family = create_position_type(client, **TICKET_TAKER)
    plan = create_plan(client, event["id"])
    slot = create_slot(
        client,
        plan["id"],
        family["id"],
        zone_code="Z100",
        shift_start="2026-09-12T18:00:00Z",
        shift_end="2026-09-12T22:05:00Z",
        required_headcount_override=2,
    )
    m1 = create_member(client, full_name="M1 Absent", hourly_rate_cents=2000)
    m2 = create_member(client, full_name="M2 Present", hourly_rate_cents=2000)
    activate_plan(client, plan["id"], event["id"])
    a1 = create_assignment(client, slot["id"], m1["id"])
    a2 = create_assignment(client, slot["id"], m2["id"])
    assert_slot_fill(read_slot(client, slot["id"]), filled=2, required=2, status="FILLED")
    advance_event(client, event["id"], "IN_PROGRESS")

    # The mutating response itself is already final — no second read is needed.
    marked = attendance(client, a1["id"], "NO_SHOW")
    assert marked["id"] == a1["id"]
    assert_fields(marked, attendance_status="NO_SHOW", payout_status="VOIDED")
    assert_cents(marked["total_payout_cents"], 0, "total_payout_cents")

    # The block's re-derivation is visible in the immediately following read.
    assert_slot_fill(
        read_slot(client, slot["id"]), filled=1, required=2, status="PARTIALLY_FILLED"
    )

    # The cascade's brand-new row is queryable at once, not on some later pass.
    opened = only(backfill_requests_for_assignment(client, a1["id"]))
    assert_fields(
        opened,
        status="OPEN",
        position_slot_id=slot["id"],
        triggering_assignment_id=a1["id"],
        attempt_count=0,
    )
    _absent(opened, "selected_staff_member_id", "filled_assignment_id", "cancel_reason")

    # Both derived scores are current in the same breath: 100 - 25 = 75, above the floor.
    absentee = read_member(client, m1["id"])
    assert_fields(
        absentee,
        reliability_score=75,
        season_reliability_score=75,
        in_backfill_pool=True,
        status="ACTIVE",
        no_show_strikes=1,
    )
    _absent(absentee, "last_status_reason")
    assert_fields(read_member(client, m2["id"]), reliability_score=100, status="ACTIVE")

    # The filtered list index reflects the new state immediately.
    items, meta = page(
        client.list_staff_assignments(
            COORDINATOR_HEADERS,
            {"position_slot_id": slot["id"], "attendance_status": "NO_SHOW"},
        )
    )
    assert meta["total_count"] == 1, f"exactly one no-show row on the block: {meta}"
    assert [item["id"] for item in items] == [a1["id"]]

    # Repeating every read returns identical bodies: there is no lag window to observe.
    assert read_slot(client, slot["id"]) == read_slot(client, slot["id"])
    assert read_member(client, m1["id"]) == read_member(client, m1["id"])
    reread = read_assignment(client, a1["id"])
    assert reread == read_assignment(client, a1["id"])
    assert_fields(
        reread,
        id=marked["id"],
        attendance_status=marked["attendance_status"],
        payout_status=marked["payout_status"],
    )
    assert_fields(read_assignment(client, a2["id"]), attendance_status="SCHEDULED")
    assert only(backfill_requests_for_assignment(client, a1["id"])) == opened


def test_immediate_derived_ledger_visible_in_the_same_response(client):
    """Derived money is never stale: the block's own cost, the parent aggregate and the grandparent ledger.

    "Costing a plan is a six-step pass over the plan's shift blocks whose `status` is not `CLOSED`, taken in `created_at` ascending order, and each step consumes the rounded output of the one before it. Step one prices each block on its own: `slot_labor_cost_cents` is the block's `required_headcount` multiplied by the family's `base_hourly_rate_cents` multiplied by the block's `shift_minutes` divided by 60, rounded half up to whole cents, one block at a time. Step two sums those already-rounded per-block figures into `base_labor_cost_cents`; the exact products are never summed. Step three sums the blocks' `required_headcount` values into `total_required_headcount`, independently of any money. Step four selects an accessibility surcharge rate from that plan-level headcount total and never from an individual block: a total of 300 heads or more draws 900 basis points, at least 150 but fewer than 300 draws 600 basis points, at least 60 but fewer than 150 draws 350 basis points, and anything below 60 draws nothing. Step five computes `accessibility_surcharge_cents` as `base_labor_cost_cents` multiplied by that basis-point rate divided by 10000, rounded half up to whole cents. Step six adds the two together into `projected_labor_cost_cents`; the surcharge never re-enters the headcount total or the surcharge-tier selection."

    "This costing pass re-runs whenever the plan's block set or its numbers move: when a block is added, when a block is retimed or resized, when a block is removed, when the plan is activated, and whenever any block's status changes to or from `CLOSED`."

    "The event's guest-recovery money is held in three fields that must always agree. `refund_budget_total_cents` is the ceiling the director set, defaulting to 100000 cents when the event is created without one. `refund_approved_total_cents` is the sum of `refund_approved_cents` across the event's guest issues whose `refund_status` is either `APPROVED` or `PARTIALLY_APPROVED`; issues whose refund state is `NONE`, `PENDING`, `DENIED` or `VOIDED` contribute nothing. `refund_budget_remaining_cents` is `refund_budget_total_cents` less `refund_approved_total_cents`."

    "The invariant `refund_budget_remaining_cents` plus `refund_approved_total_cents` equals `refund_budget_total_cents` holds after every refund decision and after every event update. Filing a refund ask changes no ledger figure; only a decision does."

    "A new issue opens in `OPEN` with `reported_by_user_id` recorded from `X-User-ID`, `refund_status` at `NONE`, `refund_requested_cents` at 0, `reopen_count` at 0, and `assigned_staff_member_id`, `resolved_by_user_id`, `resolution_type`, `resolved_at`, `relocation_zone_code`, `escalated_from_issue_id`, `refund_requested_by_user_id` and `refund_decided_by_user_id` all absent."

    "A supervisor first files the ask, supplying `refund_requested_cents`; the system stores that amount, records `refund_requested_by_user_id` from `X-User-ID`, and moves `refund_status` `NONE → PENDING`. No money moves and no ledger figure changes at this point."

    "The amount authorized is then the smallest of three figures: the `refund_requested_cents` asked for, the effective cap, and that available budget. It is stored in `refund_approved_cents`, and `refund_status` becomes `APPROVED` when the authorized amount equals the full request and `PARTIALLY_APPROVED` otherwise."

    Design: Corner/consistency_model/immediate_derived_ledger_visible_in_the_same_response
    """
    set_clock(client, "2026-09-12T19:00:00Z")
    event = _fixture_event(client, "Immediate Ledger Fixture", refund_budget_total_cents=100000)
    assert_ledger(event, approved=0, remaining=100000, total=100000)

    family = create_position_type(client, **TICKET_TAKER)
    plan = create_plan(client, event["id"])
    assert_fields(plan, status="DRAFT", total_required_headcount=0)
    assert_cents(plan["base_labor_cost_cents"], 0, "base_labor_cost_cents")
    assert_cents(plan["accessibility_surcharge_cents"], 0, "accessibility_surcharge_cents")
    assert_cents(plan["projected_labor_cost_cents"], 0, "projected_labor_cost_cents")

    # 2 heads x 2000 cents/h x 245 min / 60 = 16333.33 -> 16333, in the creation response itself.
    slot = create_slot(
        client,
        plan["id"],
        family["id"],
        zone_code="Z100",
        shift_start="2026-09-12T18:00:00Z",
        shift_end="2026-09-12T22:05:00Z",
        required_headcount_override=2,
    )
    assert_fields(slot, required_headcount=2, shift_minutes=245)
    assert_cents(slot["slot_labor_cost_cents"], 16333, "slot_labor_cost_cents")

    # The parent aggregate is not recomputed lazily on some later request.
    priced = read_plan(client, plan["id"])
    assert_fields(priced, total_required_headcount=2)
    assert_cents(priced["base_labor_cost_cents"], 16333, "base_labor_cost_cents")
    assert_cents(priced["accessibility_surcharge_cents"], 0, "accessibility_surcharge_cents")
    assert_cents(priced["projected_labor_cost_cents"], 16333, "projected_labor_cost_cents")

    activate_plan(client, plan["id"], event["id"])
    advance_event(client, event["id"], "IN_PROGRESS")
    responder = create_member(client, full_name="Ida Responder", hourly_rate_cents=2000)
    certify(client, responder["id"], "CODE_OF_CONDUCT")

    reporter = make_supervisor_headers("sup-9")
    issue = created(
        client.create_guest_issue(
            guest_issue_payload(
                event["id"],
                channel="TEXT_LINE",
                category="OTHER",
                severity="MEDIUM",
                description="Double charge at gate 4",
            ),
            reporter,
        )
    )
    assert_fields(issue, status="OPEN", reported_by_user_id="sup-9", refund_status="NONE")
    assign_issue(client, issue["id"], responder["id"], headers=reporter)

    # Filing the ask is deliberately not a ledger event: immediate does not mean eager.
    asked = file_refund(client, issue["id"], 2000, headers=make_supervisor_headers("sup-1"))
    assert_fields(asked, refund_status="PENDING", refund_requested_cents=2000)
    assert_ledger(read_event(client, event["id"]), approved=0, remaining=100000, total=100000)

    # The decision's own response carries the authorized amount: min(2000, 5000, 100000).
    decided = decide_refund(
        client, issue["id"], "APPROVE", headers=make_supervisor_headers("sup-2")
    )
    assert_fields(decided, refund_status="APPROVED")
    assert_cents(decided["refund_approved_cents"], 2000, "refund_approved_cents")

    # The grandparent ledger moved inside the same request that approved the refund.
    settled = read_event(client, event["id"], headers=DIRECTOR_HEADERS)
    assert_ledger(settled, approved=2000, remaining=98000, total=100000)
    assert settled == read_event(client, event["id"], headers=DIRECTOR_HEADERS)
    assert_ledger(read_event(client, event["id"]), approved=2000, remaining=98000, total=100000)
