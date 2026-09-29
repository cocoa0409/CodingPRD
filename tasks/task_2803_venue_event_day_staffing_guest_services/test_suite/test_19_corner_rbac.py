"""Role breadth: who may act, who may not, and who may not act twice on one refund."""

from test_helpers import (
    COORDINATOR_HEADERS,
    DIRECTOR_HEADERS,
    ERR_EVENT_STATE_INVALID,
    ERR_PAYOUT_PHASE_INVALID,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_NOT_RESOURCE_OWNER,
    SUPERVISOR_HEADERS,
    activate_plan,
    advance_event,
    assert_cents,
    assert_fields,
    assert_instant,
    assert_ledger,
    assert_slot_fill,
    attendance,
    certify,
    create_assignment,
    create_booking,
    create_event,
    create_member,
    create_plan,
    create_position_type,
    create_resource,
    create_satisfaction_response,
    create_slot,
    created,
    err,
    ids_of,
    make_director_headers,
    make_staff_member_headers,
    make_supervisor_headers,
    ok,
    page,
    read_assignment,
    read_event,
    read_issue,
    read_plan,
    read_slot,
    run_payout,
    set_clock,
)
from test_helpers.factories import (
    attendance_payload,
    event_lifecycle_payload,
    event_payload,
    guest_issue_payload,
    issue_assign_payload,
    issue_resolve_payload,
    payout_run_payload,
    refund_decision_payload,
    refund_request_payload,
    satisfaction_response_payload,
)

TICKET_TAKER = {
    "code": "TICKET_TAKER",
    "display_name": "Ticket Taker",
    "base_hourly_rate_cents": 2000,
    "attendance_ratio_per_1000": 0.8,
    "min_headcount": 1,
    "required_certifications": [],
}


def _fixture_event(client, name, **overrides):
    """The gate-day event these role recipes hang their rows from."""
    return create_event(
        client,
        name=name,
        event_date="2026-09-12T00:00:00Z",
        doors_open_at="2026-09-12T17:00:00Z",
        doors_close_at="2026-09-12T23:00:00Z",
        expected_attendance=6000,
        **overrides,
    )


def _quantized(actual, expected, label=""):
    """A two-decimal figure must arrive at exactly the half-up quantized value."""
    assert float(actual) == float(expected), (
        f"{label} must be exactly {expected}, got {actual!r}"
    )


def test_director_exclusive_lifecycle_and_payout_permitted(client):
    """Create, revise, drive and settle: the director's own chain, each write one version on.

    "A `GuestExperienceDirector` owns the event itself: it creates events, drives the event lifecycle, sets the guest-recovery budget and the gratuity pool, runs payouts, holds the larger refund cap, is the only role that may reverse an authorized refund, and is the only role that may resolve an issue that has been escalated."

    "A newly registered event opens in `FORECAST` with `version` 1, `refund_approved_total_cents` at 0, `refund_budget_remaining_cents` equal to `refund_budget_total_cents`, and `gratuity_allocated_cents` at 0."

    "On the event side, activation advances `FORECAST → PLANNED` when the event was still `FORECAST`, and in every case increments the event's `version` by exactly 1 — the same mutation the version guard protects."

    "The remaining event transitions are driven by a `GuestExperienceDirector` supplying a `target_status` and, optionally, a `reason`. Each of them increments the event's `version` by 1, and any transition the state machine does not declare from the current status is refused with `ERR_EVENT_STATE_INVALID`."

    "The `GRATUITY_ALLOCATION` phase distributes the event's tip pool; it demands that the event's `status` be `CLOSED` and that at least one gratuity-eligible assignment still sit at `payout_status` `ACCRUED`, failing which it is refused with `ERR_PAYOUT_PHASE_INVALID`."

    "The `PAYROLL` phase then settles everything; it demands that no gratuity-eligible assignment remain at `ACCRUED` awaiting its share, so attempting payroll before the gratuity run has been made is likewise refused with `ERR_PAYOUT_PHASE_INVALID`."

    Design: Corner/rbac/director_exclusive_lifecycle_and_payout_permitted
    """
    set_clock(client, "2026-09-12T10:00:00Z")

    event = created(
        client.create_event(
            event_payload(
                name="Director Chain",
                event_date="2026-09-12T00:00:00Z",
                doors_open_at="2026-09-12T17:00:00Z",
                doors_close_at="2026-09-12T23:00:00Z",
                expected_attendance=6000,
                refund_budget_total_cents=50000,
                gratuity_pool_cents=0,
            ),
            DIRECTOR_HEADERS,
        )
    )
    assert_fields(event, status="FORECAST", version=1, attendance_tier="TIER_1")
    assert_ledger(event, approved=0, remaining=50000, total=50000)
    assert_cents(event["gratuity_allocated_cents"], 0, "gratuity_allocated_cents")

    revised = ok(
        client.update_event(
            event["id"],
            {"expected_attendance": 12000, "refund_budget_total_cents": 60000},
            DIRECTOR_HEADERS,
        )
    )
    assert_fields(revised, version=2, expected_attendance=12000, attendance_tier="TIER_2")
    assert_ledger(revised, approved=0, remaining=60000, total=60000)

    plan = create_plan(client, event["id"])
    activate_plan(client, plan["id"], event["id"], expected_event_version=2)
    activated = read_event(client, event["id"])
    assert_fields(activated, status="PLANNED", version=3)

    running = ok(
        client.event_lifecycle(
            event["id"], event_lifecycle_payload("IN_PROGRESS"), DIRECTOR_HEADERS
        )
    )
    assert_fields(running, status="IN_PROGRESS", version=4)
    assert_fields(read_plan(client, plan["id"]), status="LOCKED")

    closed = ok(
        client.event_lifecycle(
            event["id"],
            event_lifecycle_payload("CLOSED", reason="Doors closed, house clear"),
            DIRECTOR_HEADERS,
        )
    )
    assert_fields(closed, status="CLOSED", version=5)

    # nothing was ever accrued, so the gratuity phase has no eligible row to distribute to
    err(
        client.event_payout_run(
            event["id"], payout_run_payload("GRATUITY_ALLOCATION"), DIRECTOR_HEADERS
        ),
        ERR_PAYOUT_PHASE_INVALID,
    )

    # payroll, by contrast, only demands that no eligible row is still waiting: none is
    settled = run_payout(client, event["id"], "PAYROLL")
    assert settled == [], f"payroll over an empty event settles nothing: {settled!r}"

    final = read_event(client, event["id"])
    assert_cents(final["gratuity_allocated_cents"], 0, "gratuity_allocated_cents")
    assert_ledger(final, approved=0, remaining=60000, total=60000)


def test_coordinator_and_supervisor_cannot_run_director_exclusive_operations(client):
    """Seven doors, three roles, one refusal each, and not a byte of the event moves.

    "When the headers are well formed but the declared role is not among the roles the target endpoint admits, the refusal is `ERR_ROLE_NOT_PERMITTED` (403)."

    "A `StaffingCoordinator` owns the labour supply side: position families, plans, shift blocks, workers, credentials, bid awards, direct assignments, attendance marking and backfill; it holds no refund authority and cannot move the event lifecycle."

    "Role authorization — the acting role is admitted by the endpoint (`ERR_ROLE_NOT_PERMITTED`)."

    Design: Corner/rbac/coordinator_and_supervisor_cannot_run_director_exclusive_operations
    """
    set_clock(client, "2026-09-12T10:00:00Z")
    event = _fixture_event(client, "Denial Fixture")
    assert_fields(event, status="FORECAST", version=1, expected_attendance=6000)
    worker = create_member(client, full_name="Ada Worker")

    intruder = event_payload(
        name="Intruder Event",
        event_date="2026-09-20T00:00:00Z",
        doors_open_at="2026-09-20T13:00:00Z",
        doors_close_at="2026-09-20T21:00:00Z",
        expected_attendance=1000,
    )
    err(client.create_event(intruder, COORDINATOR_HEADERS), ERR_ROLE_NOT_PERMITTED)
    err(client.create_event(intruder, SUPERVISOR_HEADERS), ERR_ROLE_NOT_PERMITTED)
    err(
        client.create_event(intruder, make_staff_member_headers(worker["id"])),
        ERR_ROLE_NOT_PERMITTED,
    )

    err(
        client.update_event(event["id"], {"expected_attendance": 99000}, COORDINATOR_HEADERS),
        ERR_ROLE_NOT_PERMITTED,
    )
    err(
        client.event_lifecycle(
            event["id"],
            event_lifecycle_payload("CANCELLED", reason="Not my call"),
            COORDINATOR_HEADERS,
        ),
        ERR_ROLE_NOT_PERMITTED,
    )
    err(
        client.event_lifecycle(
            event["id"], event_lifecycle_payload("IN_PROGRESS"), SUPERVISOR_HEADERS
        ),
        ERR_ROLE_NOT_PERMITTED,
    )
    # the role rung is reached before any phase or state rung, so this is not a payout error
    err(
        client.event_payout_run(
            event["id"], payout_run_payload("PAYROLL"), COORDINATOR_HEADERS
        ),
        ERR_ROLE_NOT_PERMITTED,
    )

    untouched = read_event(client, event["id"])
    assert_fields(untouched, status="FORECAST", version=1, expected_attendance=6000)

    events, meta = page(client.list_events(COORDINATOR_HEADERS, {"limit": 10, "offset": 0}))
    assert meta["total_count"] == 1, f"the three refused creates made nothing: {meta}"
    assert ids_of(events) == [event["id"]]


def test_supervisor_exclusive_guest_issue_operations_permitted(client):
    """Intake, recovery money and accessibility are the supervisor's, closed even to the director.

    "A `GuestServicesSupervisor` owns the guest-facing side: issue intake from the text line, kiosks and in-person desks, accessibility pools and bookings, satisfaction responses, and refund authority up to the smaller cap."

    "When the headers are well formed but the declared role is not among the roles the target endpoint admits, the refusal is `ERR_ROLE_NOT_PERMITTED` (403)."

    "It moves the issue `OPEN → IN_PROGRESS`, or `REOPENED → IN_PROGRESS` for an issue that had been reopened."

    "A supervisor first files the ask, supplying `refund_requested_cents`; the system stores that amount, records `refund_requested_by_user_id` from `X-User-ID`, and moves `refund_status` `NONE → PENDING`. No money moves and no ledger figure changes at this point."

    "A new pool opens with `status` `AVAILABLE` and `peak_committed_units` at 0."

    Design: Corner/rbac/supervisor_exclusive_guest_issue_operations_permitted
    """
    set_clock(client, "2026-09-12T19:00:00Z")
    event = _fixture_event(
        client, "Supervisor Exclusive Fixture", refund_budget_total_cents=100000
    )
    plan = create_plan(client, event["id"])
    activate_plan(client, plan["id"], event["id"])
    advance_event(client, event["id"], "IN_PROGRESS")

    responder = create_member(client, full_name="Ida Responder")
    certify(client, responder["id"], "CODE_OF_CONDUCT")

    issue = created(
        client.create_guest_issue(
            guest_issue_payload(
                event["id"], channel="KIOSK", category="OTHER", severity="MEDIUM",
                description="Kiosk complaint",
            ),
            make_supervisor_headers("sup-9"),
        )
    )
    assert_fields(issue, status="OPEN", reported_by_user_id="sup-9")

    handover = issue_assign_payload(responder["id"])
    err(client.assign_guest_issue(issue["id"], handover, DIRECTOR_HEADERS), ERR_ROLE_NOT_PERMITTED)
    err(
        client.assign_guest_issue(issue["id"], handover, COORDINATOR_HEADERS),
        ERR_ROLE_NOT_PERMITTED,
    )
    handed = ok(client.assign_guest_issue(issue["id"], handover, SUPERVISOR_HEADERS))
    assert_fields(handed, status="IN_PROGRESS", assigned_staff_member_id=responder["id"])

    ask = refund_request_payload(1500)
    err(client.file_refund_request(issue["id"], ask, DIRECTOR_HEADERS), ERR_ROLE_NOT_PERMITTED)
    filed = ok(client.file_refund_request(issue["id"], ask, SUPERVISOR_HEADERS))
    assert_fields(filed, refund_status="PENDING", refund_requested_by_user_id="u-supervisor-1")
    assert_cents(filed["refund_requested_cents"], 1500, "refund_requested_cents")
    assert_ledger(read_event(client, event["id"]), approved=0, remaining=100000, total=100000)

    pool_payload = {
        "event_id": event["id"],
        "resource_type": "ASSISTIVE_LISTENING_UNIT",
        "zone_code": "Z100",
        "unit_count": 6,
    }
    err(
        client.create_accessibility_resource(pool_payload, DIRECTOR_HEADERS),
        ERR_ROLE_NOT_PERMITTED,
    )
    pool = create_resource(
        client, event["id"], resource_type="ASSISTIVE_LISTENING_UNIT", zone_code="Z100",
        unit_count=6,
    )
    assert_fields(pool, status="AVAILABLE", unit_count=6, peak_committed_units=0)

    booking = create_booking(
        client,
        pool["id"],
        guest_reference="GUEST-7",
        window_start="2026-09-12T19:30:00Z",
        window_end="2026-09-12T21:00:00Z",
        units_requested=2,
        companion_seats_requested=1,
    )
    assert_fields(
        booking, status="REQUESTED", units_requested=2, companion_seats_requested=1
    )

    pools, meta = page(
        client.list_accessibility_resources(
            SUPERVISOR_HEADERS, {"event_id": event["id"], "limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 1, f"the director's refused pool was never staged: {meta}"
    assert ids_of(pools) == [pool["id"]]


def test_staff_member_cannot_mark_no_show_or_release(client):
    """One endpoint, three refusals for one worker: two on the action, one on the ownership.

    "Marking a no-show or releasing a worker from a shift is admitted only from `StaffingCoordinator`; a `StaffMember` sending either receives `ERR_ROLE_NOT_PERMITTED`, whereas a `StaffMember` sending a check-in against another worker's assignment receives `ERR_NOT_RESOURCE_OWNER`."

    "`CHECK_IN` and `CHECK_OUT` may be sent either by a `StaffingCoordinator` or by the worker who owns the assignment; `NO_SHOW` and `RELEASE` are coordinator-only, and a `StaffMember` sending either is refused with `ERR_ROLE_NOT_PERMITTED`."

    "The system stamps `check_in_at` from the current logical clock and freezes `late_check_in` at that moment: the flag is set when `check_in_at` falls strictly later than the block's `shift_start` plus a five-minute grace allowance, so a worker arriving exactly at the grace boundary is on time."

    "The assignment moves `SCHEDULED → NO_SHOW`, its `payout_status` is driven `PENDING → VOIDED` and `total_payout_cents` is set to 0."

    Design: Corner/rbac/staff_member_cannot_mark_no_show_or_release
    """
    set_clock(client, "2026-09-12T18:00:00Z")
    event = _fixture_event(client, "Attendance Role Fixture")
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
    m1 = create_member(
        client, full_name="M1 Worker", seniority_date="2018-01-01T00:00:00Z",
        hourly_rate_cents=2000,
    )
    m2 = create_member(
        client, full_name="M2 Worker", seniority_date="2019-01-01T00:00:00Z",
        hourly_rate_cents=2000,
    )
    activate_plan(client, plan["id"], event["id"])
    a1 = create_assignment(client, slot["id"], m1["id"])
    a2 = create_assignment(client, slot["id"], m2["id"])
    advance_event(client, event["id"], "IN_PROGRESS")
    assert_slot_fill(read_slot(client, slot["id"]), filled=2, required=2, status="FILLED")

    intruder = make_staff_member_headers(m1["id"])
    err(
        client.record_attendance(a2["id"], attendance_payload("NO_SHOW"), intruder),
        ERR_ROLE_NOT_PERMITTED,
    )
    err(
        client.record_attendance(a2["id"], attendance_payload("RELEASE"), intruder),
        ERR_ROLE_NOT_PERMITTED,
    )
    # CHECK_IN is a movement the role owns, so this one dies on ownership instead
    err(
        client.record_attendance(a2["id"], attendance_payload("CHECK_IN"), intruder),
        ERR_NOT_RESOURCE_OWNER,
    )
    standing = read_assignment(client, a2["id"])
    assert_fields(standing, attendance_status="SCHEDULED", payout_status="PENDING")
    assert standing.get("check_in_at") is None, "the three refusals stamped nothing"

    own = ok(client.record_attendance(a1["id"], attendance_payload("CHECK_IN"), intruder))
    assert_fields(own, attendance_status="CHECKED_IN", payout_status="PENDING", late_check_in=False)
    assert_instant(own["check_in_at"], "2026-09-12T18:00:00.000Z", "check_in_at")

    struck = attendance(client, a2["id"], "NO_SHOW")
    assert_fields(struck, attendance_status="NO_SHOW", payout_status="VOIDED")
    assert_cents(struck["total_payout_cents"], 0, "total_payout_cents")
    assert_slot_fill(read_slot(client, slot["id"]), filled=1, required=2, status="PARTIALLY_FILLED")


def test_peer_roles_shared_resolve_works_for_both_supervisor_and_director(client):
    """Resolve is genuinely shared from IN_PROGRESS and turns director-only at ESCALATED.

    "Resolving an issue records a `resolution_type` and moves the issue `IN_PROGRESS → RESOLVED` or `ESCALATED → RESOLVED`; from any other status it is refused with `ERR_ISSUE_STATE_INVALID`."

    "An issue categorised `OTHER` admits any of the eight resolutions."

    "A successful resolution stamps `resolved_at` from the current logical clock, records `resolved_by_user_id` from `X-User-ID`, freezes `sla_breached` at its computed value, stores `relocation_zone_code` when the resolution was a seat relocation, and makes the issue eligible for the resolved-issue counter of the post-event satisfaction summary."

    "Resolving an issue that sits in `ESCALATED` is admitted only from `GuestExperienceDirector`, even though the same supervisor may resolve the same issue from `IN_PROGRESS`."

    "The parent moves to `ESCALATED`, and a brand-new issue is created carrying `escalated_from_issue_id` pointing back at the parent, `severity` `CRITICAL`, `sla_minutes` 5, `sla_clock_started_at` set to the current logical clock, `status` `OPEN`, and the same `event_id`, `category`, `channel`, `seat_reference` and `description` as its parent."

    "A `GuestServicesSupervisor` or a `GuestExperienceDirector` files a response against an `event_id`, naming the `zone_code` it came from, a `score` between 1 and 5 inclusive, and an optional free-text `comment`; `submitted_by_user_id` is recorded from `X-User-ID`."

    Design: Corner/rbac/peer_roles_shared_resolve_works_for_both_supervisor_and_director
    """
    set_clock(client, "2026-09-12T19:00:00Z")
    event = _fixture_event(client, "Peer Roles Fixture")
    plan = create_plan(client, event["id"])
    activate_plan(client, plan["id"], event["id"])
    advance_event(client, event["id"], "IN_PROGRESS")
    responder = create_member(client, full_name="Ida Responder")
    certify(client, responder["id"], "CODE_OF_CONDUCT")

    def _file(description, headers):
        return created(
            client.create_guest_issue(
                guest_issue_payload(
                    event["id"], channel="TEXT_LINE", category="OTHER", severity="MEDIUM",
                    description=description,
                ),
                headers,
            )
        )

    gi_1 = _file("Issue one", make_supervisor_headers("sup-9"))
    gi_2 = _file("Issue two", make_director_headers("dir-9"))
    gi_3 = _file("Issue three", make_supervisor_headers("sup-9"))
    assert_instant(gi_1["sla_deadline"], "2026-09-12T19:45:00.000Z", "MEDIUM sla_deadline")

    handover = issue_assign_payload(responder["id"])
    for issue in (gi_1, gi_2, gi_3):
        handed = ok(client.assign_guest_issue(issue["id"], handover, SUPERVISOR_HEADERS))
        assert_fields(handed, status="IN_PROGRESS")

    set_clock(client, "2026-09-12T19:46:00Z")
    child = created(client.escalate_guest_issue(gi_3["id"], SUPERVISOR_HEADERS))
    assert_fields(
        child,
        status="OPEN",
        severity="CRITICAL",
        sla_minutes=5,
        escalated_from_issue_id=gi_3["id"],
        event_id=event["id"],
        category="OTHER",
        channel="TEXT_LINE",
    )
    escalated = read_issue(client, gi_3["id"])
    assert_fields(
        escalated,
        status="ESCALATED",
        sla_breached=True,
        assigned_staff_member_id=responder["id"],
    )

    quiet = issue_resolve_payload("NO_ACTION")
    by_supervisor = ok(
        client.resolve_guest_issue(gi_1["id"], quiet, make_supervisor_headers("sup-1"))
    )
    assert_fields(by_supervisor, status="RESOLVED", resolved_by_user_id="sup-1")
    by_director = ok(
        client.resolve_guest_issue(gi_2["id"], quiet, make_director_headers("dir-1"))
    )
    assert_fields(by_director, status="RESOLVED", resolved_by_user_id="dir-1")

    err(
        client.resolve_guest_issue(gi_3["id"], quiet, make_supervisor_headers("sup-1")),
        ERR_ROLE_NOT_PERMITTED,
    )
    assert_fields(read_issue(client, gi_3["id"]), status="ESCALATED")
    escalated_resolved = ok(
        client.resolve_guest_issue(gi_3["id"], quiet, make_director_headers("dir-1"))
    )
    assert_fields(escalated_resolved, status="RESOLVED", resolved_by_user_id="dir-1")

    from_supervisor = created(
        client.create_satisfaction_response(
            satisfaction_response_payload(event["id"], zone_code="Z100", score=4),
            make_supervisor_headers("sup-1"),
        )
    )
    assert_fields(from_supervisor, submitted_by_user_id="sup-1", score=4)
    from_director = created(
        client.create_satisfaction_response(
            satisfaction_response_payload(event["id"], zone_code="Z100", score=5),
            make_director_headers("dir-1"),
        )
    )
    assert_fields(from_director, submitted_by_user_id="dir-1", score=5)


def test_supervisor_cannot_read_staffing_model_recommendation(client):
    """The two computed reads exclude opposite roles, and neither is open to a worker.

    "It is available to a `GuestExperienceDirector` or a `StaffingCoordinator`, requires the event's `status` to be `CLOSED` — otherwise it is refused with `ERR_EVENT_STATE_INVALID` — and works from the event's `LOCKED` plan, considering that plan's shift blocks other than the `CLOSED` ones."

    "The `understaffed_slot_count` is the number of the plan's blocks whose `status` is `UNDERSTAFFED_ESCALATED`, and the `average_score` is the sentiment average described above, absent when the event drew no responses at all."

    "Within a group, `planned_headcount` is the sum of the blocks' `required_headcount`, `worked_headcount` is the number of assignments on those blocks whose `attendance_status` is `COMPLETED`, and `no_show_count` is the number whose `attendance_status` is `NO_SHOW`."

    "When `fill_rate_bp` is strictly below 8000 the factor is 1.10 and the direction is `INCREASE`."

    "When there is at least one, `average_score` is the sum of the scores divided by the count, quantized to two decimal places by rounding half up — eight responses summing to 35 give exactly 4.375, which is reported as 4.38 and not 4.37 — and `promoter_share_bp` is the count of responses scoring 4 or better, multiplied by 10000, divided by the total count, and rounded half up to a whole number of basis points."

    "When the headers are well formed but the declared role is not among the roles the target endpoint admits, the refusal is `ERR_ROLE_NOT_PERMITTED` (403)."

    Design: Corner/rbac/supervisor_cannot_read_staffing_model_recommendation
    """
    set_clock(client, "2026-09-12T23:30:00Z")
    closed_event = _fixture_event(client, "Mirror Reads A")
    open_event = create_event(
        client,
        name="Mirror Reads B",
        event_date="2026-09-20T00:00:00Z",
        doors_open_at="2026-09-20T13:00:00Z",
        doors_close_at="2026-09-20T21:00:00Z",
        expected_attendance=6000,
    )
    family = create_position_type(client, **TICKET_TAKER)
    plan = create_plan(client, closed_event["id"])
    create_slot(
        client,
        plan["id"],
        family["id"],
        zone_code="Z100",
        shift_start="2026-09-12T18:00:00Z",
        shift_end="2026-09-12T22:05:00Z",
        required_headcount_override=2,
    )
    worker = create_member(client, full_name="Ada Worker")
    activate_plan(client, plan["id"], closed_event["id"])
    create_satisfaction_response(client, closed_event["id"], "Z100", 4)
    create_satisfaction_response(client, closed_event["id"], "Z100", 5)
    advance_event(client, closed_event["id"], "IN_PROGRESS")
    advance_event(client, closed_event["id"], "CLOSED")
    assert_fields(read_event(client, closed_event["id"]), status="CLOSED")

    other_plan = create_plan(client, open_event["id"])
    activate_plan(client, other_plan["id"], open_event["id"])
    assert_fields(read_event(client, open_event["id"]), status="PLANNED")

    for_director = ok(
        client.get_staffing_model_recommendation(closed_event["id"], DIRECTOR_HEADERS)
    )
    assert_fields(for_director, event_id=closed_event["id"], understaffed_slot_count=0)
    _quantized(for_director["average_score"], 4.50, "recommendation average_score")
    group = for_director["position_recommendations"][0]
    assert_fields(
        group, planned_headcount=2, worked_headcount=0, no_show_count=0, fill_rate_bp=0,
        direction="INCREASE",
    )
    _quantized(group["recommended_ratio_per_1000"], 0.88, "recommended_ratio_per_1000")

    for_coordinator = ok(
        client.get_staffing_model_recommendation(closed_event["id"], COORDINATOR_HEADERS)
    )
    assert for_coordinator == for_director, (
        "the coordinator reads the same recommendation body as the director"
    )
    err(
        client.get_staffing_model_recommendation(closed_event["id"], SUPERVISOR_HEADERS),
        ERR_ROLE_NOT_PERMITTED,
    )
    err(
        client.get_staffing_model_recommendation(
            closed_event["id"], make_staff_member_headers(worker["id"])
        ),
        ERR_ROLE_NOT_PERMITTED,
    )

    for_supervisor = ok(client.get_satisfaction_summary(closed_event["id"], SUPERVISOR_HEADERS))
    assert_fields(for_supervisor, response_count=2)
    _quantized(for_supervisor["average_score"], 4.50, "summary average_score")
    summary_for_director = ok(
        client.get_satisfaction_summary(closed_event["id"], DIRECTOR_HEADERS)
    )
    assert_fields(summary_for_director, response_count=2)
    err(
        client.get_satisfaction_summary(closed_event["id"], COORDINATOR_HEADERS),
        ERR_ROLE_NOT_PERMITTED,
    )
    err(
        client.get_satisfaction_summary(
            closed_event["id"], make_staff_member_headers(worker["id"])
        ),
        ERR_ROLE_NOT_PERMITTED,
    )

    # the role rung passes for the director, and only then does the CLOSED requirement bite
    err(
        client.get_staffing_model_recommendation(open_event["id"], DIRECTOR_HEADERS),
        ERR_EVENT_STATE_INVALID,
    )


def test_reporter_cannot_decide_the_refund_on_their_own_issue(client):
    """Three separate people are structurally required to move one refund cent.

    "The `X-User-ID` that decides a refund on a guest issue must differ both from the `refund_requested_by_user_id` recorded when the ask was filed and from the `reported_by_user_id` recorded when the issue was first filed. A violation is refused with `ERR_SEGREGATION_OF_DUTIES` (403)."

    "The amount authorized is then the smallest of three figures: the `refund_requested_cents` asked for, the effective cap, and that available budget."

    "First a role cap: 5000 cents for a `GuestServicesSupervisor` and 50000 cents for a `GuestExperienceDirector`."

    "It is stored in `refund_approved_cents`, and `refund_status` becomes `APPROVED` when the authorized amount equals the full request and `PARTIALLY_APPROVED` otherwise."

    Design: Corner/rbac/reporter_cannot_decide_the_refund_on_their_own_issue
    """
    set_clock(client, "2026-09-12T19:00:00Z")
    event = _fixture_event(client, "Segregation Fixture", refund_budget_total_cents=100000)
    plan = create_plan(client, event["id"])
    activate_plan(client, plan["id"], event["id"])
    advance_event(client, event["id"], "IN_PROGRESS")
    responder = create_member(client, full_name="Ida Responder")
    certify(client, responder["id"], "CODE_OF_CONDUCT")

    issue = created(
        client.create_guest_issue(
            guest_issue_payload(
                event["id"], channel="TEXT_LINE", category="OTHER", severity="MEDIUM",
                description="Double charged",
            ),
            make_supervisor_headers("sup-9"),
        )
    )
    assert_fields(issue, reported_by_user_id="sup-9")
    ok(
        client.assign_guest_issue(
            issue["id"], issue_assign_payload(responder["id"]), make_supervisor_headers("sup-9")
        )
    )
    filed = ok(
        client.file_refund_request(
            issue["id"], refund_request_payload(1500), make_supervisor_headers("sup-1")
        )
    )
    assert_fields(filed, refund_status="PENDING", refund_requested_by_user_id="sup-1")

    approve = refund_decision_payload("APPROVE")
    # the reporter is barred, and presenting the higher role changes nothing
    err(
        client.file_refund_decision(issue["id"], approve, make_supervisor_headers("sup-9")),
        ERR_SEGREGATION_OF_DUTIES,
    )
    err(
        client.file_refund_decision(issue["id"], approve, make_director_headers("sup-9")),
        ERR_SEGREGATION_OF_DUTIES,
    )
    # the requester is barred too, and a denial is barred exactly like an approval
    err(
        client.file_refund_decision(
            issue["id"], refund_decision_payload("DENY"), make_supervisor_headers("sup-1")
        ),
        ERR_SEGREGATION_OF_DUTIES,
    )
    assert_ledger(read_event(client, event["id"]), approved=0, remaining=100000, total=100000)

    decided = ok(
        client.file_refund_decision(issue["id"], approve, make_supervisor_headers("sup-2"))
    )
    assert_fields(decided, refund_status="APPROVED", refund_decided_by_user_id="sup-2")
    assert_cents(decided["refund_approved_cents"], 1500, "refund_approved_cents")
    assert_ledger(read_event(client, event["id"]), approved=1500, remaining=98500, total=100000)
