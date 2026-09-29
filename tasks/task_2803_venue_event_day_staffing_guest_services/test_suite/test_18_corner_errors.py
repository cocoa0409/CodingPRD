"""Error-catalogue breadth: every id in the table must be reachable and separable."""

from test_helpers import (
    COORDINATOR_HEADERS,
    DIRECTOR_HEADERS,
    ERR_ACCESS_REQUEST_STATE_INVALID,
    ERR_ACCESSIBILITY_REQUEST_NOT_FOUND,
    ERR_ACCESSIBILITY_RESOURCE_NOT_FOUND,
    ERR_ASSIGNMENT_STATE_INVALID,
    ERR_BACKFILL_NOT_OPEN,
    ERR_BACKFILL_REQUEST_NOT_FOUND,
    ERR_BID_STATE_INVALID,
    ERR_CERTIFICATION_NOT_FOUND,
    ERR_EVENT_NOT_FOUND,
    ERR_GUEST_ISSUE_NOT_FOUND,
    ERR_PLAN_STATE_INVALID,
    ERR_POSITION_SLOT_NOT_FOUND,
    ERR_POSITION_TYPE_NOT_FOUND,
    ERR_RESOURCE_NOT_AVAILABLE,
    ERR_SHIFT_BID_NOT_FOUND,
    ERR_SLOT_CAPACITY_FULL,
    ERR_SLOT_STATE_INVALID,
    ERR_STAFF_ASSIGNMENT_NOT_FOUND,
    ERR_STAFF_MEMBER_NOT_ACTIVE,
    ERR_STAFF_MEMBER_NOT_FOUND,
    ERR_STAFFING_PLAN_NOT_FOUND,
    SUPERVISOR_HEADERS,
    activate_plan,
    advance_event,
    assert_cents,
    assert_fields,
    assert_instant,
    assert_slot_fill,
    attendance,
    backfill_requests_for_assignment,
    change_member_status,
    create_assignment,
    create_bid,
    create_booking,
    create_event,
    create_member,
    create_plan,
    create_position_type,
    create_resource,
    create_slot,
    err,
    event_version,
    ids_of,
    make_staff_member_headers,
    ok,
    page,
    read_assignment,
    read_bid,
    read_event,
    read_member,
    read_plan,
    read_resource,
    read_slot,
    set_clock,
    set_resource_status,
    transition_booking,
)
from test_helpers.factories import (
    access_transition_payload,
    attendance_payload,
    cancel_backfill_payload,
    plan_activate_payload,
    staff_assignment_payload,
    status_change_payload,
)

ABSENT_ID = "00000000-0000-0000-0000-0000000000ff"

TICKET_TAKER = {
    "code": "TICKET_TAKER",
    "display_name": "Ticket Taker",
    "base_hourly_rate_cents": 2000,
    "attendance_ratio_per_1000": 0.8,
    "min_headcount": 1,
    "required_certifications": [],
}


def _fixture_event(client, name, **overrides):
    """The gate-day event these error recipes hang their rows from."""
    return create_event(
        client,
        name=name,
        event_date="2026-09-12T00:00:00Z",
        doors_open_at="2026-09-12T17:00:00Z",
        doors_close_at="2026-09-12T23:00:00Z",
        expected_attendance=6000,
        **overrides,
    )


def _absent(entity, *fields):
    """A field the PRD calls absent reads as missing or null, never as a value."""
    for field in fields:
        assert entity.get(field) is None, (
            f"{field} must be absent, got {entity.get(field)!r}"
        )


def test_all_twelve_entity_not_found_errors_stay_distinct(client):
    """The same unknown id reaches twelve different 404s, one per persisted entity.

    "When a path carries an identifier that resolves to nothing, the request is refused with the 404 error naming that entity — `ERR_EVENT_NOT_FOUND`, `ERR_POSITION_TYPE_NOT_FOUND`, `ERR_STAFFING_PLAN_NOT_FOUND`, `ERR_POSITION_SLOT_NOT_FOUND`, `ERR_STAFF_MEMBER_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`, `ERR_SHIFT_BID_NOT_FOUND`, `ERR_STAFF_ASSIGNMENT_NOT_FOUND`, `ERR_BACKFILL_REQUEST_NOT_FOUND`, `ERR_GUEST_ISSUE_NOT_FOUND`, `ERR_ACCESSIBILITY_RESOURCE_NOT_FOUND` or `ERR_ACCESSIBILITY_REQUEST_NOT_FOUND` — and the first unresolved identifier in the path wins."

    "Path identifier existence, left to right (the entity-specific 404)."

    "Every failure answers with the status listed in §5 for the error identifier concerned, and never with more than one error identifier per request."

    Design: Corner/errors/all_twelve_not_found_errors_are_triggerable
    """
    set_clock(client, "2026-09-01T09:00:00Z")

    # nothing has been created at all, so the same id is unknown to every collection
    probes = (
        (client.get_event(ABSENT_ID, DIRECTOR_HEADERS), ERR_EVENT_NOT_FOUND),
        (client.get_position_type(ABSENT_ID, COORDINATOR_HEADERS), ERR_POSITION_TYPE_NOT_FOUND),
        (client.get_staffing_plan(ABSENT_ID, COORDINATOR_HEADERS), ERR_STAFFING_PLAN_NOT_FOUND),
        (client.get_position_slot(ABSENT_ID, COORDINATOR_HEADERS), ERR_POSITION_SLOT_NOT_FOUND),
        (client.get_staff_member(ABSENT_ID, COORDINATOR_HEADERS), ERR_STAFF_MEMBER_NOT_FOUND),
        (client.get_certification(ABSENT_ID, COORDINATOR_HEADERS), ERR_CERTIFICATION_NOT_FOUND),
        (client.get_shift_bid(ABSENT_ID, COORDINATOR_HEADERS), ERR_SHIFT_BID_NOT_FOUND),
        (
            client.get_staff_assignment(ABSENT_ID, COORDINATOR_HEADERS),
            ERR_STAFF_ASSIGNMENT_NOT_FOUND,
        ),
        (
            client.get_backfill_request(ABSENT_ID, COORDINATOR_HEADERS),
            ERR_BACKFILL_REQUEST_NOT_FOUND,
        ),
        (client.get_guest_issue(ABSENT_ID, SUPERVISOR_HEADERS), ERR_GUEST_ISSUE_NOT_FOUND),
        (
            client.get_accessibility_resource(ABSENT_ID, SUPERVISOR_HEADERS),
            ERR_ACCESSIBILITY_RESOURCE_NOT_FOUND,
        ),
        (
            client.get_accessibility_request(ABSENT_ID, SUPERVISOR_HEADERS),
            ERR_ACCESSIBILITY_REQUEST_NOT_FOUND,
        ),
    )

    reported = []
    for response, error_id in probes:
        assert response.status_code == 404, (
            f"{error_id} must answer 404, got {response.status_code}: {response.text}"
        )
        reported.append(err(response, error_id)["error_id"])

    assert len(reported) == 12, f"expected twelve probes, got {len(reported)}"
    assert len(set(reported)) == 12, (
        f"the twelve not-found ids must not collapse into fewer: {sorted(set(reported))}"
    )


def test_plan_slot_bid_and_assignment_state_errors_stay_separable(client):
    """Four sibling 409s fire from four different rows in one continuous build.

    "Removing a block entirely is permitted only while the owning plan is `DRAFT`, is refused with `ERR_PLAN_STATE_INVALID` otherwise, and is refused with `ERR_SLOT_STATE_INVALID` when any non-terminal bid or assignment still references the block; a successful removal recomputes the plan's four aggregates."

    "A `StaffingCoordinator` activates a plan that is `DRAFT`; a plan in any other status is refused with `ERR_PLAN_STATE_INVALID`."

    "A worker may withdraw their own bid from either `SUBMITTED` or `WAITLISTED`, and only their own — a withdrawal aimed at somebody else's bid is refused with `ERR_NOT_RESOURCE_OWNER`, and a withdrawal aimed at a terminal bid is refused with `ERR_BID_STATE_INVALID`."

    "Any action aimed at a row already in `COMPLETED`, `NO_SHOW`, `RELEASED` or `CANCELLED` is refused with `ERR_ASSIGNMENT_STATE_INVALID`, and so is a check-out on a row that has not yet checked in."

    Design: Corner/errors/plan_slot_bid_and_assignment_state_errors_are_triggerable
    """
    set_clock(client, "2026-09-10T09:00:00Z")
    event = _fixture_event(client, "State Error Fixture")
    family = create_position_type(client, **TICKET_TAKER)

    # an empty throwaway plan is activated first, purely to take the event to PLANNED
    opener = create_plan(client, event["id"])
    activate_plan(client, opener["id"], event["id"])
    assert_fields(read_plan(client, opener["id"]), status="ACTIVE")

    plan = create_plan(client, event["id"])
    assert_fields(plan, status="DRAFT")
    slot = create_slot(
        client,
        plan["id"],
        family["id"],
        zone_code="GATE_A",
        shift_start="2026-09-12T18:00:00Z",
        shift_end="2026-09-12T22:05:00Z",
        required_headcount_override=2,
    )

    bidder = create_member(
        client,
        full_name="Priya Raghunathan",
        seniority_date="2018-04-01T00:00:00Z",
        hourly_rate_cents=2000,
    )
    bid = create_bid(client, bidder["id"], slot["id"])
    assert_fields(bid, status="SUBMITTED")

    # the plan is still DRAFT, so the removal clears the plan rung and dies on the live bid
    err(
        client.delete_position_slot(slot["id"], COORDINATOR_HEADERS),
        ERR_SLOT_STATE_INVALID,
    )
    assert_fields(read_slot(client, slot["id"]), id=slot["id"], zone_code="GATE_A")

    activate_plan(client, plan["id"], event["id"])
    assert_fields(read_plan(client, plan["id"]), status="ACTIVE")

    settled_version = event_version(client, event["id"])
    err(
        client.activate_staffing_plan(
            plan["id"],
            plan_activate_payload(expected_event_version=settled_version),
            COORDINATOR_HEADERS,
        ),
        ERR_PLAN_STATE_INVALID,
    )
    assert event_version(client, event["id"]) == settled_version, (
        "a refused activation must not move the event version"
    )
    assert_fields(read_plan(client, plan["id"]), status="ACTIVE")

    ok(client.award_shift_bid(bid["id"], COORDINATOR_HEADERS))
    assert_fields(read_bid(client, bid["id"]), status="AWARDED", decision_reason="MANUAL_AWARD")

    err(
        client.withdraw_shift_bid(bid["id"], make_staff_member_headers(bidder["id"])),
        ERR_BID_STATE_INVALID,
    )
    assert_fields(read_bid(client, bid["id"]), status="AWARDED", decision_reason="MANUAL_AWARD")

    placements, meta = page(
        client.list_staff_assignments(COORDINATOR_HEADERS, {"shift_bid_id": bid["id"]})
    )
    assert meta["total_count"] == 1, f"the award must leave exactly one placement: {meta}"
    placement = placements[0]
    assert_fields(
        placement,
        source="BID_AWARD",
        attendance_status="SCHEDULED",
        payout_status="PENDING",
        shift_bid_id=bid["id"],
    )

    err(
        client.record_attendance(
            placement["id"], attendance_payload("CHECK_OUT"), COORDINATOR_HEADERS
        ),
        ERR_ASSIGNMENT_STATE_INVALID,
    )
    unmoved = read_assignment(client, placement["id"])
    assert_fields(unmoved, attendance_status="SCHEDULED", payout_status="PENDING")
    _absent(unmoved, "check_in_at", "check_out_at")


def test_backfill_and_member_status_errors_stay_separable(client):
    """A cancelled backfill request and a sidelined worker each refuse the next move.

    "It records the `position_slot_id` of the block left short, the `triggering_assignment_id` of the failure that opened it, and an `attempt_count` starting at 0, with `selected_staff_member_id`, `filled_assignment_id` and `cancel_reason` all absent, in status `OPEN`."

    "A coordinator may instead abandon an open request with a `cancel_reason`, moving it `OPEN → CANCELLED` and leaving the block in whatever fill state it already had; later auto-fill attempts against it are then refused with `ERR_BACKFILL_NOT_OPEN`."

    "Each successful change records the supplied `reason` in `last_status_reason` and sets `in_backfill_pool` to false when the worker becomes `SUSPENDED` or `TERMINATED` and to true when the worker becomes `ACTIVE`."

    "Sending a `target_status` equal to the worker's current status is refused with `ERR_VALIDATION_FAILED`, and any standing change attempted on a worker already in `TERMINATED` is refused with `ERR_STAFF_MEMBER_NOT_ACTIVE`."

    "The worker's `status` must be `ACTIVE` — `PROBATION`, `SUSPENDED` and `TERMINATED` are all refused with `ERR_STAFF_MEMBER_NOT_ACTIVE`."

    Design: Corner/errors/backfill_and_member_status_errors_are_triggerable
    """
    set_clock(client, "2026-09-10T09:00:00Z")
    event = _fixture_event(client, "Backfill Error Fixture")
    family = create_position_type(client, **TICKET_TAKER)
    plan = create_plan(client, event["id"])
    slot = create_slot(
        client,
        plan["id"],
        family["id"],
        zone_code="GATE_B",
        shift_start="2026-09-12T18:00:00Z",
        shift_end="2026-09-12T22:05:00Z",
        required_headcount_override=2,
    )
    absentee = create_member(
        client,
        full_name="Marcus Odalvo",
        seniority_date="2018-04-01T00:00:00Z",
        hourly_rate_cents=2000,
    )
    sidelined = create_member(
        client,
        full_name="Yelena Brackston",
        seniority_date="2019-04-01T00:00:00Z",
        hourly_rate_cents=2000,
    )
    activate_plan(client, plan["id"], event["id"])

    failing = create_assignment(client, slot["id"], absentee["id"])
    advance_event(client, event["id"], "IN_PROGRESS")
    struck = attendance(client, failing["id"], "NO_SHOW", at="2026-09-12T18:10:00Z")
    assert_fields(struck, attendance_status="NO_SHOW", payout_status="VOIDED")
    assert_slot_fill(read_slot(client, slot["id"]), filled=0, required=2, status="OPEN")

    opened = backfill_requests_for_assignment(client, failing["id"])
    assert len(opened) == 1, f"the no-show must open exactly one request: {ids_of(opened)}"
    request = opened[0]
    assert_fields(
        request,
        status="OPEN",
        position_slot_id=slot["id"],
        triggering_assignment_id=failing["id"],
        attempt_count=0,
    )
    _absent(request, "selected_staff_member_id", "filled_assignment_id", "cancel_reason")

    abandoned = ok(
        client.cancel_backfill_request(
            request["id"],
            cancel_backfill_payload("Gate B closed for the remainder of the event"),
            COORDINATOR_HEADERS,
        )
    )
    assert_fields(abandoned, status="CANCELLED", attempt_count=0)

    err(
        client.auto_fill_backfill_request(request["id"], COORDINATOR_HEADERS),
        ERR_BACKFILL_NOT_OPEN,
    )
    err(
        client.cancel_backfill_request(
            request["id"], cancel_backfill_payload("Second attempt"), COORDINATOR_HEADERS
        ),
        ERR_BACKFILL_NOT_OPEN,
    )
    still_cancelled = ok(client.get_backfill_request(request["id"], COORDINATOR_HEADERS))
    assert_fields(still_cancelled, status="CANCELLED", attempt_count=0)
    _absent(still_cancelled, "selected_staff_member_id", "filled_assignment_id")

    suspended = change_member_status(
        client, sidelined["id"], "SUSPENDED", "Pending conduct review"
    )
    assert_fields(
        suspended,
        status="SUSPENDED",
        in_backfill_pool=False,
        last_status_reason="Pending conduct review",
    )

    err(
        client.create_staff_assignment(
            staff_assignment_payload(slot["id"], sidelined["id"]), COORDINATOR_HEADERS
        ),
        ERR_STAFF_MEMBER_NOT_ACTIVE,
    )
    assert_slot_fill(read_slot(client, slot["id"]), filled=0, required=2, status="OPEN")

    terminated = change_member_status(
        client, sidelined["id"], "TERMINATED", "Review concluded against the worker"
    )
    assert_fields(
        terminated,
        status="TERMINATED",
        in_backfill_pool=False,
        last_status_reason="Review concluded against the worker",
    )

    err(
        client.staff_member_status_change(
            sidelined["id"],
            status_change_payload("ACTIVE", "Appeal upheld too late"),
            COORDINATOR_HEADERS,
        ),
        ERR_STAFF_MEMBER_NOT_ACTIVE,
    )
    assert_fields(read_member(client, sidelined["id"]), status="TERMINATED", in_backfill_pool=False)


def test_accessibility_resource_and_request_state_errors_stay_separable(client):
    """The pool's own status and the booking's own status raise two different refusals.

    "A new pool opens with `status` `AVAILABLE` and `peak_committed_units` at 0."

    "A new booking opens with `status` `REQUESTED` and with `confirmed_at`, `service_started_at`, `completed_at` and `denial_reason` all absent."

    "Six movements are permitted and no others; anything else is refused with `ERR_ACCESS_REQUEST_STATE_INVALID`."

    "The parent event must stand in `PLANNED` or `IN_PROGRESS`, or the request is refused with `ERR_EVENT_STATE_INVALID`; the pool's `status` must be `AVAILABLE`, or it is refused with `ERR_RESOURCE_NOT_AVAILABLE`; and the pool must have room across the whole of the requested window once this booking's own `units_requested` is counted in, or it is refused with `ERR_ACCESSIBILITY_CAPACITY_EXCEEDED`."

    "Cancellation from `CONFIRMED`, by contrast, releases capacity immediately: the pool's `peak_committed_units` over the affected window drops by the cancelled booking's `units_requested`."

    Design: Corner/errors/accessibility_resource_and_request_state_errors_are_triggerable
    """
    set_clock(client, "2026-09-12T10:00:00Z")
    event = _fixture_event(client, "Accessibility Error Fixture")
    plan = create_plan(client, event["id"])
    activate_plan(client, plan["id"], event["id"])
    assert_fields(read_event(client, event["id"]), status="PLANNED")

    pool = create_resource(
        client,
        event["id"],
        resource_type="WHEELCHAIR_ESCORT",
        zone_code="GATE_A",
        unit_count=4,
    )
    assert_fields(pool, status="AVAILABLE", unit_count=4, peak_committed_units=0)

    booking = create_booking(
        client,
        pool["id"],
        guest_reference="WILL-CALL-88",
        window_start="2026-09-12T18:00:00Z",
        window_end="2026-09-12T19:00:00Z",
        units_requested=1,
    )
    assert_fields(booking, status="REQUESTED", units_requested=1, companion_seats_requested=0)
    _absent(booking, "confirmed_at", "service_started_at", "completed_at", "denial_reason")

    # REQUESTED -> IN_SERVICE is not one of the six permitted movements
    err(
        client.transition_accessibility_request(
            booking["id"], access_transition_payload("IN_SERVICE"), SUPERVISOR_HEADERS
        ),
        ERR_ACCESS_REQUEST_STATE_INVALID,
    )
    assert_fields(
        ok(client.get_accessibility_request(booking["id"], SUPERVISOR_HEADERS)),
        status="REQUESTED",
    )

    assert_fields(set_resource_status(client, pool["id"], "MAINTENANCE"), status="MAINTENANCE")
    err(
        client.transition_accessibility_request(
            booking["id"], access_transition_payload("CONFIRMED"), SUPERVISOR_HEADERS
        ),
        ERR_RESOURCE_NOT_AVAILABLE,
    )
    assert_fields(read_resource(client, pool["id"]), unit_count=4, peak_committed_units=0)
    assert_fields(
        ok(client.get_accessibility_request(booking["id"], SUPERVISOR_HEADERS)),
        status="REQUESTED",
    )

    assert_fields(set_resource_status(client, pool["id"], "AVAILABLE"), status="AVAILABLE")
    confirmed = transition_booking(client, booking["id"], "CONFIRMED")
    assert_fields(confirmed, status="CONFIRMED")
    assert_instant(confirmed["confirmed_at"], "2026-09-12T10:00:00.000Z", "confirmed_at")
    assert_fields(read_resource(client, pool["id"]), unit_count=4, peak_committed_units=1)

    cancelled = transition_booking(client, booking["id"], "CANCELLED")
    assert_fields(cancelled, status="CANCELLED")
    assert_fields(read_resource(client, pool["id"]), unit_count=4, peak_committed_units=0)

    # CANCELLED is terminal, so no seventh movement out of it exists
    err(
        client.transition_accessibility_request(
            booking["id"], access_transition_payload("COMPLETED"), SUPERVISOR_HEADERS
        ),
        ERR_ACCESS_REQUEST_STATE_INVALID,
    )
    assert_fields(
        ok(client.get_accessibility_request(booking["id"], SUPERVISOR_HEADERS)),
        status="CANCELLED",
    )
    assert_fields(read_resource(client, pool["id"]), unit_count=4, peak_committed_units=0)


def test_slot_capacity_full_error_speaks_alone(client):
    """A one-head block fills on its first placement and refuses a flawless second worker.

    "Finally the block must have room — `filled_headcount` strictly below `required_headcount` — or the attempt is refused with `ERR_SLOT_CAPACITY_FULL`."

    "The resulting assignment carries `source` `MANUAL` with `shift_bid_id` absent, opens in `SCHEDULED` and `PENDING`, and increments the block's `filled_headcount` by 1."

    "Step one prices each block on its own: `slot_labor_cost_cents` is the block's `required_headcount` multiplied by the family's `base_hourly_rate_cents` multiplied by the block's `shift_minutes` divided by 60, rounded half up to whole cents, one block at a time. Step two sums those already-rounded per-block figures into `base_labor_cost_cents`; the exact products are never summed. Step three sums the blocks' `required_headcount` values into `total_required_headcount`, independently of any money. Step four selects an accessibility surcharge rate from that plan-level headcount total and never from an individual block: a total of 300 heads or more draws 900 basis points, at least 150 but fewer than 300 draws 600 basis points, at least 60 but fewer than 150 draws 350 basis points, and anything below 60 draws nothing. Step five computes `accessibility_surcharge_cents` as `base_labor_cost_cents` multiplied by that basis-point rate divided by 10000, rounded half up to whole cents. Step six adds the two together into `projected_labor_cost_cents`; the surcharge never re-enters the headcount total or the surcharge-tier selection."

    Design: Corner/errors/slot_capacity_full_error_is_triggerable
    """
    set_clock(client, "2026-09-10T09:00:00Z")
    event = _fixture_event(client, "Capacity Error Fixture")
    family = create_position_type(client, **TICKET_TAKER)
    plan = create_plan(client, event["id"])
    slot = create_slot(
        client,
        plan["id"],
        family["id"],
        zone_code="GATE_C",
        shift_start="2026-09-12T18:00:00Z",
        shift_end="2026-09-12T22:05:00Z",
        required_headcount_override=1,
    )
    incumbent = create_member(
        client,
        full_name="Rosalind Achebe",
        seniority_date="2018-04-01T00:00:00Z",
        hourly_rate_cents=2000,
    )
    latecomer = create_member(
        client,
        full_name="Tobias Fenwright",
        seniority_date="2019-04-01T00:00:00Z",
        hourly_rate_cents=2000,
    )
    activate_plan(client, plan["id"], event["id"])

    placed = create_assignment(client, slot["id"], incumbent["id"])
    assert_fields(
        placed, source="MANUAL", attendance_status="SCHEDULED", payout_status="PENDING"
    )
    _absent(placed, "shift_bid_id")
    # one head required, so the very first placement skips PARTIALLY_FILLED entirely
    assert_slot_fill(read_slot(client, slot["id"]), filled=1, required=1, status="FILLED")

    # the latecomer is ACTIVE, needs no credential, holds nothing else: only room is missing
    err(
        client.create_staff_assignment(
            staff_assignment_payload(slot["id"], latecomer["id"]), COORDINATOR_HEADERS
        ),
        ERR_SLOT_CAPACITY_FULL,
    )
    assert_slot_fill(read_slot(client, slot["id"]), filled=1, required=1, status="FILLED")

    placements, meta = page(
        client.list_staff_assignments(COORDINATOR_HEADERS, {"position_slot_id": slot["id"]})
    )
    assert meta["total_count"] == 1, f"the refusal must persist nothing: {meta}"
    assert ids_of(placements) == [placed["id"]]

    priced = read_plan(client, plan["id"])
    assert_fields(priced, total_required_headcount=1)
    assert_cents(priced["base_labor_cost_cents"], 8167, "plan base labor cost")
    assert_cents(priced["accessibility_surcharge_cents"], 0, "plan accessibility surcharge")
    assert_cents(priced["projected_labor_cost_cents"], 8167, "plan projected labor cost")
