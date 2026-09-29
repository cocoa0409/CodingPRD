"""State-machine breadth: declared initial states, legal arcs and refused arcs."""

from test_helpers import (
    COORDINATOR_HEADERS,
    DIRECTOR_HEADERS,
    ERR_ACCESS_REQUEST_STATE_INVALID,
    ERR_ASSIGNMENT_STATE_INVALID,
    ERR_BID_STATE_INVALID,
    ERR_EVENT_STATE_INVALID,
    ERR_ISSUE_STATE_INVALID,
    ERR_PLAN_STATE_INVALID,
    SUPERVISOR_HEADERS,
    SUPERVISOR_USER_ID,
    activate_plan,
    advance_event,
    assert_cents,
    assert_fields,
    assert_instant,
    assert_payout_totals,
    assert_ratio,
    assert_slot_fill,
    attendance,
    award_bid,
    backfill_requests_for_slot,
    create_assignment,
    create_bid,
    create_booking,
    create_event,
    create_issue,
    create_member,
    create_plan,
    create_resource,
    create_slot,
    create_ticket_taker,
    created,
    err,
    event_version,
    make_staff_member_headers,
    ok,
    page,
    read_assignment,
    read_bid,
    read_event,
    read_issue,
    read_member,
    read_plan,
    read_resource,
    read_slot,
    set_clock,
    transition_booking,
    withdraw_bid,
)
from test_helpers.factories import (
    access_transition_payload,
    attendance_payload,
    event_lifecycle_payload,
    plan_activate_payload,
)

EVENT_DATE = "2026-09-12T00:00:00Z"
DOORS_OPEN = "2026-09-12T17:00:00Z"
DOORS_CLOSE = "2026-09-12T23:00:00Z"
SHIFT_START = "2026-09-12T18:00:00Z"
SHIFT_END = "2026-09-12T22:00:00Z"


def _unset(entity, *fields):
    """A field the PRD calls absent reads as missing or null, never as a value."""
    for field in fields:
        assert entity.get(field) is None, (
            f"{field} should be absent here, got {entity.get(field)!r}"
        )


def _staffed_event(client, *, clock, name, zone_code, required_headcount_override=2):
    """An event in FORECAST with a DRAFT plan carrying one ticket-taker block."""
    set_clock(client, clock)
    event = create_event(
        client,
        name=name,
        event_date=EVENT_DATE,
        doors_open_at=DOORS_OPEN,
        doors_close_at=DOORS_CLOSE,
        expected_attendance=20000,
    )
    family = create_ticket_taker(
        client,
        base_hourly_rate_cents=2000,
        attendance_ratio_per_1000=0.8,
        min_headcount=3,
        required_certifications=[],
    )
    plan = create_plan(client, event["id"], plan_variant="FORECAST_BASED")
    slot = create_slot(
        client,
        plan["id"],
        family["id"],
        zone_code=zone_code,
        shift_start=SHIFT_START,
        shift_end=SHIFT_END,
        required_headcount_override=required_headcount_override,
    )
    return {"event": event, "family": family, "plan": plan, "slot": slot}


def _worker(client, full_name, seniority_date, hourly_rate_cents=2000):
    return create_member(
        client,
        full_name=full_name,
        employment_type="PART_TIME_EMPLOYEE",
        seniority_date=seniority_date,
        hourly_rate_cents=hourly_rate_cents,
    )


def test_every_row_this_workflow_creates_opens_in_its_declared_state(client):
    """Nine entity families, each read back at the instant it was created.

    "A bid opens in `SUBMITTED` with `submitted_at` stamped from the current logical
    clock, `rank_score` absent and `decision_reason` absent."

    "A new booking opens with `status` `REQUESTED` and with `confirmed_at`,
    `service_started_at`, `completed_at` and `denial_reason` all absent."

    Design: Corner/state_machines/every_created_entity_starts_in_its_declared_initial_state
    """
    context = _staffed_event(
        client, clock="2026-09-01T12:00:00Z", name="Initial State Sweep", zone_code="Z410"
    )

    assert_fields(context["event"], status="FORECAST", version=1)
    plan = read_plan(client, context["plan"]["id"])
    assert_fields(plan, status="DRAFT", revision_number=1, total_required_headcount=2)
    _unset(plan, "activated_at")
    assert_slot_fill(read_slot(client, context["slot"]["id"]), filled=0, required=2, status="OPEN")

    worker = _worker(client, "Tess Alaro", "2024-01-05T00:00:00Z")
    bidder = _worker(client, "Urs Beltra", "2024-02-05T00:00:00Z")
    assert_fields(
        worker,
        status="ACTIVE",
        in_backfill_pool=True,
        reliability_score=100,
        season_reliability_score=100,
        no_show_strikes=0,
        completed_assignment_count=0,
    )
    _unset(worker, "last_status_reason")

    activate_plan(client, context["plan"]["id"], context["event"]["id"])

    bid = create_bid(client, bidder["id"], context["slot"]["id"])
    assert_fields(bid, status="SUBMITTED")
    assert_instant(bid["submitted_at"], "2026-09-01T12:00:00.000Z", "submitted_at")
    _unset(bid, "rank_score", "decision_reason")

    assignment = create_assignment(client, context["slot"]["id"], worker["id"])
    assert_fields(assignment, attendance_status="SCHEDULED", payout_status="PENDING", source="MANUAL")
    _unset(assignment, "shift_bid_id", "check_in_at", "checked_out_at")

    issue = create_issue(client, context["event"]["id"])
    assert_fields(issue, status="OPEN", refund_status="NONE", reopen_count=0)
    assert_cents(issue["refund_requested_cents"], 0, "refund_requested_cents")
    _unset(issue, "assigned_staff_member_id", "resolved_at", "resolution_type")

    pool = create_resource(client, context["event"]["id"])
    assert_fields(pool, status="AVAILABLE", peak_committed_units=0)

    booking = create_booking(client, pool["id"])
    assert_fields(booking, status="REQUESTED")
    _unset(booking, "confirmed_at", "service_started_at", "completed_at", "denial_reason")

    _items, meta = page(client.list_backfill_requests(COORDINATOR_HEADERS))
    assert meta["total_count"] == 0, "nothing in this sequence opens a backfill request"


def test_activation_stamps_the_plan_and_promotes_the_event_together(client):
    """One write moves two rows: the plan into ACTIVE and the event into PLANNED.

    "On success the plan moves `DRAFT → ACTIVE`, its `activated_at` is stamped with the
    current logical clock, and its four aggregates are recomputed by the costing pass of
    §3.2."

    "On the event side, activation advances `FORECAST → PLANNED` when the event was
    still `FORECAST`, and in every case increments the event's `version` by exactly 1 —
    the same mutation the version guard protects."

    Design: Corner/state_machines/plan_activation_promotes_event_and_stamps_activated_at
    """
    context = _staffed_event(
        client, clock="2026-09-02T10:00:00Z", name="Activation Arc", zone_code="Z411"
    )

    activated = activate_plan(client, context["plan"]["id"], context["event"]["id"], 1)

    assert_fields(activated, status="ACTIVE", total_required_headcount=2)
    assert_instant(activated["activated_at"], "2026-09-02T10:00:00.000Z", "activated_at")
    assert_cents(activated["base_labor_cost_cents"], 16000, "base_labor_cost_cents")
    assert_cents(activated["accessibility_surcharge_cents"], 0, "accessibility_surcharge_cents")
    assert_cents(activated["projected_labor_cost_cents"], 16000, "projected_labor_cost_cents")

    assert_fields(read_event(client, context["event"]["id"]), status="PLANNED", version=2)


def test_closing_the_event_releases_the_unworked_rows_and_opens_the_recommendation(client):
    """The close arc voids the money on scheduled rows and unlocks the season read.

    "On success, every assignment on that locked plan whose `attendance_status` is
    `SCHEDULED` is set to `RELEASED` and its `payout_status` driven to `VOIDED`, and
    every shift block touched by that release has its `filled_headcount` recomputed and
    its `status` re-derived."

    "This particular release opens no backfill request and triggers no reliability
    recomputation."

    Design: Corner/state_machines/event_close_releases_scheduled_assignments_and_voids_payout
    """
    context = _staffed_event(
        client, clock="2026-09-03T09:00:00Z", name="Close Release Arc", zone_code="Z412"
    )
    event_id = context["event"]["id"]
    slot_id = context["slot"]["id"]
    first = _worker(client, "Vic Cardew", "2024-03-05T00:00:00Z")
    second = _worker(client, "Wynn Doss", "2024-04-05T00:00:00Z")
    activate_plan(client, context["plan"]["id"], event_id)
    first_row = create_assignment(client, slot_id, first["id"])
    second_row = create_assignment(client, slot_id, second["id"])
    advance_event(client, event_id, "IN_PROGRESS")

    err(client.get_staffing_model_recommendation(event_id, DIRECTOR_HEADERS), ERR_EVENT_STATE_INVALID)

    closed = advance_event(client, event_id, "CLOSED")
    assert_fields(closed, status="CLOSED", version=4)

    for row in (first_row, second_row):
        settled = read_assignment(client, row["id"])
        assert_fields(settled, attendance_status="RELEASED", payout_status="VOIDED")
        assert_cents(settled["total_payout_cents"], 0, "total_payout_cents")
    assert_slot_fill(read_slot(client, slot_id), filled=0, required=2, status="OPEN")
    assert_fields(read_plan(client, context["plan"]["id"]), status="LOCKED")
    assert backfill_requests_for_slot(client, slot_id) == [], (
        "the close release opens no backfill request"
    )
    assert_fields(read_member(client, first["id"]), reliability_score=100, no_show_strikes=0)

    recommendation = ok(client.get_staffing_model_recommendation(event_id, DIRECTOR_HEADERS))
    assert_fields(recommendation, event_id=event_id, understaffed_slot_count=0)
    groups = recommendation["position_recommendations"]
    assert len(groups) == 1, f"one position family was planned, got {len(groups)} groups"
    assert_fields(
        groups[0],
        position_type_id=context["family"]["id"],
        planned_headcount=2,
        worked_headcount=0,
        no_show_count=0,
        fill_rate_bp=0,
        direction="INCREASE",
    )
    assert_ratio(groups[0]["recommended_ratio_per_1000"], 0.88, "recommended_ratio_per_1000")


def test_a_locked_plan_can_no_longer_be_activated(client):
    """LOCKED is terminal for a plan, and a fresh version does not buy a second arc.

    "A `StaffingCoordinator` activates a plan that is `DRAFT`; a plan in any other
    status is refused with `ERR_PLAN_STATE_INVALID`."

    Design: Corner/state_machines/plan_activate_from_locked_state_rejected
    """
    context = _staffed_event(
        client, clock="2026-09-03T10:00:00Z", name="Locked Plan Arc", zone_code="Z413"
    )
    event_id = context["event"]["id"]
    plan_id = context["plan"]["id"]
    activate_plan(client, plan_id, event_id)
    advance_event(client, event_id, "IN_PROGRESS")
    assert_fields(read_plan(client, plan_id), status="LOCKED")

    live_version = event_version(client, event_id)
    assert live_version == 3, f"one creation, one activation, one advance; got {live_version}"

    err(
        client.activate_staffing_plan(
            plan_id, plan_activate_payload(expected_event_version=live_version), COORDINATOR_HEADERS
        ),
        ERR_PLAN_STATE_INVALID,
    )

    assert_fields(read_plan(client, plan_id), status="LOCKED")
    assert_fields(read_event(client, event_id), status="IN_PROGRESS", version=3)


def test_a_closed_or_cancelled_event_accepts_no_further_movement(client):
    """Both terminal events refuse a lifecycle call, and the closed one refuses a revision.

    "`CLOSED` and `CANCELLED` are terminal for an event, and `SUPERSEDED`, `LOCKED` and
    `VOIDED` are terminal for a plan."

    "Once the event has reached `IN_PROGRESS`, `CLOSED` or `CANCELLED`, a revision is
    refused with `ERR_EVENT_STATE_INVALID`, and it is precisely this refusal that freezes
    the headcounts of a locked plan."

    Design: Corner/state_machines/event_terminal_states_reject_further_lifecycle_calls
    """
    context = _staffed_event(
        client, clock="2026-09-03T11:00:00Z", name="Terminal Close Arc", zone_code="Z414"
    )
    closed_id = context["event"]["id"]
    activate_plan(client, context["plan"]["id"], closed_id)
    advance_event(client, closed_id, "IN_PROGRESS")
    advance_event(client, closed_id, "CLOSED")

    cancelled = create_event(
        client,
        name="Terminal Cancel Arc",
        event_date=EVENT_DATE,
        doors_open_at=DOORS_OPEN,
        doors_close_at=DOORS_CLOSE,
        expected_attendance=20000,
    )
    cancelled_id = cancelled["id"]
    advance_event(client, cancelled_id, "CANCELLED")
    assert_fields(read_event(client, cancelled_id), status="CANCELLED", version=2)

    for event_id, target in (
        (closed_id, "CANCELLED"),
        (closed_id, "IN_PROGRESS"),
        (cancelled_id, "IN_PROGRESS"),
        (cancelled_id, "CLOSED"),
    ):
        err(
            client.event_lifecycle(event_id, event_lifecycle_payload(target), DIRECTOR_HEADERS),
            ERR_EVENT_STATE_INVALID,
        )

    err(
        client.update_event(closed_id, {"expected_attendance": 21000}, DIRECTOR_HEADERS),
        ERR_EVENT_STATE_INVALID,
    )
    err(
        client.update_event(cancelled_id, {"expected_attendance": 21000}, DIRECTOR_HEADERS),
        ERR_EVENT_STATE_INVALID,
    )

    assert_fields(read_event(client, closed_id), status="CLOSED", version=4, expected_attendance=20000)
    assert_fields(
        read_event(client, cancelled_id), status="CANCELLED", version=2, expected_attendance=20000
    )


def test_awarding_the_same_bid_a_second_time_is_refused(client):
    """AWARDED is terminal, so the replay mints no second assignment.

    "The bid must be `SUBMITTED`; a bid already `AWARDED`, `DECLINED_BY_SYSTEM` or
    `WITHDRAWN` is refused with `ERR_BID_STATE_INVALID`."

    Design: Corner/state_machines/bid_award_twice_second_attempt_rejected
    """
    context = _staffed_event(
        client, clock="2026-09-04T09:00:00Z", name="Award Replay Arc", zone_code="Z415"
    )
    slot_id = context["slot"]["id"]
    activate_plan(client, context["plan"]["id"], context["event"]["id"])
    bidder = _worker(client, "Xan Everly", "2024-05-05T00:00:00Z")
    bid = create_bid(client, bidder["id"], slot_id)

    awarded = award_bid(client, bid["id"])
    assert_fields(awarded, status="AWARDED", decision_reason="MANUAL_AWARD")
    rows, _meta = page(client.list_staff_assignments(COORDINATOR_HEADERS, {"position_slot_id": slot_id}))
    assert len(rows) == 1, f"the award mints exactly one assignment, got {len(rows)}"
    assert_fields(rows[0], source="BID_AWARD", shift_bid_id=bid["id"], attendance_status="SCHEDULED")
    assert_slot_fill(read_slot(client, slot_id), filled=1, required=2, status="PARTIALLY_FILLED")

    err(client.award_shift_bid(bid["id"], COORDINATOR_HEADERS), ERR_BID_STATE_INVALID)

    assert_fields(read_bid(client, bid["id"]), status="AWARDED", decision_reason="MANUAL_AWARD")
    rows_after, _meta_after = page(
        client.list_staff_assignments(COORDINATOR_HEADERS, {"position_slot_id": slot_id})
    )
    assert len(rows_after) == 1, "the refused replay must not mint a second assignment"
    assert_slot_fill(read_slot(client, slot_id), filled=1, required=2, status="PARTIALLY_FILLED")


def test_the_attendance_arcs_only_run_in_their_declared_order(client):
    """Checking out before checking in, and both actions replayed, are all refused.

    "Any action aimed at a row already in `COMPLETED`, `NO_SHOW`, `RELEASED` or
    `CANCELLED` is refused with `ERR_ASSIGNMENT_STATE_INVALID`, and so is a check-out on
    a row that has not yet checked in."

    Design: Corner/state_machines/assignment_checkout_before_checkin_rejected
    """
    context = _staffed_event(
        client, clock="2026-09-12T17:30:00Z", name="Attendance Order Arc", zone_code="Z416"
    )
    event_id = context["event"]["id"]
    activate_plan(client, context["plan"]["id"], event_id)
    worker = _worker(client, "Yara Foss", "2024-06-05T00:00:00Z")
    assignment = create_assignment(client, context["slot"]["id"], worker["id"])
    advance_event(client, event_id, "IN_PROGRESS")

    err(
        client.record_attendance(assignment["id"], attendance_payload("CHECK_OUT"), COORDINATOR_HEADERS),
        ERR_ASSIGNMENT_STATE_INVALID,
    )
    still_scheduled = read_assignment(client, assignment["id"])
    assert_fields(still_scheduled, attendance_status="SCHEDULED", payout_status="PENDING")
    _unset(still_scheduled, "check_in_at", "checked_out_at")

    checked_in = attendance(client, assignment["id"], "CHECK_IN", at="2026-09-12T18:00:00Z")
    assert_fields(checked_in, attendance_status="CHECKED_IN", payout_status="PENDING", late_check_in=False)

    err(
        client.record_attendance(assignment["id"], attendance_payload("CHECK_IN"), COORDINATOR_HEADERS),
        ERR_ASSIGNMENT_STATE_INVALID,
    )
    assert_fields(read_assignment(client, assignment["id"]), attendance_status="CHECKED_IN")

    completed = attendance(client, assignment["id"], "CHECK_OUT", at="2026-09-12T20:00:00Z")
    assert_fields(
        completed, attendance_status="COMPLETED", payout_status="ACCRUED", worked_minutes=120
    )
    assert_payout_totals(completed, base=4000, gratuity=0, total=4000)

    err(
        client.record_attendance(assignment["id"], attendance_payload("CHECK_OUT"), COORDINATOR_HEADERS),
        ERR_ASSIGNMENT_STATE_INVALID,
    )
    assert_fields(
        read_assignment(client, assignment["id"]),
        attendance_status="COMPLETED",
        payout_status="ACCRUED",
        worked_minutes=120,
    )
    assert_fields(
        read_member(client, worker["id"]), completed_assignment_count=1, reliability_score=100
    )


def test_a_worker_still_clocked_in_blocks_the_close_until_they_clock_out(client):
    """The close gate reads the attendance dimension of every row on the locked plan.

    "Advancing `IN_PROGRESS → CLOSED` requires that no assignment on any shift block of
    the event's locked plan is still standing in `CHECKED_IN`; a worker who has clocked
    in and not clocked out blocks the close with `ERR_ASSIGNMENT_STATE_INVALID`."

    Design: Corner/state_machines/event_close_with_checked_in_assignment_rejected
    """
    context = _staffed_event(
        client, clock="2026-09-12T17:30:00Z", name="Close Gate Arc", zone_code="Z417"
    )
    event_id = context["event"]["id"]
    slot_id = context["slot"]["id"]
    activate_plan(client, context["plan"]["id"], event_id)
    on_shift = _worker(client, "Zeke Gantry", "2024-07-05T00:00:00Z")
    absent = _worker(client, "Ada Hollis", "2024-08-05T00:00:00Z")
    worked_row = create_assignment(client, slot_id, on_shift["id"])
    idle_row = create_assignment(client, slot_id, absent["id"])
    advance_event(client, event_id, "IN_PROGRESS")
    attendance(client, worked_row["id"], "CHECK_IN", at="2026-09-12T18:00:00Z")

    err(
        client.event_lifecycle(event_id, event_lifecycle_payload("CLOSED"), DIRECTOR_HEADERS),
        ERR_ASSIGNMENT_STATE_INVALID,
    )
    assert_fields(read_event(client, event_id), status="IN_PROGRESS", version=3)
    assert_fields(read_assignment(client, idle_row["id"]), attendance_status="SCHEDULED")

    attendance(client, worked_row["id"], "CHECK_OUT", at="2026-09-12T21:00:00Z")
    closed = advance_event(client, event_id, "CLOSED")
    assert_fields(closed, status="CLOSED", version=4)

    settled = read_assignment(client, worked_row["id"])
    assert_fields(
        settled, attendance_status="COMPLETED", payout_status="ACCRUED", worked_minutes=180
    )
    assert_payout_totals(settled, base=6000, gratuity=0, total=6000)
    released = read_assignment(client, idle_row["id"])
    assert_fields(released, attendance_status="RELEASED", payout_status="VOIDED")
    assert_cents(released["total_payout_cents"], 0, "total_payout_cents")
    assert_slot_fill(read_slot(client, slot_id), filled=1, required=2, status="PARTIALLY_FILLED")


def _breachable_issue(client):
    """A MEDIUM issue filed at 18:30Z, so its 45-minute allowance expires at 19:15Z."""
    set_clock(client, "2026-09-12T18:30:00Z")
    event = create_event(
        client,
        name="Escalation Clock Arc",
        event_date=EVENT_DATE,
        doors_open_at=DOORS_OPEN,
        doors_close_at=DOORS_CLOSE,
        expected_attendance=20000,
    )
    issue = create_issue(
        client,
        event["id"],
        channel="TEXT_LINE",
        category="SEAT_RELOCATION",
        severity="MEDIUM",
        description="Guest asked to be moved away from a broken seat.",
        seat_reference="112-R-14",
    )
    assert_fields(issue, status="OPEN", severity="MEDIUM", sla_minutes=45, sla_breached=False)
    assert_instant(issue["sla_deadline"], "2026-09-12T19:15:00.000Z", "sla_deadline")
    return {"event": event, "issue": issue}


def test_escalation_is_refused_while_the_allowance_still_holds(client):
    """Ten minutes early is refused, and so is the deadline instant itself.

    "A supervisor may escalate from `OPEN` or from `IN_PROGRESS`, but only while
    `sla_breached` evaluates true at the current logical clock; escalating an issue that
    is still inside its allowance is refused with `ERR_ISSUE_STATE_INVALID`."

    Design: Corner/state_machines/escalate_without_sla_breach_rejected
    """
    context = _breachable_issue(client)
    issue_id = context["issue"]["id"]

    set_clock(client, "2026-09-12T19:10:00Z")
    err(client.escalate_guest_issue(issue_id, SUPERVISOR_HEADERS), ERR_ISSUE_STATE_INVALID)
    assert_fields(read_issue(client, issue_id), status="OPEN", sla_breached=False)

    set_clock(client, "2026-09-12T19:15:00Z")
    err(client.escalate_guest_issue(issue_id, SUPERVISOR_HEADERS), ERR_ISSUE_STATE_INVALID)

    parent = read_issue(client, issue_id)
    assert_fields(parent, status="OPEN", sla_breached=False, severity="MEDIUM", sla_minutes=45)

    children, child_meta = page(
        client.list_guest_issues(SUPERVISOR_HEADERS, {"escalated_from_issue_id": issue_id})
    )
    assert children == [], "a refused escalation must mint no child issue"
    assert child_meta["total_count"] == 0, "a refused escalation must mint no child issue"
    _all, all_meta = page(client.list_guest_issues(SUPERVISOR_HEADERS))
    assert all_meta["total_count"] == 1, "only the parent issue exists"


def test_escalation_mints_a_critical_child_on_a_restarted_clock(client):
    """One minute past the deadline the valve opens and the child is what comes back.

    "The parent moves to `ESCALATED`, and a brand-new issue is created carrying
    `escalated_from_issue_id` pointing back at the parent, `severity` `CRITICAL`,
    `sla_minutes` 5, `sla_clock_started_at` set to the current logical clock, `status`
    `OPEN`, and the same `event_id`, `category`, `channel`, `seat_reference` and
    `description` as its parent."

    Design: Corner/state_machines/escalate_creates_critical_child_issue_with_five_minute_sla
    """
    context = _breachable_issue(client)
    parent_id = context["issue"]["id"]

    set_clock(client, "2026-09-12T19:16:00Z")
    child = created(client.escalate_guest_issue(parent_id, SUPERVISOR_HEADERS))

    assert_fields(
        child,
        status="OPEN",
        severity="CRITICAL",
        sla_minutes=5,
        sla_breached=False,
        escalated_from_issue_id=parent_id,
        event_id=context["event"]["id"],
        channel="TEXT_LINE",
        category="SEAT_RELOCATION",
        seat_reference="112-R-14",
        description=context["issue"]["description"],
        reported_by_user_id=SUPERVISOR_USER_ID,
    )
    assert child["id"] != parent_id, "the escalation returns the child, not the parent"
    assert_instant(child["sla_clock_started_at"], "2026-09-12T19:16:00.000Z", "sla_clock_started_at")
    assert_instant(child["sla_deadline"], "2026-09-12T19:21:00.000Z", "sla_deadline")

    parent = read_issue(client, parent_id)
    assert_fields(parent, status="ESCALATED", severity="MEDIUM", sla_minutes=45, sla_breached=True)
    assert_instant(parent["sla_clock_started_at"], "2026-09-12T18:30:00.000Z", "parent clock")
    _unset(parent, "escalated_from_issue_id")


def test_a_withdrawn_bid_can_be_neither_awarded_nor_withdrawn_again(client):
    """WITHDRAWN is terminal, so both later movements answer with the same refusal.

    "A worker may withdraw their own bid from either `SUBMITTED` or `WAITLISTED`, and
    only their own — a withdrawal aimed at somebody else's bid is refused with
    `ERR_NOT_RESOURCE_OWNER`, and a withdrawal aimed at a terminal bid is refused with
    `ERR_BID_STATE_INVALID`."

    Design: Corner/state_machines/bid_withdraw_then_award_is_rejected
    """
    context = _staffed_event(
        client, clock="2026-09-04T10:00:00Z", name="Withdraw Arc", zone_code="Z418"
    )
    slot_id = context["slot"]["id"]
    activate_plan(client, context["plan"]["id"], context["event"]["id"])
    bidder = _worker(client, "Bram Ives", "2024-09-05T00:00:00Z")
    bid = create_bid(client, bidder["id"], slot_id)

    withdrawn = withdraw_bid(client, bid["id"], bidder["id"])
    assert_fields(withdrawn, status="WITHDRAWN", decision_reason="WITHDRAWN_BY_MEMBER")

    err(client.award_shift_bid(bid["id"], COORDINATOR_HEADERS), ERR_BID_STATE_INVALID)
    err(
        client.withdraw_shift_bid(bid["id"], make_staff_member_headers(bidder["id"])),
        ERR_BID_STATE_INVALID,
    )

    assert_fields(read_bid(client, bid["id"]), status="WITHDRAWN", decision_reason="WITHDRAWN_BY_MEMBER")
    rows, meta = page(client.list_staff_assignments(COORDINATOR_HEADERS, {"position_slot_id": slot_id}))
    assert rows == [], "a withdrawn bid never becomes an assignment"
    assert meta["total_count"] == 0, "a withdrawn bid never becomes an assignment"
    assert_slot_fill(read_slot(client, slot_id), filled=0, required=2, status="OPEN")


def test_a_booking_cannot_jump_straight_from_requested_into_service(client):
    """Only six movements exist, and REQUESTED reaches service only through CONFIRMED.

    "Six movements are permitted and no others; anything else is refused with
    `ERR_ACCESS_REQUEST_STATE_INVALID`."

    "Beginning service moves a booking `CONFIRMED → IN_SERVICE` and requires the event to
    stand exactly in `IN_PROGRESS` and the pool to be `AVAILABLE`; it stamps
    `service_started_at` and continues to occupy the booking's `units_requested`."

    Design: Corner/state_machines/accessibility_in_service_direct_from_requested_rejected
    """
    context = _staffed_event(
        client, clock="2026-09-12T17:45:00Z", name="Booking Arc", zone_code="Z419"
    )
    event_id = context["event"]["id"]
    activate_plan(client, context["plan"]["id"], event_id)
    advance_event(client, event_id, "IN_PROGRESS")
    pool = create_resource(
        client, event_id, resource_type="WHEELCHAIR_ESCORT", zone_code="Z419", unit_count=2
    )
    booking = create_booking(
        client,
        pool["id"],
        guest_reference="WILL-CALL-88",
        window_start="2026-09-12T18:00:00Z",
        window_end="2026-09-12T20:00:00Z",
        units_requested=1,
    )

    for target in ("IN_SERVICE", "COMPLETED"):
        err(
            client.transition_accessibility_request(
                booking["id"], access_transition_payload(target), SUPERVISOR_HEADERS
            ),
            ERR_ACCESS_REQUEST_STATE_INVALID,
        )
    still_requested = read_resource(client, pool["id"])
    assert_fields(still_requested, peak_committed_units=0, status="AVAILABLE")
    _unset(
        ok(client.get_accessibility_request(booking["id"], SUPERVISOR_HEADERS)),
        "confirmed_at",
        "service_started_at",
    )

    set_clock(client, "2026-09-12T17:50:00Z")
    confirmed = transition_booking(client, booking["id"], "CONFIRMED")
    assert_fields(confirmed, status="CONFIRMED")
    assert_instant(confirmed["confirmed_at"], "2026-09-12T17:50:00.000Z", "confirmed_at")
    assert_fields(read_resource(client, pool["id"]), peak_committed_units=1)

    set_clock(client, "2026-09-12T18:05:00Z")
    in_service = transition_booking(client, booking["id"], "IN_SERVICE")
    assert_fields(in_service, status="IN_SERVICE")
    assert_instant(in_service["service_started_at"], "2026-09-12T18:05:00.000Z", "service_started_at")
    assert_fields(read_resource(client, pool["id"]), peak_committed_units=1)
