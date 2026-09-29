"""Resource temporal overlap: the room's half-open occupancy interval tested one
minute before and exactly at the turnover release instant, against the
therapist's closed calendar interval tested at a touching instant.
"""

from test_helpers import (
    ApiErrorId,
    assert_list_count,
    assert_same_instant,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.constants import CANON_QUOTED_PRICE_CENTS, CANON_START_AT
from test_helpers import factories as f
from test_helpers import fixtures as fx

RELEASE_INSTANT = "2026-08-10T19:00:00.000Z"
ONE_MINUTE_EARLY = "2026-08-10T18:59:00.000Z"


def _occupied_room_world():
    """One REQUESTED 90-minute appointment at 17:00Z in a room whose turnover
    buffer is 30 minutes, so the room occupancy interval is [17:00, 19:00)."""
    world = fx.build_world(
        shift_block_overrides={"start_at": "2026-08-10T08:00:00.000Z",
                               "end_at": "2026-08-10T23:00:00.000Z"})
    world.appointments["a"] = fx.book_appointment(
        world.guest_id, world.treatment_type_id, world.room_id, CANON_START_AT,
        world.therapist_id)
    return world


def test_booking_one_minute_before_the_turnover_release_conflicts_on_the_room():
    """18:59 is still inside the half-open occupancy interval by one minute.

    PRD §3.5: "The room has its own, deliberately different geometry: a room's
    occupancy interval begins at the appointment's `start_at` and runs up to but
    not including its `end_at` advanced by that room's `turnover_buffer_minutes`,
    and the new occupancy may not overlap the occupancy interval of any
    appointment in that room that is non-terminal or `COMPLETED`."

    PRD §3.5: "`end_at` is `start_at` advanced by `scheduled_duration_minutes`."

    Design: Difficulty/resource_temporal_overlap/room_turnover_half_open_adjacency_at_exact_release_instant
    """
    world = _occupied_room_world()
    assert_same_instant(world.appointments["a"]["end_at"],
                        "2026-08-10T18:30:00.000Z", "end_at")

    response = api_client.create_appointment(
        f.appointment_payload(world.guest_id, world.treatment_type_id,
                              world.room_id, ONE_MINUTE_EARLY,
                              world.therapist_id),
        fx.COORDINATOR)
    error = validate_error(response,
                           ApiErrorId.ERR_ROOM_TURNOVER_CONFLICT.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_THERAPIST_DOUBLE_BOOKED.value, (
        "the therapist's closed interval [17:00, 18:30] does not contain 18:59, "
        "so only the room rule can fire")

    assert world.fetch_room()["booked_minutes_total"] == 120, (
        "the rejected request contributed nothing")
    assert_list_count(
        api_client.list_appointments(fx.COORDINATOR,
                                     params={"room_id": world.room_id}),
        1, "appointments in the room")


def test_booking_at_the_exact_turnover_release_instant_is_accepted():
    """Touching at the excluded upper bound is legal.

    PRD §3.5: "Because the upper bound is excluded, a booking that starts at
    exactly the instant the previous appointment's turnover ends is accepted
    (`ERR_ROOM_TURNOVER_CONFLICT` otherwise)."

    PRD §3.5: "a peak component of 1,500 basis points applies when the UTC hour of
    the submitted `start_at` is at least 16 and less than 20 (this is the UTC hour
    of the submitted instant and never a local-time conversion) and is otherwise
    zero"

    Design: Difficulty/resource_temporal_overlap/room_turnover_half_open_adjacency_at_exact_release_instant
    """
    world = _occupied_room_world()
    validate_error(
        api_client.create_appointment(
            f.appointment_payload(world.guest_id, world.treatment_type_id,
                                  world.room_id, ONE_MINUTE_EARLY,
                                  world.therapist_id),
            fx.COORDINATOR),
        ApiErrorId.ERR_ROOM_TURNOVER_CONFLICT.value, 409)

    accepted = validate_success(api_client.create_appointment(
        f.appointment_payload(world.guest_id, world.treatment_type_id,
                              world.room_id, RELEASE_INSTANT,
                              world.therapist_id),
        fx.COORDINATOR), 201)
    assert_same_instant(accepted["start_at"], RELEASE_INSTANT, "start_at")
    assert accepted["quoted_price_cents"] == CANON_QUOTED_PRICE_CENTS, (
        "19:00Z is still inside the 16 <= hour < 20 peak window")

    assert world.fetch_room()["booked_minutes_total"] == 240, (
        "two committed bookings of 90 plus 30 turnover minutes each")
    assert_list_count(
        api_client.list_appointments(fx.COORDINATOR,
                                     params={"room_id": world.room_id}),
        2, "appointments in the room")


# ---------------------------------------------------------------------------
# The therapist's closed calendar interval
# ---------------------------------------------------------------------------

def _world_with_break_block():
    """The canonical world where the therapist also holds a BREAK block running
    18:30-19:30Z, exactly abutting a 17:00 booking's end."""
    world = fx.build_world()
    world.break_block = fx.add_shift_block(
        world.therapist_id, block_type="BREAK",
        start_at="2026-08-10T18:30:00.000Z", end_at="2026-08-10T19:30:00.000Z",
        note="statutory rest")
    return world


def test_booking_whose_end_touches_a_break_block_start_is_double_booked():
    """Both bounds inclusive means a touching endpoint is a conflict.

    PRD §3.5: "The therapist must also be free: no `BREAK` or `ADMIN` block of
    theirs and no other appointment of theirs in `REQUESTED`, `CONFIRMED`,
    `CHECKED_IN` or `IN_SERVICE` may intersect the appointment's interval, where
    intersection is judged with both intervals closed at both ends, so merely
    touching at an endpoint counts as a conflict
    (`ERR_THERAPIST_DOUBLE_BOOKED`)."

    PRD §3.2: "A block carries a `block_type` of `AVAILABLE`, `BREAK` or `ADMIN`,
    an inclusive `start_at`, an inclusive `end_at` that must be strictly after
    `start_at`, and an optional scheduling `note` that defaults to null; a block
    whose `end_at` is not strictly after its `start_at` is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Difficulty/resource_temporal_overlap/therapist_closed_interval_break_adjacency_at_touching_instant
    """
    world = _world_with_break_block()
    assert world.break_block["block_type"] == "BREAK"
    assert world.break_block["note"] == "statutory rest"

    response = api_client.create_appointment(
        f.appointment_payload(world.guest_id, world.treatment_type_id,
                              world.room_id, CANON_START_AT, world.therapist_id),
        fx.COORDINATOR)
    validate_error(response, ApiErrorId.ERR_THERAPIST_DOUBLE_BOOKED.value, 409)

    assert world.fetch_therapist()["assigned_minutes_total"] == 0, (
        "the refused request moved no ledger")
    assert world.fetch_room()["booked_minutes_total"] == 0
    assert_list_count(api_client.list_appointments(fx.COORDINATOR), 0,
                      "appointments after the refused booking")


def test_booking_ending_an_hour_before_the_break_is_accepted():
    """A gap of a full hour clears the closed-interval test.

    PRD §2.12: "A room's `booked_minutes_total` is the running total of committed
    occupancy minutes for that room, where one appointment's committed occupancy is
    its scheduled duration plus that room's `turnover_buffer_minutes`."

    PRD §2.12: "A therapist's `assigned_minutes_total` is the running total of
    scheduled treatment minutes committed to that therapist, excluding turnover:
    booking adds the appointment's scheduled duration and every releasing
    transition subtracts it."

    Design: Difficulty/resource_temporal_overlap/therapist_closed_interval_break_adjacency_at_touching_instant
    """
    world = _world_with_break_block()
    validate_error(
        api_client.create_appointment(
            f.appointment_payload(world.guest_id, world.treatment_type_id,
                                  world.room_id, CANON_START_AT,
                                  world.therapist_id),
            fx.COORDINATOR),
        ApiErrorId.ERR_THERAPIST_DOUBLE_BOOKED.value, 409)

    accepted = validate_success(api_client.create_appointment(
        f.appointment_payload(world.guest_id, world.treatment_type_id,
                              world.room_id, "2026-08-10T16:00:00.000Z",
                              world.therapist_id),
        fx.COORDINATOR), 201)
    assert accepted["quoted_price_cents"] == CANON_QUOTED_PRICE_CENTS, (
        "16:00Z is the first hour of the 16 <= hour < 20 peak window")

    assert world.fetch_therapist()["assigned_minutes_total"] == 90
    assert world.fetch_room()["booked_minutes_total"] == 120
    assert_list_count(
        api_client.list_shift_blocks(world.therapist_id, fx.COORDINATOR,
                                     params={"block_type": "BREAK"}),
        1, "BREAK shift blocks")
