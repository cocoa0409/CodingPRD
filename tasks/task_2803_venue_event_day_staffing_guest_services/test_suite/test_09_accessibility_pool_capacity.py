"""Accessibility pool availability and peak concurrent occupancy."""

from test_helpers import (
    ERR_ACCESS_REQUEST_STATE_INVALID,
    ERR_ACCESSIBILITY_CAPACITY_EXCEEDED,
    ERR_RESOURCE_NOT_AVAILABLE,
    SUPERVISOR_HEADERS,
    assert_fields,
    assert_instant,
    create_booking,
    create_resource,
    err,
    event_with_active_plan,
    ok,
    read_resource,
    set_clock,
    set_resource_status,
    transition_booking,
)
from test_helpers.factories import access_transition_payload, ticket_taker_payload


def _planned_event(client, zone_code, name):
    return event_with_active_plan(
        client,
        position_type_payload=ticket_taker_payload(required_certifications=[]),
        slot_overrides={
            "zone_code": zone_code,
            "shift_start": "2026-09-12T18:00:00Z",
            "shift_end": "2026-09-12T22:00:00Z",
            "required_headcount_override": 1,
        },
        name=name,
        doors_open_at="2026-09-12T16:00:00Z",
        doors_close_at="2026-09-12T23:00:00Z",
        expected_attendance=20000,
    )


def _try_confirm(client, request_id):
    return client.transition_accessibility_request(
        request_id, access_transition_payload("CONFIRMED"), SUPERVISOR_HEADERS
    )


def _pool_out_of_service(client):
    """A two-unit booking standing against a pool that has been taken out of service."""
    set_clock(client, "2026-09-12T15:00:00Z")
    context = _planned_event(client, "Z950", "Resource Gate Fixture")
    resource = create_resource(
        client,
        context["event"]["id"],
        resource_type="WHEELCHAIR_ESCORT",
        zone_code="Z950",
        unit_count=3,
    )
    booking = create_booking(
        client,
        resource["id"],
        guest_reference="G-77120",
        window_start="2026-09-12T18:00:00Z",
        window_end="2026-09-12T20:00:00Z",
        units_requested=2,
    )
    set_resource_status(client, resource["id"], "MAINTENANCE")
    context.update(resource=resource, booking=booking)
    return context


def test_confirmation_is_refused_while_the_pool_is_out_of_service(client):
    """A pool in MAINTENANCE cannot take a commitment, and the peak must not move.

    "the pool's `status` must be `AVAILABLE`, or it is refused with
    `ERR_RESOURCE_NOT_AVAILABLE`; and the pool must have room across the whole of
    the requested window once this booking's own `units_requested` is counted in,
    or it is refused with `ERR_ACCESSIBILITY_CAPACITY_EXCEEDED`."

    Design: Difficulty/cross_entity_state_dependency/accessibility_confirm_requires_available_resource
    """
    context = _pool_out_of_service(client)

    err(_try_confirm(client, context["booking"]["id"]), ERR_RESOURCE_NOT_AVAILABLE)

    booking = ok(
        client.get_accessibility_request(context["booking"]["id"], SUPERVISOR_HEADERS)
    )
    assert_fields(booking, status="REQUESTED", confirmed_at=None)
    pool = read_resource(client, context["resource"]["id"])
    assert_fields(pool, status="MAINTENANCE", peak_committed_units=0, unit_count=3)


def test_the_committed_peak_moves_only_once_the_pool_is_back_in_service(client):
    """Returning the pool to AVAILABLE lets the identical request through.

    "On success `confirmed_at` is stamped from the current logical clock and the
    pool's `peak_committed_units` is recomputed with this booking included."

    Design: Difficulty/cross_entity_state_dependency/accessibility_confirm_requires_available_resource
    """
    context = _pool_out_of_service(client)

    err(_try_confirm(client, context["booking"]["id"]), ERR_RESOURCE_NOT_AVAILABLE)
    set_resource_status(client, context["resource"]["id"], "AVAILABLE")

    confirmed = ok(_try_confirm(client, context["booking"]["id"]))
    assert_fields(confirmed, status="CONFIRMED", companion_seats_requested=0)
    assert_instant(confirmed["confirmed_at"], "2026-09-12T15:00:00.000Z", "confirmed_at")

    pool = read_resource(client, context["resource"]["id"])
    assert_fields(pool, peak_committed_units=2, unit_count=3, status="AVAILABLE")


def test_reconfirming_a_confirmed_booking_is_refused_and_never_double_counts(client):
    """The units a booking holds are counted once, however often confirmation is retried.

    "Every subsequent movement of a booking is a supervisor action naming the
    desired `target_status`, optionally accompanied by a `denial_reason`. Six
    movements are permitted and no others; anything else is refused with
    `ERR_ACCESS_REQUEST_STATE_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/accessibility_confirm_requires_available_resource
    """
    context = _pool_out_of_service(client)
    set_resource_status(client, context["resource"]["id"], "AVAILABLE")
    ok(_try_confirm(client, context["booking"]["id"]))

    err(_try_confirm(client, context["booking"]["id"]), ERR_ACCESS_REQUEST_STATE_INVALID)

    pool = read_resource(client, context["resource"]["id"])
    assert_fields(pool, peak_committed_units=2, unit_count=3)


def _full_three_unit_pool(client):
    """Three confirmed single-unit bookings whose busiest slice is [19:30, 19:45)."""
    set_clock(client, "2026-09-12T15:00:00Z")
    context = _planned_event(client, "Z960", "Peak Occupancy Fixture")
    resource = create_resource(
        client,
        context["event"]["id"],
        resource_type="ASSISTIVE_LISTENING_UNIT",
        zone_code="Z960",
        unit_count=3,
    )
    windows = [
        ("G-901", "2026-09-12T18:00:00Z", "2026-09-12T20:00:00Z"),
        ("G-902", "2026-09-12T19:00:00Z", "2026-09-12T21:00:00Z"),
        ("G-903", "2026-09-12T19:30:00Z", "2026-09-12T19:45:00Z"),
    ]
    bookings = []
    for guest_reference, window_start, window_end in windows:
        booking = create_booking(
            client,
            resource["id"],
            guest_reference=guest_reference,
            window_start=window_start,
            window_end=window_end,
            units_requested=1,
        )
        transition_booking(client, booking["id"], "CONFIRMED")
        bookings.append(booking)
    context.update(resource=resource, bookings=bookings)
    return context


def test_three_concurrent_single_unit_bookings_exactly_fill_a_three_unit_pool(client):
    """The capacity gate admits equality, so a pool of three accepts three overlaps.

    "Because the gate admits equality, a pool of 3 units accepts three fully
    overlapping single-unit bookings, reaching a peak of exactly 3; a fourth
    overlapping booking is refused with `ERR_ACCESSIBILITY_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/accessibility_peak_units_half_open_slices
    """
    context = _full_three_unit_pool(client)

    pool = read_resource(client, context["resource"]["id"])
    assert_fields(pool, peak_committed_units=3, unit_count=3)


def test_adjacent_half_open_windows_are_never_concurrent(client):
    """A booking that ends exactly when another begins adds nothing to the peak.

    "Windows are treated as half-open, so two bookings where one ends at exactly
    the instant the other begins are never concurrent and never compete for the
    same unit."

    Design: Difficulty/resource_temporal_overlap/accessibility_peak_units_half_open_slices
    """
    context = _full_three_unit_pool(client)

    adjacent = create_booking(
        client,
        context["resource"]["id"],
        guest_reference="G-907",
        window_start="2026-09-12T17:00:00Z",
        window_end="2026-09-12T18:00:00Z",
        units_requested=1,
    )
    confirmed = ok(_try_confirm(client, adjacent["id"]))
    assert_fields(confirmed, status="CONFIRMED")

    pool = read_resource(client, context["resource"]["id"])
    assert_fields(pool, peak_committed_units=3, unit_count=3)


def test_a_sliver_of_overlap_refuses_and_a_cancellation_frees_exactly_that_sliver(client):
    """Capacity is recomputed from the live row set, not tracked as a monotone counter.

    "Cancellation from `CONFIRMED`, by contrast, releases capacity immediately: the
    pool's `peak_committed_units` over the affected window drops by the cancelled
    booking's `units_requested`."

    Design: Difficulty/resource_temporal_overlap/accessibility_peak_units_half_open_slices
    """
    context = _full_three_unit_pool(client)
    resource_id = context["resource"]["id"]

    # Only the 10-minute slice [19:30, 19:40) would reach a fourth unit.
    sliver = create_booking(
        client,
        resource_id,
        guest_reference="G-904",
        window_start="2026-09-12T19:00:00Z",
        window_end="2026-09-12T19:40:00Z",
        units_requested=1,
    )
    err(_try_confirm(client, sliver["id"]), ERR_ACCESSIBILITY_CAPACITY_EXCEEDED)

    refused = ok(client.get_accessibility_request(sliver["id"], SUPERVISOR_HEADERS))
    assert_fields(refused, status="REQUESTED", confirmed_at=None)
    assert_fields(read_resource(client, resource_id), peak_committed_units=3)

    released = transition_booking(client, context["bookings"][2]["id"], "CANCELLED")
    assert_fields(released, status="CANCELLED")
    assert_fields(read_resource(client, resource_id), peak_committed_units=2)

    assert_fields(ok(_try_confirm(client, sliver["id"])), status="CONFIRMED")
    assert_fields(read_resource(client, resource_id), peak_committed_units=3)
