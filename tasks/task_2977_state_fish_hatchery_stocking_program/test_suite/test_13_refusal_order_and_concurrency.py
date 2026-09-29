"""
The staleness tokens, and the ladder that decides which of two broken rules is reported.

Three writes quote a parent revision, and each of them must refuse a caller who read
that parent before someone else moved it — the lot before a feeding, the plan before an
attach. The same discipline governs collisions between rules: when a request breaks
several at once the answer is a function of the request and not of the order the server
happened to evaluate, so an aborted trip on a quarantined lot reports its own state, an
overlapping warm load reports the calendar, and a quarantined lot beats an exhausted
appropriation.
"""

from test_helpers import (
    ADMIN_HEADERS,
    BIO_CARLA_HEADERS,
    VET_ANNA_HEADERS,
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

# Every trip in this file is scheduled against a clock standing at 08:00.
TRIP_CLOCK = f.instant(2026, 9, 1, 8)


def _lot_read_then_fed(api):
    """
    A certified lot with a granted 2400-fish request, fed after the caller read it.

    `ctx["stale_version"]` is the `version` the manager observed before the feeding,
    so it is exactly one behind the lot by the time the trip is scheduled. Nothing
    else about the trip is objectionable: the request is `ALLOCATED` 2400, the lot
    holds 16000 fish and the station's appropriation is untouched.
    """
    ctx = fx.certified_yearling_lot(api)
    ctx = fx.granted_request(api, ctx)
    ctx["unit"] = fx.create_transport_unit(api, ctx["hatchery"])
    fx.set_clock(api, TRIP_CLOCK)
    ctx["stale_version"] = fx.lot_version(api, ctx["hatchery"], ctx["lot"]["id"])
    fx.record_feeding(
        api, ctx["hatchery"], ctx["lot"]["id"], TRIP_CLOCK, 50.0, 45.4, 0
    )
    return ctx


def _trip_body(ctx, expected_lot_version):
    """The same 2400-fish trip body, varying only in the lot revision it quotes."""
    return f.stocking_event_payload(
        ctx["request"]["id"],
        ctx["lot"]["id"],
        ctx["unit"]["id"],
        expected_lot_version,
        scheduled_depart_at=f.instant(2026, 9, 1, 9),
        scheduled_return_at=f.instant(2026, 9, 1, 17),
    )


def test_a_trip_scheduled_against_a_stale_lot_revision_is_refused(api):
    """
    The manager read the lot, a feeding moved it, and the trip he then tries to schedule
    quotes the revision he read. The refusal is a staleness test rather than a race: no
    two requests overlap here at all, and because the token is checked above the state,
    safety, count and fiscal gates, neither the reservation nor the appropriation moves.

    PRD 2.8: "If the value does not match the parent's current `version`, the write is
    refused and nothing is mutated."

    PRD 2.8: "Any earlier write that touched the lot — a recorded feeding, a stage
    advance, a health cascade, another trip scheduled against the same lot — has advanced
    the lot's `version`, and a mismatch is rejected with `ERR_STALE_LOT_VERSION` (HTTP
    412)."

    PRD 2.8: "The version check is evaluated before the state checks, before the health
    and capacity gates, and before the reservation itself."

    Design: Corner/cross_cutting_complexity_layers/stale_lot_version_on_event_creation_returns_412
    """
    ctx = _lot_read_then_fed(api)

    response = api.create_stocking_event(
        _trip_body(ctx, ctx["stale_version"]), ctx["manager"]
    )

    validate_error(response, err.ERR_STALE_LOT_VERSION, 412)

    lot = fx.read_lot(api, ctx["hatchery"], ctx["lot"]["id"])
    assert_integer_equals(lot["version"], ctx["stale_version"] + 1, "version")
    assert_integer_equals(lot["reserved_count"], 0, "reserved_count")

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_integer_equals(
        station["budget_committed_cents"], 0, "budget_committed_cents"
    )


def test_the_refused_reservation_is_refused_and_not_lost(api):
    """
    Staleness is recoverable by re-reading: the identical trip body carrying the lot's
    current revision is accepted, which is what distinguishes a concurrency token from a
    substantive gate. The accepted trip reserves its 2400 fish and advances the lot once
    more.

    PRD 2.8: "This is not a race-detection mechanism and does not depend on requests
    overlapping in time — it is a staleness test against a value the caller read at some
    earlier point."

    PRD 3.8: "On success the trip opens in `SCHEDULED` status, the `fish_count` is added
    to the lot's `reserved_count` and the lot's `version` advances, and the
    `transport_cost_cents` is added to the station's `budget_committed_cents` with
    `budget_available_cents` recomputed."

    Design: Corner/cross_cutting_complexity_layers/stale_lot_version_on_event_creation_returns_412
    """
    ctx = _lot_read_then_fed(api)

    validate_error(
        api.create_stocking_event(
            _trip_body(ctx, ctx["stale_version"]), ctx["manager"]
        ),
        err.ERR_STALE_LOT_VERSION,
        412,
    )

    fresh = fx.lot_version(api, ctx["hatchery"], ctx["lot"]["id"])
    assert fresh == ctx["stale_version"] + 1, fresh

    event = validate_success(
        api.create_stocking_event(_trip_body(ctx, fresh), ctx["manager"]), 201
    )

    assert event["status"] == k.EVENT_SCHEDULED, event["status"]
    assert_integer_equals(event["fish_count"], 2400, "fish_count")

    lot = fx.read_lot(api, ctx["hatchery"], ctx["lot"]["id"])
    assert_integer_equals(lot["reserved_count"], 2400, "reserved_count")
    assert_integer_equals(lot["version"], fresh + 1, "version")


# Taylor Park is the second destination, so two requests can contend on one plan.
TAYLOR_PARK = {
    "name": "Taylor Park Reservoir",
    "county": "Gunnison",
    "habitat_suitability_score": 70,
    "angler_demand_index": 60,
    "plan_target_count": 4000,
    "access_type": k.ACCESS_SHORE_ONLY,
}

SECOND_ASK = {
    "requested_count": 1000,
    "justification": "Taylor Park yearling supplement",
}


def test_an_allocation_run_quoting_the_pre_attach_plan_revision_is_refused(api):
    """
    The administrator read the plan at version 1 and an attach has since taken it to 2, so
    the run he submits would resolve a candidate set he never saw. The token is checked
    above the eligibility walk, so the plan stays `DRAFT` with no run to its name and the
    queued request keeps its place in line with nothing granted.

    PRD 2.8: "Every attach advances the plan's `version`, so a run built from an older read
    is refused with `ERR_STALE_PLAN_VERSION` (HTTP 412) rather than silently allocating
    against a candidate set that has changed underneath it."

    PRD 2.8: "The version check is evaluated before `ERR_NO_ELIGIBLE_REQUESTS` and before
    every per-request eligibility test."

    Design: Corner/cross_cutting_complexity_layers/stale_plan_version_on_the_allocation_run_returns_412
    """
    ctx = fx.station_at_rest(api)
    request = fx.create_stocking_request(api, fx.create_water(api))
    plan = fx.create_allocation_plan(api, ctx["hatchery"])
    stale = plan["version"]
    assert_integer_equals(stale, 1, "version")
    fx.attach_request(api, request, plan, ADMIN_HEADERS)

    response = api.run_allocation_plan(
        plan["id"], f.run_plan_payload(stale), ADMIN_HEADERS
    )

    validate_error(response, err.ERR_STALE_PLAN_VERSION, 412)

    after = fx.read_plan(api, plan["id"])
    assert after["status"] == k.PLAN_DRAFT, after["status"]
    assert_integer_equals(after["run_count"], 0, "run_count")
    assert_integer_equals(after["version"], stale + 1, "version")

    queued = fx.read_request(api, request["id"])
    assert queued["status"] == k.REQUEST_QUEUED, queued["status"]
    assert_integer_equals(queued["allocated_count"], 0, "allocated_count")


def test_a_second_attach_quoting_the_pre_first_attach_revision_is_refused(api):
    """
    Two requesters contend on the same counter: the first attach moved the plan, and the
    second requester still holds the revision from before it. That is the concrete reason
    the attach endpoint advances a version it otherwise has no need to touch — and the
    refusal leaves the second request unattached, with the plan's revision unmoved by the
    attempt. Re-reading the plan lets the same attach through.

    PRD 2.8: "Attaching enlarges the plan's candidate set, and because two different
    requests attaching to one plan both advance that plan's `version`, the second caller
    has to re-read the plan before it may attach; otherwise `ERR_STALE_PLAN_VERSION` (HTTP
    412)."

    PRD 2.8: "This check is evaluated before the plan's own status checks and before
    `ERR_SIZE_CLASS_MISMATCH`."

    Design: Corner/cross_cutting_complexity_layers/stale_plan_version_on_a_second_attach_returns_412
    """
    ctx = fx.station_at_rest(api)
    plan = fx.create_allocation_plan(api, ctx["hatchery"])
    stale = plan["version"]
    first = fx.create_stocking_request(api, fx.create_water(api))
    second = fx.create_stocking_request(
        api, fx.create_water(api, **TAYLOR_PARK), **SECOND_ASK
    )
    fx.attach_request(api, first, plan, ADMIN_HEADERS)

    response = api.attach_to_plan(
        second["id"],
        f.attach_to_plan_payload(plan["id"], stale),
        BIO_CARLA_HEADERS,
    )

    validate_error(response, err.ERR_STALE_PLAN_VERSION, 412)

    refused = fx.read_request(api, second["id"])
    assert refused["status"] == k.REQUEST_SUBMITTED, refused["status"]
    assert_is_none(refused["allocation_plan_id"], "allocation_plan_id")

    after = fx.read_plan(api, plan["id"])
    assert_integer_equals(after["version"], stale + 1, "version")

    attached = validate_success(
        api.attach_to_plan(
            second["id"],
            f.attach_to_plan_payload(plan["id"], after["version"]),
            BIO_CARLA_HEADERS,
        ),
        200,
    )
    assert attached["status"] == k.REQUEST_QUEUED, attached["status"]
    assert attached["allocation_plan_id"] == plan["id"], attached["allocation_plan_id"]


def test_the_lots_revision_moves_on_every_write_and_stands_still_on_reads(api):
    """
    The token is only useful if it actually moves, and it must move for three unrelated
    write shapes: the take that brings the lot into existence leaves it at 1, a feeding
    takes it to 2, and a stage advance to 3. A read of the same lot changes nothing.

    PRD 2.7: "`version` begins at 1 when the record is created and increments by exactly
    one on every mutation of that record, whether the mutation came from a caller acting on
    it directly or from a cascade reaching it from elsewhere."

    PRD 2.7: "The rule to hold onto is that every record the service actually changes gets
    a `version` bump and a fresh `updated_at`, and no record the service merely reads
    does."

    Design: Corner/cross_cutting_complexity_layers/lot_version_increments_on_every_write_that_touches_it
    """
    ctx = fx.lot_at_egg(api)
    lot_id = ctx["lot"]["id"]
    assert_integer_equals(ctx["lot"]["version"], 1, "version")
    assert_integer_equals(ctx["lot"]["count_on_hand"], 20000, "count_on_hand")

    fed = validate_success(
        api.record_feeding(
            lot_id,
            f.feeding_payload(f.instant(2026, 8, 10), 300.0, 4.53592, 2000),
            ctx["manager"],
        ),
        200,
    )
    assert_integer_equals(fed["version"], 2, "version")

    advanced = validate_success(
        api.advance_stage(
            lot_id, f.advance_stage_payload(k.STAGE_FRY), ctx["manager"]
        ),
        200,
    )
    assert advanced["rearing_stage"] == k.STAGE_FRY, advanced["rearing_stage"]
    assert_integer_equals(advanced["version"], 3, "version")

    read_again = fx.read_lot(api, ctx["hatchery"], lot_id)
    assert_integer_equals(read_again["version"], 3, "version")


# A surveillance screen drawn at the trip clock, which comes back reportable.
SURVEILLANCE = {
    "inspection_type": k.INSPECTION_TYPE_ROUTINE,
    "sample_size": 30,
    "sampled_at": TRIP_CLOCK,
}


def _aborted_trip_on_a_quarantined_lot(api):
    """
    A trip the manager aborted, whose lot a later reportable finding then quarantined.

    The order matters: the trip is already `ABORTED` with `abort_reason`
    `OPERATOR_ABORT` when the finding lands, so the quarantine cascade — which touches
    only `SCHEDULED` and `IN_TRANSIT` trips — leaves it exactly as the manager left it.
    Both the state rule and the quarantine rule are therefore live on a load attempt.
    """
    ctx = fx.scheduled_trip(api)
    ctx["event"] = validate_success(
        api.abort_stocking_event(ctx["event"]["id"], ctx["manager"]), 200
    )
    inspection = fx.open_inspection(
        api, ctx["lot"]["id"], VET_ANNA_HEADERS, **SURVEILLANCE
    )
    ctx["inspection"] = fx.record_result(
        api, inspection["id"], k.RESULT_POSITIVE_REPORTABLE, k.PATHOGEN_VHSV
    )
    ctx["lot"] = fx.read_lot(api, ctx["hatchery"], ctx["lot"]["id"])
    return ctx


def test_loading_an_aborted_trip_reports_its_state_and_not_the_quarantine(api):
    """
    Both rules are broken by the same call — the trip is terminal and its lot is
    unshippable — and the ladder settles which one is reported: own-record state at level 8
    beats business safety at level 10, so the caller sees the 409 and never the more
    alarming 422 about the pathogen.

    PRD 2.10: "Loading a stocking trip that has already been aborted, on a lot that has
    since been quarantined, violates both the own-record state rule and the quarantine
    safety rule; the answer is `ERR_INVALID_STATE` (HTTP 409) and never
    `ERR_LOT_QUARANTINED` (HTTP 422), because state sits at level 8 and safety at level
    10."

    PRD 3.8: "Both `RELEASED` and `ABORTED` are terminal: neither can be loaded, released
    or aborted again."

    Design: Difficulty/priority_pair_validation_conflict/own_state_beats_quarantine_safety_on_load_of_aborted_event
    """
    ctx = _aborted_trip_on_a_quarantined_lot(api)
    assert ctx["event"]["status"] == k.EVENT_ABORTED, ctx["event"]["status"]
    assert ctx["lot"]["health_status"] == k.HEALTH_QUARANTINED, ctx["lot"][
        "health_status"
    ]

    response = api.load_stocking_event(
        ctx["event"]["id"], f.load_payload(TRIP_CLOCK, 12.0), ctx["manager"]
    )

    validate_error(response, err.ERR_INVALID_STATE, 409)


def test_the_refused_load_leaves_the_operator_abort_and_the_truck_as_they_were(api):
    """
    The refusal writes nothing and rewrites nothing: the abort reason stays the operator's
    own, not the cascade's `LOT_QUARANTINED`, the loading fields stay null, and the truck
    the abort returned to the fleet stays free.

    PRD 3.8: "Aborting stamps `aborted_at` from the clock, sets `abort_reason` to
    `OPERATOR_ABORT`, and sets `released_count` to 0."

    PRD 3.5: "Because the lot is quarantined, every stocking event on that lot in
    `SCHEDULED` or `IN_TRANSIT` status transitions to `ABORTED`, stamping `aborted_at` with
    the logical clock, setting `abort_reason` to `LOT_QUARANTINED` and `released_count` to
    zero, returning that event's `fish_count` out of the lot's `reserved_count`, releasing
    that event's `transport_cost_cents` from the station's `budget_committed_cents`, and
    returning the truck to `AVAILABLE` with its `current_event_id` cleared to null."

    Design: Difficulty/priority_pair_validation_conflict/own_state_beats_quarantine_safety_on_load_of_aborted_event
    """
    ctx = _aborted_trip_on_a_quarantined_lot(api)

    validate_error(
        api.load_stocking_event(
            ctx["event"]["id"], f.load_payload(TRIP_CLOCK, 12.0), ctx["manager"]
        ),
        err.ERR_INVALID_STATE,
        409,
    )

    event = fx.read_event(api, ctx["event"]["id"])
    assert event["status"] == k.EVENT_ABORTED, event["status"]
    assert event["abort_reason"] == k.ABORT_REASON_OPERATOR, event["abort_reason"]
    assert_integer_equals(event["released_count"], 0, "released_count")
    assert_is_none(event["loaded_at"], "loaded_at")
    assert_is_none(event["load_water_temp_c"], "load_water_temp_c")

    unit = fx.read_unit(api, ctx["unit"]["id"])
    assert unit["status"] == k.UNIT_AVAILABLE, unit["status"]
    assert_is_none(unit["current_event_id"], "current_event_id")


# The released first trip ran 08:00 to 14:00; the second books 13:00 to 19:00.
SECOND_DEPART_AT = f.instant(2026, 9, 1, 13)
SECOND_RETURN_AT = f.instant(2026, 9, 1, 19)


def _warm_load():
    """A load into 18.0-degree water, which derates the density to 0.40 lb per gallon."""
    return f.load_payload(SECOND_DEPART_AT, 18.0)


def _grant_of_2500(api, ctx, justification):
    """An `ALLOCATED` request for 2500 fish, granted whole out of a 2500-fish pool."""
    request = fx.create_stocking_request(
        api, ctx["water"], requested_count=2500, justification=justification
    )
    plan = fx.create_allocation_plan(api, ctx["hatchery"], available_count=2500)
    fx.attach_request(api, request, plan, ADMIN_HEADERS)
    fx.run_plan(api, plan)
    return fx.read_request(api, request["id"])


def _overlapping_second_trip(api):
    """
    A released first trip on TRK-01, and a second 2500-fish trip booked inside its window.

    The first trip is `RELEASED`, which returned TRK-01 to `AVAILABLE` but left its
    08:00–14:00 interval on record. The lot still holds 13600 certified fish and the
    appropriation still holds 49919000 cents, so the second trip's only problems are the
    ones the test is about: it overlaps that interval, and its 2500 fish weigh 250.00 lb
    against a warm-water ceiling of 200.00.
    """
    ctx = fx.released_trip(api)
    ctx["request_two"] = _grant_of_2500(
        api, ctx, "Second-round supplement for Blue Mesa"
    )
    fx.set_clock(api, SECOND_DEPART_AT)
    ctx["event_two"] = fx.create_stocking_event(
        api,
        ctx["hatchery"],
        ctx["request_two"],
        ctx["lot"]["id"],
        ctx["unit"],
        fish_count=2500,
        scheduled_depart_at=SECOND_DEPART_AT,
        scheduled_return_at=SECOND_RETURN_AT,
    )
    return ctx


def test_an_overlapping_warm_load_reports_the_calendar_and_not_the_capacity(api):
    """
    One call breaks two rules: the truck is already booked for part of this window by a
    trip that has finished, and 2500 fish exceed what 500 gallons of 18.0-degree water may
    legally carry. Temporal conflicts sit at level 12 and capacity ceilings at level 13, so
    the answer is the 409 about the truck and never the 422 about the load.

    PRD 2.10: "A load whose trip interval overlaps another trip on the same truck **and**
    whose `fish_count` exceeds the warm-water load plan answers
    `ERR_TRANSPORT_UNIT_UNAVAILABLE` (HTTP 409) and never
    `ERR_TRANSPORT_CAPACITY_EXCEEDED` (HTTP 422), because temporal conflicts sit at level
    12 and capacity ceilings at level 13."

    PRD 3.8: "Note that terminal trips keep their intervals on record for exactly this
    comparison, so a released trip still blocks the same slot."

    Design: Difficulty/priority_pair_validation_conflict/transport_overlap_beats_capacity_ceiling_on_warm_load
    """
    ctx = _overlapping_second_trip(api)
    assert fx.read_event(api, ctx["event"]["id"])["status"] == k.EVENT_RELEASED
    assert_number_equals(
        ctx["event_two"]["planned_load_lbs"], 250.0, 2, "planned_load_lbs"
    )

    response = api.load_stocking_event(
        ctx["event_two"]["id"], _warm_load(), ctx["manager"]
    )

    validate_error(response, err.ERR_TRANSPORT_UNIT_UNAVAILABLE, 409)

    event = fx.read_event(api, ctx["event_two"]["id"])
    assert event["status"] == k.EVENT_SCHEDULED, event["status"]
    assert_is_none(event["max_fish_allowed"], "max_fish_allowed")
    assert_is_none(event["loaded_at"], "loaded_at")

    unit = fx.read_unit(api, ctx["unit"]["id"])
    assert unit["status"] == k.UNIT_AVAILABLE, unit["status"]
    assert_is_none(unit["current_event_id"], "current_event_id")


def test_the_identical_warm_load_on_a_free_truck_reports_the_capacity(api):
    """
    The capacity ceiling really is broken, which is what makes the ordering falsifiable: an
    identical 2500-fish load into 18.0-degree water on a second, uncommitted truck of the
    same specification is refused with the 422 the first call must not have produced. Only
    the calendar differs between the two attempts.

    PRD 3.8: "Next the safe loading density is set: a baseline of 0.50 pounds of fish per
    gallon of water, multiplied by a derating factor of 0.80 when the reported
    `load_water_temp_c` is strictly warmer than 15.0 degrees Celsius, and left at the full
    baseline otherwise."

    PRD 3.8: "If the trip's `fish_count` exceeds `max_fish_allowed`, loading is refused with
    `ERR_TRANSPORT_CAPACITY_EXCEEDED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/transport_overlap_beats_capacity_ceiling_on_warm_load
    """
    ctx = _overlapping_second_trip(api)
    free_truck = fx.create_transport_unit(api, ctx["hatchery"], unit_code="TRK-02")
    request_three = _grant_of_2500(
        api, ctx, "Third-round supplement for Blue Mesa"
    )
    event_three = fx.create_stocking_event(
        api,
        ctx["hatchery"],
        request_three,
        ctx["lot"]["id"],
        free_truck,
        fish_count=2500,
        scheduled_depart_at=SECOND_DEPART_AT,
        scheduled_return_at=SECOND_RETURN_AT,
    )

    validate_error(
        api.load_stocking_event(ctx["event_two"]["id"], _warm_load(), ctx["manager"]),
        err.ERR_TRANSPORT_UNIT_UNAVAILABLE,
        409,
    )
    validate_error(
        api.load_stocking_event(event_three["id"], _warm_load(), ctx["manager"]),
        err.ERR_TRANSPORT_CAPACITY_EXCEEDED,
        422,
    )

    assert fx.read_unit(api, free_truck["id"])["status"] == k.UNIT_AVAILABLE
    booked = fx.read_event(api, event_three["id"])
    assert booked["status"] == k.EVENT_SCHEDULED, booked["status"]
    assert_is_none(booked["max_fish_allowed"], "max_fish_allowed")


# A station whose whole appropriation is smaller than one trip's base fare.
PINE_CREEK = {"name": "Pine Creek Hatchery", "annual_budget_cents": 40000}

PRE_TRANSFER_SCREEN = {
    "inspection_type": k.INSPECTION_TYPE_PRE_TRANSFER,
    "sample_size": 30,
    "sampled_at": f.instant(2026, 8, 10),
}

FRY_ASK = {
    "requested_count": 1000,
    "size_class": k.SIZE_CLASS_FRY,
    "justification": "Taylor Park fry supplement",
}

FRY_POOL = {"size_class": k.SIZE_CLASS_FRY, "available_count": 2000}


def _quarantined_lot_at_a_station_out_of_money(api):
    """
    A quarantined lot of 20000 fish at a station holding only 40000 cents.

    Both gates the trip will break are set up at once: the reportable finding has driven
    the lot to `QUARANTINED`, and the appropriation is smaller than the 45000-cent base
    fare, let alone the 45033 cents this 0.22-pound load actually costs. Everything else
    is in order — the request is `ALLOCATED` 1000 on an `ACTIVE` water and the truck is
    `AVAILABLE`.
    """
    ctx = fx.lot_at_egg(api, hatchery_overrides=PINE_CREEK)
    inspection = fx.open_inspection(
        api, ctx["lot"]["id"], VET_ANNA_HEADERS, **PRE_TRANSFER_SCREEN
    )
    fx.record_result(
        api, inspection["id"], k.RESULT_POSITIVE_REPORTABLE, k.PATHOGEN_IHNV
    )
    ctx["lot"] = fx.read_lot(api, ctx["hatchery"], ctx["lot"]["id"])
    ctx = fx.granted_request(
        api,
        ctx,
        water_overrides=TAYLOR_PARK,
        request_overrides=FRY_ASK,
        plan_overrides=FRY_POOL,
    )
    ctx["unit"] = fx.create_transport_unit(api, ctx["hatchery"], unit_code="TRK-09")
    return ctx


def _fry_trip_body(api, ctx):
    """The 1000-fish trip, quoting whatever revision the lot currently stands at."""
    return f.stocking_event_payload(
        ctx["request"]["id"],
        ctx["lot"]["id"],
        ctx["unit"]["id"],
        fx.lot_version(api, ctx["hatchery"], ctx["lot"]["id"]),
        fish_count=1000,
        scheduled_depart_at=f.instant(2026, 8, 11, 8),
        scheduled_return_at=f.instant(2026, 8, 11, 14),
    )


def test_scheduling_against_a_quarantined_lot_reports_the_health_and_not_the_money(api):
    """
    The trip costs 45033 cents against 40000 available and draws on a quarantined lot, so
    two gates are broken at once. Business safety sits at level 10 and fiscal ceilings at
    level 15, so the answer names the pathogen and never the appropriation — the inversion
    is tempting precisely because the shortfall is the number a caller notices first.

    PRD 2.10: "And scheduling a trip against a quarantined lot with a transport cost the
    appropriation cannot absorb answers `ERR_LOT_QUARANTINED` (HTTP 422) and never
    `ERR_BUDGET_EXCEEDED`, because safety sits at level 10 and fiscal ceilings at level
    15."

    PRD 2.10: "Because the ladder is total, whenever two rules are both violated the one
    with the lower number always wins."

    PRD 3.8: "Its `transport_cost_cents` is a flat 45000-cent base plus the
    `planned_load_lbs` figure multiplied by 150 cents per pound, that per-pound term
    rounded **up** to a whole cent, so a load of 240.00 pounds costs 45000 plus 36000, or
    81000 cents in total."

    PRD 3.8: "And finally the trip's computed transport cost must not exceed the station's
    `budget_available_cents`, or the answer is `ERR_BUDGET_EXCEEDED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/quarantine_safety_beats_budget_ceiling_on_event_creation
    """
    ctx = _quarantined_lot_at_a_station_out_of_money(api)
    assert ctx["lot"]["health_status"] == k.HEALTH_QUARANTINED, ctx["lot"][
        "health_status"
    ]
    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_integer_equals(
        station["budget_available_cents"], 40000, "budget_available_cents"
    )

    response = api.create_stocking_event(_fry_trip_body(api, ctx), ctx["manager"])

    validate_error(response, err.ERR_LOT_QUARANTINED, 422)


def test_the_refused_schedule_reserves_no_fish_and_commits_no_money(api):
    """
    A refusal at level 10 stops before either commitment scheduling would make: no trip
    exists for the request at all, the lot's whole 20000 fish are still unreserved, the
    appropriation is untouched, and the grant the request holds is still hers to spend on
    a healthy lot.

    PRD 3.8: "The lot must not be `QUARANTINED`, or the answer is `ERR_LOT_QUARANTINED`."

    PRD 3.8: "On success the trip opens in `SCHEDULED` status, the `fish_count` is added
    to the lot's `reserved_count` and the lot's `version` advances, and the
    `transport_cost_cents` is added to the station's `budget_committed_cents` with
    `budget_available_cents` recomputed."

    Design: Difficulty/priority_pair_validation_conflict/quarantine_safety_beats_budget_ceiling_on_event_creation
    """
    ctx = _quarantined_lot_at_a_station_out_of_money(api)

    validate_error(
        api.create_stocking_event(_fry_trip_body(api, ctx), ctx["manager"]),
        err.ERR_LOT_QUARANTINED,
        422,
    )

    _, meta = validate_paginated(
        api.list_stocking_events(
            ADMIN_HEADERS, {"stocking_request_id": ctx["request"]["id"]}
        )
    )
    assert meta["total_count"] == 0, meta

    lot = fx.read_lot(api, ctx["hatchery"], ctx["lot"]["id"])
    assert_integer_equals(lot["reserved_count"], 0, "reserved_count")
    assert_integer_equals(lot["count_on_hand"], 20000, "count_on_hand")

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_integer_equals(
        station["budget_committed_cents"], 0, "budget_committed_cents"
    )
    assert_integer_equals(
        station["budget_available_cents"], 40000, "budget_available_cents"
    )

    request = fx.read_request(api, ctx["request"]["id"])
    assert request["status"] == k.REQUEST_ALLOCATED, request["status"]
    assert_integer_equals(request["allocated_count"], 1000, "allocated_count")
