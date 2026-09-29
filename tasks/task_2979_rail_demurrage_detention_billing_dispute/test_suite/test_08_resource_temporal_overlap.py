"""Queue A - rule ``resource_temporal_overlap``.

Two instances contending for a scarce resource across time: one physical car,
whose occupation interval is half-open, and one single-spot track, which hosts
two different overlap gates behind one priority.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CAR_CYCLE_OVERLAP,
    ERR_FACILITY_SPOT_UNAVAILABLE,
    ERR_FACILITY_SWITCH_BUFFER,
)
from test_helpers.assertions import (
    assert_error_meta_is_minimal,
    error_id_of,
    assert_instant_eq,
    assert_subset_equal,
)
from test_helpers.constants import (
    CHARGE_FINAL,
    CHARGE_VOIDED,
    CLOCK_BASIS_CONSTRUCTIVE,
    CYCLE_A_GROSS_CENTS,
    CYCLE_A_RELEASE_AT,
    MOVEMENT_ACTUALLY_PLACED,
    MOVEMENT_CONSTRUCTIVELY_PLACED,
    MOVEMENT_ORDERED,
    MOVEMENT_RELEASED,
    MOVEMENT_VOIDED,
)
from test_helpers.test_users import AGENT

# --- instance 21 literals --------------------------------------------------
CLOCK_ONE_MS_BEFORE_RELEASE = "2026-08-10T15:59:59.999Z"
CLOCK_AT_RELEASE_INSTANT = CYCLE_A_RELEASE_AT  # 2026-08-10T16:00:00.000Z

# --- instance 22 literals --------------------------------------------------
SINGLE_SPOT_OVERRIDES = {"car_spot_capacity": 1, "switch_buffer_minutes": 120}
TRACK_CP_AT = "2026-08-03T08:00:00.000Z"
TRACK_NOTICE_AT = "2026-08-03T09:00:00.000Z"
CYCLE_A_SPOT_AT = "2026-08-03T10:00:00.000Z"
CYCLE_A_LEAVES_AT = "2026-08-03T12:00:00.000Z"
CLOCK_AT_SPOT_ATTEMPTS = "2026-08-03T14:00:00.000Z"
BUFFER_STILL_BITING_AT = "2026-08-03T13:59:59.999Z"
BUFFER_CLEARS_AT = "2026-08-03T14:00:00.000Z"


def _released_cycle_and_a_replayable_token(api):
    """Cycle 1 released at 2026-08-10T16:00:00.000Z, plus a create payload for its car.

    Cycle 1's own occupation interval is therefore
    ``[2026-08-01T00:00:00.000Z, 2026-08-10T16:00:00.000Z)``, because PRD 3.2
    takes the lower bound from the logical clock at creation.
    """
    world = fx.reference_world(api)
    cycle_one = fx.released_cycle_a(api, world)
    assert cycle_one["movement_status"] == MOVEMENT_RELEASED
    assert_instant_eq(cycle_one["released_at"], CYCLE_A_RELEASE_AT, "released_at")

    car_id = cycle_one["rail_car_id"]
    car = fx.get_car(api, car_id)
    assert car["active_cycle_count"] == 0

    payload = f.placement_cycle_payload(
        world["customer_id"],
        car_id,
        world["facility_id"],
        world["tariff_id"],
        car["version"],
    )
    return world, cycle_one, car, payload


# ===========================================================================
# instance: rail_car_occupation_interval_is_half_open_at_released_at
# ===========================================================================
def test_the_car_interval_is_open_at_released_at_to_the_millisecond(api):
    """A new cycle at exactly the old released_at is legal; one millisecond earlier is not.

    PRD 3.2: "Because the interval is half-open at its upper end, creating a new
    cycle for the same car with the logical clock set to *exactly* the prior
    cycle's `released_at` succeeds, while setting the clock one millisecond
    earlier fails with `ERR_CAR_CYCLE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/rail_car_occupation_interval_is_half_open_at_released_at
    """
    _world, cycle_one, car, payload = _released_cycle_and_a_replayable_token(api)

    fx.set_clock(api, CLOCK_ONE_MS_BEFORE_RELEASE)
    overlapping = api.create_placement_cycle(payload, AGENT)
    validate_error(overlapping, ERR_CAR_CYCLE_OVERLAP)
    assert overlapping.status_code == 409
    assert_error_meta_is_minimal(overlapping)

    # The rejection consumed no OCC token, so the retry replays the same one.
    untouched = fx.get_car(api, car["id"])
    assert untouched["version"] == car["version"]
    assert untouched["active_cycle_count"] == 0

    fx.set_clock(api, CLOCK_AT_RELEASE_INSTANT)
    adjacent = get_success_data(api.create_placement_cycle(payload, AGENT), 201)
    assert adjacent["movement_status"] == MOVEMENT_ORDERED
    assert adjacent["rail_car_id"] == car["id"]

    moved = fx.get_car(api, car["id"])
    assert moved["version"] == car["version"] + 1
    assert moved["active_cycle_count"] == 1

    # The first cycle was not disturbed by the second.
    first_again = fx.get_cycle(api, cycle_one["id"])
    assert first_again["movement_status"] == MOVEMENT_RELEASED
    assert first_again["version"] == cycle_one["version"]
    first_charge = fx.charge_of_cycle(api, cycle_one["id"])
    assert first_charge["status"] == CHARGE_FINAL
    assert first_charge["gross_amount_cents"] == CYCLE_A_GROSS_CENTS


def test_a_voided_cycle_occupies_no_interval_at_all(api):
    """Void the first cycle and even the overlapping instant becomes available.

    PRD 3.2: "A cycle's **occupation interval** runs from its `created_at`, which
    is the logical clock at the moment of creation, up to but not including its
    `released_at` once it has been released, and from its `created_at` to positive
    infinity while it is any other non-voided state; a voided cycle occupies no
    interval at all."

    Design: Difficulty/resource_temporal_overlap/rail_car_occupation_interval_is_half_open_at_released_at
    """
    world, cycle_one, car, _payload = _released_cycle_and_a_replayable_token(api)

    voided = fx.void_cycle(api, cycle_one["id"])
    assert voided["movement_status"] == MOVEMENT_VOIDED
    assert fx.charge_of_cycle(api, cycle_one["id"])["status"] == CHARGE_VOIDED

    fresh = fx.get_car(api, car["id"])
    assert fresh["active_cycle_count"] == 0
    replay = f.placement_cycle_payload(
        world["customer_id"],
        car["id"],
        world["facility_id"],
        world["tariff_id"],
        fresh["version"],
    )

    # The instant that overlapped a RELEASED cycle overlaps nothing now.
    fx.set_clock(api, CLOCK_ONE_MS_BEFORE_RELEASE)
    accepted = get_success_data(api.create_placement_cycle(replay, AGENT), 201)
    assert accepted["movement_status"] == MOVEMENT_ORDERED
    assert fx.get_car(api, car["id"])["active_cycle_count"] == 1
    assert fx.get_cycle(api, cycle_one["id"])["movement_status"] == MOVEMENT_VOIDED


def _one_spot_track_with_a_car_on_it_and_a_car_waiting(api):
    """A capacity-1, buffer-120 track holding cycle A, with cycle B queued behind it."""
    world = fx.reference_world(api, facility_overrides=dict(SINGLE_SPOT_OVERRIDES))
    assert world["facility"]["car_spot_capacity"] == 1
    assert world["facility"]["switch_buffer_minutes"] == 120

    cycle_a = fx.actually_placed_cycle(
        api,
        world,
        constructive_at=TRACK_CP_AT,
        sent_at=TRACK_NOTICE_AT,
        actual_at=CYCLE_A_SPOT_AT,
    )
    cycle_b = fx.noticed_cycle(
        api, world, constructive_at=TRACK_CP_AT, sent_at=TRACK_NOTICE_AT
    )
    assert cycle_b["movement_status"] == MOVEMENT_CONSTRUCTIVELY_PLACED

    occupied = fx.probe_facility(api, world["facility_id"])
    assert occupied["occupied_spot_count"] == 1
    assert_instant_eq(occupied["last_switch_at"], CYCLE_A_SPOT_AT, "last_switch_at")

    fx.set_clock(api, CLOCK_AT_SPOT_ATTEMPTS)
    return world, cycle_a, fx.get_cycle(api, cycle_b["id"])


def _spot_attempt(api, cycle_id, at):
    return api.actual_placement(cycle_id, f.actual_placement_payload(at), AGENT)


# ===========================================================================
# instance: facility_spot_capacity_and_switch_buffer_are_separate_overlap_gates
# ===========================================================================
def test_a_full_track_fails_the_count_gate_and_not_the_buffer_gate(api):
    """The aggregate count fires while the buffer has long since elapsed.

    PRD 3.4: "The facility must have a spare spot, meaning its
    `occupied_spot_count` is strictly less than its `car_spot_capacity`, or the
    request yields `ERR_FACILITY_SPOT_UNAVAILABLE`; this is an aggregate
    condition, so several cars can each be individually placeable while the
    collective attempt exceeds the track's capacity."

    Design: Difficulty/resource_temporal_overlap/facility_spot_capacity_and_switch_buffer_are_separate_overlap_gates
    """
    world, cycle_a, cycle_b = _one_spot_track_with_a_car_on_it_and_a_car_waiting(api)
    charge_a_before = fx.charge_of_cycle(api, cycle_a["id"])

    refused = _spot_attempt(api, cycle_b["id"], CLOCK_AT_SPOT_ATTEMPTS)
    validate_error(refused, ERR_FACILITY_SPOT_UNAVAILABLE)
    assert refused.status_code == 409
    assert error_id_of(refused) != ERR_FACILITY_SWITCH_BUFFER
    assert_error_meta_is_minimal(refused)

    # The buffer was demonstrably clear: 10:00 plus 120 minutes is 12:00, and the
    # attempted spot instant is 14:00.
    still_full = fx.probe_facility(api, world["facility_id"])
    assert_instant_eq(still_full["last_switch_at"], CYCLE_A_SPOT_AT, "last_switch_at")
    assert still_full["occupied_spot_count"] == 1

    frozen = fx.get_cycle(api, cycle_b["id"])
    assert frozen == cycle_b
    assert_subset_equal(
        frozen,
        {
            "movement_status": MOVEMENT_CONSTRUCTIVELY_PLACED,
            "actual_placement_at": None,
            "clock_basis": CLOCK_BASIS_CONSTRUCTIVE,
        },
    )
    assert fx.charge_of_cycle(api, cycle_a["id"]) == charge_a_before


def test_the_emptied_track_stays_unavailable_for_the_whole_switch_buffer(api):
    """Emptiness is not availability: the bound is 12:00 plus 120 minutes, closed.

    PRD 3.4: "The facility's switch buffer must have elapsed, meaning either
    `last_switch_at` is null or the supplied `actual_placement_at` is at or after
    `last_switch_at` advanced by `switch_buffer_minutes` minutes, or the request
    yields `ERR_FACILITY_SWITCH_BUFFER`."

    Design: Difficulty/resource_temporal_overlap/facility_spot_capacity_and_switch_buffer_are_separate_overlap_gates
    """
    world, cycle_a, cycle_b = _one_spot_track_with_a_car_on_it_and_a_car_waiting(api)
    validate_error(
        _spot_attempt(api, cycle_b["id"], CLOCK_AT_SPOT_ATTEMPTS),
        ERR_FACILITY_SPOT_UNAVAILABLE,
    )

    fx.release_cycle(api, cycle_a["id"], CYCLE_A_LEAVES_AT, world["customer_id"])
    emptied = fx.probe_facility(api, world["facility_id"])
    assert emptied["occupied_spot_count"] == 0
    assert_instant_eq(emptied["last_switch_at"], CYCLE_A_LEAVES_AT, "last_switch_at")
    charge_a_before = fx.charge_of_cycle(api, cycle_a["id"])

    # The count gate now passes, and a different gate takes its place.
    too_soon = _spot_attempt(api, cycle_b["id"], BUFFER_STILL_BITING_AT)
    validate_error(too_soon, ERR_FACILITY_SWITCH_BUFFER)
    assert too_soon.status_code == 409
    assert error_id_of(too_soon) != ERR_FACILITY_SPOT_UNAVAILABLE
    assert fx.get_cycle(api, cycle_b["id"]) == cycle_b

    # One millisecond later the buffer is exhausted, because the bound is closed.
    fx.place_actually(api, cycle_b["id"], BUFFER_CLEARS_AT)
    spotted = fx.get_cycle(api, cycle_b["id"])
    assert spotted["movement_status"] == MOVEMENT_ACTUALLY_PLACED
    assert_instant_eq(
        spotted["actual_placement_at"], BUFFER_CLEARS_AT, "actual_placement_at"
    )

    refilled = fx.probe_facility(api, world["facility_id"])
    assert refilled["occupied_spot_count"] == 1
    assert_instant_eq(refilled["last_switch_at"], BUFFER_CLEARS_AT, "last_switch_at")
    # Cycle A's own money was never touched by any of cycle B's three attempts.
    assert fx.charge_of_cycle(api, cycle_a["id"]) == charge_a_before
