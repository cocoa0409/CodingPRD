"""Berths on a shared dock: route membership, the occupancy count and the OCC guard."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_dock,
    assert_dock_slot,
    create_dock_slot_payload,
    create_trip,
    current_dock_version,
    reserve_dock_slot,
    setup_harbor_world,
    validate_error,
    validate_paginated,
    validate_success,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_reserving_a_berth_on_a_dock_off_the_route_is_rejected(api):
    """PRD §3.4: "The trip whose reservation this is comes from the trip addressed in
    the request, and the dock must actually be on that trip's route: it has to be the
    dock of the trip's origin stop or the dock of its destination stop, and any other
    dock is rejected with `ERR_SLOT_DOCK_NOT_ON_ROUTE`."

    Design: Corner/validations/dock_slot_on_a_dock_that_is_not_on_the_trip_route_is_rejected
    """
    world = setup_harbor_world()
    trip = create_trip(world)
    remote = add_dock(name="Remote Wharf", berth_count=3, min_turnaround_minutes=0,
                      landing_fee_per_pax_cents=50, berth_minute_rate_cents=10,
                      monthly_fee_cap_cents=900_000)

    response = api.create_dock_slot(
        trip["id"],
        create_dock_slot_payload(remote["id"], remote["version"], purpose="LANDING",
                                 start_utc="2026-09-12T14:00:00Z",
                                 end_utc="2026-09-12T14:20:00Z"),
        DISPATCHER,
    )
    validate_error(response, ApiErrorId.ERR_SLOT_DOCK_NOT_ON_ROUTE.value, 422)

    unchanged = validate_success(api.get_dock(remote["id"], DISPATCHER))
    assert unchanged["version"] == remote["version"], (
        f"A rejected reservation must not bump the dock version: "
        f"{remote['version']} -> {unchanged['version']}"
    )
    _slots, meta = validate_paginated(
        api.list_dock_slots(DISPATCHER, params={"trip_id": trip["id"]})
    )
    assert meta["total_count"] == 0


def test_second_reservation_carrying_the_pre_reservation_dock_version_is_rejected(api):
    """PRD §2.7: "A berth-reservation request — `POST /harbor/trips/{id}/dock-slots` —
    must carry `expected_dock_version`, a non-optional integer in the request body
    carrying the client's last observed `version` of the target `Dock`."
    PRD §2.7: "If it does not equal that dock's current `version` at the moment the
    request is processed, the reservation is rejected with `ERR_STALE_DOCK_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_layers/stale_expected_dock_version_on_a_berth_reservation_is_rejected_with_412
    """
    world = setup_harbor_world()
    trip = create_trip(world)
    stale_version = current_dock_version(world["dock_a_id"])
    first_slot = reserve_dock_slot(trip["id"], world["dock_a_id"],
                                   "2026-09-12T14:00:00Z", "2026-09-12T14:20:00Z",
                                   expected_dock_version=stale_version)

    response = api.create_dock_slot(
        trip["id"],
        create_dock_slot_payload(world["dock_a_id"], stale_version, purpose="LAYOVER",
                                 start_utc="2026-09-12T16:00:00Z",
                                 end_utc="2026-09-12T16:20:00Z"),
        DISPATCHER,
    )
    validate_error(response, ApiErrorId.ERR_STALE_DOCK_VERSION.value, 412)

    _slots, meta = validate_paginated(
        api.list_dock_slots(DISPATCHER, params={"dock_id": world["dock_a_id"]})
    )
    assert meta["total_count"] == 1, (
        f"The stale reservation must not have been written, got {meta['total_count']}"
    )
    survivor = validate_success(api.get_dock_slot(first_slot["id"], DISPATCHER))
    assert survivor["status"] == "RESERVED"


def test_berth_listing_filters_by_trip_and_by_dock(api):
    """PRD §3.4: "Slots may be read individually or listed with `dock_id`, `trip_id`,
    and `status` filters alongside `limit` and `offset`."
    PRD §3.4: "The trip whose reservation this is comes from the trip addressed in
    the request, and the dock must actually be on that trip's route: it has to be the
    dock of the trip's origin stop or the dock of its destination stop, and any other
    dock is rejected with `ERR_SLOT_DOCK_NOT_ON_ROUTE`."

    Design: Corner/endpoints/dock_slot_list_filtered_by_trip_returns_only_that_trips_reservations
    """
    world = setup_harbor_world()
    trip_one = create_trip(world)
    slot_one = reserve_dock_slot(trip_one["id"], world["dock_a_id"],
                                 "2026-09-12T14:00:00Z", "2026-09-12T14:20:00Z")
    trip_two = create_trip(world, scheduled_departure_utc="2026-09-12T16:00:00Z",
                           scheduled_arrival_utc="2026-09-12T16:25:00Z")
    slot_two = reserve_dock_slot(trip_two["id"], world["dock_a_id"],
                                 "2026-09-12T16:00:00Z", "2026-09-12T16:20:00Z")

    by_trip, trip_meta = validate_paginated(
        api.list_dock_slots(DISPATCHER, params={"trip_id": trip_one["id"]})
    )
    assert trip_meta["total_count"] == 1, (
        f"Only trip one's reservation may match, got {trip_meta['total_count']}"
    )
    assert by_trip[0]["id"] == slot_one["id"]

    by_dock, dock_meta = validate_paginated(
        api.list_dock_slots(DISPATCHER, params={"dock_id": world["dock_a_id"]})
    )
    assert dock_meta["total_count"] == 2
    assert {row["id"] for row in by_dock} == {slot_one["id"], slot_two["id"]}

    assert_dock_slot(slot_two)
    assert slot_two["trip_id"] == trip_two["id"]


def _buffered_dock_world():
    """Pier One with two berths and a 15-minute turnaround buffer, one long sailing."""
    world = setup_harbor_world()
    trip = create_trip(world, scheduled_departure_utc="2026-09-12T14:00:00Z",
                       scheduled_arrival_utc="2026-09-12T15:00:00Z")
    return world, trip


def test_adjacent_berth_window_is_accepted_while_one_berth_remains(api):
    """PRD §3.4: "Concretely, an existing slot counts as occupied against the
    candidate when the candidate's `start_utc` falls strictly before that slot's
    `end_utc` plus the buffer, and that slot's `start_utc` falls strictly before the
    candidate's `end_utc` plus the buffer."
    PRD §3.4: "Count the occupying slots: if that count is already at or above the
    dock's `berth_count`, the reservation is rejected with `ERR_DOCK_BERTH_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/dock_berth_halfopen_window_with_turnaround_buffer_saturates_aggregate_capacity
    """
    world, trip = _buffered_dock_world()

    first = reserve_dock_slot(trip["id"], world["dock_a_id"],
                              "2026-09-12T14:00:00Z", "2026-09-12T14:20:00Z")
    second = reserve_dock_slot(trip["id"], world["dock_a_id"],
                               "2026-09-12T14:20:00Z", "2026-09-12T14:40:00Z",
                               purpose="LAYOVER")

    assert first["status"] == "RESERVED"
    assert second["status"] == "RESERVED", (
        "One buffered overlap on a two-berth dock still leaves a berth free"
    )
    _slots, meta = validate_paginated(
        api.list_dock_slots(DISPATCHER, params={"dock_id": world["dock_a_id"]})
    )
    assert meta["total_count"] == 2


def test_third_buffered_overlap_saturates_the_two_berth_dock(api):
    """PRD §3.4: "Take the dock's `min_turnaround_minutes` as a buffer in whole
    minutes and apply it symmetrically to both ends of both intervals: an existing
    slot occupies the berth from the buffer before its `start_utc` until the buffer
    after its `end_utc`, and the candidate is tested over the same widened span."
    PRD §3.4: "Count the occupying slots: if that count is already at or above the
    dock's `berth_count`, the reservation is rejected with `ERR_DOCK_BERTH_CONFLICT`."
    PRD §3.4: "In other words, a dock with a `berth_count` of three accepts two
    overlapping reservations and rejects the third."

    Design: Difficulty/resource_temporal_overlap/dock_berth_halfopen_window_with_turnaround_buffer_saturates_aggregate_capacity
    """
    world, trip = _buffered_dock_world()
    first = reserve_dock_slot(trip["id"], world["dock_a_id"],
                              "2026-09-12T14:00:00Z", "2026-09-12T14:20:00Z")
    second = reserve_dock_slot(trip["id"], world["dock_a_id"],
                               "2026-09-12T14:20:00Z", "2026-09-12T14:40:00Z",
                               purpose="LAYOVER")
    version_before = current_dock_version(world["dock_a_id"])

    response = api.create_dock_slot(
        trip["id"],
        create_dock_slot_payload(world["dock_a_id"], version_before, purpose="LAYOVER",
                                 start_utc="2026-09-12T14:25:00Z",
                                 end_utc="2026-09-12T14:45:00Z"),
        DISPATCHER,
    )
    validate_error(response, ApiErrorId.ERR_DOCK_BERTH_CONFLICT.value, 409)

    assert validate_success(api.get_dock_slot(first["id"], DISPATCHER))["status"] == "RESERVED"
    assert validate_success(api.get_dock_slot(second["id"], DISPATCHER))["status"] == "RESERVED"
    _slots, meta = validate_paginated(
        api.list_dock_slots(DISPATCHER, params={"dock_id": world["dock_a_id"]})
    )
    assert meta["total_count"] == 2, (
        f"The rejected candidate must not be written, got {meta['total_count']}"
    )
    assert current_dock_version(world["dock_a_id"]) == version_before, (
        "A rejected reservation must not bump the dock version"
    )
