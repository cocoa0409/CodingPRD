"""The cancellation cascade down the ownership hierarchy, and the supersession cascade."""

from test_helpers import (
    COORDINATOR_HEADERS,
    DIRECTOR_HEADERS,
    ERR_EVENT_STATE_INVALID,
    ERR_PLAN_STATE_INVALID,
    ERR_STALE_EVENT_VERSION,
    activate_plan,
    advance_event,
    assert_cents,
    assert_fields,
    assert_instant,
    backfill_requests_for_slot,
    create_assignment,
    create_bid,
    create_event,
    create_member,
    create_plan,
    create_slot,
    create_ticket_taker,
    err,
    event_version,
    page,
    read_assignment,
    read_bid,
    read_event,
    read_plan,
    read_slot,
    set_clock,
)
from test_helpers.factories import event_lifecycle_payload, plan_activate_payload

TICKET_TAKER = {
    "base_hourly_rate_cents": 2000,
    "attendance_ratio_per_1000": 0.8,
    "min_headcount": 3,
    "required_certifications": [],
}


def _assert_all_aggregates_zero(plan, label):
    assert_fields(plan, total_required_headcount=0)
    assert_cents(plan["base_labor_cost_cents"], 0, f"{label} base_labor_cost_cents")
    assert_cents(
        plan["accessibility_surcharge_cents"], 0, f"{label} accessibility_surcharge_cents"
    )
    assert_cents(
        plan["projected_labor_cost_cents"], 0, f"{label} projected_labor_cost_cents"
    )


def _two_plans_one_with_work_on_it(client, *, name, clock, zone_code):
    """An event in PLANNED with one ACTIVE plan carrying real work and one DRAFT rival."""
    set_clock(client, clock)
    event = create_event(
        client,
        name=name,
        event_date="2026-09-19T00:00:00Z",
        doors_open_at="2026-09-19T17:00:00Z",
        doors_close_at="2026-09-19T23:00:00Z",
        expected_attendance=20000,
    )
    baseline_version = event["version"]
    position_type = create_ticket_taker(client, **TICKET_TAKER)
    plan_a = create_plan(client, event["id"], plan_variant="FORECAST_BASED")
    slot_a = create_slot(
        client,
        plan_a["id"],
        position_type["id"],
        zone_code=zone_code,
        shift_start="2026-09-19T18:00:00Z",
        shift_end="2026-09-19T22:00:00Z",
        required_headcount_override=2,
    )
    plan_b = create_plan(client, event["id"], plan_variant="FORECAST_BASED")
    worker = create_member(
        client,
        full_name="Ivy Marsh",
        employment_type="PART_TIME_EMPLOYEE",
        seniority_date="2024-01-01T00:00:00Z",
        hourly_rate_cents=2000,
    )
    bidder = create_member(
        client,
        full_name="Jon Petty",
        employment_type="PART_TIME_EMPLOYEE",
        seniority_date="2024-06-01T00:00:00Z",
        hourly_rate_cents=2000,
    )
    activate_plan(client, plan_a["id"], event["id"], baseline_version)
    assignment = create_assignment(client, slot_a["id"], worker["id"])
    bid = create_bid(client, bidder["id"], slot_a["id"])
    return {
        "event": event,
        "baseline_version": baseline_version,
        "position_type": position_type,
        "plan_a": plan_a,
        "plan_b": plan_b,
        "slot_a": slot_a,
        "worker": worker,
        "bidder": bidder,
        "assignment": assignment,
        "bid": bid,
    }


def _cancellation_fixture(client):
    """The scene above, with the DRAFT rival also carrying a block of its own."""
    context = _two_plans_one_with_work_on_it(
        client,
        name="Cancel Cascade Fixture",
        clock="2026-09-10T08:00:00Z",
        zone_code="Z210",
    )
    context["slot_b"] = create_slot(
        client,
        context["plan_b"]["id"],
        context["position_type"]["id"],
        zone_code="Z211",
        shift_start="2026-09-19T18:00:00Z",
        shift_end="2026-09-19T22:00:00Z",
        required_headcount_override=2,
    )
    return context


def test_cancelling_the_event_descends_all_four_links_of_the_hierarchy(client):
    """Event to plans to blocks to the bids and assignments those blocks own.

    "Link four, caused by link three, acts on each newly closed block: every
    assignment whose `attendance_status` is `SCHEDULED` or `CHECKED_IN` moves to
    `CANCELLED` with `payout_status` driven to `VOIDED`, and every bid whose `status`
    is `SUBMITTED` or `WAITLISTED` moves to `DECLINED_BY_SYSTEM` with
    `decision_reason` recorded as `EVENT_CANCELLED`."

    Design: Difficulty/transitive_cascade/event_cancel_four_link_cascade
    """
    context = _cancellation_fixture(client)
    event_id = context["event"]["id"]

    cancelled = advance_event(client, event_id, "CANCELLED")

    assert_fields(cancelled, status="CANCELLED")
    assert cancelled["version"] == context["baseline_version"] + 2, (
        "one increment came from the activation and one from the lifecycle write"
    )
    assert_fields(read_plan(client, context["plan_a"]["id"]), status="VOIDED")
    assert_fields(read_plan(client, context["plan_b"]["id"]), status="VOIDED")
    assert_fields(read_slot(client, context["slot_a"]["id"]), status="CLOSED")
    assert_fields(read_slot(client, context["slot_b"]["id"]), status="CLOSED")
    assert_fields(
        read_assignment(client, context["assignment"]["id"]),
        attendance_status="CANCELLED",
        payout_status="VOIDED",
    )
    assert_fields(
        read_bid(client, context["bid"]["id"]),
        status="DECLINED_BY_SYSTEM",
        decision_reason="EVENT_CANCELLED",
    )


def test_the_cascade_zeroes_both_plans_and_opens_no_backfill_request(client):
    """The block keeps its CLOSED state while its head count drops to nothing.

    "Link three, caused by link two, closes every shift block of each voided plan
    whose `status` is not already `CLOSED`, and drives that plan's four aggregates to
    zero."

    Design: Difficulty/transitive_cascade/event_cancel_four_link_cascade
    """
    context = _cancellation_fixture(client)
    slot_a_id = context["slot_a"]["id"]

    before = read_slot(client, slot_a_id)
    assert_fields(before, filled_headcount=1, required_headcount=2, status="PARTIALLY_FILLED")

    advance_event(client, context["event"]["id"], "CANCELLED")

    after = read_slot(client, slot_a_id)
    assert_fields(after, filled_headcount=0, status="CLOSED")
    _assert_all_aggregates_zero(read_plan(client, context["plan_a"]["id"]), "plan A")
    _assert_all_aggregates_zero(read_plan(client, context["plan_b"]["id"]), "plan B")

    assert backfill_requests_for_slot(client, slot_a_id) == [], (
        "a cancellation cascade opens no backfill request anywhere"
    )
    assert backfill_requests_for_slot(client, context["slot_b"]["id"]) == [], (
        "the rival plan's block is closed without any backfill request either"
    )


def test_the_terminal_cancellation_cannot_be_replayed_over_the_same_event(client):
    """CANCELLED is terminal, and the untouched sibling block stays free of children.

    "`CLOSED` and `CANCELLED` are terminal for an event, and `SUPERSEDED`, `LOCKED`
    and `VOIDED` are terminal for a plan."

    Design: Difficulty/transitive_cascade/event_cancel_four_link_cascade
    """
    context = _cancellation_fixture(client)
    event_id = context["event"]["id"]

    advance_event(client, event_id, "CANCELLED")
    settled_version = read_event(client, event_id)["version"]

    err(
        client.event_lifecycle(
            event_id,
            event_lifecycle_payload("CANCELLED", reason="Replay of the same decision"),
            DIRECTOR_HEADERS,
        ),
        ERR_EVENT_STATE_INVALID,
    )

    replayed = read_event(client, event_id)
    assert_fields(replayed, status="CANCELLED", version=settled_version)

    assignments, _meta = page(
        client.list_staff_assignments(
            COORDINATOR_HEADERS, {"position_slot_id": context["slot_b"]["id"]}
        )
    )
    assert assignments == [], "the rival plan's block never carried an assignment"
    bids, _bid_meta = page(
        client.list_shift_bids(
            COORDINATOR_HEADERS, {"position_slot_id": context["slot_b"]["id"]}
        )
    )
    assert bids == [], "the rival plan's block never carried a bid"


def _supersession_fixture(client):
    """The same scene, with the event version re-read so the rival can be activated."""
    context = _two_plans_one_with_work_on_it(
        client,
        name="Supersede Cascade Fixture",
        clock="2026-09-10T09:00:00Z",
        zone_code="Z310",
    )
    context["live_version"] = event_version(client, context["event"]["id"])
    return context


def test_activating_the_rival_plan_supersedes_the_incumbent_and_cascades(client):
    """A third trigger, three links deep, and a decision reason of its own.

    "Any other plan of the same event standing in `ACTIVE` moves `ACTIVE →
    SUPERSEDED`, and supersession runs its own cascade: every shift block of the
    superseded plan whose `status` is not `CLOSED` moves to `CLOSED`; on each such
    block, every bid whose `status` is `SUBMITTED` or `WAITLISTED` moves to
    `DECLINED_BY_SYSTEM` with `decision_reason` recorded as `PLAN_SUPERSEDED`; on each
    such block, every assignment whose `attendance_status` is `SCHEDULED` or
    `CHECKED_IN` moves to `CANCELLED` with `payout_status` driven to `VOIDED`; and the
    superseded plan's `total_required_headcount`, `base_labor_cost_cents`,
    `accessibility_surcharge_cents` and `projected_labor_cost_cents` are recomputed over
    the now-closed block set, which drives all four to zero."

    Design: Difficulty/transitive_cascade/plan_supersede_three_link_cascade
    """
    context = _supersession_fixture(client)

    activated = activate_plan(
        client, context["plan_b"]["id"], context["event"]["id"], context["live_version"]
    )

    assert_fields(activated, status="ACTIVE")
    assert_instant(activated["activated_at"], "2026-09-10T09:00:00.000Z", "activated_at")
    assert_fields(read_plan(client, context["plan_a"]["id"]), status="SUPERSEDED")
    assert_fields(read_slot(client, context["slot_a"]["id"]), status="CLOSED")
    assert_fields(
        read_assignment(client, context["assignment"]["id"]),
        attendance_status="CANCELLED",
        payout_status="VOIDED",
    )
    declined = read_bid(client, context["bid"]["id"])
    assert_fields(declined, status="DECLINED_BY_SYSTEM", decision_reason="PLAN_SUPERSEDED")
    assert declined["decision_reason"] != "EVENT_CANCELLED", (
        "supersession records its own reason, distinct from a cancellation"
    )


def test_the_superseded_plan_is_zeroed_while_the_event_stays_planned(client):
    """The second activation moves the version without moving the event's status.

    "A second activation against an event already in `PLANNED` leaves the event's
    `status` at `PLANNED` and still increments its `version` by 1."

    Design: Difficulty/transitive_cascade/plan_supersede_three_link_cascade
    """
    context = _supersession_fixture(client)

    activate_plan(
        client, context["plan_b"]["id"], context["event"]["id"], context["live_version"]
    )

    _assert_all_aggregates_zero(read_plan(client, context["plan_a"]["id"]), "superseded plan")
    assert_fields(read_slot(client, context["slot_a"]["id"]), filled_headcount=0, status="CLOSED")

    event = read_event(client, context["event"]["id"])
    assert_fields(event, status="PLANNED", version=context["live_version"] + 1)


def test_the_version_guard_answers_before_the_superseded_plans_own_state(client):
    """Replaying the first activation trips the guard; replaying it freshly trips the state.

    "The version check sits after authentication, role authorization, request-schema
    validation and the resolution of path and body foreign keys, and before any check
    on the plan's or the event's own status."

    Design: Difficulty/transitive_cascade/plan_supersede_three_link_cascade
    """
    context = _supersession_fixture(client)
    event_id = context["event"]["id"]
    plan_a_id = context["plan_a"]["id"]

    activate_plan(client, context["plan_b"]["id"], event_id, context["live_version"])

    err(
        client.activate_staffing_plan(
            plan_a_id,
            plan_activate_payload(expected_event_version=context["live_version"]),
            COORDINATOR_HEADERS,
        ),
        ERR_STALE_EVENT_VERSION,
    )
    assert_fields(read_plan(client, plan_a_id), status="SUPERSEDED")
    assert_fields(read_event(client, event_id), version=context["live_version"] + 1)

    err(
        client.activate_staffing_plan(
            plan_a_id,
            plan_activate_payload(expected_event_version=context["live_version"] + 1),
            COORDINATOR_HEADERS,
        ),
        ERR_PLAN_STATE_INVALID,
    )
    assert_fields(read_plan(client, plan_a_id), status="SUPERSEDED")
    assert_fields(read_plan(client, context["plan_b"]["id"]), status="ACTIVE")
