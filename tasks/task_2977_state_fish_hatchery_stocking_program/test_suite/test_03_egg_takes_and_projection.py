"""
Planning an egg take, the survival projection, and reconciling the actual take.

Covers the computed projection fields and the derate tier they read from stored
density, the rearing lot that only a recorded take can create, the water-right
ceiling on the actual egg count, the compensation a cancel performs on two
parents at once, terminal-state lockdown after a take, and the identifier and
posture gates that guard planning.
"""

from test_helpers import (
    ADMIN_HEADERS,
    NON_EXISTENT_UUID,
    assert_common_fields,
    assert_female_ledger,
    assert_integer_equals,
    assert_is_none,
    assert_number_equals,
    assert_water_right_ledger,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors as err
from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures as fx

UNKNOWN_LOT_ID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_SPAWN_EVENT_ID = "11111111-1111-4111-8111-111111111111"


def test_spawn_event_projection_ignores_client_supplied_computed_fields(api):
    """
    The projection fields are computed from the group's fecundity and the
    station's stored density; values supplied in the body change nothing.

    PRD 3.3: "The eggs the take can expect to yield, `planned_eggs`, is the
    `females_spawned` count multiplied by the group's
    `expected_fecundity_per_female`."

    Design: Corner/entities/spawn_event_projection_fields_are_computed_and_client_values_input_ignored
    """
    ctx = fx.spawning_group(api, {"annual_water_right_af": 120.0})

    body = f.spawn_event_payload(
        ctx["brood_stock"]["id"],
        planned_take_date=f.instant(2026, 8, 10),
        females_spawned=20,
        target_release_count=15000,
    )
    body["planned_eggs"] = 999999
    body["water_reserved_af"] = 0.0
    body["cumulative_survival"] = 1.0

    spawn_event = validate_success(api.create_spawn_event(body, ctx["manager"]), 201)

    assert_integer_equals(spawn_event["planned_eggs"], 60000, "planned_eggs")
    assert_number_equals(
        spawn_event["cumulative_survival"], 0.6840, 4, "cumulative_survival"
    )
    assert_integer_equals(
        spawn_event["required_eggs_for_target"], 21930, "required_eggs_for_target"
    )
    assert_integer_equals(
        spawn_event["projected_release_count"], 41040, "projected_release_count"
    )
    assert_number_equals(spawn_event["water_reserved_af"], 3.0, 4, "water_reserved_af")
    assert_is_none(spawn_event["eggs_taken"], "eggs_taken")
    assert_is_none(spawn_event["taken_at"], "taken_at")
    assert spawn_event["status"] == k.SPAWN_PLANNED

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_number_equals(station["water_reserved_af"], 3.0, 4, "water_reserved_af")
    assert_number_equals(station["water_available_af"], 117.0, 4, "water_available_af")

    brood_stock = fx.read_brood_stock(api, ctx["hatchery"], ctx["brood_stock"]["id"])
    assert_integer_equals(brood_stock["females_reserved"], 20, "females_reserved")
    assert_integer_equals(brood_stock["females_available"], 380, "females_available")


def test_rearing_lot_system_fields_are_assigned_by_the_record_take(api):
    """
    A rearing lot has no create endpoint: the recorded take back-fills every
    identity field from the spawn chain and freezes the initial biomass.

    PRD 3.3: "The recorded take is also the only way a rearing lot comes into
    existence; there is no operation that creates one directly."

    Design: Corner/entities/rearing_lot_system_fields_are_assigned_by_the_record_take
    """
    ctx = fx.spawning_group(api)
    spawn_event = fx.create_spawn_event(api, ctx["hatchery"], ctx["brood_stock"])
    fx.set_clock(api, f.instant(2026, 8, 10))

    taken = validate_success(
        api.record_take(
            spawn_event["id"],
            f.record_take_payload(eggs_taken=20000, taken_at=f.instant(2026, 8, 10)),
            ctx["manager"],
        ),
        200,
    )
    assert taken["status"] == k.SPAWN_TAKEN
    assert_integer_equals(taken["eggs_taken"], 20000, "eggs_taken")

    lots, meta = validate_paginated(
        api.list_rearing_lots(ctx["manager"], {"spawn_event_id": spawn_event["id"]})
    )
    assert meta["total_count"] == 1, meta
    lot = lots[0]

    assert lot["hatchery_id"] == ctx["hatchery"]["id"]
    assert lot["spawn_event_id"] == spawn_event["id"]
    assert lot["species"] == k.SPECIES_RAINBOW_TROUT
    assert_integer_equals(lot["initial_count"], 20000, "initial_count")
    assert_integer_equals(lot["count_on_hand"], 20000, "count_on_hand")
    assert_integer_equals(lot["reserved_count"], 0, "reserved_count")
    assert_number_equals(lot["avg_weight_g"], 0.1, 4, "avg_weight_g")
    assert_number_equals(lot["initial_biomass_lbs"], 4.41, 2, "initial_biomass_lbs")
    assert_number_equals(lot["biomass_lbs"], 4.41, 2, "biomass_lbs")
    assert lot["rearing_stage"] == k.STAGE_EGG
    assert lot["health_status"] == k.HEALTH_UNSCREENED
    assert_common_fields(lot, expected_version=1)

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_number_equals(station["water_reserved_af"], 0.0, 4, "water_reserved_af")
    assert_number_equals(station["water_used_af"], 1.0, 4, "water_used_af")
    assert_number_equals(station["water_available_af"], 119.0, 4, "water_available_af")
    assert_number_equals(
        station["biomass_on_hand_lbs"], 4.41, 2, "biomass_on_hand_lbs"
    )
    assert_number_equals(station["density_index"], 0.0022, 4, "density_index")

    brood_stock = fx.read_brood_stock(api, ctx["hatchery"], ctx["brood_stock"]["id"])
    assert_integer_equals(brood_stock["females_reserved"], 0, "females_reserved")
    assert_integer_equals(brood_stock["females_spent"], 20, "females_spent")
    assert_integer_equals(
        brood_stock["cumulative_eggs_taken"], 20000, "cumulative_eggs_taken"
    )
    assert brood_stock["status"] == k.BROOD_SPAWNING


def test_spawn_event_with_an_unknown_brood_stock_reports_the_broods_own_404(api):
    """
    A body foreign key that resolves to no row fails with the referenced
    collection's own 404, ahead of the parent-state gate the same body would also
    fail.

    PRD 2.11: "Identifiers carried in a request body are resolved the same way,
    against the collection each one names, and they too report the referenced
    collection's own 404."

    Design: Corner/entities/spawn_event_with_unknown_brood_stock_returns_not_found
    """
    ctx = fx.station_at_rest(api)

    response = api.create_spawn_event(
        f.spawn_event_payload(
            NON_EXISTENT_UUID,
            planned_take_date=f.instant(2026, 8, 10),
            females_spawned=20,
            target_release_count=15000,
        ),
        ctx["manager"],
    )

    validate_error(response, err.ERR_BROOD_STOCK_NOT_FOUND, 404)

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_number_equals(station["water_reserved_af"], 0.0, 4, "water_reserved_af")


def test_unknown_spawn_event_id_returns_the_spawn_events_own_404(api):
    """
    A well-formed UUID addressing no spawn event produces
    ERR_SPAWN_EVENT_NOT_FOUND, never a generic shape complaint.

    PRD 2.11: "An identifier in the URL path is resolved against the collection
    the path addresses, and a value that resolves to nothing produces that
    collection's own 404: `ERR_HATCHERY_NOT_FOUND`, `ERR_WATER_NOT_FOUND`,
    `ERR_BROOD_STOCK_NOT_FOUND`, `ERR_SPAWN_EVENT_NOT_FOUND`,
    `ERR_LOT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`,
    `ERR_PLAN_NOT_FOUND`, `ERR_TRANSPORT_UNIT_NOT_FOUND` or
    `ERR_EVENT_NOT_FOUND`."

    Design: Corner/errors/unknown_spawn_event_id_returns_spawn_event_not_found
    """
    response = api.get_spawn_event(UNKNOWN_SPAWN_EVENT_ID, ADMIN_HEADERS)

    validate_error(response, err.ERR_SPAWN_EVENT_NOT_FOUND, 404)


def test_path_row_existence_is_checked_before_body_shape(api):
    """
    A feeding posted to a lot id that does not exist, with a malformed body, is a
    404 on the lot rather than a 400 on the shape.

    PRD 2.10: "4. **Path record existence** — the identifier in the URL resolves
    to a record of the addressed collection."

    Design: Corner/validations/path_row_existence_is_checked_before_body_shape_and_returns_not_found
    """
    ctx = fx.station_at_rest(api)

    response = api.record_feeding(
        UNKNOWN_LOT_ID,
        {"fed_at": f.instant(2026, 8, 1), "feed_lbs": "one hundred"},
        ctx["manager"],
    )

    validate_error(response, err.ERR_LOT_NOT_FOUND, 404)


def test_a_three_million_egg_take_reports_water_right_exceeded(api):
    """
    Acre-feet are charged at 0.05 per thousand eggs, so a 3,000,000-egg take asks
    for 150.0000 af against a 120.0 af decree even counting its own reservation,
    and the refusal leaves the reservation intact.

    PRD 3.3: "The fiscal gate is evaluated against the actual count rather than
    the planned one: the acre-feet the actual `eggs_taken` will consume — that
    count divided by one thousand, multiplied by 0.05, rounded to four decimal
    places — must not exceed the station's `water_available_af` plus the
    reservation this very take already holds, and otherwise the answer is
    `ERR_WATER_RIGHT_EXCEEDED`."

    Design: Corner/errors/a_three_million_egg_take_reports_water_right_exceeded
    """
    ctx = fx.spawning_group(api, {"annual_water_right_af": 120.0})
    spawn_event = fx.create_spawn_event(api, ctx["hatchery"], ctx["brood_stock"])
    fx.set_clock(api, f.instant(2026, 8, 10))

    response = api.record_take(
        spawn_event["id"],
        f.record_take_payload(eggs_taken=3000000, taken_at=f.instant(2026, 8, 10)),
        ctx["manager"],
    )

    validate_error(response, err.ERR_WATER_RIGHT_EXCEEDED, 422)

    unchanged = validate_success(
        api.get_spawn_event(spawn_event["id"], ctx["manager"]), 200
    )
    assert unchanged["status"] == k.SPAWN_PLANNED
    assert_is_none(unchanged["eggs_taken"], "eggs_taken")

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_number_equals(station["water_reserved_af"], 3.0, 4, "water_reserved_af")
    assert_number_equals(station["water_used_af"], 0.0, 4, "water_used_af")
    assert_number_equals(station["water_available_af"], 117.0, 4, "water_available_af")

    brood_stock = fx.read_brood_stock(api, ctx["hatchery"], ctx["brood_stock"]["id"])
    assert_integer_equals(
        brood_stock["cumulative_eggs_taken"], 0, "cumulative_eggs_taken"
    )
    assert_integer_equals(brood_stock["females_spent"], 0, "females_spent")

    _, meta = validate_paginated(
        api.list_rearing_lots(ctx["manager"], {"spawn_event_id": spawn_event["id"]})
    )
    assert meta["total_count"] == 0, meta


def test_cancel_on_a_taken_spawn_event_is_refused_from_a_terminal_state(api):
    """
    TAKEN is terminal, so a cancel after the take is refused and the converted
    acre-feet are not refunded a second time.

    PRD 3.3: "Both `TAKEN` and `CANCELLED` are terminal: recording a take against
    a cancelled event, cancelling one that has already been taken, or cancelling
    one twice all answer `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_on_a_taken_spawn_event_is_refused_from_a_terminal_state
    """
    ctx = fx.lot_at_egg(api)
    spawn_event = ctx["spawn_event"]
    assert spawn_event["status"] == k.SPAWN_TAKEN

    response = api.cancel_spawn_event(spawn_event["id"], ctx["manager"])

    validate_error(response, err.ERR_INVALID_STATE, 409)

    still_taken = validate_success(
        api.get_spawn_event(spawn_event["id"], ctx["manager"]), 200
    )
    assert still_taken["status"] == k.SPAWN_TAKEN

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_number_equals(station["water_used_af"], 1.0, 4, "water_used_af")
    assert_number_equals(station["water_reserved_af"], 0.0, 4, "water_reserved_af")
    assert_number_equals(station["water_available_af"], 119.0, 4, "water_available_af")
    assert_water_right_ledger(station)

    brood_stock = fx.read_brood_stock(api, ctx["hatchery"], ctx["brood_stock"]["id"])
    assert_integer_equals(brood_stock["females_spent"], 20, "females_spent")
    assert_integer_equals(brood_stock["females_available"], 380, "females_available")


def test_planning_a_take_on_a_restricted_station_is_refused(api):
    """
    RESTRICTED gates only new production: planning a take is refused while the
    feedings that produced the density are still legal.

    PRD 3.3: "Planning is also the operation most tightly gated on compliance:
    the parent group must be in `SPAWNING` status or the answer is
    `ERR_BROOD_STOCK_NOT_SPAWNING`, the station must not be `FROZEN` or the answer
    is `ERR_HATCHERY_FROZEN`, and — uniquely among all operations — the station
    must not be `RESTRICTED` either, or the answer is `ERR_HATCHERY_RESTRICTED`."

    Design: Corner/validations/spawn_event_on_a_restricted_station_is_refused
    """
    ctx = fx.yearling_lot(api)

    filled = validate_success(
        api.record_feeding(
            ctx["lot"]["id"],
            f.feeding_payload(
                fed_at=f.instant(2026, 8, 20, 12),
                feed_lbs=200.0,
                avg_weight_g_after=56.699,
                mortality_count=0,
            ),
            ctx["manager"],
        ),
        200,
    )
    assert_number_equals(filled["biomass_lbs"], 2000.0, 2, "biomass_lbs")

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_number_equals(
        station["biomass_on_hand_lbs"], 2000.0, 2, "biomass_on_hand_lbs"
    )
    assert_number_equals(station["density_index"], 1.0, 4, "density_index")
    assert station["operating_posture"] == k.POSTURE_RESTRICTED
    assert_integer_equals(
        station["exceedance_count_rolling"], 0, "exceedance_count_rolling"
    )
    assert_number_equals(station["water_available_af"], 119.0, 4, "water_available_af")

    response = api.create_spawn_event(
        f.spawn_event_payload(
            ctx["brood_stock"]["id"],
            planned_take_date=f.instant(2026, 8, 20),
            females_spawned=20,
            target_release_count=15000,
        ),
        ctx["manager"],
    )

    validate_error(response, err.ERR_HATCHERY_RESTRICTED, 409)

    brood_stock = fx.read_brood_stock(api, ctx["hatchery"], ctx["brood_stock"]["id"])
    assert_integer_equals(brood_stock["females_reserved"], 0, "females_reserved")
    assert_integer_equals(brood_stock["females_available"], 380, "females_available")


def test_egg_projection_uses_the_top_derate_tier_on_an_empty_station(api):
    """
    On a station whose density is still zero the derate factor is 1.00, so the
    survival chain stands at 0.6840 and drives both planning numbers.

    PRD 3.3: "That chained product is then derated by how crowded the station
    already is, using a density tier read from the station's `density_index` **as
    it stands at the moment the take is planned** — a factor of 1.00 when
    `density_index` is below 0.50, 0.95 when it is at or above 0.50 but below
    0.90, and 0.85 when it is at or above 0.90."

    Design: Difficulty/combinatorial_formula/egg_projection_derate_tier_read_from_stored_density
    """
    ctx = fx.spawning_group(api, {"annual_water_right_af": 120.0})
    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_number_equals(station["density_index"], 0.0, 4, "density_index")

    spawn_event = validate_success(
        api.create_spawn_event(
            f.spawn_event_payload(
                ctx["brood_stock"]["id"],
                planned_take_date=f.instant(2026, 9, 15),
                females_spawned=20,
                target_release_count=15000,
            ),
            ctx["manager"],
        ),
        201,
    )

    assert_integer_equals(spawn_event["planned_eggs"], 60000, "planned_eggs")
    assert_number_equals(
        spawn_event["cumulative_survival"], 0.6840, 4, "cumulative_survival"
    )
    assert_integer_equals(
        spawn_event["required_eggs_for_target"], 21930, "required_eggs_for_target"
    )
    assert_integer_equals(
        spawn_event["projected_release_count"], 41040, "projected_release_count"
    )
    assert_number_equals(spawn_event["water_reserved_af"], 3.0, 4, "water_reserved_af")


def test_egg_projection_derate_tier_is_read_from_the_stored_density(api):
    """
    The same call on a station standing at a density of 0.8000 picks the middle
    derate tier, so the survival chain becomes 0.6498 rather than 0.6840 — the
    tier is read from stored state and never recomputed from the incoming eggs.

    PRD 3.3: "The derate tier is resolved once and never revisited: a station
    sitting at a `density_index` of 0.4999 projects on the 1.00 tier even though
    the incoming eggs will push it past 0.50, and a later feeding that changes the
    station's density does not re-project an existing take."

    Design: Difficulty/combinatorial_formula/egg_projection_derate_tier_read_from_stored_density
    """
    ctx = fx.yearling_lot(api)
    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_number_equals(station["density_index"], 0.8, 4, "density_index")
    assert station["operating_posture"] == k.POSTURE_OPEN
    assert_number_equals(station["water_available_af"], 119.0, 4, "water_available_af")

    spawn_event = validate_success(
        api.create_spawn_event(
            f.spawn_event_payload(
                ctx["brood_stock"]["id"],
                planned_take_date=f.instant(2026, 9, 15),
                females_spawned=20,
                target_release_count=15000,
            ),
            ctx["manager"],
        ),
        201,
    )

    assert_integer_equals(spawn_event["planned_eggs"], 60000, "planned_eggs")
    assert_number_equals(
        spawn_event["cumulative_survival"], 0.6498, 4, "cumulative_survival"
    )
    assert_integer_equals(
        spawn_event["required_eggs_for_target"], 23085, "required_eggs_for_target"
    )
    assert_integer_equals(
        spawn_event["projected_release_count"], 38988, "projected_release_count"
    )
    assert_number_equals(spawn_event["water_reserved_af"], 3.0, 4, "water_reserved_af")

    brood_stock = fx.read_brood_stock(api, ctx["hatchery"], ctx["brood_stock"]["id"])
    assert_integer_equals(brood_stock["females_reserved"], 20, "females_reserved")
    assert_integer_equals(brood_stock["females_available"], 360, "females_available")

    after = fx.read_hatchery(api, ctx["hatchery"])
    assert_number_equals(after["water_reserved_af"], 3.0, 4, "water_reserved_af")
    assert_number_equals(after["water_available_af"], 116.0, 4, "water_available_af")


def test_spawn_cancel_restores_the_water_right_and_the_female_ledger(api):
    """
    One cancellation unwinds reservations on two different parents at once: the
    acre-feet go back to the station and the females go back to the group.

    PRD 3.3: "Cancellation subtracts `females_spawned` from the group's
    `females_reserved`, returning those females to `females_available`, and
    subtracts the take's `water_reserved_af` from the station's
    `water_reserved_af`, returning those acre-feet to `water_available_af`; the
    station's `water_available_af` and `operating_posture` are then recomputed, so
    cancelling a take can thaw a station that a reservation had frozen."

    Design: Difficulty/compensating_invariant/spawn_cancel_restores_water_right_and_female_identities
    """
    ctx = fx.spawning_group(api, {"annual_water_right_af": 120.0})
    spawn_event = fx.create_spawn_event(api, ctx["hatchery"], ctx["brood_stock"])
    assert_number_equals(spawn_event["water_reserved_af"], 3.0, 4, "water_reserved_af")

    cancelled = validate_success(
        api.cancel_spawn_event(spawn_event["id"], ctx["manager"]), 200
    )

    assert cancelled["status"] == k.SPAWN_CANCELLED
    assert_number_equals(cancelled["water_reserved_af"], 3.0, 4, "water_reserved_af")
    assert_is_none(cancelled["eggs_taken"], "eggs_taken")

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_number_equals(station["water_reserved_af"], 0.0, 4, "water_reserved_af")
    assert_number_equals(station["water_used_af"], 0.0, 4, "water_used_af")
    assert_number_equals(station["water_available_af"], 120.0, 4, "water_available_af")
    assert_water_right_ledger(station)
    assert station["operating_posture"] == k.POSTURE_OPEN

    brood_stock = fx.read_brood_stock(api, ctx["hatchery"], ctx["brood_stock"]["id"])
    assert_integer_equals(brood_stock["females_reserved"], 0, "females_reserved")
    assert_integer_equals(brood_stock["females_available"], 400, "females_available")
    assert_integer_equals(brood_stock["females_spent"], 0, "females_spent")
    assert_integer_equals(
        brood_stock["cumulative_eggs_taken"], 0, "cumulative_eggs_taken"
    )
    assert brood_stock["status"] == k.BROOD_SPAWNING
    assert_female_ledger(brood_stock)

    _, meta = validate_paginated(
        api.list_rearing_lots(ctx["manager"], {"spawn_event_id": spawn_event["id"]})
    )
    assert meta["total_count"] == 0, meta


def test_replaying_the_spawn_cancel_does_not_refund_a_second_time(api):
    """
    The compensation is not idempotent in its arithmetic: a second cancel is
    refused outright, so the acre-feet cannot be refunded twice.

    PRD 3.3: "Both `TAKEN` and `CANCELLED` are terminal: recording a take against
    a cancelled event, cancelling one that has already been taken, or cancelling
    one twice all answer `ERR_INVALID_STATE`."

    Design: Difficulty/compensating_invariant/spawn_cancel_restores_water_right_and_female_identities
    """
    ctx = fx.spawning_group(api, {"annual_water_right_af": 120.0})
    spawn_event = fx.create_spawn_event(api, ctx["hatchery"], ctx["brood_stock"])

    first = validate_success(
        api.cancel_spawn_event(spawn_event["id"], ctx["manager"]), 200
    )
    assert first["status"] == k.SPAWN_CANCELLED
    refunded = fx.read_hatchery(api, ctx["hatchery"])
    assert_number_equals(refunded["water_available_af"], 120.0, 4, "water_available_af")

    replay = api.cancel_spawn_event(spawn_event["id"], ctx["manager"])

    validate_error(replay, err.ERR_INVALID_STATE, 409)

    still = fx.read_hatchery(api, ctx["hatchery"])
    assert_number_equals(still["water_reserved_af"], 0.0, 4, "water_reserved_af")
    assert_number_equals(still["water_available_af"], 120.0, 4, "water_available_af")
    assert_water_right_ledger(still)

    brood_stock = fx.read_brood_stock(api, ctx["hatchery"], ctx["brood_stock"]["id"])
    assert_integer_equals(brood_stock["females_available"], 400, "females_available")
    assert_female_ledger(brood_stock)
