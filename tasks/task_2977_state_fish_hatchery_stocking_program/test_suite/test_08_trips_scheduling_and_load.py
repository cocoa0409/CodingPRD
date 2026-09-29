"""
Scheduling a trip and loading the truck.

Covers the two optional marking inputs, the order the three body identifiers are
resolved in, the derived figures the trip read exposes and the moments each of
them is filled in, the ceilinged transport cost, the five count-, species- and
fiscal gates on scheduling, the fleet's own clock-driven exit, and then the load:
the three capacity ceilings reduced by a minimum, the derate that starts strictly
above fifteen degrees, the inclusive far edge of the health certificate, and the
station posture that blocks the whole thing.
"""

from test_helpers import (
    ADMIN_HEADERS,
    assert_common_fields,
    assert_instant_equals,
    assert_integer_equals,
    assert_is_none,
    assert_number_equals,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors as err
from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures as fx

# Syntactically valid UUIDs that name no row of their collection.
UNKNOWN_LOT_ID = "77777777-7777-4777-8777-777777777777"
UNKNOWN_UNIT_ID = "55555555-5555-4555-8555-555555555555"
UNKNOWN_EVENT_ID = "66666666-6666-4666-8666-666666666666"

# The certificate the default certified lot carries, and the trip window a load
# on the far edge of it uses.
CERTIFICATE_EXPIRES_AT = f.instant(2026, 9, 24)
EDGE_TRIP = {
    "scheduled_depart_at": f.instant(2026, 9, 24, 8),
    "scheduled_return_at": f.instant(2026, 9, 24, 14),
}


def _trip_on_the_certificate_edge(api):
    """A `SCHEDULED` 2400-fish trip with the clock parked exactly on the expiry."""
    return fx.scheduled_trip(
        api, trip_clock=CERTIFICATE_EXPIRES_AT, event_overrides=dict(EDGE_TRIP)
    )


def test_scheduling_defaults_the_marking_programme_to_none_and_zero(api):
    """
    A trip scheduled without a marking programme persists `NONE` and 0 rather than
    nulls, and the three figures scheduling computes are on the row while the two
    that belong to later steps are still null.

    PRD 3.8: "Optionally the manager declares the marking programme: a `mark_type`
    of `NONE`, `AD_CLIP`, `CWT` or `PIT`, defaulting to `NONE`, and a `marked_count`
    of fish carrying the mark, defaulting to 0."

    Design: Corner/entities/stocking_event_mark_type_defaults_to_none_and_marked_count_to_zero
    """
    ctx = fx.scheduled_trip(api)
    event = ctx["event"]
    assert "mark_type" not in f.stocking_event_payload("r", "l", "u", 1)

    assert event["mark_type"] == k.MARK_NONE, event["mark_type"]
    assert_integer_equals(event["marked_count"], 0, "marked_count")
    assert_is_none(
        event["contribution_index_cohort"], "contribution_index_cohort"
    )
    assert event["status"] == k.EVENT_SCHEDULED, event["status"]
    assert_number_equals(event["planned_load_lbs"], 240.00, 2, "planned_load_lbs")
    assert_integer_equals(event["transport_cost_cents"], 81000, "transport_cost_cents")
    assert_number_equals(event["oxygen_flow_lpm"], 3.600, 3, "oxygen_flow_lpm")
    assert_is_none(event["max_fish_allowed"], "max_fish_allowed")
    assert_is_none(
        event["tempering_minutes_required"], "tempering_minutes_required"
    )
    assert_common_fields(event, expected_version=1)

    lot = fx.read_lot(api, ctx["hatchery"], ctx["lot"]["id"])
    assert_integer_equals(lot["reserved_count"], 2400, "reserved_count")
    assert_integer_equals(lot["count_on_hand"], 16000, "count_on_hand")

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_integer_equals(
        station["budget_committed_cents"], 81000, "budget_committed_cents"
    )
    assert_integer_equals(station["budget_spent_cents"], 0, "budget_spent_cents")
    assert_integer_equals(
        station["budget_available_cents"], 49919000, "budget_available_cents"
    )


def test_body_identifiers_on_a_trip_are_resolved_left_to_right(api):
    """
    With both the lot and the truck unresolvable the answer names the lot, because
    `lot_id` is declared first; with a real lot and the same bad truck the answer
    moves on to the truck. Neither attempt reserves anything.

    PRD 2.11: "Body keys are resolved strictly left to right in the order the
    endpoint declares its inputs, which makes the reported error predictable when a
    caller sends several bad identifiers at once."

    Design: Corner/entities/body_foreign_keys_are_resolved_in_declared_order_returns_not_found
    """
    ctx = fx.granted_request(api, fx.certified_yearling_lot(api))
    fx.set_clock(api, f.instant(2026, 9, 1, 8))
    lot_id = ctx["lot"]["id"]
    version = fx.lot_version(api, ctx["hatchery"], lot_id)

    both_unknown = api.create_stocking_event(
        f.stocking_event_payload(
            ctx["request"]["id"], UNKNOWN_LOT_ID, UNKNOWN_UNIT_ID, version
        ),
        ctx["manager"],
    )
    validate_error(both_unknown, err.ERR_LOT_NOT_FOUND, 404)

    unit_unknown = api.create_stocking_event(
        f.stocking_event_payload(
            ctx["request"]["id"], lot_id, UNKNOWN_UNIT_ID, version
        ),
        ctx["manager"],
    )
    validate_error(unit_unknown, err.ERR_TRANSPORT_UNIT_NOT_FOUND, 404)

    lot = fx.read_lot(api, ctx["hatchery"], lot_id)
    assert_integer_equals(lot["reserved_count"], 0, "reserved_count")
    assert_integer_equals(lot["version"], version, "version")

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_integer_equals(
        station["budget_committed_cents"], 0, "budget_committed_cents"
    )


def test_the_trip_read_exposes_the_load_plan_it_computed(api):
    """
    Reading a loaded trip shows the figures from both moments: the three computed at
    scheduling, the ceiling computed at load from the reported water temperature, and
    nothing yet from the release that has not happened.

    PRD 3.8: "A successful load records the supplied `loaded_at`, `load_water_temp_c`
    and `measured_load_lbs` on the trip alongside the freshly computed
    `oxygen_flow_lpm` and `max_fish_allowed`, moves the trip to `IN_TRANSIT`, moves
    the transport unit to `IN_USE` with this trip as its `current_event_id`, and
    advances the `version` of both the trip and the unit."

    Design: Corner/endpoints/stocking_event_read_exposes_the_load_plan_it_computed
    """
    ctx = fx.in_transit_trip(
        api, event_overrides={"mark_type": k.MARK_CWT, "marked_count": 2400}
    )

    event = fx.read_event(api, ctx["event"]["id"])

    assert event["status"] == k.EVENT_IN_TRANSIT, event["status"]
    assert_number_equals(event["planned_load_lbs"], 240.00, 2, "planned_load_lbs")
    assert_integer_equals(event["transport_cost_cents"], 81000, "transport_cost_cents")
    assert_number_equals(event["oxygen_flow_lpm"], 3.600, 3, "oxygen_flow_lpm")
    assert_integer_equals(event["max_fish_allowed"], 2500, "max_fish_allowed")
    assert_is_none(
        event["tempering_minutes_required"], "tempering_minutes_required"
    )
    assert_is_none(event["released_count"], "released_count")
    assert_is_none(
        event["contribution_index_cohort"], "contribution_index_cohort"
    )
    assert_is_none(
        event["contribution_index_harvest"], "contribution_index_harvest"
    )
    # A CWT programme loses 5 percent of its tags: 2400 * 0.95 = 2280.
    assert_integer_equals(
        event["effective_marked_count"], 2280, "effective_marked_count"
    )

    unit = fx.read_unit(api, ctx["unit"]["id"])
    assert unit["status"] == k.UNIT_IN_USE, unit["status"]
    assert unit["current_event_id"] == event["id"], unit["current_event_id"]


def test_transport_cost_ceils_the_per_pound_term_onto_the_base_fee(api):
    """
    The trip's cost is a flat mobilisation fee plus a ceilinged per-pound term, and
    it is committed rather than spent: the appropriation shows the whole 81000 cents
    against `budget_committed_cents` with `budget_spent_cents` still zero.

    PRD 3.8: "Its `transport_cost_cents` is a flat 45000-cent base plus the
    `planned_load_lbs` figure multiplied by 150 cents per pound, that per-pound term
    rounded **up** to a whole cent, so a load of 240.00 pounds costs 45000 plus
    36000, or 81000 cents in total."

    Design: Corner/calculations/transport_cost_ceils_the_per_pound_term_onto_the_base_fee
    """
    ctx = fx.scheduled_trip(
        api,
        event_overrides={
            "mark_type": k.MARK_CWT,
            "marked_count": 2400,
            "scheduled_depart_at": f.instant(2026, 9, 1, 9),
            "scheduled_return_at": f.instant(2026, 9, 1, 17),
        },
    )
    event = ctx["event"]

    # 2400 fish at 45.3592 g is exactly 0.1 lb each, so 240.00 lb of fish.
    assert_number_equals(event["planned_load_lbs"], 240.00, 2, "planned_load_lbs")
    assert_integer_equals(event["transport_cost_cents"], 81000, "transport_cost_cents")
    assert_number_equals(event["oxygen_flow_lpm"], 3.600, 3, "oxygen_flow_lpm")
    assert event["status"] == k.EVENT_SCHEDULED, event["status"]
    assert_is_none(event["max_fish_allowed"], "max_fish_allowed")

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_integer_equals(
        station["budget_committed_cents"], 81000, "budget_committed_cents"
    )
    assert_integer_equals(station["budget_spent_cents"], 0, "budget_spent_cents")
    assert_integer_equals(
        station["budget_available_cents"], 49919000, "budget_available_cents"
    )

    lot = fx.read_lot(api, ctx["hatchery"], ctx["lot"]["id"])
    assert_integer_equals(lot["reserved_count"], 2400, "reserved_count")
    assert_integer_equals(lot["count_on_hand"], 16000, "count_on_hand")


def test_scheduling_more_fish_than_the_lot_holds_reports_lot_insufficient_fish(api):
    """
    A grant larger than the lot cannot be shipped out of that lot: with a 17000-fish
    grant against 16000 uncommitted fish the count rule that fires is the lot's, not
    the grant's, and nothing is reserved or committed.

    PRD 3.8: "The `fish_count` must not exceed the lot's unreserved stock — its
    `count_on_hand` less its `reserved_count` — or the answer is
    `ERR_LOT_INSUFFICIENT_FISH` (HTTP 422)."

    Design: Corner/errors/scheduling_more_fish_than_the_lot_holds_reports_lot_insufficient_fish
    """
    ctx = fx.granted_request(
        api,
        fx.certified_yearling_lot(api),
        request_overrides={
            "requested_count": 17000,
            "justification": "Whole-lot transfer to Blue Mesa",
        },
        plan_overrides={"available_count": 20000},
    )
    assert_integer_equals(ctx["request"]["allocated_count"], 17000, "allocated_count")
    fx.set_clock(api, f.instant(2026, 9, 1, 8))
    unit = fx.create_transport_unit(api, ctx["hatchery"])
    lot_id = ctx["lot"]["id"]
    version = fx.lot_version(api, ctx["hatchery"], lot_id)

    response = api.create_stocking_event(
        f.stocking_event_payload(
            ctx["request"]["id"],
            lot_id,
            unit["id"],
            version,
            fish_count=17000,
            scheduled_depart_at=f.instant(2026, 9, 1, 9),
            scheduled_return_at=f.instant(2026, 9, 1, 17),
        ),
        ctx["manager"],
    )

    validate_error(response, err.ERR_LOT_INSUFFICIENT_FISH, 422)

    request = fx.read_request(api, ctx["request"]["id"])
    assert request["status"] == k.REQUEST_ALLOCATED, request["status"]
    assert_integer_equals(request["allocated_count"], 17000, "allocated_count")

    lot = fx.read_lot(api, ctx["hatchery"], lot_id)
    assert_integer_equals(lot["reserved_count"], 0, "reserved_count")
    assert_integer_equals(lot["version"], version, "version")

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_integer_equals(
        station["budget_committed_cents"], 0, "budget_committed_cents"
    )


def test_scheduling_more_fish_than_the_grant_reports_allocation_exceeded(api):
    """
    The mirror case: the lot is deep enough but the grant is not, so a 2500-fish trip
    against a 2400-fish grant is refused on the grant.

    PRD 3.8: "The `fish_count` must not exceed the request's `allocated_count`, or the
    answer is `ERR_ALLOCATION_EXCEEDED` (HTTP 422): a trip may not ship more fish than
    the request was granted."

    Design: Corner/errors/scheduling_more_fish_than_the_grant_reports_allocation_exceeded
    """
    ctx = fx.granted_request(api, fx.certified_yearling_lot(api))
    assert_integer_equals(ctx["request"]["allocated_count"], 2400, "allocated_count")
    fx.set_clock(api, f.instant(2026, 9, 1, 8))
    unit = fx.create_transport_unit(api, ctx["hatchery"])
    lot_id = ctx["lot"]["id"]
    version = fx.lot_version(api, ctx["hatchery"], lot_id)

    response = api.create_stocking_event(
        f.stocking_event_payload(
            ctx["request"]["id"],
            lot_id,
            unit["id"],
            version,
            fish_count=2500,
            scheduled_depart_at=f.instant(2026, 9, 1, 9),
            scheduled_return_at=f.instant(2026, 9, 1, 17),
        ),
        ctx["manager"],
    )

    validate_error(response, err.ERR_ALLOCATION_EXCEEDED, 422)

    request = fx.read_request(api, ctx["request"]["id"])
    assert request["status"] == k.REQUEST_ALLOCATED, request["status"]
    assert_integer_equals(request["allocated_count"], 2400, "allocated_count")

    lot = fx.read_lot(api, ctx["hatchery"], lot_id)
    # 2500 is well inside the lot's 16000 uncommitted fish, so this was not the
    # lot's own count rule.
    assert_integer_equals(lot["count_on_hand"], 16000, "count_on_hand")
    assert_integer_equals(lot["reserved_count"], 0, "reserved_count")


def test_shipping_a_rainbow_lot_against_a_brown_trout_grant_reports_species_mismatch(
    api,
):
    """
    Species agreement holds between the lot and the request, so a legally granted
    brown-trout request cannot be filled from a rainbow-trout lot even though every
    count and the appropriation would allow it.

    PRD 3.8: "The lot's `species` must equal the request's `species`, or the answer is
    `ERR_SPECIES_MISMATCH` (HTTP 422)."

    Design: Corner/errors/shipping_a_rainbow_lot_against_a_brown_trout_grant_reports_species_mismatch
    """
    ctx = fx.granted_request(
        api,
        fx.certified_yearling_lot(api),
        request_overrides={
            "species": k.SPECIES_BROWN_TROUT,
            "justification": "Brown trout diversification on Blue Mesa",
        },
        plan_overrides={"species": k.SPECIES_BROWN_TROUT},
    )
    assert ctx["lot"]["species"] == k.SPECIES_RAINBOW_TROUT, ctx["lot"]["species"]
    assert_integer_equals(ctx["request"]["allocated_count"], 2400, "allocated_count")
    fx.set_clock(api, f.instant(2026, 9, 1, 8))
    unit = fx.create_transport_unit(api, ctx["hatchery"])
    lot_id = ctx["lot"]["id"]

    response = api.create_stocking_event(
        f.stocking_event_payload(
            ctx["request"]["id"],
            lot_id,
            unit["id"],
            fx.lot_version(api, ctx["hatchery"], lot_id),
            scheduled_depart_at=f.instant(2026, 9, 1, 9),
            scheduled_return_at=f.instant(2026, 9, 1, 17),
        ),
        ctx["manager"],
    )

    validate_error(response, err.ERR_SPECIES_MISMATCH, 422)

    # The grant itself was legal; only this fill is not.
    request = fx.read_request(api, ctx["request"]["id"])
    assert_integer_equals(request["allocated_count"], 2400, "allocated_count")

    lot = fx.read_lot(api, ctx["hatchery"], lot_id)
    assert_integer_equals(lot["reserved_count"], 0, "reserved_count")

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_integer_equals(
        station["budget_committed_cents"], 0, "budget_committed_cents"
    )

    water = fx.read_water(api, ctx["water"]["id"])
    assert_integer_equals(water["allocated_count_ytd"], 2400, "allocated_count_ytd")


def test_a_trip_costing_more_than_the_appropriation_reports_budget_exceeded(api):
    """
    The fiscal gate sits last, so it is only observable when everything else passes: a
    station whose whole appropriation is 40000 cents cannot even afford the 45000-cent
    mobilisation fee, and the 0.22-pound trip that costs 45033 is refused.

    PRD 3.8: "And finally the trip's computed transport cost must not exceed the
    station's `budget_available_cents`, or the answer is `ERR_BUDGET_EXCEEDED` (HTTP
    422)."

    Design: Corner/errors/a_trip_costing_more_than_the_appropriation_reports_budget_exceeded
    """
    ctx = fx.lot_at_egg(
        api,
        hatchery_overrides={
            "name": "Golden Springs Hatchery",
            "water_source_type": k.WATER_SOURCE_WELL,
            "annual_water_right_af": 50.0,
            "rearing_capacity_lbs": 2000.0,
            "oxygen_supply_lpm": 6.0,
            "tss_permit_limit_mg_l": 25.0,
            "annual_budget_cents": 40000,
        },
        spawn_overrides={"target_release_count": 500},
        take_overrides={"eggs_taken": 1000},
    )
    assert ctx["lot"]["rearing_stage"] == k.STAGE_EGG, ctx["lot"]["rearing_stage"]
    assert_number_equals(ctx["lot"]["avg_weight_g"], 0.1, 4, "avg_weight_g")
    ctx = fx.granted_request(
        api,
        ctx,
        request_overrides={
            "requested_count": 1000,
            "size_class": k.SIZE_CLASS_FRY,
            "justification": "Fry plant from Golden Springs",
        },
        plan_overrides={"size_class": k.SIZE_CLASS_FRY},
    )
    assert_integer_equals(ctx["request"]["allocated_count"], 1000, "allocated_count")
    unit = fx.create_transport_unit(api, ctx["hatchery"], unit_code="TRK-02")
    lot_id = ctx["lot"]["id"]
    version = fx.lot_version(api, ctx["hatchery"], lot_id)

    # 1000 eggs at 0.1 g is 0.22 lb, so 45000 + ceil(0.22 * 150) = 45033 cents.
    response = api.create_stocking_event(
        f.stocking_event_payload(
            ctx["request"]["id"],
            lot_id,
            unit["id"],
            version,
            fish_count=1000,
            scheduled_depart_at=f.instant(2026, 8, 11, 9),
            scheduled_return_at=f.instant(2026, 8, 11, 17),
        ),
        ctx["manager"],
    )

    validate_error(response, err.ERR_BUDGET_EXCEEDED, 422)

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_integer_equals(
        station["budget_committed_cents"], 0, "budget_committed_cents"
    )
    assert_integer_equals(station["budget_spent_cents"], 0, "budget_spent_cents")
    assert_integer_equals(
        station["budget_available_cents"], 40000, "budget_available_cents"
    )

    lot = fx.read_lot(api, ctx["hatchery"], lot_id)
    assert_integer_equals(lot["reserved_count"], 0, "reserved_count")
    assert_integer_equals(lot["version"], version, "version")

    # The grant survives the failed trip.
    request = fx.read_request(api, ctx["request"]["id"])
    assert request["status"] == k.REQUEST_ALLOCATED, request["status"]
    assert_integer_equals(request["allocated_count"], 1000, "allocated_count")


def test_loading_2400_fish_into_warm_water_reports_transport_capacity_exceeded(api):
    """
    The derate is what refuses this load, not the truck and not the fish count: the
    identical trip that fails at 18.0 degrees loads cleanly at 15.0, because the
    volume ceiling falls from 250.00 to 200.00 pounds and the fish ceiling from 2500
    to 2000.

    PRD 3.8: "Next the safe loading density is set: a baseline of 0.50 pounds of fish
    per gallon of water, multiplied by a derating factor of 0.80 when the reported
    `load_water_temp_c` is strictly warmer than 15.0 degrees Celsius, and left at the
    full baseline otherwise."

    PRD 3.8: "If the trip's `fish_count` exceeds `max_fish_allowed`, loading is
    refused with `ERR_TRANSPORT_CAPACITY_EXCEEDED` (HTTP 422)."

    Design: Corner/errors/loading_2400_fish_into_warm_water_reports_transport_capacity_exceeded
    """
    ctx = fx.scheduled_trip(api)
    event_id = ctx["event"]["id"]

    refused = api.load_stocking_event(
        event_id, f.load_payload(f.instant(2026, 9, 1, 8), 18.0), ctx["manager"]
    )

    validate_error(refused, err.ERR_TRANSPORT_CAPACITY_EXCEEDED, 422)

    # TRK-01 carries no other trip, so this was capacity and not availability.
    still_scheduled = fx.read_event(api, event_id)
    assert still_scheduled["status"] == k.EVENT_SCHEDULED, still_scheduled["status"]
    assert_is_none(still_scheduled["max_fish_allowed"], "max_fish_allowed")
    unit = fx.read_unit(api, ctx["unit"]["id"])
    assert unit["status"] == k.UNIT_AVAILABLE, unit["status"]
    assert_is_none(unit["current_event_id"], "current_event_id")

    loaded = validate_success(
        api.load_stocking_event(
            event_id, f.load_payload(f.instant(2026, 9, 1, 8), 15.0), ctx["manager"]
        ),
        200,
    )
    assert loaded["status"] == k.EVENT_IN_TRANSIT, loaded["status"]
    assert_integer_equals(loaded["max_fish_allowed"], 2500, "max_fish_allowed")


def test_unknown_transport_unit_in_the_body_returns_transport_unit_not_found(api):
    """
    Body identifiers are settled before any status or count rule looks at the row, so
    a trip naming an unknown truck against a merely `SUBMITTED` request reports the
    fleet's 404 rather than the state or grant failure that also applies.

    PRD 2.10: "5. **Body foreign-key existence** — each identifier carried in the body
    resolves, checked left to right in the order the endpoint declares its inputs."

    Design: Corner/errors/unknown_transport_unit_in_the_body_returns_transport_unit_not_found
    """
    ctx = fx.certified_yearling_lot(api)
    water = fx.create_water(api)
    request = fx.create_stocking_request(api, water)
    assert request["status"] == k.REQUEST_SUBMITTED, request["status"]
    assert_integer_equals(request["allocated_count"], 0, "allocated_count")
    lot_id = ctx["lot"]["id"]
    version = fx.lot_version(api, ctx["hatchery"], lot_id)

    response = api.create_stocking_event(
        f.stocking_event_payload(
            request["id"],
            lot_id,
            UNKNOWN_UNIT_ID,
            version,
            fish_count=100,
            scheduled_depart_at=f.instant(2026, 8, 11, 9),
            scheduled_return_at=f.instant(2026, 8, 11, 17),
        ),
        ctx["manager"],
    )

    validate_error(response, err.ERR_TRANSPORT_UNIT_NOT_FOUND, 404)

    lot = fx.read_lot(api, ctx["hatchery"], lot_id)
    assert_integer_equals(lot["reserved_count"], 0, "reserved_count")
    assert_integer_equals(lot["version"], version, "version")


def test_unknown_event_id_on_abort_returns_event_not_found(api):
    """
    Aborting a trip that does not exist is the trips collection's own 404: there is no
    status for the state rule to find illegal.

    PRD 2.11: "An identifier in the URL path is resolved against the collection the
    path addresses, and a value that resolves to nothing produces that collection's
    own 404: `ERR_HATCHERY_NOT_FOUND`, `ERR_WATER_NOT_FOUND`,
    `ERR_BROOD_STOCK_NOT_FOUND`, `ERR_SPAWN_EVENT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
    `ERR_INSPECTION_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
    `ERR_TRANSPORT_UNIT_NOT_FOUND` or `ERR_EVENT_NOT_FOUND`."

    Design: Corner/errors/unknown_event_id_returns_event_not_found
    """
    response = api.abort_stocking_event(UNKNOWN_EVENT_ID, ADMIN_HEADERS)

    validate_error(response, err.ERR_EVENT_NOT_FOUND, 404)


def test_transport_unit_goes_out_of_service_when_its_certification_lapses(api):
    """
    The fleet's exit is driven by the clock alone and its boundary includes equality:
    one second short of the certification instant the truck is still `AVAILABLE`, and
    at the instant itself it is `OUT_OF_SERVICE` without anyone calling a fleet
    endpoint.

    PRD 3.8: "Certification lapse is the exit: on a clock advance, an `AVAILABLE` unit
    whose `certification_expires_at` the clock has reached or passed goes
    `OUT_OF_SERVICE`, which is terminal — such a unit can no longer be booked, and an
    attempt to load with it is refused with `ERR_TRANSPORT_UNIT_UNAVAILABLE` (HTTP
    409)."

    Design: Corner/state_machines/transport_unit_goes_out_of_service_when_its_certification_lapses
    """
    ctx = fx.station_at_rest(api)
    unit = fx.create_transport_unit(api, ctx["hatchery"])
    assert unit["status"] == k.UNIT_AVAILABLE, unit["status"]
    assert_instant_equals(
        unit["certification_expires_at"],
        f.instant(2027, 1, 1),
        "certification_expires_at",
    )

    fx.set_clock(api, "2026-12-31T23:59:59Z")
    one_second_short = fx.read_unit(api, unit["id"])
    assert one_second_short["status"] == k.UNIT_AVAILABLE, one_second_short["status"]

    fx.set_clock(api, f.instant(2027, 1, 1))

    lapsed = fx.read_unit(api, unit["id"])
    assert lapsed["status"] == k.UNIT_OUT_OF_SERVICE, lapsed["status"]
    assert_is_none(lapsed["current_event_id"], "current_event_id")

    _, meta = validate_paginated(
        api.list_transport_units(ADMIN_HEADERS, {"status": k.UNIT_AVAILABLE})
    )
    assert meta["total_count"] == 0, meta


def test_the_volume_ceiling_binds_over_oxygen_and_payload_on_a_cold_load(api):
    """
    Three ceilings are computed independently and reduced by a minimum. On TRK-01 in
    cold water they are 250.00 pounds of volume, 800.00 pounds of oxygen and 300.0
    pounds of rated payload, and the resulting 2500 fish could only have come from the
    volume term.

    PRD 3.8: "Three separate ceilings are then computed in pounds. The volume ceiling
    is the truck's `tank_gallons` multiplied by that density, rounded to two decimal
    places. The oxygen ceiling is the truck's `oxygen_lpm` divided by the 0.015
    litres-per-minute-per-pound demand, rounded to two decimal places. The mechanical
    ceiling is the truck's `max_load_lbs` as registered. The trip's gross capacity is
    the smallest of those three figures, and the trip's `max_fish_allowed` is that
    gross capacity divided by the average fish weight in pounds, rounded **down** to a
    whole fish."

    Design: Difficulty/combinatorial_formula/transport_load_plan_volume_limit_binds_over_oxygen_and_payload
    """
    ctx = fx.in_transit_trip(api)
    event = fx.read_event(api, ctx["event"]["id"])

    assert event["status"] == k.EVENT_IN_TRANSIT, event["status"]
    # 500 gal * 0.50 = 250.00 lb beats 12.0 / 0.015 = 800.00 lb and the 300.0 lb
    # rating; 250.00 / 0.1 lb per fish is 2500 fish.
    assert_integer_equals(event["max_fish_allowed"], 2500, "max_fish_allowed")
    assert_number_equals(event["planned_load_lbs"], 240.00, 2, "planned_load_lbs")
    assert_number_equals(event["oxygen_flow_lpm"], 3.600, 3, "oxygen_flow_lpm")
    assert_integer_equals(event["transport_cost_cents"], 81000, "transport_cost_cents")

    unit = fx.read_unit(api, ctx["unit"]["id"])
    assert unit["status"] == k.UNIT_IN_USE, unit["status"]
    assert unit["current_event_id"] == event["id"], unit["current_event_id"]


def test_a_smaller_tank_moves_the_binding_ceiling_and_the_fish_count_with_it(api):
    """
    Re-specify the truck so the same minimum lands elsewhere: a 400-gallon tank rated
    for 1000.0 pounds with a 30.0 lpm diffuser bank has ceilings of 200.00, 2000.00
    and 1000.0 pounds, and the answer of exactly 2000 fish is reachable only from the
    volume term.

    PRD 3.8: "The trip's gross capacity is the smallest of those three figures, and the
    trip's `max_fish_allowed` is that gross capacity divided by the average fish weight
    in pounds, rounded **down** to a whole fish."

    Design: Difficulty/combinatorial_formula/transport_load_plan_volume_limit_binds_over_oxygen_and_payload
    """
    ctx = fx.in_transit_trip(
        api,
        measured_load_lbs=200.0,
        unit_overrides={
            "unit_code": "TRK-07",
            "tank_gallons": 400.0,
            "max_load_lbs": 1000.0,
            "oxygen_lpm": 30.0,
        },
        event_overrides={"fish_count": 2000},
    )
    event = fx.read_event(api, ctx["event"]["id"])

    assert event["status"] == k.EVENT_IN_TRANSIT, event["status"]
    # The oxygen term would allow 20000 fish and the payload term 10000, so only
    # the 200.00 lb volume term can produce 2000.
    assert_integer_equals(event["max_fish_allowed"], 2000, "max_fish_allowed")
    assert_number_equals(event["planned_load_lbs"], 200.00, 2, "planned_load_lbs")
    assert_number_equals(event["oxygen_flow_lpm"], 3.000, 3, "oxygen_flow_lpm")
    assert_integer_equals(event["transport_cost_cents"], 75000, "transport_cost_cents")


def test_water_at_exactly_fifteen_degrees_carries_the_full_loading_density(api):
    """
    The derate threshold is strict, so water at exactly 15.0 degrees keeps the whole
    0.50 pounds per gallon and the 2400-fish trip loads against an un-derated ceiling
    of 2500.

    PRD 3.8: "Water at exactly 15.0 degrees carries the full 0.50 density; water at
    15.1 degrees carries only 0.40."

    Design: Difficulty/boundary_precision_check/warm_water_derate_starts_strictly_above_fifteen_degrees
    """
    ctx = fx.scheduled_trip(api)

    loaded = validate_success(
        api.load_stocking_event(
            ctx["event"]["id"],
            f.load_payload(f.instant(2026, 9, 1, 8), 15.0, 240.0),
            ctx["manager"],
        ),
        200,
    )

    assert loaded["status"] == k.EVENT_IN_TRANSIT, loaded["status"]
    # 500 gal * 0.50 = 250.00 lb, not the derated 200.00 lb.
    assert_integer_equals(loaded["max_fish_allowed"], 2500, "max_fish_allowed")
    assert_number_equals(loaded["load_water_temp_c"], 15.0, 1, "load_water_temp_c")
    assert_number_equals(loaded["oxygen_flow_lpm"], 3.600, 3, "oxygen_flow_lpm")


def test_a_tenth_of_a_degree_above_fifteen_derates_the_truck_and_refuses_the_load(api):
    """
    One tenth of a degree the other side of the threshold takes the density to 0.40,
    the ceiling to 2000 fish, and the same 2400-fish trip becomes unloadable — then
    loads unchanged at 15.0.

    PRD 3.8: "Water at exactly 15.0 degrees carries the full 0.50 density; water at
    15.1 degrees carries only 0.40."

    Design: Difficulty/boundary_precision_check/warm_water_derate_starts_strictly_above_fifteen_degrees
    """
    ctx = fx.scheduled_trip(api)
    event_id = ctx["event"]["id"]

    refused = api.load_stocking_event(
        event_id, f.load_payload(f.instant(2026, 9, 1, 8), 15.1, 240.0), ctx["manager"]
    )

    validate_error(refused, err.ERR_TRANSPORT_CAPACITY_EXCEEDED, 422)

    unchanged = fx.read_event(api, event_id)
    assert unchanged["status"] == k.EVENT_SCHEDULED, unchanged["status"]
    assert_is_none(unchanged["max_fish_allowed"], "max_fish_allowed")
    assert_is_none(unchanged["load_water_temp_c"], "load_water_temp_c")

    loaded = validate_success(
        api.load_stocking_event(
            event_id,
            f.load_payload(f.instant(2026, 9, 1, 8), 15.0, 240.0),
            ctx["manager"],
        ),
        200,
    )
    assert loaded["status"] == k.EVENT_IN_TRANSIT, loaded["status"]
    assert_integer_equals(loaded["max_fish_allowed"], 2500, "max_fish_allowed")


def test_loading_exactly_at_the_certificate_expiry_instant_is_still_legal(api):
    """
    Parking the clock exactly on `certificate_expires_at` must not fire the lapse
    sweep, because that test is strictly greater, and the load on that instant is
    accepted.

    PRD 3.8: "Then come the health gates, in the level-10 order set out earlier: a
    `QUARANTINED` lot answers `ERR_LOT_QUARANTINED`; a lot whose retained
    `certificate_expires_at` the clock has moved past answers
    `ERR_HEALTH_CERTIFICATE_EXPIRED` (HTTP 422), with loading exactly at
    `certificate_expires_at` still legal and one second later not; a lot whose
    `health_status` is `UNDER_INSPECTION` or `RESTRICTED`, or `UNSCREENED` with a null
    `certificate_expires_at` because it was never certified, answers
    `ERR_LOT_NOT_CERTIFIED` (HTTP 422); and a lot whose latest inspection has a
    `withdrawal_clears_at` the clock has not yet reached answers
    `ERR_WITHDRAWAL_PERIOD_ACTIVE` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/load_at_the_certificate_expiry_instant_is_still_legal
    """
    ctx = _trip_on_the_certificate_edge(api)

    on_the_edge = fx.read_lot(api, ctx["hatchery"], ctx["lot"]["id"])
    assert on_the_edge["health_status"] == k.HEALTH_CERTIFIED, on_the_edge[
        "health_status"
    ]
    assert_instant_equals(
        on_the_edge["certificate_expires_at"],
        CERTIFICATE_EXPIRES_AT,
        "certificate_expires_at",
    )

    loaded = validate_success(
        api.load_stocking_event(
            ctx["event"]["id"],
            f.load_payload(CERTIFICATE_EXPIRES_AT, 12.0),
            ctx["manager"],
        ),
        200,
    )

    assert loaded["status"] == k.EVENT_IN_TRANSIT, loaded["status"]
    assert_instant_equals(loaded["loaded_at"], CERTIFICATE_EXPIRES_AT, "loaded_at")


def test_the_load_on_the_expiry_instant_still_computes_the_full_cold_water_ceiling(api):
    """
    The accepted far edge is a full load and not a degraded one: the capacity ceiling
    and the oxygen draw are computed exactly as on any other cold-water load, and the
    truck is taken into use.

    PRD 3.8: "with loading exactly at `certificate_expires_at` still legal and one
    second later not"

    Design: Difficulty/boundary_precision_check/load_at_the_certificate_expiry_instant_is_still_legal
    """
    ctx = _trip_on_the_certificate_edge(api)

    validate_success(
        api.load_stocking_event(
            ctx["event"]["id"],
            f.load_payload(CERTIFICATE_EXPIRES_AT, 12.0),
            ctx["manager"],
        ),
        200,
    )

    event = fx.read_event(api, ctx["event"]["id"])
    assert_integer_equals(event["max_fish_allowed"], 2500, "max_fish_allowed")
    assert_number_equals(event["oxygen_flow_lpm"], 3.600, 3, "oxygen_flow_lpm")

    unit = fx.read_unit(api, ctx["unit"]["id"])
    assert unit["status"] == k.UNIT_IN_USE, unit["status"]
    assert unit["current_event_id"] == ctx["event"]["id"], unit["current_event_id"]


def test_loading_one_second_past_the_expiry_reports_the_certificate_expired(api):
    """
    One second later the sweep has lapsed the lot, and the load is refused as an
    expired certificate rather than as a lot that was never certified — the two 422s
    are told apart only by the retained expiry instant.

    PRD 2.10: "An expired certificate is checked next and reports
    `ERR_HEALTH_CERTIFICATE_EXPIRED`; a lot that has never been certified at all
    reports `ERR_LOT_NOT_CERTIFIED`."

    Design: Difficulty/boundary_precision_check/load_one_second_past_expiry_reports_certificate_expired
    """
    ctx = _trip_on_the_certificate_edge(api)
    one_second_later = f.shift_instant(CERTIFICATE_EXPIRES_AT, seconds=1)
    fx.set_clock(api, one_second_later)

    response = api.load_stocking_event(
        ctx["event"]["id"],
        f.load_payload(one_second_later, 12.0),
        ctx["manager"],
    )

    validate_error(response, err.ERR_HEALTH_CERTIFICATE_EXPIRED, 422)


def test_the_lapsed_lot_retains_its_expiry_and_keeps_its_inspection_certified(api):
    """
    The lapse is a health-status change only: the expiry instant stays on the lot, the
    signed inspection stays `CERTIFIED` as the historical document, and the refused
    trip and its truck are both left where they were.

    PRD 3.5: "Crucially, the lapsed expiry instant is **retained** on the lot rather
    than cleared — that retained value is exactly what lets a load attempt distinguish
    a lot whose certificate ran out, which answers `ERR_HEALTH_CERTIFICATE_EXPIRED`,
    from a lot that was never certified at all and carries a null
    `certificate_expires_at`, which answers `ERR_LOT_NOT_CERTIFIED`."

    Design: Difficulty/boundary_precision_check/load_one_second_past_expiry_reports_certificate_expired
    """
    ctx = _trip_on_the_certificate_edge(api)
    one_second_later = f.shift_instant(CERTIFICATE_EXPIRES_AT, seconds=1)
    fx.set_clock(api, one_second_later)

    validate_error(
        api.load_stocking_event(
            ctx["event"]["id"],
            f.load_payload(one_second_later, 12.0),
            ctx["manager"],
        ),
        err.ERR_HEALTH_CERTIFICATE_EXPIRED,
        422,
    )

    lot = fx.read_lot(api, ctx["hatchery"], ctx["lot"]["id"])
    assert lot["health_status"] == k.HEALTH_UNSCREENED, lot["health_status"]
    assert_instant_equals(
        lot["certificate_expires_at"],
        CERTIFICATE_EXPIRES_AT,
        "certificate_expires_at",
    )

    inspection = fx.read_inspection(api, ctx["inspection"]["id"])
    assert inspection["status"] == k.INSPECTION_CERTIFIED, inspection["status"]

    event = fx.read_event(api, ctx["event"]["id"])
    assert event["status"] == k.EVENT_SCHEDULED, event["status"]
    unit = fx.read_unit(api, ctx["unit"]["id"])
    assert unit["status"] == k.UNIT_AVAILABLE, unit["status"]
    assert_is_none(unit["current_event_id"], "current_event_id")


def test_a_frozen_station_refuses_the_load_while_the_lot_is_still_certified(api):
    """
    The gate reached from the trip through the lot is the station's derived posture, not
    any status a caller set: two discharge exceedances logged between scheduling and
    loading turn the same load call into `ERR_HATCHERY_FROZEN` while the lot itself is
    still perfectly certified.

    PRD 2.6: "At `FROZEN`, five operations are refused with `ERR_HATCHERY_FROZEN` (HTTP
    409): opening a spawning window, planning an egg take, recording an egg take,
    running an allocation plan, and loading a truck."

    Design: Difficulty/cross_entity_state_dependency/load_blocked_while_the_station_posture_is_frozen
    """
    ctx = fx.scheduled_trip(api)
    fx.log_exceedance(api, ctx["hatchery"], f.instant(2026, 9, 1, 8))
    fx.log_exceedance(api, ctx["hatchery"], f.instant(2026, 9, 1, 8), tss_mg_l=30.0)

    response = api.load_stocking_event(
        ctx["event"]["id"],
        f.load_payload(f.instant(2026, 9, 1, 8), 12.0),
        ctx["manager"],
    )

    validate_error(response, err.ERR_HATCHERY_FROZEN, 409)

    # Not ERR_LOT_NOT_CERTIFIED: the lot is untouched by the station's posture.
    lot = fx.read_lot(api, ctx["hatchery"], ctx["lot"]["id"])
    assert lot["health_status"] == k.HEALTH_CERTIFIED, lot["health_status"]
    assert_integer_equals(lot["reserved_count"], 2400, "reserved_count")


def test_the_freeze_that_blocks_the_load_also_suspends_the_brood_group(api):
    """
    The same two samples that block the truck drive the station's whole compliance
    dimension: the rolling count reaches two, the posture freezes, the water-right
    ledger records both samples, and the freeze cascades into the `SPAWNING` brood
    group while the egg take that has already happened is left alone.

    PRD 2.6: "Because the freeze test runs first, a station with two exceedances inside
    the rolling window is `FROZEN` even when its density is comfortable and its water
    right untouched."

    PRD 2.6: "When a station becomes `FROZEN` — whether from `OPEN` or from
    `RESTRICTED` — every brood group of that station in `SPAWNING` status transitions to
    `SUSPENDED`, and because each of those groups is now suspended, each of its spawn
    events still in `PLANNED` status transitions to `CANCELLED`, returning that event's
    committed females to the group's available pool and that event's reserved acre-feet
    to the station's available water."

    Design: Difficulty/cross_entity_state_dependency/load_blocked_while_the_station_posture_is_frozen
    """
    ctx = fx.scheduled_trip(api)
    fx.log_exceedance(api, ctx["hatchery"], f.instant(2026, 9, 1, 8))
    fx.log_exceedance(api, ctx["hatchery"], f.instant(2026, 9, 1, 8), tss_mg_l=30.0)

    validate_error(
        api.load_stocking_event(
            ctx["event"]["id"],
            f.load_payload(f.instant(2026, 9, 1, 8), 12.0),
            ctx["manager"],
        ),
        err.ERR_HATCHERY_FROZEN,
        409,
    )

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_integer_equals(
        station["exceedance_count_rolling"], 2, "exceedance_count_rolling"
    )
    assert station["operating_posture"] == k.POSTURE_FROZEN, station[
        "operating_posture"
    ]
    # 1.0000 AF used by the 20000-egg take plus 0.5 AF of discharge per sample.
    assert_number_equals(station["water_used_af"], 2.0, 4, "water_used_af")
    assert_number_equals(station["water_available_af"], 118.0, 4, "water_available_af")

    brood_stock = fx.read_brood_stock(
        api, ctx["hatchery"], ctx["brood_stock"]["id"]
    )
    assert brood_stock["status"] == k.BROOD_SUSPENDED, brood_stock["status"]

    spawn_event = validate_success(
        api.get_spawn_event(ctx["spawn_event"]["id"], ctx["manager"]), 200
    )
    assert spawn_event["status"] == k.SPAWN_TAKEN, spawn_event["status"]

    event = fx.read_event(api, ctx["event"]["id"])
    assert event["status"] == k.EVENT_SCHEDULED, event["status"]
    unit = fx.read_unit(api, ctx["unit"]["id"])
    assert unit["status"] == k.UNIT_AVAILABLE, unit["status"]
