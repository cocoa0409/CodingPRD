"""Scheduling tracking dates: engagement gates, room occupancy and AFM booking guards."""
from test_helpers import (
    ApiErrorId,
    add_shortlisted_demo,
    assert_musician_booking,
    assert_session_call,
    book_musician,
    create_musician,
    create_studio_room,
    get_project,
    get_session_call,
    make_producer_headers,
    schedule_session_call,
    set_afm_clearance,
    set_clock,
    setup_engagement_in_demo,
    setup_engagement_in_production,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_session_call_cannot_be_scheduled_while_the_engagement_is_in_demo(api):
    """PRD §3.4: "A `MusicHouseProducer` books a date against a `project_id` and a
    `studio_room_id`, giving the downbeat as `scheduled_start_utc` and the planned wrap
    as `scheduled_end_utc`; scheduling against an engagement that is not
    `IN_PRODUCTION` is refused with `ERR_PROJECT_NOT_IN_PRODUCTION`."

    Design: Difficulty/cross_entity_state_dependency/session_call_creation_gated_by_project_status_in_demo
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_demo(budget_cents=4_000_000)
    add_shortlisted_demo(env, title="Sunrise Pop", demo_fee_cents=150_000,
                         submitted_length_seconds=60)
    room = create_studio_room()

    response = api.create_session_call(
        {"project_id": env["project"]["id"], "studio_room_id": room["id"],
         "scheduled_start_utc": "2026-09-10T09:00:00Z",
         "scheduled_end_utc": "2026-09-10T13:00:00Z"},
        make_producer_headers())
    validate_error(response, ApiErrorId.ERR_PROJECT_NOT_IN_PRODUCTION.value, 409)


def test_rejected_session_call_leaves_no_row_and_no_engagement_change(api):
    """PRD §2.5: "**Ancestor state.** The associated engagement or deal is in the status
    the operation requires: brief creation needs the engagement `DRAFT` or `BRIEFING`
    (`ERR_PROJECT_NOT_IN_BRIEFING`); demo creation, demo submission, shortlisting,
    revision requests and demo selection need it `IN_DEMO` (`ERR_PROJECT_NOT_IN_DEMO`);
    session-call scheduling, session-call confirmation and licence-deal drafting need it
    `IN_PRODUCTION` (`ERR_PROJECT_NOT_IN_PRODUCTION`); cue-sheet registration needs the
    governing licence deal `ACTIVE` (`ERR_LICENSE_NOT_ACTIVE`)."

    Design: Difficulty/cross_entity_state_dependency/session_call_creation_gated_by_project_status_in_demo
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_demo(budget_cents=4_000_000)
    add_shortlisted_demo(env, title="Sunrise Pop", demo_fee_cents=150_000,
                         submitted_length_seconds=60)
    room = create_studio_room()

    validate_error(
        api.create_session_call(
            {"project_id": env["project"]["id"], "studio_room_id": room["id"],
             "scheduled_start_utc": "2026-09-10T09:00:00Z",
             "scheduled_end_utc": "2026-09-10T13:00:00Z"},
            make_producer_headers()),
        ApiErrorId.ERR_PROJECT_NOT_IN_PRODUCTION.value, 409)

    _, meta = validate_paginated(api.list_session_calls(
        make_producer_headers(), params={"project_id": env["project"]["id"]}))
    assert meta["total_count"] == 0, (
        f"No call may be stored behind the gate; got {meta['total_count']}")
    project = get_project(env["project"]["id"])
    assert project["status"] == "IN_DEMO", f"Expected IN_DEMO, got {project['status']}"


def test_room_accepts_a_call_starting_exactly_when_another_ends(api):
    """PRD §3.4: "A room's occupancy interval is **half-open** — it includes the
    downbeat and excludes the wrap — and carries no buffer at all."
    PRD §3.4: "Exact adjacency is therefore allowed: a call starting at the very instant
    another one ends, or ending at the very instant another one starts, is accepted."
    PRD §3.4: "Its `scheduled_hours` is the elapsed time from `scheduled_start_utc` to
    `scheduled_end_utc` expressed in hours and held to four decimal places, and its
    `billed_hours` equals `scheduled_hours` until the call is completed."

    Design: Difficulty/resource_temporal_overlap/studio_room_half_open_window_allows_touching_rejects_crossing
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production(demo_fee_cents=150_000, submitted_length_seconds=60)
    room = create_studio_room()
    schedule_session_call(env["project"]["id"], room["id"],
                          start="2026-09-10T09:00:00Z", end="2026-09-10T13:00:00Z")

    response = api.create_session_call(
        {"project_id": env["project"]["id"], "studio_room_id": room["id"],
         "scheduled_start_utc": "2026-09-10T13:00:00Z",
         "scheduled_end_utc": "2026-09-10T15:00:00Z"},
        make_producer_headers())
    touching = validate_success(response, 201)
    assert_session_call(touching)
    assert touching["status"] == "SCHEDULED", f"Expected SCHEDULED, got {touching['status']}"
    assert touching["scheduled_hours"] == 2, (
        f"A 13:00-15:00 window is 2 hours; got {touching['scheduled_hours']}")

    _, meta = validate_paginated(api.list_session_calls(
        make_producer_headers(), params={"studio_room_id": room["id"]}))
    assert meta["total_count"] == 2, (
        f"The room must now hold both adjacent calls; got {meta['total_count']}")


def test_room_rejects_a_call_crossing_an_occupied_window(api):
    """PRD §3.4: "The requested window is refused with `ERR_STUDIO_ROOM_DOUBLE_BOOKED`
    when it intersects any other call on the same room whose status is `SCHEDULED`,
    `SUSPENDED_BUDGET`, `CONFIRMED` or `COMPLETED`; concretely, the conflict exists when
    the new downbeat is strictly before the other call's wrap and the new wrap is
    strictly after the other call's downbeat."

    Design: Difficulty/resource_temporal_overlap/studio_room_half_open_window_allows_touching_rejects_crossing
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production(demo_fee_cents=150_000, submitted_length_seconds=60)
    room = create_studio_room()
    schedule_session_call(env["project"]["id"], room["id"],
                          start="2026-09-10T09:00:00Z", end="2026-09-10T13:00:00Z")

    validate_error(
        api.create_session_call(
            {"project_id": env["project"]["id"], "studio_room_id": room["id"],
             "scheduled_start_utc": "2026-09-10T12:00:00Z",
             "scheduled_end_utc": "2026-09-10T12:30:00Z"},
            make_producer_headers()),
        ApiErrorId.ERR_STUDIO_ROOM_DOUBLE_BOOKED.value, 409)

    _, meta = validate_paginated(api.list_session_calls(
        make_producer_headers(), params={"studio_room_id": room["id"]}))
    assert meta["total_count"] == 1, (
        f"The crossing call must not be stored; got {meta['total_count']}")


def test_player_accepts_a_booking_exactly_sixty_minutes_clear(api):
    """PRD §3.4: "The player must have adequate turnaround: unlike the room rule, the
    AFM turnaround rule is **closed and buffered on both sides**, requiring at least 60
    minutes of clear air between this call and any of that player's other bookings whose
    status is `BOOKED`, `WAGE_ACCRUED` or `PENALTY_ACCRUED` on calls whose status is
    `SCHEDULED`, `SUSPENDED_BUDGET`, `CONFIRMED` or `COMPLETED`."
    PRD §3.4: "The conflict exists — and the line is refused with
    `ERR_MUSICIAN_TURNAROUND_CONFLICT` — when the new downbeat falls strictly before the
    other call's wrap extended by 60 minutes and the new wrap extended by 60 minutes
    falls strictly after the other call's downbeat; a gap of exactly 60 minutes on
    either side is accepted."

    Design: Difficulty/resource_temporal_overlap/musician_turnaround_closed_sixty_minute_buffer_on_both_sides
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production(demo_fee_cents=150_000, submitted_length_seconds=60)
    room_a = create_studio_room(name="Room A", hourly_rate_cents=40_000)
    room_b = create_studio_room(name="Room B", hourly_rate_cents=30_000)
    player = create_musician(index=0)
    first = schedule_session_call(env["project"]["id"], room_a["id"],
                                  start="2026-09-10T09:00:00Z", end="2026-09-10T13:00:00Z")
    book_musician(first["id"], player["id"])
    later = schedule_session_call(env["project"]["id"], room_b["id"],
                                  start="2026-09-10T14:00:00Z", end="2026-09-10T15:00:00Z")

    booking = validate_success(api.create_booking(
        later["id"], {"musician_id": player["id"], "is_leader": False, "doubles_count": 0},
        make_producer_headers()), 201)
    assert_musician_booking(booking)
    assert booking["status"] == "BOOKED", (
        f"A gap of exactly 60 minutes is accepted; got {booking['status']}")

    _, meta = validate_paginated(api.list_bookings(
        make_producer_headers(), params={"musician_id": player["id"]}))
    assert meta["total_count"] == 2, (
        f"The player must now hold both booking lines; got {meta['total_count']}")


def test_player_rejects_a_booking_thirty_minutes_clear(api):
    """PRD §3.4: "The conflict exists — and the line is refused with
    `ERR_MUSICIAN_TURNAROUND_CONFLICT` — when the new downbeat falls strictly before the
    other call's wrap extended by 60 minutes and the new wrap extended by 60 minutes
    falls strictly after the other call's downbeat; a gap of exactly 60 minutes on
    either side is accepted."

    Design: Difficulty/resource_temporal_overlap/musician_turnaround_closed_sixty_minute_buffer_on_both_sides
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production(demo_fee_cents=150_000, submitted_length_seconds=60)
    room_a = create_studio_room(name="Room A", hourly_rate_cents=40_000)
    room_c = create_studio_room(name="Room C", hourly_rate_cents=20_000)
    player = create_musician(index=0)
    first = schedule_session_call(env["project"]["id"], room_a["id"],
                                  start="2026-09-10T09:00:00Z", end="2026-09-10T13:00:00Z")
    book_musician(first["id"], player["id"])
    too_soon = schedule_session_call(env["project"]["id"], room_c["id"],
                                     start="2026-09-10T13:30:00Z", end="2026-09-10T13:45:00Z")

    validate_error(
        api.create_booking(too_soon["id"],
                           {"musician_id": player["id"], "is_leader": False, "doubles_count": 0},
                           make_producer_headers()),
        ApiErrorId.ERR_MUSICIAN_TURNAROUND_CONFLICT.value, 409)

    _, meta = validate_paginated(api.list_bookings(
        make_producer_headers(), params={"session_call_id": too_soon["id"]}))
    assert meta["total_count"] == 0, (
        f"The refused line must not be stored; got {meta['total_count']}")


def test_suspended_player_booking_reports_signatory_standing_not_turnaround(api):
    """PRD §3.1: "Booking a player whose standing is anything other than
    `SIGNATORY_CLEARED` is refused with `ERR_MUSICIAN_NOT_SIGNATORY_CLEARED`."
    PRD §2.5: "Checks are evaluated in the following fixed order, and the first one that
    fails ends the request; later checks are never reached."
    PRD §2.5: "**Signatory standing.** On player booking, the musician's
    `afm_member_status` is `SIGNATORY_CLEARED` — otherwise
    `ERR_MUSICIAN_NOT_SIGNATORY_CLEARED` (422)."

    Design: Difficulty/priority_pair_validation_conflict/afm_signatory_business_safety_outranks_turnaround_business_temporal
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production(demo_fee_cents=150_000, submitted_length_seconds=60)
    room = create_studio_room()
    player = create_musician(index=3)
    first = schedule_session_call(env["project"]["id"], room["id"],
                                  start="2026-09-10T09:00:00Z", end="2026-09-10T13:00:00Z")
    book_musician(first["id"], player["id"], is_leader=True)
    set_afm_clearance(player["id"], "SUSPENDED")
    thirty_minutes_later = schedule_session_call(
        env["project"]["id"], room["id"],
        start="2026-09-10T13:30:00Z", end="2026-09-10T14:30:00Z")

    error = validate_error(
        api.create_booking(thirty_minutes_later["id"],
                           {"musician_id": player["id"], "is_leader": False, "doubles_count": 0},
                           make_producer_headers()),
        ApiErrorId.ERR_MUSICIAN_NOT_SIGNATORY_CLEARED.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_MUSICIAN_TURNAROUND_CONFLICT.value, (
        "Signatory standing is judged before turnaround, so the 409 turnaround error "
        "must never surface here")


def test_refused_signatory_booking_creates_no_line_and_leaves_the_call_scheduled(api):
    """PRD §3.1: "Booking a player whose standing is anything other than
    `SIGNATORY_CLEARED` is refused with `ERR_MUSICIAN_NOT_SIGNATORY_CLEARED`."
    PRD §3.4: "A newly scheduled call opens in `SCHEDULED` with `actual_end_utc` and
    `cancelled_at` null and with `studio_cost_cents`, `wage_estimate_cents`,
    `committed_cents`, `wage_total_cents`, `settled_total_cents` and
    `wage_liability_cents` all at zero."

    Design: Difficulty/priority_pair_validation_conflict/afm_signatory_business_safety_outranks_turnaround_business_temporal
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production(demo_fee_cents=150_000, submitted_length_seconds=60)
    room = create_studio_room()
    player = create_musician(index=3)
    first = schedule_session_call(env["project"]["id"], room["id"],
                                  start="2026-09-10T09:00:00Z", end="2026-09-10T13:00:00Z")
    book_musician(first["id"], player["id"], is_leader=True)
    set_afm_clearance(player["id"], "SUSPENDED")
    thirty_minutes_later = schedule_session_call(
        env["project"]["id"], room["id"],
        start="2026-09-10T13:30:00Z", end="2026-09-10T14:30:00Z")

    validate_error(
        api.create_booking(thirty_minutes_later["id"], {"musician_id": player["id"]},
                           make_producer_headers()),
        ApiErrorId.ERR_MUSICIAN_NOT_SIGNATORY_CLEARED.value, 422)

    _, meta = validate_paginated(api.list_bookings(
        make_producer_headers(), params={"session_call_id": thirty_minutes_later["id"]}))
    assert meta["total_count"] == 0, (
        f"The refused line must not be stored; got {meta['total_count']}")
    call = get_session_call(thirty_minutes_later["id"])
    assert call["status"] == "SCHEDULED", f"Expected SCHEDULED, got {call['status']}"
    assert call["committed_cents"] == 0


def test_zero_length_session_window_is_rejected(api):
    """PRD §3.4: "The wrap must be strictly after the downbeat, and a window that is
    inverted or zero-length is refused with `ERR_INVALID_TIME_WINDOW`."

    Design: Corner/validations/corner_session_call_with_end_equal_to_start_is_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production()
    room = create_studio_room()

    validate_error(
        api.create_session_call(
            {"project_id": env["project"]["id"], "studio_room_id": room["id"],
             "scheduled_start_utc": "2026-09-10T09:00:00Z",
             "scheduled_end_utc": "2026-09-10T09:00:00Z"},
            make_producer_headers()),
        ApiErrorId.ERR_INVALID_TIME_WINDOW.value, 400)

    _, meta = validate_paginated(api.list_session_calls(
        make_producer_headers(), params={"project_id": env["project"]["id"]}))
    assert meta["total_count"] == 0, (
        f"A rejected window must not create a call; got {meta['total_count']}")


def test_booking_the_same_player_twice_on_one_call_is_rejected(api):
    """PRD §3.4: "The player must not already hold a booking on this same call whose
    status is anything other than `RELEASED`, otherwise the line is refused with
    `ERR_MUSICIAN_ALREADY_BOOKED` — a released line does not block a re-booking."

    Design: Corner/validations/corner_same_musician_booked_twice_on_one_call_is_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production()
    room = create_studio_room()
    player = create_musician(index=0)
    call = schedule_session_call(env["project"]["id"], room["id"])
    book_musician(call["id"], player["id"])

    validate_error(
        api.create_booking(call["id"],
                           {"musician_id": player["id"], "is_leader": False, "doubles_count": 0},
                           make_producer_headers()),
        ApiErrorId.ERR_MUSICIAN_ALREADY_BOOKED.value, 409)

    _, meta = validate_paginated(api.list_bookings(
        make_producer_headers(), params={"session_call_id": call["id"]}))
    assert meta["total_count"] == 1, (
        f"The call must keep exactly one line; got {meta['total_count']}")


def test_booking_beyond_room_capacity_is_rejected(api):
    """PRD §3.4: "Finally, the number of non-`RELEASED` lines on the call after this one
    must not exceed the room's `capacity_players`, otherwise the request is refused with
    `ERR_SESSION_CAPACITY_EXCEEDED`."

    Design: Corner/validations/corner_booking_past_room_capacity_is_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production()
    room = create_studio_room(name="Room S", capacity_players=1)
    first_player = create_musician(index=0)
    second_player = create_musician(index=1)
    call = schedule_session_call(env["project"]["id"], room["id"])
    book_musician(call["id"], first_player["id"])

    validate_error(
        api.create_booking(call["id"],
                           {"musician_id": second_player["id"], "is_leader": False,
                            "doubles_count": 0},
                           make_producer_headers()),
        ApiErrorId.ERR_SESSION_CAPACITY_EXCEEDED.value, 422)

    _, meta = validate_paginated(api.list_bookings(
        make_producer_headers(), params={"session_call_id": call["id"]}))
    assert meta["total_count"] == 1, (
        f"The over-capacity line must not be stored; got {meta['total_count']}")


def test_call_in_a_maintenance_room_is_rejected(api):
    """PRD §3.4: "The room must be `ACTIVE` at the moment the call is created; a room in
    `MAINTENANCE` is refused with `ERR_STUDIO_ROOM_UNAVAILABLE`."

    Design: Corner/validations/corner_session_call_in_a_maintenance_room_is_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production()
    room = create_studio_room(name="Room M", status="MAINTENANCE")

    validate_error(
        api.create_session_call(
            {"project_id": env["project"]["id"], "studio_room_id": room["id"],
             "scheduled_start_utc": "2026-09-10T09:00:00Z",
             "scheduled_end_utc": "2026-09-10T13:00:00Z"},
            make_producer_headers()),
        ApiErrorId.ERR_STUDIO_ROOM_UNAVAILABLE.value, 422)

    _, meta = validate_paginated(api.list_session_calls(
        make_producer_headers(), params={"studio_room_id": room["id"]}))
    assert meta["total_count"] == 0, (
        f"A room in MAINTENANCE must host no call; got {meta['total_count']}")
