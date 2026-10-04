"""Club programs: capacity boundary, venue conflicts, roadside rules, cascades."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_roadside_invariant,
    create_club_membership_for,
    create_event,
    create_member,
    register_member,
    setup_active_policy,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


def test_event_capacity_exact_boundary_admission(api):
    """PRD §3.11: "Registration is member-driven and capacity-gated: the
    member registers by passing their `member_id`, which must match the
    acting member; when the event's `registered_count` has reached
    `capacity`, further registrations are rejected with `ERR_EVENT_FULL`."

    Design: Difficulty/boundary_precision_check/event_capacity_exact_boundary
    """
    member_a, _ = create_member(full_name="A", email="a@x.com")
    member_b, _ = create_member(full_name="B", email="b@x.com")
    event = create_event(name="Fall Tour", venue="Fairground",
                         start_date="2026-10-10T00:00:00Z",
                         end_date="2026-10-11T00:00:00Z", capacity=2)
    reg_a = validate_success(register_member(event["id"], member_a), expected_status=201)
    assert reg_a["status"] == "REGISTERED"
    reg_b = validate_success(register_member(event["id"], member_b), expected_status=201)
    assert reg_b["status"] == "REGISTERED"
    fetched = validate_success(api.get_club_event(event["id"], COORD))
    assert fetched["registered_count"] == 2, (
        "count == capacity is reached, not exceeded, after two registrations"
    )


def test_event_capacity_full_rejects_next_registration(api):
    """PRD §3.11: "when the event's `registered_count` has reached
    `capacity`, further registrations are rejected with `ERR_EVENT_FULL`."

    Design: Difficulty/boundary_precision_check/event_capacity_exact_boundary
    """
    member_a, _ = create_member(full_name="A", email="a@x.com")
    member_b, _ = create_member(full_name="B", email="b@x.com")
    member_c, _ = create_member(full_name="C", email="c@x.com")
    event = create_event(name="Fall Tour", venue="Fairground",
                         start_date="2026-10-10T00:00:00Z",
                         end_date="2026-10-11T00:00:00Z", capacity=2)
    register_member(event["id"], member_a)
    register_member(event["id"], member_b)
    resp = register_member(event["id"], member_c)
    validate_error(resp, ApiErrorId.ERR_EVENT_FULL)


def test_venue_event_closed_interval_with_buffer_conflict(api):
    """PRD §3.11: "Venue scheduling is conservative: the new event's closed
    interval, expanded by a one-day buffer on each side, must not intersect
    the correspondingly buffered interval of any other `SCHEDULED` event at
    the same venue — a conflict is rejected with
    `ERR_EVENT_VENUE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/venue_event_closed_interval_with_buffer
    """
    create_event(name="Fall Tour", venue="Fairground",
                 start_date="2026-10-10T00:00:00Z", end_date="2026-10-11T00:00:00Z",
                 capacity=50)
    # One day after E1's end: inside the 1-day teardown buffer -> conflict.
    resp = api.create_club_event(
        {
            "name": "Swap Meet",
            "venue": "Fairground",
            "start_date": "2026-10-12T00:00:00Z",
            "end_date": "2026-10-12T00:00:00Z",
            "capacity": 30,
        },
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_EVENT_VENUE_CONFLICT)


def test_venue_event_closed_interval_different_venue_allowed(api):
    """PRD §3.11: "Venue scheduling is conservative: the new event's closed
    interval, expanded by a one-day buffer on each side, must not intersect
    the correspondingly buffered interval of any other `SCHEDULED` event at
    the same venue — a conflict is rejected with
    `ERR_EVENT_VENUE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/venue_event_closed_interval_with_buffer
    """
    create_event(name="Fall Tour", venue="Fairground",
                 start_date="2026-10-10T00:00:00Z", end_date="2026-10-11T00:00:00Z",
                 capacity=50)
    resp = api.create_club_event(
        {
            "name": "Swap Meet",
            "venue": "Speedway",
            "start_date": "2026-10-12T00:00:00Z",
            "end_date": "2026-10-12T00:00:00Z",
            "capacity": 30,
        },
        COORD,
    )
    validate_success(resp, expected_status=201)


def test_club_event_cancel_cascades_registrations(api):
    """PRD §3.11: "Cancelling the event itself cascades — every registration
    in `REGISTERED` becomes `CANCELLED` and `registered_count` falls to
    zero."

    Design: Corner/endpoints/club_event_cancel_cascades_registrations
    """
    member_a, _ = create_member(full_name="S1", email="s1@x.com")
    member_b, _ = create_member(full_name="S2", email="s2@x.com")
    event = create_event(name="Show", venue="Dome",
                         start_date="2026-10-10T00:00:00Z",
                         end_date="2026-10-11T00:00:00Z", capacity=10)
    register_member(event["id"], member_a)
    register_member(event["id"], member_b)
    cancelled = validate_success(api.cancel_club_event(event["id"], COORD))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["registered_count"] == 0, (
        "Cancelling the event zeroes registered_count via cascade"
    )


def test_roadside_dispatch_cancel_invariant(api):
    """PRD §3.11: "the member may cancel their own dispatch, moving it to
    `CANCELLED`, and cancellation is compensating — the used count decrements
    so that used plus remaining returns exactly to its pre-dispatch value."
    PRD §3.11: "the membership's `roadside_calls_limit` is derived from the
    tier — two calls per year at `BASIC`, four at `ENTHUSIAST`, six at
    `CONCOURS`."

    Design: Difficulty/compensating_invariant/roadside_dispatch_cancel_invariant
    """
    ctx = setup_active_policy()
    membership = create_club_membership_for(ctx["member"], tier="BASIC")
    assert membership["roadside_calls_limit"] == 2
    assert membership["roadside_calls_used"] == 0

    dispatch = validate_success(
        api.dispatch_roadside_event(
            membership["id"],
            {
                "vehicle_id": ctx["vehicle"]["id"],
                "service_type": "FLATBED_TOW",
                "event_date": "2026-10-05T00:00:00Z",
            },
            ctx["member_headers"],
        ),
        expected_status=201,
    )
    after_dispatch = validate_success(
        api.get_club_membership(membership["id"], ctx["member_headers"])
    )
    assert after_dispatch["roadside_calls_used"] == 1
    validate_success(api.cancel_roadside_event(dispatch["id"], ctx["member_headers"]))
    after_cancel = validate_success(
        api.get_club_membership(membership["id"], ctx["member_headers"])
    )
    assert after_cancel["roadside_calls_used"] == 0, (
        "dispatch + cancel must restore the used count to its pre-dispatch value"
    )
    assert_roadside_invariant(after_cancel)


def test_roadside_dispatch_increments_used_count(api):
    """PRD §3.11: "The dispatch counts against the tier allowance:
    `roadside_calls_used` counts the membership's dispatches in `DISPATCHED`
    or `COMPLETED` status".

    Design: Difficulty/compensating_invariant/roadside_dispatch_cancel_invariant
    """
    ctx = setup_active_policy()
    membership = create_club_membership_for(ctx["member"], tier="BASIC")
    dispatch = validate_success(
        api.dispatch_roadside_event(
            membership["id"],
            {
                "vehicle_id": ctx["vehicle"]["id"],
                "service_type": "FLATBED_TOW",
                "event_date": "2026-10-05T00:00:00Z",
            },
            ctx["member_headers"],
        ),
        expected_status=201,
    )
    assert dispatch["status"] == "DISPATCHED"
    after = validate_success(
        api.get_club_membership(membership["id"], ctx["member_headers"])
    )
    assert after["roadside_calls_used"] == 1


def test_error_flatbed_required_for_classics(api):
    """PRD §3.11: "Because classics cannot be towed conventionally, the only
    permitted service type is `FLATBED_TOW`; a request for `BATTERY`, `FUEL`,
    or `LOCKOUT` service is rejected with `ERR_ROADSIDE_FLATBED_REQUIRED`."

    Design: Corner/errors/error_flatbed_required_for_classics
    """
    ctx = setup_active_policy()
    membership = create_club_membership_for(ctx["member"], tier="BASIC")
    resp = api.dispatch_roadside_event(
        membership["id"],
        {
            "vehicle_id": ctx["vehicle"]["id"],
            "service_type": "BATTERY",
            "event_date": "2026-10-05T00:00:00Z",
        },
        ctx["member_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_ROADSIDE_FLATBED_REQUIRED)


def test_error_roadside_limit_reached(api):
    """PRD §3.11: "The dispatch counts against the tier allowance:
    `roadside_calls_used` counts the membership's dispatches in `DISPATCHED`
    or `COMPLETED` status, and a dispatch attempted when the used count has
    already reached the limit is rejected with
    `ERR_ROADSIDE_LIMIT_REACHED`."

    Design: Corner/errors/error_roadside_limit_reached
    """
    ctx = setup_active_policy()
    membership = create_club_membership_for(ctx["member"], tier="BASIC")
    for date in ("2026-10-05T00:00:00Z", "2026-11-05T00:00:00Z"):
        validate_success(
            api.dispatch_roadside_event(
                membership["id"],
                {
                    "vehicle_id": ctx["vehicle"]["id"],
                    "service_type": "FLATBED_TOW",
                    "event_date": date,
                },
                ctx["member_headers"],
            ),
            expected_status=201,
        )
    resp = api.dispatch_roadside_event(
        membership["id"],
        {
            "vehicle_id": ctx["vehicle"]["id"],
            "service_type": "FLATBED_TOW",
            "event_date": "2026-12-05T00:00:00Z",
        },
        ctx["member_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_ROADSIDE_LIMIT_REACHED)
