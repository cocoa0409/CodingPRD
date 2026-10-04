"""Rebuild events, capacity accounting, and enrollment lifecycles (PRD §3.6)."""

from test_helpers import (
    ApiErrorId,
    api_client,
    create_candidate,
    create_cycle,
    create_eligible_volunteer,
    create_enrollment_payload,
    create_event,
    create_published_event,
    enroll_volunteer,
    get_enrollment,
    get_event,
    get_project,
    get_project_for_application,
    get_scope_item,
    make_volunteer_headers,
    open_selection,
    reset_clock,
    run_selection,
    set_clock,
    setup_event_with_team_leader,
    setup_selected_project,
    validate_error,
    validate_ok,
    validate_paginated,
    DEFAULT_EVENT_CLOCK_ISO,
    STAFF,
)


def _setup_two_project_cycle():
    """One cycle with two selected volunteer-only projects."""
    reset_clock()
    cycle = create_cycle()
    ctx1 = create_candidate(cycle["id"], homeowner_name="Site One")
    ctx2 = create_candidate(cycle["id"], homeowner_name="Site Two")
    open_selection(cycle["id"])
    sel = run_selection(cycle["id"])
    assert sel["apply"]["applied_count"] == 2
    p1 = get_project_for_application(ctx1["application"]["id"])
    p2 = get_project_for_application(ctx2["application"]["id"])
    return cycle, p1, p2


def test_event_capacity_fills_exactly():
    """PRD §3.6: "The enrollment that brings the active count equal to
    `max_volunteers` succeeds; the next attempt fails with
    `ERR_EVENT_AT_CAPACITY`."
    PRD §3.6: "An event's `open_slots` is `max_volunteers` minus the count of
    active enrollments — those in `ENROLLED`, `CONFIRMED`, or `CHECKED_IN` —
    and a team-leader enrollment occupies one slot exactly like any other."

    With max_volunteers 2, the team-leader enrollment and the second general
    enrollment both succeed; active count equals max and open_slots is 0.

    Design: Difficulty/boundary_precision_check/event_capacity_fills_exactly_then_rejects
    """
    ctx = setup_selected_project()
    event = create_published_event(
        ctx["project"]["id"], event_date="2026-10-10", max_volunteers=2
    )
    leader = create_eligible_volunteer(team_leader_eligible=True)
    enroll_volunteer(event["id"], leader["id"], is_team_leader=True)
    second = create_eligible_volunteer()
    enrollment2 = enroll_volunteer(event["id"], second["id"])
    assert enrollment2["status"] == "ENROLLED", (
        "the enrollment reaching equality with max_volunteers succeeds"
    )
    assert get_event(event["id"])["open_slots"] == 0


def test_event_capacity_rejects_beyond_max():
    """PRD §3.6: "The enrollment that brings the active count equal to
    `max_volunteers` succeeds; the next attempt fails with
    `ERR_EVENT_AT_CAPACITY`."

    The third enrollment against a full event is the one rejected, and no seat
    is freed or consumed by the failure.

    Design: Difficulty/boundary_precision_check/event_capacity_fills_exactly_then_rejects
    """
    ctx = setup_selected_project()
    event = create_published_event(
        ctx["project"]["id"], event_date="2026-10-10", max_volunteers=2
    )
    leader = create_eligible_volunteer(team_leader_eligible=True)
    enroll_volunteer(event["id"], leader["id"], is_team_leader=True)
    second = create_eligible_volunteer()
    enroll_volunteer(event["id"], second["id"])
    third = create_eligible_volunteer()
    resp = api_client.create_enrollment(
        create_enrollment_payload(event["id"], third["id"]),
        make_volunteer_headers(third["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_EVENT_AT_CAPACITY)
    assert get_event(event["id"])["open_slots"] == 0


def test_volunteer_same_day_double_booking_rejected():
    """PRD §3.6: "The event must be `PUBLISHED` (`ERR_EVENT_NOT_PUBLISHED`),
    the volunteer must satisfy `is_eligible` (`ERR_VOLUNTEER_NOT_ELIGIBLE`), a
    slot must be free, and the volunteer must not already hold an active
    enrollment on another event sharing the same calendar `event_date`
    (`ERR_VOLUNTEER_DOUBLE_BOOKED`)."

    Two events sharing only the calendar event_date collide under whole-day
    semantics, regardless of any time-of-day.

    Design: Difficulty/resource_temporal_overlap/volunteer_same_calendar_day_double_booking
    """
    _, p1, p2 = _setup_two_project_cycle()
    e1 = create_published_event(p1["id"], name="Day One A", event_date="2026-10-10")
    e2 = create_published_event(p2["id"], name="Day One B", event_date="2026-10-10")
    volunteer = create_eligible_volunteer()
    enroll_volunteer(e1["id"], volunteer["id"])
    resp = api_client.create_enrollment(
        create_enrollment_payload(e2["id"], volunteer["id"]),
        make_volunteer_headers(volunteer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VOLUNTEER_DOUBLE_BOOKED)


def test_volunteer_next_day_enrollment_succeeds():
    """PRD §3.6: "The event must be `PUBLISHED` (`ERR_EVENT_NOT_PUBLISHED`),
    the volunteer must satisfy `is_eligible` (`ERR_VOLUNTEER_NOT_ELIGIBLE`), a
    slot must be free, and the volunteer must not already hold an active
    enrollment on another event sharing the same calendar `event_date`
    (`ERR_VOLUNTEER_DOUBLE_BOOKED`)."

    The adjacent calendar day is free: after a 2026-10-10 enrollment, a
    2026-10-11 event accepts the same volunteer.

    Design: Difficulty/resource_temporal_overlap/volunteer_same_calendar_day_double_booking
    """
    _, p1, p2 = _setup_two_project_cycle()
    e1 = create_published_event(p1["id"], name="Day One A", event_date="2026-10-10")
    e3 = create_published_event(p2["id"], name="Day Two B", event_date="2026-10-11")
    volunteer = create_eligible_volunteer()
    enroll_volunteer(e1["id"], volunteer["id"])
    enrollment3 = enroll_volunteer(e3["id"], volunteer["id"])
    assert enrollment3["status"] == "ENROLLED"


def test_event_slots_released_on_withdrawal():
    """PRD §3.6: "Volunteers (or staff) may withdraw an `ENROLLED` or
    `CONFIRMED` enrollment to `WITHDRAWN`, releasing the slot so `open_slots`
    rises."
    PRD §3.6: "The invariant that `max_volunteers` equals the active count plus
    `open_slots` holds at all times, and an enrollment paired with a later
    withdrawal leaves `open_slots` unchanged."

    Two active enrollments against max_volunteers 3 leave open_slots 1;
    withdrawing one returns it to 2.

    Design: Difficulty/compensating_invariant/event_slots_conserved_across_enroll_withdraw_reenroll
    """
    ctx = setup_selected_project()
    event = create_published_event(
        ctx["project"]["id"], event_date="2026-10-10", max_volunteers=3
    )
    v1 = create_eligible_volunteer()
    v2 = create_eligible_volunteer()
    enr1 = enroll_volunteer(event["id"], v1["id"])
    enroll_volunteer(event["id"], v2["id"])
    assert get_event(event["id"])["open_slots"] == 1
    withdrawn = validate_ok(
        api_client.patch_enrollment(
            enr1["id"], {"status": "WITHDRAWN"}, make_volunteer_headers(v1["id"])
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert get_event(event["id"])["open_slots"] == 2, (
        "the withdrawal released exactly one seat"
    )


def test_event_slots_consumed_on_reenrollment():
    """PRD §3.6: "A withdrawn enrollment may later re-enroll (`WITHDRAWN` →
    `ENROLLED`), and re-enrollment re-runs the full creation gauntlet: the
    event still `PUBLISHED`, the volunteer still eligible, a slot free, the
    same-day double-booking check re-evaluated, and — for a `Volunteer` actor —
    ownership of the enrollment."

    Re-enrollment consumes the seat again: open_slots returns to the exact
    pre-withdrawal figure 1.

    Design: Difficulty/compensating_invariant/event_slots_conserved_across_enroll_withdraw_reenroll
    """
    ctx = setup_selected_project()
    event = create_published_event(
        ctx["project"]["id"], event_date="2026-10-10", max_volunteers=3
    )
    v1 = create_eligible_volunteer()
    v2 = create_eligible_volunteer()
    enr1 = enroll_volunteer(event["id"], v1["id"])
    enroll_volunteer(event["id"], v2["id"])
    validate_ok(
        api_client.patch_enrollment(
            enr1["id"], {"status": "WITHDRAWN"}, make_volunteer_headers(v1["id"])
        )
    )
    reenrolled = validate_ok(
        api_client.patch_enrollment(
            enr1["id"], {"status": "ENROLLED"}, make_volunteer_headers(v1["id"])
        )
    )
    assert reenrolled["status"] == "ENROLLED", (
        "WITHDRAWN -> ENROLLED is a legal cycle while the event is PUBLISHED"
    )
    assert get_event(event["id"])["open_slots"] == 1


def test_event_terminal_cancelled_rejects_execute():
    """PRD §3.6: "Executing a `LOCKED` event requires the clock date to be on
    or after `event_date`."
    PRD §2.10: "6. State-machine from-state legality (`ERR_INVALID_STATE` and
    the specific state errors `ERR_CYCLE_NOT_SELECTION_OPEN`,
    `ERR_EVENT_NOT_PUBLISHED`, `ERR_EVENT_NOT_LOCKABLE`,
    `ERR_PROJECT_NOT_COMPLETED`)."

    A CANCELLED event is terminal: EXECUTED names LOCKED as its only source
    state, so the attempt is a from-state violation with no side effects.

    Design: Corner/state_machines/event_terminal_cancelled_rejects_execute
    """
    ctx = setup_selected_project()
    event = create_published_event(
        ctx["project"]["id"], event_date="2026-10-10", max_volunteers=2
    )
    validate_ok(api_client.patch_event(event["id"], {"status": "CANCELLED"}, STAFF))
    resp = api_client.patch_event(event["id"], {"status": "EXECUTED"}, STAFF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_event(event["id"])["status"] == "CANCELLED"


def test_event_execute_settles_attendance_and_completes_volunteer_items():
    """PRD §3.6: "Execution finalizes attendance — every `CHECKED_IN`
    enrollment becomes `COMPLETED` and every still-`CONFIRMED` enrollment
    becomes `NO_SHOW` — completes the volunteer work by moving every `INCLUDED`
    scope item of the project's assessment with `volunteer_performable` true to
    `COMPLETED`, and advances the project `EVENT_SCHEDULED` → `IN_BUILD`."

    The executed event fans out deterministically: the checked-in leader
    completes, the merely-confirmed volunteer is a no-show, the volunteer scope
    item completes, and the project enters the build.

    Design: Corner/state_machines/event_execute_settles_attendance_and_completes_volunteer_items
    """
    ctx = setup_selected_project()
    ev = setup_event_with_team_leader(
        ctx["project"]["id"], event_date="2026-10-10", max_volunteers=3
    )
    ghost = create_eligible_volunteer()
    enr2 = enroll_volunteer(ev["event"]["id"], ghost["id"])
    validate_ok(api_client.patch_event(ev["event"]["id"], {"status": "LOCKED"}, STAFF))
    set_clock(DEFAULT_EVENT_CLOCK_ISO)
    validate_ok(
        api_client.patch_enrollment(
            ev["leader_enrollment"]["id"],
            {"status": "CHECKED_IN"},
            make_volunteer_headers(ev["leader"]["id"]),
        )
    )
    validate_ok(api_client.patch_event(ev["event"]["id"], {"status": "EXECUTED"}, STAFF))
    assert get_enrollment(ev["leader_enrollment"]["id"])["status"] == "COMPLETED"
    assert get_enrollment(enr2["id"])["status"] == "NO_SHOW", (
        "still merely CONFIRMED at execution"
    )
    item = get_scope_item(ctx["scope_items"][0]["id"])
    assert item["status"] == "COMPLETED", (
        "the volunteer-performable item is completed by the executed event"
    )
    assert get_project(ctx["project"]["id"])["status"] == "IN_BUILD"


def test_second_team_leader_enrollment_returns_already_assigned():
    """PRD §3.6: "A payload setting `is_team_leader` adds two further checks:
    the volunteer must be `team_leader_eligible` (else `ERR_INVALID_REQUEST`),
    and the event must not already carry an active team-leader enrollment (else
    `ERR_TEAM_LEADER_ALREADY_ASSIGNED`)."

    Exactly one active team-leader enrollment per event: a second
    is_team_leader=true enrollment is rejected while the same volunteer's
    general enrollment passes.

    Design: Corner/validations/second_team_leader_enrollment_returns_already_assigned
    """
    ctx = setup_selected_project()
    ev = setup_event_with_team_leader(
        ctx["project"]["id"], event_date="2026-10-10", max_volunteers=5
    )
    second = create_eligible_volunteer(team_leader_eligible=True)
    resp = api_client.create_enrollment(
        create_enrollment_payload(
            ev["event"]["id"], second["id"], is_team_leader=True
        ),
        make_volunteer_headers(second["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TEAM_LEADER_ALREADY_ASSIGNED)
    general = enroll_volunteer(ev["event"]["id"], second["id"])
    assert general["status"] == "ENROLLED"
    assert general["is_team_leader"] is False


def test_enroll_in_draft_event_returns_event_not_published():
    """PRD §3.6: "The event must be `PUBLISHED` (`ERR_EVENT_NOT_PUBLISHED`),
    the volunteer must satisfy `is_eligible` (`ERR_VOLUNTEER_NOT_ELIGIBLE`), a
    slot must be free, and the volunteer must not already hold an active
    enrollment on another event sharing the same calendar `event_date`
    (`ERR_VOLUNTEER_DOUBLE_BOOKED`)."

    A DRAFT event rejects enrollment even when the volunteer is fully eligible
    and seats are free; no seat is consumed.

    Design: Corner/endpoints/enroll_in_draft_event_returns_event_not_published
    """
    ctx = setup_selected_project()
    event = create_event(
        ctx["project"]["id"], name="Draft Day", event_date="2026-10-10",
        max_volunteers=5,
    )
    volunteer = create_eligible_volunteer()
    resp = api_client.create_enrollment(
        create_enrollment_payload(event["id"], volunteer["id"]),
        make_volunteer_headers(volunteer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_PUBLISHED)
    assert get_event(event["id"])["open_slots"] == 5


def test_enrollment_side_effects_visible_immediately():
    """PRD §3.6: "An event's `open_slots` is `max_volunteers` minus the count
    of active enrollments — those in `ENROLLED`, `CONFIRMED`, or `CHECKED_IN` —
    and a team-leader enrollment occupies one slot exactly like any other."

    Immediate consistency: the very next reads after a 201 enrollment already
    show open_slots decremented and the enrollment row listed.

    Design: Corner/consistency_model/enrollment_side_effects_visible_immediately_in_same_reads
    """
    ctx = setup_selected_project()
    event = create_published_event(
        ctx["project"]["id"], name="Now Day", event_date="2026-10-10",
        max_volunteers=3,
    )
    volunteer = create_eligible_volunteer()
    enrollment = enroll_volunteer(event["id"], volunteer["id"])
    assert get_event(event["id"])["open_slots"] == 2
    rows, _ = validate_paginated(
        api_client.list_enrollments(STAFF, params={"event_id": event["id"]})
    )
    matched = [row for row in rows if row["id"] == enrollment["id"]]
    assert len(matched) == 1
    assert matched[0]["status"] == "ENROLLED"
