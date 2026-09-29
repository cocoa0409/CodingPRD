"""
Brood groups, the spawning window, and the parent-state gate on an egg take.

Covers the female ledger a group opens with, the READY to SPAWNING edge and the
two conditions that guard it, the inverted-window shape gate, the female ceiling
on a planned take, the SPAWNING to CLOSED edge at the end of a recorded take, and
the cross-entity dependency that makes a spawn event unreachable while its parent
group is still READY.
"""

from test_helpers import (
    assert_common_fields,
    assert_female_ledger,
    assert_integer_equals,
    assert_number_equals,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors as err
from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures as fx


def test_brood_group_opens_ready_with_its_female_ledger_at_rest(api):
    """
    A new group is READY, not SPAWNING, even though the clock already sits inside
    the window it declares.

    PRD 3.2: "A newly registered group opens in `READY` status with its female
    ledger at rest: `females_reserved` and `females_spent` both zero, so
    `females_available` — the `female_count` less the reserved and the spent —
    equals the whole `female_count`, and `cumulative_eggs_taken` is zero."

    Design: Corner/state_machines/brood_stock_starts_in_ready_with_no_females_reserved
    """
    ctx = fx.station_at_rest(api)

    brood_stock = validate_success(
        api.create_brood_stock(
            f.brood_stock_payload(
                ctx["hatchery"]["id"],
                female_count=400,
                male_count=200,
                expected_fecundity_per_female=3000,
                spawning_window_start=f.instant(2026, 8, 1),
                spawning_window_end=f.instant(2026, 10, 31),
            ),
            ctx["manager"],
        ),
        201,
    )

    assert brood_stock["status"] == k.BROOD_READY
    assert_integer_equals(brood_stock["females_reserved"], 0, "females_reserved")
    assert_integer_equals(brood_stock["females_spent"], 0, "females_spent")
    assert_integer_equals(brood_stock["females_available"], 400, "females_available")
    assert_female_ledger(brood_stock)
    assert_integer_equals(
        brood_stock["cumulative_eggs_taken"], 0, "cumulative_eggs_taken"
    )
    assert_common_fields(brood_stock, expected_version=1)


def test_open_spawning_window_moves_ready_to_spawning(api):
    """
    The owning manager, inside the window and on an unfrozen station, moves the
    group from READY to SPAWNING and reserves nothing by doing so.

    PRD 3.2: "Only the station's own manager may declare the group ripe, moving
    it from `READY` to `SPAWNING`; a manager whose `X-User-ID` is not the group's
    `hatchery_id` is refused with `ERR_HATCHERY_SCOPE_VIOLATION`."

    Design: Corner/state_machines/open_spawning_window_moves_ready_to_spawning
    """
    ctx = fx.station_at_rest(api)
    brood_stock = fx.create_brood_stock(api, ctx["hatchery"])

    opened = validate_success(
        api.open_spawning_window(brood_stock["id"], ctx["manager"]), 200
    )

    assert opened["status"] == k.BROOD_SPAWNING
    assert_integer_equals(opened["version"], 2, "version")
    assert_integer_equals(opened["females_available"], 400, "females_available")
    assert_integer_equals(opened["females_reserved"], 0, "females_reserved")

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert station["operating_posture"] == k.POSTURE_OPEN


def test_opening_the_window_before_it_starts_is_refused_then_legal_on_the_bound(api):
    """
    The window precondition is inclusive at the lower bound: sixteen days early
    the transition is refused, and at exactly the start instant it succeeds.

    PRD 3.2: "The logical clock must lie inside the group's spawning window — at
    or after `spawning_window_start` and strictly before `spawning_window_end` —
    and a clock outside that range is refused with `ERR_SPAWN_WINDOW_CLOSED`
    (HTTP 409)."

    Design: Corner/state_machines/open_spawning_window_before_the_window_starts_is_refused
    """
    fx.set_clock(api, f.instant(2026, 7, 15))
    ctx = fx.station_at_rest(api)
    brood_stock = fx.create_brood_stock(
        api,
        ctx["hatchery"],
        spawning_window_start=f.instant(2026, 8, 1),
        spawning_window_end=f.instant(2026, 10, 31),
    )

    early = api.open_spawning_window(brood_stock["id"], ctx["manager"])
    validate_error(early, err.ERR_SPAWN_WINDOW_CLOSED, 409)

    unchanged = fx.read_brood_stock(api, ctx["hatchery"], brood_stock["id"])
    assert unchanged["status"] == k.BROOD_READY
    assert_integer_equals(unchanged["version"], 1, "version")

    fx.set_clock(api, f.instant(2026, 8, 1))
    on_the_bound = validate_success(
        api.open_spawning_window(brood_stock["id"], ctx["manager"]), 200
    )
    assert on_the_bound["status"] == k.BROOD_SPAWNING


def test_inverted_spawning_window_is_refused_by_the_shape_gate(api):
    """
    A window whose end equals its start is a request-shape failure, not a window
    rule, so the answer is ERR_INVALID_REQUEST and no group is written.

    PRD 3.2: "Each of `female_count`, `male_count` and
    `expected_fecundity_per_female` must be at least 1, and
    `spawning_window_end` must fall strictly after `spawning_window_start`; an
    inverted window is a request-shape failure."

    Design: Corner/validations/inverted_spawning_window_is_refused_by_the_shape_gate
    """
    ctx = fx.station_at_rest(api)

    response = api.create_brood_stock(
        f.brood_stock_payload(
            ctx["hatchery"]["id"],
            spawning_window_start=f.instant(2026, 8, 1),
            spawning_window_end=f.instant(2026, 8, 1),
        ),
        ctx["manager"],
    )

    validate_error(response, err.ERR_INVALID_REQUEST, 400)

    _, meta = validate_paginated(
        api.list_brood_stocks(ctx["manager"], {"hatchery_id": ctx["hatchery"]["id"]})
    )
    assert meta["total_count"] == 0, meta


def test_spawning_more_females_than_the_group_holds_is_refused(api):
    """
    The female ceiling is checked ahead of the water-right ceiling: 500 of 400
    females is refused on the females even though the acre-feet those females
    imply are affordable.

    PRD 3.3: "If the take asks for more females than the group has available, it
    is refused with `ERR_BROOD_FEMALES_INSUFFICIENT` (HTTP 422); if the acre-feet
    it would reserve exceed the station's `water_available_af`, it is refused
    with `ERR_WATER_RIGHT_EXCEEDED` (HTTP 422)."

    Design: Corner/errors/spawning_more_females_than_the_group_holds_reports_brood_females_insufficient
    """
    ctx = fx.spawning_group(api, {"annual_water_right_af": 120.0})

    response = api.create_spawn_event(
        f.spawn_event_payload(
            ctx["brood_stock"]["id"], females_spawned=500, target_release_count=15000
        ),
        ctx["manager"],
    )

    validate_error(response, err.ERR_BROOD_FEMALES_INSUFFICIENT, 422)

    brood_stock = fx.read_brood_stock(api, ctx["hatchery"], ctx["brood_stock"]["id"])
    assert_integer_equals(brood_stock["females_available"], 400, "females_available")
    assert_integer_equals(brood_stock["version"], 2, "version")

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_number_equals(station["water_reserved_af"], 0.0, 4, "water_reserved_af")


def test_record_take_closes_the_group_when_the_egg_target_is_met(api):
    """
    The SPAWNING to CLOSED edge is evaluated at the end of a recorded take from
    a `>=` comparison, so a 20000-egg take against a 20000-egg target closes the
    group while the take itself still succeeds and still produces its lot.

    PRD 3.2: "The end of a recorded egg take evaluates whether
    `cumulative_eggs_taken` has reached or passed `egg_take_target`, and a
    `SPAWNING` group that has met its target transitions to `CLOSED`."

    Design: Corner/state_machines/record_take_closes_the_brood_group_when_the_egg_target_is_met
    """
    ctx = fx.spawning_group(api, brood_overrides={"egg_take_target": 20000})
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

    brood_stock = fx.read_brood_stock(api, ctx["hatchery"], ctx["brood_stock"]["id"])
    assert_integer_equals(
        brood_stock["cumulative_eggs_taken"], 20000, "cumulative_eggs_taken"
    )
    assert brood_stock["status"] == k.BROOD_CLOSED
    assert_integer_equals(brood_stock["females_spent"], 20, "females_spent")
    assert_integer_equals(brood_stock["females_reserved"], 0, "females_reserved")

    _, meta = validate_paginated(
        api.list_rearing_lots(ctx["manager"], {"spawn_event_id": spawn_event["id"]})
    )
    assert meta["total_count"] == 1, meta


def test_spawn_event_is_refused_while_the_parent_group_is_still_ready(api):
    """
    A spawn event cannot be created at all while its parent group sits in READY,
    even though every field of the request is valid and the station is OPEN with
    water to spare.

    PRD 3.2: "A group in `READY`, `SUSPENDED` or `CLOSED` status is not a legal
    parent for a new egg take or for a recorded take, and both operations refuse
    it with `ERR_BROOD_STOCK_NOT_SPAWNING` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/spawn_event_creation_requires_brood_stock_in_spawning
    """
    ctx = fx.station_at_rest(api, annual_water_right_af=120.0)
    brood_stock = fx.create_brood_stock(api, ctx["hatchery"])
    assert brood_stock["status"] == k.BROOD_READY

    response = api.create_spawn_event(
        f.spawn_event_payload(
            brood_stock["id"],
            planned_take_date=f.instant(2026, 8, 10),
            females_spawned=20,
            target_release_count=15000,
        ),
        ctx["manager"],
    )

    validate_error(response, err.ERR_BROOD_STOCK_NOT_SPAWNING, 409)

    still_ready = fx.read_brood_stock(api, ctx["hatchery"], brood_stock["id"])
    assert still_ready["status"] == k.BROOD_READY
    assert_integer_equals(still_ready["females_reserved"], 0, "females_reserved")
    assert_integer_equals(still_ready["females_available"], 400, "females_available")

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_number_equals(station["water_reserved_af"], 0.0, 4, "water_reserved_af")
    assert_number_equals(station["water_available_af"], 120.0, 4, "water_available_af")


def test_opening_the_window_makes_the_identical_spawn_event_call_succeed(api):
    """
    Opening the spawning window is the only thing that changes between the
    refusal and the success, which isolates the parent-state gate from the shape,
    scope and fiscal checks.

    PRD 3.2: "A group that reaches `SPAWNING` is the only kind of group against
    which egg takes may be planned."

    Design: Difficulty/cross_entity_state_dependency/spawn_event_creation_requires_brood_stock_in_spawning
    """
    ctx = fx.station_at_rest(api, annual_water_right_af=120.0)
    brood_stock = fx.create_brood_stock(api, ctx["hatchery"])
    body = f.spawn_event_payload(
        brood_stock["id"],
        planned_take_date=f.instant(2026, 8, 10),
        females_spawned=20,
        target_release_count=15000,
    )

    validate_error(
        api.create_spawn_event(body, ctx["manager"]),
        err.ERR_BROOD_STOCK_NOT_SPAWNING,
        409,
    )

    fx.open_spawning_window(api, ctx["hatchery"], brood_stock)

    created = validate_success(api.create_spawn_event(body, ctx["manager"]), 201)
    assert created["status"] == k.SPAWN_PLANNED
    assert_integer_equals(created["females_spawned"], 20, "females_spawned")

    after = fx.read_brood_stock(api, ctx["hatchery"], brood_stock["id"])
    assert_integer_equals(after["females_reserved"], 20, "females_reserved")
    assert_integer_equals(after["females_available"], 380, "females_available")

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_number_equals(station["water_reserved_af"], 3.0, 4, "water_reserved_af")
