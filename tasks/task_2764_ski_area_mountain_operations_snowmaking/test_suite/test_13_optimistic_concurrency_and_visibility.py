"""Version guards on the two gated creates, and the immediate visibility of a cascade.

Two creates in this service make the caller declare the row it read before it
committed: a snowmaking session declares the terrain area version it planned
against, and a guest admission declares the day plan version it allocated
capacity against. Both guards are exercised here from the writer that moves the
row underneath them — a snow stake reading in one case, a terrain opening
decision in the other — together with the proof that a success consumes the
token just as surely as a rejection preserves it.

The rest of the module follows the mountain's deepest chain of consequences: a
single weather observation puts a lift on a wind hold, pushes the terrain it
serves onto a patrol hold, aborts the snow it was making and hands the reserved
water back to the season, then lets the operator release the hold and watches
each area re-gated on its own grooming currency. Every figure asserted is read
back from the row itself, and the settled numbers are demanded of the very
response body that caused them.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_MITIGATION_NOT_CURRENT,
    ERR_STALE_DAY_PLAN_VERSION,
    ERR_STALE_TERRAIN_AREA_VERSION,
    ERR_WIND_ABOVE_RELEASE_THRESHOLD,
)
from test_helpers.assertions import (
    assert_instant_equals,
    assert_integer,
    assert_one_decimal,
    assert_usd,
    assert_water_af,
    assert_water_ledger_identity,
)
from test_helpers.test_users import (
    DIRECTOR_HEADERS,
    GROOMING_HEADERS,
    GUEST_SERVICES_HEADERS,
    LIFT_OPS_HEADERS,
    SNOWMAKING_HEADERS,
)


def _two_areas_open_on_one_lift(mountain) -> Dict[str, Any]:
    """Two areas served by one lift and groomed six hours apart, both standing
    open on a published day, with one scheduled session on the smaller area.

    Sunbowl is groomed at midnight and Meadows at six, so a release later in the
    day finds exactly one of them still groom-current.
    """
    mountain.set_clock("2026-08-01T00:00:00Z")
    season = mountain.create_season()
    lift = mountain.create_lift(
        season["id"], wind_hold_threshold_mph=40.0, hourly_capacity_pph=1800
    )
    mountain.inspect_lift(lift["id"], "PASS")
    mountain.staff_lift(lift["id"], shift_end="2026-08-01T23:00:00Z")
    mountain.set_lift_status(lift["id"], "STANDBY")

    sunbowl = mountain.create_terrain_area(
        season["id"], lift["id"], trail_code="T1", name="Sunbowl", acres=18.0
    )
    mountain.record_reading(sunbowl["id"], stake_code="S1", depth_in=40.0)
    mountain.groom_area(
        sunbowl["id"],
        20,
        cat_route_code="R1",
        snowcat_unit_code="CAT-1",
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-01T04:00:00Z",
    )

    meadows = mountain.create_terrain_area(
        season["id"], lift["id"], trail_code="T2", name="Meadows", acres=8.0
    )
    mountain.record_reading(meadows["id"], stake_code="S1", depth_in=40.0)

    mountain.set_clock("2026-08-01T06:00:00Z")
    mountain.groom_area(
        meadows["id"],
        20,
        cat_route_code="R2",
        snowcat_unit_code="CAT-2",
        window_start="2026-08-01T06:00:00Z",
        window_end="2026-08-01T10:00:00Z",
    )

    for code, cert, area_id in (
        ("P1", "EMT", sunbowl["id"]),
        ("P2", "PARAMEDIC", sunbowl["id"]),
        ("P3", "EMT", meadows["id"]),
        ("P4", "PARAMEDIC", meadows["id"]),
    ):
        mountain.create_patroller(
            season["id"],
            patroller_code=code,
            cert_level=cert,
            on_duty=True,
            assigned_terrain_area_id=area_id,
        )

    pump_house = mountain.create_pump_house(season["id"], status="ONLINE")
    session = mountain.schedule_session(
        meadows["id"],
        pump_house["id"],
        window_start="2026-08-01T07:00:00Z",
        window_end="2026-08-01T14:00:00Z",
        gun_count=30,
        gpm=1200,
    )

    day_plan = mountain.create_day_plan(season["id"])
    mountain.publish_day_plan(day_plan["id"])
    mountain.post_weather(day_plan["id"], 10.0, 22.0, new_snow_in=0.0)
    mountain.set_lift_status(lift["id"], "OPEN")
    mountain.decide_opening(sunbowl["id"], "OPEN")
    mountain.decide_opening(meadows["id"], "OPEN")

    return {
        "season_id": season["id"],
        "lift_id": lift["id"],
        "sunbowl_id": sunbowl["id"],
        "meadows_id": meadows["id"],
        "pump_house_id": pump_house["id"],
        "session_id": session["id"],
        "day_plan_id": day_plan["id"],
    }


def test_a_stale_terrain_area_version_is_rejected_and_the_refreshed_retry_succeeds(
    api, mountain
):
    """A session create carrying a superseded terrain area version is refused and reserves nothing, while the identical request on the re-read version is accepted.

    If `expected_terrain_area_version` does not equal the terrain area's current `version`, the create is rejected with `ERR_STALE_TERRAIN_AREA_VERSION` (HTTP 412), and the caller must re-read the area and re-derive the plan from fresh gate inputs.

    Design: Corner/complexity_layers/a_stale_terrain_area_version_is_rejected_and_the_refreshed_retry_succeeds
    """
    mountain.set_clock("2026-08-01T00:00:00Z")
    season = mountain.create_season()
    lift = mountain.create_lift(season["id"], wind_hold_threshold_mph=40.0)
    mountain.inspect_lift(lift["id"], "PASS")
    area = mountain.create_terrain_area(
        season["id"], lift["id"], trail_code="T1", name="Sunbowl", acres=18.0
    )
    mountain.record_reading(area["id"], stake_code="S1", depth_in=40.0)
    pump_house = mountain.create_pump_house(season["id"], status="ONLINE")

    stale_version = mountain.area(area["id"])["version"]

    # An unrelated writer moves the area underneath the planner.
    reading = validate_success(
        api.record_snow_depth_reading(
            area["id"],
            f.snow_depth_reading_payload(stake_code="S2", depth_in=36.0),
            GROOMING_HEADERS,
        ),
        expected_status=201,
    )
    assert reading["stake_code"] == "S2"
    moved_area = mountain.area(area["id"])
    assert_one_decimal(moved_area["base_depth_in"], 38.0)
    assert moved_area["version"] == stale_version + 1

    rejected = validate_error(
        api.create_session(
            f.session_payload(area["id"], pump_house["id"], stale_version),
            SNOWMAKING_HEADERS,
        ),
        ERR_STALE_TERRAIN_AREA_VERSION,
        expected_status=412,
    )
    assert rejected["error_id"] == ERR_STALE_TERRAIN_AREA_VERSION
    assert mountain.area(area["id"])["opening_state"] == "CLOSED"

    untouched_season = mountain.season(season["id"])
    assert_water_af(untouched_season["water_reserved_af"], 0.000)
    assert_water_af(untouched_season["water_used_af"], 0.000)
    assert_water_ledger_identity(untouched_season, 250.000)

    untouched_plant = mountain.pump_house(pump_house["id"])
    assert_integer(untouched_plant["peak_committed_gpm"], 0)
    assert_integer(untouched_plant["active_session_count"], 0)

    # The rejection did not consume the token, so replaying it is refused again.
    validate_error(
        api.create_session(
            f.session_payload(area["id"], pump_house["id"], stale_version),
            SNOWMAKING_HEADERS,
        ),
        ERR_STALE_TERRAIN_AREA_VERSION,
        expected_status=412,
    )

    refreshed_version = mountain.area(area["id"])["version"]
    assert refreshed_version == stale_version + 1

    first_session = validate_success(
        api.create_session(
            f.session_payload(area["id"], pump_house["id"], refreshed_version),
            SNOWMAKING_HEADERS,
        ),
        expected_status=201,
    )
    assert_water_af(first_session["water_af_reserved"], 1.547)
    assert_integer(first_session["planned_minutes"], 420)

    reserved_season = mountain.season(season["id"])
    assert_water_af(reserved_season["water_reserved_af"], 1.547)
    assert_water_ledger_identity(reserved_season, 248.453)

    # The accepted create advanced the area, so the token it used is now stale.
    validate_error(
        api.create_session(
            f.session_payload(
                area["id"],
                pump_house["id"],
                refreshed_version,
                window_start="2026-08-01T14:00:00Z",
                window_end="2026-08-01T16:00:00Z",
            ),
            SNOWMAKING_HEADERS,
        ),
        ERR_STALE_TERRAIN_AREA_VERSION,
        expected_status=412,
    )

    advanced_version = mountain.area(area["id"])["version"]
    assert advanced_version == refreshed_version + 1

    second_session = validate_success(
        api.create_session(
            f.session_payload(
                area["id"],
                pump_house["id"],
                advanced_version,
                window_start="2026-08-01T14:00:00Z",
                window_end="2026-08-01T16:00:00Z",
            ),
            SNOWMAKING_HEADERS,
        ),
        expected_status=201,
    )
    assert_water_af(second_session["water_af_reserved"], 0.442)

    rollup = validate_success(
        api.get_season_snow_accounting(season["id"], SNOWMAKING_HEADERS)
    )
    assert_water_af(rollup["water_reserved_af"], 1.989)
    assert_water_af(rollup["water_used_af"], 0.000)
    assert_water_af(rollup["water_right_remaining_af"], 248.011)
    assert_integer(rollup["completed_session_count"], 0)


def test_a_stale_day_plan_version_is_rejected_and_admission_resumes_on_the_refreshed_version(
    api, mountain
):
    """An admission carrying a superseded day plan version is refused and admits nobody, and one observed version can seat only one party.

    If `expected_day_plan_version` does not equal the day plan's current `version`, the create is rejected with `ERR_STALE_DAY_PLAN_VERSION` (HTTP 412), so an admission decision can never be made against a capacity figure the server has already superseded.

    Design: Corner/complexity_layers/a_stale_day_plan_version_is_rejected_and_admission_resumes_on_the_refreshed_version
    """
    mountain.set_clock("2026-08-01T00:00:00Z")
    state = mountain.operating_season(lift_overrides={"wind_hold_threshold_mph": 40.0})
    day_plan_id = state["day_plan_id"]

    observed_version = mountain.day_plan(day_plan_id)["version"]

    opened = validate_success(
        api.decide_opening(
            state["area_id"], f.opening_decision_payload("OPEN"), DIRECTOR_HEADERS
        )
    )
    assert opened["opening_state"] == "OPEN"

    validate_error(
        api.create_reservation(
            f.reservation_payload(
                day_plan_id,
                observed_version,
                party_code="G1",
                pass_type="DAY_TICKET",
                party_size=10,
                vehicle_count=3,
            ),
            GUEST_SERVICES_HEADERS,
        ),
        ERR_STALE_DAY_PLAN_VERSION,
        expected_status=412,
    )

    after_rejection = mountain.day_plan(day_plan_id)
    assert_integer(after_rejection["admitted_guest_count"], 0)
    assert_integer(after_rejection["non_season_admitted_count"], 0)
    assert_integer(after_rejection["waitlisted_guest_count"], 0)
    assert_integer(after_rejection["parking_stalls_used"], 0)
    assert_integer(after_rejection["guest_capacity"], 918)
    assert_integer(after_rejection["non_season_pool"], 642)
    assert after_rejection["version"] != observed_version

    refreshed_version = after_rejection["version"]
    day_ticket_party = validate_success(
        api.create_reservation(
            f.reservation_payload(
                day_plan_id,
                refreshed_version,
                party_code="G1",
                pass_type="DAY_TICKET",
                party_size=10,
                vehicle_count=3,
            ),
            GUEST_SERVICES_HEADERS,
        ),
        expected_status=201,
    )
    assert day_ticket_party["state"] == "CONFIRMED"
    assert day_ticket_party["waitlist_reason"] == "NONE"
    assert_integer(day_ticket_party["allocated_stalls"], 3)

    # The successful admission consumed the very token it was made against.
    validate_error(
        api.create_reservation(
            f.reservation_payload(
                day_plan_id,
                refreshed_version,
                party_code="G2",
                pass_type="SEASON",
                party_size=10,
                vehicle_count=3,
            ),
            GUEST_SERVICES_HEADERS,
        ),
        ERR_STALE_DAY_PLAN_VERSION,
        expected_status=412,
    )

    after_second_rejection = mountain.day_plan(day_plan_id)
    assert_integer(after_second_rejection["admitted_guest_count"], 10)
    assert_integer(after_second_rejection["non_season_admitted_count"], 10)
    assert_integer(after_second_rejection["parking_stalls_used"], 3)
    assert after_second_rejection["version"] == refreshed_version + 1

    season_party = validate_success(
        api.create_reservation(
            f.reservation_payload(
                day_plan_id,
                after_second_rejection["version"],
                party_code="G2",
                pass_type="SEASON",
                party_size=10,
                vehicle_count=3,
            ),
            GUEST_SERVICES_HEADERS,
        ),
        expected_status=201,
    )
    assert season_party["state"] == "CONFIRMED"

    settled = mountain.day_plan(day_plan_id)
    assert_integer(settled["admitted_guest_count"], 20)
    assert_integer(settled["non_season_admitted_count"], 10)
    assert_integer(settled["parking_stalls_used"], 6)

    rows, meta = validate_paginated(
        api.list_day_plan_reservations(
            day_plan_id, GUEST_SERVICES_HEADERS, state="CONFIRMED"
        )
    )
    assert meta["total_count"] == 2
    assert sorted(row["party_code"] for row in rows) == ["G1", "G2"]


def test_new_snow_at_exactly_twelve_inches_invalidates_the_avalanche_clearance(
    api, mountain
):
    """A foot of new snow voids the avalanche clearance and drops the open avalanche area onto a patrol hold, while a tenth of an inch less changes nothing.

    Second, a `new_snow_in` of 12.0 inches or more — a foot of new snow — invalidates avalanche work outright: `mitigation_clearance_expires_at` is set to null on every `avalanche_terrain` area of the season, and any such area that was `OPEN` is dropped to `PATROL_HOLD`.

    Design: Corner/complexity_layers/new_snow_at_exactly_twelve_inches_invalidates_the_avalanche_clearance
    """
    mountain.set_clock("2026-08-01T00:00:00Z")
    state = mountain.ready_area(
        lift_overrides={"wind_hold_threshold_mph": 40.0},
        area_overrides={
            "trail_code": "T1",
            "name": "Sunbowl",
            "acres": 18.0,
            "avalanche_terrain": True,
        },
        blaster_certified=True,
    )
    area_id = state["area_id"]
    executing_patroller, clearing_patroller = state["patroller_ids"][:2]

    ski_cut = mountain.clear_avalanche_terrain(
        area_id,
        executing_patroller,
        clearing_patroller,
        method="SKI_CUT",
        charges_used=0,
        planned_charges=0,
        route_code="AV-1",
    )

    day_plan = mountain.create_day_plan(state["season_id"])
    mountain.publish_day_plan(day_plan["id"])
    mountain.post_weather(day_plan["id"], 10.0, 22.0, new_snow_in=0.0)
    mountain.set_lift_status(state["lift_id"], "OPEN")
    mountain.decide_opening(area_id, "OPEN")

    standing = mountain.area(area_id)
    assert standing["opening_state"] == "OPEN"
    assert_instant_equals(
        standing["mitigation_clearance_expires_at"], "2026-08-01T08:00:00Z"
    )

    just_short = validate_success(
        api.post_weather(
            day_plan["id"],
            f.weather_payload(10.0, 22.0, new_snow_in=11.9),
            DIRECTOR_HEADERS,
        )
    )
    assert_one_decimal(just_short["new_snow_in"], 11.9)

    unmoved = mountain.area(area_id)
    assert unmoved["opening_state"] == "OPEN"
    assert_instant_equals(
        unmoved["mitigation_clearance_expires_at"], "2026-08-01T08:00:00Z"
    )
    before_the_foot = mountain.day_plan(day_plan["id"])
    assert before_the_foot["posture"] == "PUBLISHED_FULL"
    assert_integer(before_the_foot["open_terrain_count"], 1)
    assert_one_decimal(before_the_foot["terrain_open_acres"], 18.0)

    a_foot_of_snow = validate_success(
        api.post_weather(
            day_plan["id"],
            f.weather_payload(10.0, 22.0, new_snow_in=12.0),
            DIRECTOR_HEADERS,
        )
    )
    assert_one_decimal(a_foot_of_snow["new_snow_in"], 12.0)
    assert a_foot_of_snow["posture"] == "PUBLISHED_PARTIAL"
    assert_integer(a_foot_of_snow["open_terrain_count"], 0)
    assert_one_decimal(a_foot_of_snow["terrain_open_acres"], 0.0)

    voided = mountain.area(area_id)
    assert voided["opening_state"] == "PATROL_HOLD"
    assert voided["mitigation_clearance_expires_at"] is None
    assert mountain.lift(state["lift_id"])["service_status"] == "OPEN"

    history = mountain.mission(ski_cut["id"])
    assert history["state"] == "CLEARED"
    assert history["hazard_rating_post"] == "LOW"

    validate_error(
        api.decide_opening(
            area_id, f.opening_decision_payload("OPEN"), DIRECTOR_HEADERS
        ),
        ERR_MITIGATION_NOT_CURRENT,
        expected_status=422,
    )

    fresh_ski_cut = mountain.clear_avalanche_terrain(
        area_id,
        executing_patroller,
        clearing_patroller,
        method="SKI_CUT",
        charges_used=0,
        planned_charges=0,
        route_code="AV-2",
    )
    assert fresh_ski_cut["state"] == "CLEARED"

    recleared = mountain.area(area_id)
    assert_instant_equals(
        recleared["mitigation_clearance_expires_at"], "2026-08-01T08:00:00Z"
    )
    assert recleared["opening_state"] == "PATROL_HOLD"

    reopened = validate_success(
        api.decide_opening(
            area_id, f.opening_decision_payload("OPEN"), DIRECTOR_HEADERS
        )
    )
    assert reopened["opening_state"] == "OPEN"

    recovered = mountain.day_plan(day_plan["id"])
    assert recovered["posture"] == "PUBLISHED_FULL"
    assert_integer(recovered["open_terrain_count"], 1)
    assert_one_decimal(recovered["terrain_open_acres"], 18.0)
    assert_one_decimal(recovered["new_snow_in"], 12.0)


def test_the_lift_wind_hold_fires_strictly_above_its_threshold_while_the_day_hold_fires_at_sixty(
    api, mountain
):
    """Wind exactly at a lift's hold threshold leaves it running, a tenth above shuts it, the release band is inclusive five below, and a sixty mile per hour reading holds the whole mountain without its retreat releasing any lift.

    First, every lift of the season whose `service_status` is `OPEN` and whose `wind_hold_threshold_mph` is **strictly below** the reported wind moves `OPEN → WIND_HOLD` with `wind_hold_since` stamped, processed in ascending `lift_code` order; a lift whose threshold exactly equals the reported wind stays open.

    Design: Corner/complexity_layers/the_lift_wind_hold_fires_strictly_above_its_threshold_while_the_day_hold_fires_at_sixty
    """
    mountain.set_clock("2026-08-01T00:00:00Z")
    state = mountain.open_mountain(lift_overrides={"wind_hold_threshold_mph": 40.0})
    lift_id = state["lift_id"]
    area_id = state["area_id"]
    day_plan_id = state["day_plan_id"]

    at_the_threshold = validate_success(
        api.post_weather(
            day_plan_id, f.weather_payload(40.0, 22.0, new_snow_in=0.0), DIRECTOR_HEADERS
        )
    )
    assert at_the_threshold["posture"] == "PUBLISHED_FULL"
    assert_integer(at_the_threshold["open_lift_capacity_pph"], 1800)
    assert_integer(at_the_threshold["raw_ccc"], 1080)
    assert_integer(at_the_threshold["guest_capacity"], 918)

    still_spinning = mountain.lift(lift_id)
    assert still_spinning["service_status"] == "OPEN"
    assert still_spinning["wind_hold_since"] is None

    a_tenth_above = validate_success(
        api.post_weather(
            day_plan_id, f.weather_payload(40.1, 22.0, new_snow_in=0.0), DIRECTOR_HEADERS
        )
    )
    assert a_tenth_above["posture"] == "PUBLISHED_PARTIAL"
    assert_integer(a_tenth_above["open_terrain_count"], 0)
    assert_one_decimal(a_tenth_above["terrain_open_acres"], 0.0)
    assert_integer(a_tenth_above["open_lift_capacity_pph"], 0)
    assert_integer(a_tenth_above["raw_ccc"], 0)
    assert_integer(a_tenth_above["guest_capacity"], 0)
    assert_integer(a_tenth_above["non_season_pool"], 0)

    held_lift = mountain.lift(lift_id)
    assert held_lift["service_status"] == "WIND_HOLD"
    assert_instant_equals(held_lift["wind_hold_since"], "2026-08-01T00:00:00Z")
    assert mountain.area(area_id)["opening_state"] == "PATROL_HOLD"

    validate_error(
        api.set_lift_service_status(
            lift_id, f.service_status_payload("OPEN"), LIFT_OPS_HEADERS
        ),
        ERR_WIND_ABOVE_RELEASE_THRESHOLD,
        expected_status=422,
    )

    mountain.post_weather(day_plan_id, 35.1, 22.0, new_snow_in=0.0)
    validate_error(
        api.set_lift_service_status(
            lift_id, f.service_status_payload("OPEN"), LIFT_OPS_HEADERS
        ),
        ERR_WIND_ABOVE_RELEASE_THRESHOLD,
        expected_status=422,
    )

    mountain.post_weather(day_plan_id, 35.0, 22.0, new_snow_in=0.0)
    released = validate_success(
        api.set_lift_service_status(
            lift_id, f.service_status_payload("OPEN"), LIFT_OPS_HEADERS
        )
    )
    assert released["service_status"] == "OPEN"
    assert released["wind_hold_since"] is None
    assert mountain.area(area_id)["opening_state"] == "OPEN"

    recovered = mountain.day_plan(day_plan_id)
    assert recovered["posture"] == "PUBLISHED_FULL"
    assert_integer(recovered["open_lift_capacity_pph"], 1800)
    assert_integer(recovered["raw_ccc"], 1080)
    assert_integer(recovered["guest_capacity"], 918)

    mountain_wide = validate_success(
        api.post_weather(
            day_plan_id, f.weather_payload(60.0, 22.0, new_snow_in=0.0), DIRECTOR_HEADERS
        )
    )
    assert mountain_wide["posture"] == "WEATHER_HOLD"
    assert mountain.lift(lift_id)["service_status"] == "WIND_HOLD"
    assert mountain.area(area_id)["opening_state"] == "PATROL_HOLD"

    calmer = validate_success(
        api.post_weather(
            day_plan_id, f.weather_payload(10.0, 22.0, new_snow_in=0.0), DIRECTOR_HEADERS
        )
    )
    assert calmer["posture"] == "PUBLISHED_PARTIAL"
    assert mountain.lift(lift_id)["service_status"] == "WIND_HOLD"

    released_again = validate_success(
        api.set_lift_service_status(
            lift_id, f.service_status_payload("OPEN"), LIFT_OPS_HEADERS
        )
    )
    assert released_again["service_status"] == "OPEN"

    settled = mountain.day_plan(day_plan_id)
    assert settled["posture"] == "PUBLISHED_FULL"
    assert_integer(settled["open_terrain_count"], 1)
    assert_integer(settled["guest_capacity"], 918)


def test_the_season_area_counts_and_the_day_counters_reconcile_across_an_open_and_a_close(
    api, mountain
):
    """Opening and closing terrain keeps the season's open, openable and percentage figures and the day's capacity and admission counters reconciled, and putting the day to bed returns every counter to zero while the released party is retained.

    Either decision recomputes the season's `open_area_count` and increments the season's `version` by 1; recomputes the active day plan's `open_terrain_count`, `terrain_open_acres`, `open_lift_capacity_pph`, `raw_ccc`, `guest_capacity` and `non_season_pool` and increments the day plan's `version` by 1; and increments the area's own `version` by 1.

    Design: Corner/complexity_layers/the_season_area_counts_and_the_day_counters_reconcile_across_an_open_and_a_close
    """
    mountain.set_clock("2026-08-01T00:00:00Z")
    state = mountain.operating_season(lift_overrides={"wind_hold_threshold_mph": 40.0})
    season_id = state["season_id"]
    sunbowl_id = state["area_id"]
    day_plan_id = state["day_plan_id"]

    meadows = mountain.create_terrain_area(
        season_id, state["lift_id"], trail_code="T2", name="Meadows", acres=8.0
    )
    mountain.record_reading(meadows["id"], stake_code="S1", depth_in=40.0)
    mountain.groom_area(
        meadows["id"], 20, cat_route_code="R2", snowcat_unit_code="CAT-2"
    )
    for code, cert in (("P3", "EMT"), ("P4", "PARAMEDIC")):
        mountain.create_patroller(
            season_id,
            patroller_code=code,
            cert_level=cert,
            on_duty=True,
            assigned_terrain_area_id=meadows["id"],
        )

    nothing_open = validate_success(
        api.get_season_snow_accounting(season_id, DIRECTOR_HEADERS)
    )
    assert_integer(nothing_open["open_area_count"], 0)
    assert_one_decimal(nothing_open["open_acres"], 0.0)
    assert_one_decimal(nothing_open["openable_acres"], 26.0)
    assert_one_decimal(nothing_open["terrain_open_pct"], 0.0)

    season_before = mountain.season(season_id)
    area_before = mountain.area(sunbowl_id)
    first_open = validate_success(
        api.decide_opening(
            sunbowl_id, f.opening_decision_payload("OPEN"), DIRECTOR_HEADERS
        )
    )
    assert first_open["opening_state"] == "OPEN"
    assert first_open["version"] == area_before["version"] + 1
    assert mountain.season(season_id)["version"] == season_before["version"] + 1

    one_open = validate_success(
        api.get_season_snow_accounting(season_id, DIRECTOR_HEADERS)
    )
    assert_integer(one_open["open_area_count"], 1)
    assert_one_decimal(one_open["open_acres"], 18.0)
    assert_one_decimal(one_open["openable_acres"], 26.0)
    assert_one_decimal(one_open["terrain_open_pct"], 69.2)

    mountain.decide_opening(meadows["id"], "OPEN")
    both_open = validate_success(
        api.get_season_snow_accounting(season_id, DIRECTOR_HEADERS)
    )
    assert_integer(both_open["open_area_count"], 2)
    assert_one_decimal(both_open["open_acres"], 26.0)
    assert_one_decimal(both_open["openable_acres"], 26.0)
    assert_one_decimal(both_open["terrain_open_pct"], 100.0)

    full_day = mountain.day_plan(day_plan_id)
    assert full_day["posture"] == "PUBLISHED_FULL"
    assert_integer(full_day["open_terrain_count"], 2)
    assert_one_decimal(full_day["terrain_open_acres"], 26.0)
    assert_integer(full_day["open_lift_capacity_pph"], 1800)
    assert_integer(full_day["raw_ccc"], 1080)
    assert_integer(full_day["guest_capacity"], 918)
    assert_integer(full_day["non_season_pool"], 642)

    party = validate_success(
        api.create_reservation(
            f.reservation_payload(
                day_plan_id,
                full_day["version"],
                party_code="G1",
                pass_type="DAY_TICKET",
                party_size=10,
                vehicle_count=3,
            ),
            GUEST_SERVICES_HEADERS,
        ),
        expected_status=201,
    )
    assert party["state"] == "CONFIRMED"
    assert_integer(party["allocated_stalls"], 3)

    admitted = mountain.day_plan(day_plan_id)
    assert_integer(admitted["admitted_guest_count"], 10)
    assert_integer(admitted["non_season_admitted_count"], 10)
    assert_integer(admitted["parking_stalls_used"], 3)

    closed_area = validate_success(
        api.decide_opening(
            sunbowl_id, f.opening_decision_payload("CLOSE"), DIRECTOR_HEADERS
        )
    )
    assert closed_area["opening_state"] == "CLOSED"

    one_closed = validate_success(
        api.get_season_snow_accounting(season_id, DIRECTOR_HEADERS)
    )
    assert_integer(one_closed["open_area_count"], 1)
    assert_one_decimal(one_closed["open_acres"], 8.0)
    assert_one_decimal(one_closed["openable_acres"], 8.0)
    assert_one_decimal(one_closed["terrain_open_pct"], 30.8)

    partial_day = mountain.day_plan(day_plan_id)
    assert partial_day["posture"] == "PUBLISHED_PARTIAL"
    assert_integer(partial_day["open_terrain_count"], 1)
    assert_one_decimal(partial_day["terrain_open_acres"], 8.0)
    assert_integer(partial_day["raw_ccc"], 1080)
    assert_integer(partial_day["guest_capacity"], 918)
    assert_integer(partial_day["admitted_guest_count"], 10)
    assert_integer(partial_day["parking_stalls_used"], 3)

    put_to_bed = validate_success(
        api.close_day(day_plan_id, DIRECTOR_HEADERS, f.close_day_payload(False))
    )
    assert put_to_bed["posture"] == "DAY_CLOSED"
    assert_instant_equals(put_to_bed["closed_at"], "2026-08-01T00:00:00Z")

    dark = mountain.day_plan(day_plan_id)
    assert_integer(dark["open_terrain_count"], 0)
    assert_one_decimal(dark["terrain_open_acres"], 0.0)
    assert_integer(dark["open_lift_capacity_pph"], 0)
    assert_integer(dark["raw_ccc"], 0)
    assert_integer(dark["guest_capacity"], 0)
    assert_integer(dark["non_season_pool"], 0)
    assert_integer(dark["admitted_guest_count"], 0)
    assert_integer(dark["non_season_admitted_count"], 0)
    assert_integer(dark["parking_stalls_used"], 0)

    after_close = validate_success(
        api.get_season_snow_accounting(season_id, DIRECTOR_HEADERS)
    )
    assert_integer(after_close["open_area_count"], 0)
    assert_one_decimal(after_close["open_acres"], 0.0)
    assert_one_decimal(after_close["openable_acres"], 0.0)
    assert_one_decimal(after_close["terrain_open_pct"], 0.0)

    rows, meta = validate_paginated(
        api.list_day_plan_reservations(
            day_plan_id, GUEST_SERVICES_HEADERS, state="RELEASED"
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["party_code"] == "G1"
    assert_integer(rows[0]["allocated_stalls"], 0)


def test_one_weather_call_cascades_four_levels_from_the_lift_to_the_season_water_ledger(
    api, mountain
):
    """A single wind reading above the lift threshold holds the lift, pushes both areas it serves onto a patrol hold, aborts the snowmaking on them and hands the reserved water back to the season, all from the one call.

    The full deterioration chain, from its deepest head, runs: a weather observation puts lifts on a wind hold → each held lift pushes every terrain area it serves that was open onto a patrol hold → each held area defers its planned and dispatched grooming tasks and aborts its scheduled, running and paused snowmaking sessions → each aborted session releases its water reservation back to the season ledger → the active day plan's counters, carrying capacity and posture are recomputed.

    Design: Corner/complexity_layers/one_weather_call_cascades_four_levels_and_the_release_re_gates_each_area_separately
    """
    state = _two_areas_open_on_one_lift(mountain)

    committed_season = mountain.season(state["season_id"])
    assert_water_af(committed_season["water_reserved_af"], 1.547)
    assert_water_ledger_identity(committed_season, 248.453)
    assert_integer(committed_season["open_area_count"], 2)

    full_day = mountain.day_plan(state["day_plan_id"])
    assert full_day["posture"] == "PUBLISHED_FULL"
    assert_integer(full_day["open_terrain_count"], 2)
    assert_one_decimal(full_day["terrain_open_acres"], 26.0)
    assert_integer(full_day["open_lift_capacity_pph"], 1800)
    assert_integer(full_day["raw_ccc"], 1080)
    assert_integer(full_day["guest_capacity"], 918)

    blown_down = validate_success(
        api.post_weather(
            state["day_plan_id"],
            f.weather_payload(40.1, 22.0, new_snow_in=0.0),
            DIRECTOR_HEADERS,
        )
    )
    assert blown_down["posture"] == "PUBLISHED_PARTIAL"
    assert_integer(blown_down["open_terrain_count"], 0)
    assert_one_decimal(blown_down["terrain_open_acres"], 0.0)
    assert_integer(blown_down["open_lift_capacity_pph"], 0)
    assert_integer(blown_down["raw_ccc"], 0)
    assert_integer(blown_down["guest_capacity"], 0)
    assert_integer(blown_down["non_season_pool"], 0)

    held_lift = mountain.lift(state["lift_id"])
    assert held_lift["service_status"] == "WIND_HOLD"
    assert_instant_equals(held_lift["wind_hold_since"], "2026-08-01T06:00:00Z")

    assert mountain.area(state["sunbowl_id"])["opening_state"] == "PATROL_HOLD"

    held_meadows = mountain.area(state["meadows_id"])
    assert held_meadows["opening_state"] == "PATROL_HOLD"
    assert_instant_equals(held_meadows["last_groomed_at"], "2026-08-01T06:00:00Z")

    aborted = mountain.session(state["session_id"])
    assert aborted["state"] == "ABORTED"
    assert aborted["abort_reason"] == "TERRAIN_HOLD"
    assert_instant_equals(aborted["ended_at"], "2026-08-01T06:00:00Z")
    assert_water_af(aborted["water_af_actual"], 0.000)
    assert_water_af(aborted["snow_swe_af"], 0.000)
    assert_usd(aborted["energy_cost_usd"], 0.00)

    refunded = validate_success(
        api.get_season_snow_accounting(state["season_id"], DIRECTOR_HEADERS)
    )
    assert_water_af(refunded["water_reserved_af"], 0.000)
    assert_water_af(refunded["water_used_af"], 0.000)
    assert_water_af(refunded["water_right_remaining_af"], 250.000)
    assert_integer(refunded["aborted_session_count"], 1)


def test_releasing_the_wind_hold_re_gates_each_area_separately_on_its_own_groom_currency(
    api, mountain
):
    """One hold release returns only the area whose groom is still current at the clock of the release and leaves the stale one on its patrol hold, and the calmer reading before it releases no lift by itself.

    A successful release sets `service_status` to `OPEN`, sets `wind_hold_since` back to null, and conditionally recovers terrain: every area served by this lift sitting on `PATROL_HOLD` is re-gated against the current clock, those satisfying every opening gate return to `OPEN`, and those that do not simply stay on `PATROL_HOLD`.

    Design: Corner/complexity_layers/one_weather_call_cascades_four_levels_and_the_release_re_gates_each_area_separately
    """
    state = _two_areas_open_on_one_lift(mountain)
    mountain.post_weather(state["day_plan_id"], 40.1, 22.0, new_snow_in=0.0)
    assert mountain.lift(state["lift_id"])["service_status"] == "WIND_HOLD"

    mountain.set_clock("2026-08-01T18:00:00Z")
    calmer = validate_success(
        api.post_weather(
            state["day_plan_id"],
            f.weather_payload(35.0, 22.0, new_snow_in=0.0),
            DIRECTOR_HEADERS,
        )
    )
    assert calmer["posture"] == "PUBLISHED_PARTIAL"
    assert mountain.lift(state["lift_id"])["service_status"] == "WIND_HOLD"

    released = validate_success(
        api.set_lift_service_status(
            state["lift_id"], f.service_status_payload("OPEN"), LIFT_OPS_HEADERS
        )
    )
    assert released["service_status"] == "OPEN"
    assert released["wind_hold_since"] is None
    assert_integer(released["staffed_operator_count"], 2)
    assert_instant_equals(released["inspection_valid_until"], "2026-08-02T00:00:00Z")

    # Sunbowl was groomed at midnight, so eighteen hours later it is no longer
    # groom-current and the re-gate leaves it held.
    assert mountain.area(state["sunbowl_id"])["opening_state"] == "PATROL_HOLD"

    # Meadows was groomed at six, so the identical re-gate returns it to service.
    assert mountain.area(state["meadows_id"])["opening_state"] == "OPEN"

    recomputed = mountain.day_plan(state["day_plan_id"])
    assert recomputed["posture"] == "PUBLISHED_PARTIAL"
    assert_integer(recomputed["open_terrain_count"], 1)
    assert_one_decimal(recomputed["terrain_open_acres"], 8.0)
    assert_integer(recomputed["open_lift_capacity_pph"], 1800)
    assert_integer(recomputed["raw_ccc"], 1080)
    assert_integer(recomputed["guest_capacity"], 918)

    rollup = validate_success(
        api.get_season_snow_accounting(state["season_id"], DIRECTOR_HEADERS)
    )
    assert_integer(rollup["open_area_count"], 1)
    assert_one_decimal(rollup["open_acres"], 8.0)
    assert_one_decimal(rollup["openable_acres"], 26.0)
    assert_one_decimal(rollup["terrain_open_pct"], 30.8)
    assert_water_af(rollup["water_reserved_af"], 0.000)


def test_every_cascade_effect_is_already_visible_in_the_response_body_that_caused_it(
    api, mountain
):
    """The weather call that fires the deepest chain already returns the settled day plan, and the first read of every row the chain touched agrees with it without a retry.

    Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.

    Design: Corner/consistency_model/every_cascade_effect_is_already_visible_in_the_response_body_that_caused_it
    """
    mountain.set_clock("2026-08-01T00:00:00Z")
    state = mountain.open_mountain(
        lift_overrides={"wind_hold_threshold_mph": 40.0},
        with_pump_house=True,
        pump_house_overrides={"status": "ONLINE"},
    )
    day_plan_id = state["day_plan_id"]
    session = mountain.schedule_session(
        state["area_id"],
        state["pump_house_id"],
        window_start="2026-08-01T05:00:00Z",
        window_end="2026-08-01T12:00:00Z",
        gun_count=30,
        gpm=1200,
    )

    committed_season = mountain.season(state["season_id"])
    assert_water_af(committed_season["water_reserved_af"], 1.547)
    assert_water_ledger_identity(committed_season, 248.453)

    committed_plant = mountain.pump_house(state["pump_house_id"])
    assert_integer(committed_plant["peak_committed_gpm"], 1200)
    assert_integer(committed_plant["active_session_count"], 0)

    counters = (
        "posture",
        "open_terrain_count",
        "terrain_open_acres",
        "open_lift_capacity_pph",
        "raw_ccc",
        "guest_capacity",
        "non_season_pool",
        "admitted_guest_count",
        "non_season_admitted_count",
        "waitlisted_guest_count",
        "parking_stalls_used",
    )

    mutating_body = validate_success(
        api.post_weather(
            day_plan_id,
            f.weather_payload(40.1, 22.0, new_snow_in=0.0),
            DIRECTOR_HEADERS,
        )
    )
    assert mutating_body["posture"] == "PUBLISHED_PARTIAL"
    assert_integer(mutating_body["open_terrain_count"], 0)
    assert_one_decimal(mutating_body["terrain_open_acres"], 0.0)
    assert_integer(mutating_body["open_lift_capacity_pph"], 0)
    assert_integer(mutating_body["raw_ccc"], 0)
    assert_integer(mutating_body["guest_capacity"], 0)
    assert_integer(mutating_body["non_season_pool"], 0)
    assert_one_decimal(mutating_body["wind_speed_mph"], 40.1)

    # Every row four levels down the chain is settled on its first read.
    aborted = validate_success(api.get_session(session["id"], SNOWMAKING_HEADERS))
    assert aborted["state"] == "ABORTED"
    assert aborted["abort_reason"] == "TERRAIN_HOLD"
    assert_instant_equals(aborted["ended_at"], "2026-08-01T00:00:00Z")

    refunded_season = validate_success(
        api.get_season(state["season_id"], DIRECTOR_HEADERS)
    )
    assert_water_af(refunded_season["water_reserved_af"], 0.000)
    assert_water_ledger_identity(refunded_season, 250.000)

    held_area = validate_success(
        api.get_terrain_area(state["area_id"], DIRECTOR_HEADERS)
    )
    assert held_area["opening_state"] == "PATROL_HOLD"

    held_lift = validate_success(api.get_lift(state["lift_id"], LIFT_OPS_HEADERS))
    assert held_lift["service_status"] == "WIND_HOLD"
    assert_instant_equals(held_lift["wind_hold_since"], "2026-08-01T00:00:00Z")

    released_plant = validate_success(
        api.get_pump_house(state["pump_house_id"], SNOWMAKING_HEADERS)
    )
    assert_integer(released_plant["peak_committed_gpm"], 0)
    assert_integer(released_plant["active_session_count"], 0)

    stored = validate_success(api.get_day_plan(day_plan_id, DIRECTOR_HEADERS))
    for field in counters:
        assert stored[field] == mutating_body[field], (
            f"Stored day plan disagrees with the response that settled it on {field}"
        )
    assert stored["version"] == mutating_body["version"]

    report = validate_success(api.get_opening_report(day_plan_id, GUEST_SERVICES_HEADERS))
    assert_integer(report["open_terrain_count"], 0)
    assert_one_decimal(report["terrain_open_acres"], 0.0)
    assert_integer(report["guest_capacity"], 0)
    assert_integer(report["held_area_count"], 1)
    assert_integer(report["wind_held_lift_count"], 1)

    read_again = validate_success(api.get_day_plan(day_plan_id, GUEST_SERVICES_HEADERS))
    assert read_again["version"] == stored["version"] == mutating_body["version"]
    for field in counters:
        assert read_again[field] == mutating_body[field], (
            f"Repeating the read moved {field}, so the first read was not settled"
        )

    rollup = validate_success(
        api.get_season_snow_accounting(state["season_id"], GUEST_SERVICES_HEADERS)
    )
    assert_water_af(rollup["water_used_af"], 0.000)
    assert_water_af(rollup["water_reserved_af"], 0.000)
    assert_water_af(rollup["water_right_remaining_af"], 250.000)
    assert_integer(rollup["aborted_session_count"], 1)
