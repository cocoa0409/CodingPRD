"""
The two temporal conflicts checked at loading: one truck's calendar, one station's air.

The interval predicate is strict at both ends, so a trip departing at the exact
instant the previous one returned may load while a trip departing an hour inside
that window may not — and terminal trips keep their intervals on record for the
comparison. The oxygen test is an aggregate over a different set entirely: only
trips that are *currently* out, on any truck of the station, and two loads that are
each comfortably inside their own truck's rating can still overrun the diffusers.
"""

from test_helpers import (
    ADMIN_HEADERS,
    assert_integer_equals,
    assert_is_none,
    assert_number_equals,
    validate_error,
    validate_success,
)
from test_helpers import api_errors as err
from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures as fx

# The first trip runs 08:00 to 14:00; the second one's slot is what varies.
FIRST_RETURN_AT = f.instant(2026, 9, 1, 14)


def _second_grant(api, ctx):
    """A second `ALLOCATED` request for 2500 fish, from a pool holding exactly 2500."""
    request = fx.create_stocking_request(
        api,
        ctx["water"],
        requested_count=2500,
        justification="Second Blue Mesa plant on the same operating day",
    )
    plan = fx.create_allocation_plan(api, ctx["hatchery"], available_count=2500)
    fx.attach_request(api, request, plan, ADMIN_HEADERS)
    fx.run_plan(api, plan)
    return fx.read_request(api, request["id"])


def _second_trip_on_the_same_truck(api, depart_at, return_at):
    """
    A released first trip, then a second 2500-fish trip booked on the same truck.

    The first trip occupied TRK-01 from 08:00 to 14:00 and has reached `RELEASED`,
    which leaves the truck `AVAILABLE` but keeps that interval on record. The lot
    still holds 13600 fish and is still `CERTIFIED`, so nothing but the calendar can
    stand in the second trip's way. Its 2500 fish weigh 250.00 lb.
    """
    ctx = fx.released_trip(api)
    ctx["request_two"] = _second_grant(api, ctx)
    fx.set_clock(api, depart_at)
    ctx["event_two"] = fx.create_stocking_event(
        api,
        ctx["hatchery"],
        ctx["request_two"],
        ctx["lot"]["id"],
        ctx["unit"],
        fish_count=2500,
        scheduled_depart_at=depart_at,
        scheduled_return_at=return_at,
    )
    return ctx


def test_a_trip_departing_the_instant_the_last_one_returned_may_load(api):
    """
    The second trip departs at 14:00:00, exactly when the released first trip returned.
    A closed-interval reading of the predicate refuses this load; the strict one required
    by the PRD allows it, and the truck changes hands.

    PRD 3.8: "The truck's calendar must be free: the trip is compared against every other
    trip on the same transport unit in `SCHEDULED`, `IN_TRANSIT` or `RELEASED` status, and
    two trips intersect exactly when this trip's `scheduled_depart_at` falls strictly
    before the other's `scheduled_return_at` **and** the other's `scheduled_depart_at`
    falls strictly before this trip's `scheduled_return_at`."

    PRD 3.8: "Trips that merely touch — one returning at exactly the instant the next
    departs — do not intersect."

    Design: Difficulty/resource_temporal_overlap/touching_trips_on_one_unit_do_not_overlap
    """
    ctx = _second_trip_on_the_same_truck(
        api, FIRST_RETURN_AT, f.instant(2026, 9, 1, 20)
    )

    loaded = validate_success(
        api.load_stocking_event(
            ctx["event_two"]["id"],
            f.load_payload(FIRST_RETURN_AT, 12.0, 250.0),
            ctx["manager"],
        ),
        200,
    )

    assert loaded["status"] == k.EVENT_IN_TRANSIT, loaded["status"]

    unit = fx.read_unit(api, ctx["unit"]["id"])
    assert unit["status"] == k.UNIT_IN_USE, unit["status"]
    assert unit["current_event_id"] == ctx["event_two"]["id"], unit["current_event_id"]

    first = fx.read_event(api, ctx["event"]["id"])
    assert first["status"] == k.EVENT_RELEASED, first["status"]


def test_the_touching_trip_computes_its_own_two_hundred_fifty_pound_load_plan(api):
    """
    The load the calendar allowed sits exactly on its ceiling: 2500 fish at 0.1 lb each
    are 250.00 lb, and a 500-gallon tank at the full cold-water density of 0.50 lb per
    gallon is worth exactly 250.00 lb, so `max_fish_allowed` lands on 2500 and the trip
    is neither refused nor given any headroom.

    PRD 3.8: "The trip's `planned_load_lbs` is the `fish_count` multiplied by the lot's
    current `avg_weight_g`, converted to pounds at 453.592 grams per pound and rounded to
    two decimal places."

    PRD 3.8: "Its `transport_cost_cents` is a flat 45000-cent base plus the
    `planned_load_lbs` figure multiplied by 150 cents per pound, that per-pound term
    rounded **up** to a whole cent, so a load of 240.00 pounds costs 45000 plus 36000, or
    81000 cents in total."

    PRD 3.8: "Its `oxygen_flow_lpm` is the `planned_load_lbs` figure multiplied by an
    oxygen demand of 0.015 litres per minute per pound of fish, rounded to three decimal
    places."

    PRD 3.8: "The trip's gross capacity is the smallest of those three figures, and the
    trip's `max_fish_allowed` is that gross capacity divided by the average fish weight in
    pounds, rounded **down** to a whole fish."

    Design: Difficulty/resource_temporal_overlap/touching_trips_on_one_unit_do_not_overlap
    """
    ctx = _second_trip_on_the_same_truck(
        api, FIRST_RETURN_AT, f.instant(2026, 9, 1, 20)
    )

    scheduled = ctx["event_two"]
    assert_number_equals(scheduled["planned_load_lbs"], 250.0, 2, "planned_load_lbs")
    assert_integer_equals(
        scheduled["transport_cost_cents"], 82500, "transport_cost_cents"
    )
    assert_number_equals(scheduled["oxygen_flow_lpm"], 3.75, 3, "oxygen_flow_lpm")

    loaded = validate_success(
        api.load_stocking_event(
            ctx["event_two"]["id"],
            f.load_payload(FIRST_RETURN_AT, 12.0, 250.0),
            ctx["manager"],
        ),
        200,
    )

    assert_integer_equals(loaded["max_fish_allowed"], 2500, "max_fish_allowed")
    assert_integer_equals(loaded["fish_count"], 2500, "fish_count")
    assert_number_equals(loaded["planned_load_lbs"], 250.0, 2, "planned_load_lbs")
    assert_number_equals(loaded["oxygen_flow_lpm"], 3.75, 3, "oxygen_flow_lpm")


def test_a_trip_departing_inside_the_last_trips_window_cannot_load(api):
    """
    One hour inside the previous trip's window on the same truck is an intersection, and
    the released trip still holds the slot even though the truck itself reads `AVAILABLE`.
    Loading at a cold 12.0 degrees keeps the capacity ceiling at 2500, so the only rule
    the trip can break is the calendar.

    PRD 3.8: "An intersection, or a unit that has gone `OUT_OF_SERVICE`, is
    `ERR_TRANSPORT_UNIT_UNAVAILABLE`."

    PRD 3.8: "Note that terminal trips keep their intervals on record for exactly this
    comparison, so a released trip still blocks the same slot."

    Design: Difficulty/resource_temporal_overlap/overlapping_trip_on_the_same_unit_is_refused
    """
    ctx = _second_trip_on_the_same_truck(
        api, f.instant(2026, 9, 1, 13), f.instant(2026, 9, 1, 19)
    )
    before = fx.read_unit(api, ctx["unit"]["id"])
    assert before["status"] == k.UNIT_AVAILABLE, before["status"]

    response = api.load_stocking_event(
        ctx["event_two"]["id"],
        f.load_payload(f.instant(2026, 9, 1, 13), 12.0, 250.0),
        ctx["manager"],
    )

    validate_error(response, err.ERR_TRANSPORT_UNIT_UNAVAILABLE, 409)


def test_the_refused_overlapping_load_leaves_the_trip_and_the_truck_untouched(api):
    """
    Nothing the load would have computed or moved survives the refusal: no capacity
    figures on the trip, no loaded instant, the truck still free, and the reservation the
    scheduling made still standing at its full 2500 fish.

    PRD 3.8: "A successful load records the supplied `loaded_at`, `load_water_temp_c` and
    `measured_load_lbs` on the trip alongside the freshly computed `oxygen_flow_lpm` and
    `max_fish_allowed`, moves the trip to `IN_TRANSIT`, moves the transport unit to
    `IN_USE` with this trip as its `current_event_id`, and advances the `version` of both
    the trip and the unit."

    Design: Difficulty/resource_temporal_overlap/overlapping_trip_on_the_same_unit_is_refused
    """
    ctx = _second_trip_on_the_same_truck(
        api, f.instant(2026, 9, 1, 13), f.instant(2026, 9, 1, 19)
    )

    validate_error(
        api.load_stocking_event(
            ctx["event_two"]["id"],
            f.load_payload(f.instant(2026, 9, 1, 13), 12.0, 250.0),
            ctx["manager"],
        ),
        err.ERR_TRANSPORT_UNIT_UNAVAILABLE,
        409,
    )

    event = fx.read_event(api, ctx["event_two"]["id"])
    assert event["status"] == k.EVENT_SCHEDULED, event["status"]
    assert_is_none(event["max_fish_allowed"], "max_fish_allowed")
    assert_is_none(event["loaded_at"], "loaded_at")
    assert_is_none(event["load_water_temp_c"], "load_water_temp_c")

    unit = fx.read_unit(api, ctx["unit"]["id"])
    assert unit["status"] == k.UNIT_AVAILABLE, unit["status"]
    assert_is_none(unit["current_event_id"], "current_event_id")

    lot = fx.read_lot(api, ctx["hatchery"], ctx["lot"]["id"])
    assert_integer_equals(lot["reserved_count"], 2500, "reserved_count")


SECOND_LOAD_AT = f.instant(2026, 9, 1, 13)


def _two_trips_overlapping_on_two_trucks(api):
    """
    The first trip out on TRK-01, and a second trip booked on TRK-02 inside its window.

    The first trip is `IN_TRANSIT` from 08:00 to 14:00 drawing 3.600 lpm. The second
    truck is registered with identical ratings, so its own 2500-fish load at 3.750 lpm
    is well inside its 12.0 lpm diffuser — but the station is rated 6.0 lpm in total.
    The two trips sit on different trucks, so no unit's calendar is in question.
    """
    ctx = fx.in_transit_trip(api)
    ctx["unit_two"] = fx.create_transport_unit(
        api, ctx["hatchery"], unit_code="TRK-02"
    )
    ctx["request_two"] = _second_grant(api, ctx)
    fx.set_clock(api, SECOND_LOAD_AT)
    ctx["event_two"] = fx.create_stocking_event(
        api,
        ctx["hatchery"],
        ctx["request_two"],
        ctx["lot"]["id"],
        ctx["unit_two"],
        fish_count=2500,
        scheduled_depart_at=SECOND_LOAD_AT,
        scheduled_return_at=f.instant(2026, 9, 1, 19),
    )
    return ctx


def test_two_trucks_out_together_exceed_the_stations_bulk_oxygen_supply(api):
    """
    Neither load is anywhere near its own truck's 12.0 lpm rating, and neither truck has
    a trip of its own to collide with. Only the sum over intersecting trips that are
    currently out — 3.600 already aboard TRK-01 plus 3.750 asked for TRK-02 — reaches the
    7.350 lpm that overruns the station's 6.0.

    PRD 3.8: "Separately, the station's bulk oxygen supply is shared across every truck
    that is out at the same time: the total `oxygen_flow_lpm` of this station's trips that
    are currently `IN_TRANSIT` with an intersecting trip interval, plus this trip's own
    `oxygen_flow_lpm`, must not exceed the station's `oxygen_supply_lpm`, and an overrun is
    `ERR_OXYGEN_SUPPLY_EXCEEDED` (HTTP 422)."

    PRD 3.8: "Each individual load can be well inside its own truck's rating and the
    station can still fail this aggregate test."

    Design: Difficulty/resource_temporal_overlap/station_oxygen_supply_exceeded_across_two_concurrent_trips
    """
    ctx = _two_trips_overlapping_on_two_trucks(api)
    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_number_equals(station["oxygen_supply_lpm"], 6.0, 1, "oxygen_supply_lpm")
    assert_number_equals(ctx["unit_two"]["oxygen_lpm"], 12.0, 1, "oxygen_lpm")

    response = api.load_stocking_event(
        ctx["event_two"]["id"],
        f.load_payload(SECOND_LOAD_AT, 12.0, 250.0),
        ctx["manager"],
    )

    validate_error(response, err.ERR_OXYGEN_SUPPLY_EXCEEDED, 422)

    first = fx.read_event(api, ctx["event"]["id"])
    assert first["status"] == k.EVENT_IN_TRANSIT, first["status"]
    assert_number_equals(first["oxygen_flow_lpm"], 3.6, 3, "oxygen_flow_lpm")

    second = fx.read_event(api, ctx["event_two"]["id"])
    assert second["status"] == k.EVENT_SCHEDULED, second["status"]
    assert_is_none(second["max_fish_allowed"], "max_fish_allowed")

    unit_two = fx.read_unit(api, ctx["unit_two"]["id"])
    assert unit_two["status"] == k.UNIT_AVAILABLE, unit_two["status"]
    assert_is_none(unit_two["current_event_id"], "current_event_id")


def test_the_same_load_succeeds_once_the_first_trip_is_terminal(api):
    """
    The aggregate counts only trips that are out right now, so the identical load that
    overran the diffusers is accepted the moment the first trip reaches `RELEASED` — the
    interval is still on record for the calendar test, but a terminal trip no longer
    draws air.

    PRD 3.8: "Separately, the station's bulk oxygen supply is shared across every truck
    that is out at the same time: the total `oxygen_flow_lpm` of this station's trips that
    are currently `IN_TRANSIT` with an intersecting trip interval, plus this trip's own
    `oxygen_flow_lpm`, must not exceed the station's `oxygen_supply_lpm`, and an overrun is
    `ERR_OXYGEN_SUPPLY_EXCEEDED` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/station_oxygen_supply_exceeded_across_two_concurrent_trips
    """
    ctx = _two_trips_overlapping_on_two_trucks(api)
    payload = f.load_payload(SECOND_LOAD_AT, 12.0, 250.0)

    validate_error(
        api.load_stocking_event(ctx["event_two"]["id"], payload, ctx["manager"]),
        err.ERR_OXYGEN_SUPPLY_EXCEEDED,
        422,
    )

    released = fx.release_event(
        api, ctx["hatchery"], ctx["event"]["id"], SECOND_LOAD_AT, 4.5, 48, 20
    )
    assert released["status"] == k.EVENT_RELEASED, released["status"]

    loaded = validate_success(
        api.load_stocking_event(ctx["event_two"]["id"], payload, ctx["manager"]), 200
    )

    assert loaded["status"] == k.EVENT_IN_TRANSIT, loaded["status"]
    assert_number_equals(loaded["oxygen_flow_lpm"], 3.75, 3, "oxygen_flow_lpm")
    assert_integer_equals(loaded["max_fish_allowed"], 2500, "max_fish_allowed")

    unit_two = fx.read_unit(api, ctx["unit_two"]["id"])
    assert unit_two["status"] == k.UNIT_IN_USE, unit_two["status"]
    assert unit_two["current_event_id"] == ctx["event_two"]["id"], unit_two[
        "current_event_id"
    ]
