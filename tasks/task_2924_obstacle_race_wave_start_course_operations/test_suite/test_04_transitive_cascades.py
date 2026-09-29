"""Four-link cascades that must run to the end inside one operation.

Every test in this module translates exactly one instance of the
`transitive_cascade` rule of the difficulty design index. Two origins are
probed: a `SafetyOfficer` releasing the last marshal from a station, and the
logical clock stepping past a governing permit's validity horizon with no
operator touching the parcel at all.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.assertions import (
    assert_course_capacities,
    assert_obstacle_staffing,
    assert_wave_state,
)
from test_helpers.constants import (
    ASSIGNMENT_VACATED,
    BYPASS_MODE_MANDATORY,
    BYPASS_MODE_NONE,
    BYPASS_MODE_TIMED_PENALTY,
    BYPASS_POLICY_DQ_ON_BYPASS,
    COURSE_PUBLISHED,
    COURSE_SUSPENDED,
    DIVISION_COMPETITIVE,
    HOLD_REASON_COURSE_RESTRICTED,
    HOLD_REASON_VENUE_FROZEN,
    PERMIT_APPROVED,
    PERMIT_EXPIRED,
    READINESS_FROZEN,
    READINESS_OPEN,
    READINESS_RESTRICTED,
    RELEASE_HELD,
    RELEASE_SCHEDULED,
    ROSTER_LOCKED,
    ROSTER_OPEN,
    SCORING_CHIP_TIME,
    SERVICE_CLOSED,
    SERVICE_OPEN,
    SERVICE_RINSE_STATION,
    SITE_POSTURE_FROZEN,
    SITE_POSTURE_OPEN,
    STAFFING_MARSHALED,
    STAFFING_PARTIAL,
    STAFFING_UNSTAFFED,
    STAFF_MEDIC_1,
    STAFF_SWIMMER_1,
    STAFF_SWIMMER_2,
)

# ─── The canonical quarry parcel of the design index ─────────────────────

_PERMIT_VALID_UNTIL_UTC = "2026-09-15T00:00:00.000Z"
_CLOCK_INSIDE_HOLDBACK_UTC = "2026-09-12T07:30:00.000Z"
_HEAT_A1_START_UTC = "2026-09-12T08:00:00.000Z"
_HEAT_A2_START_UTC = "2026-09-12T08:30:00.000Z"
_LATE_SEASON_HEAT_UTC = "2026-09-20T08:00:00.000Z"
_CLOCK_AT_VALID_UNTIL_UTC = "2026-09-15T00:00:00.000Z"
_CLOCK_ONE_SECOND_PAST_UTC = "2026-09-15T00:00:01.000Z"
_CLOCK_PAST_EXPIRY_UTC = "2026-09-16T00:00:00.000Z"

#: floor(min(12.00, 7.50, 12.00) * 60) — the paper rate of the slowest station.
_DESIGN_CAPACITY_PPH = 450
#: The same figure once every station is fully marshaled.
_BOTTLENECK_STAFFED_PPH = 450
#: floor(450 * 15 / 60), the §3.4 design-capacity ceiling on one heat.
_HEAT_CAPACITY = 112
#: Station 1 at a 0.60 staffing factor: floor(4 * 3.00 * 0.60 * 60).
_BOTTLENECK_PARTIAL_PPH = 432
_PARTIAL_STATION_RATE = 7.20

#: The three obstacle footprints plus one 200 sqm rinse station.
_DISTURBED_AREA_SQM = 3900

_COURSE_KWARGS = {
    "name": "Quarry Gauntlet",
    "total_distance_m": 10000,
    "corral_release_rate_per_min": 12.00,
    "corral_throughput_capacity": 200,
}

_STATION_KWARGS = [
    {
        "name": "Cargo Net",
        "difficulty_rating": 3,
        "lane_count": 4,
        "service_rate_per_min": 3.00,
        "marshals_required": 2,
        "footprint_sqm": 1200,
        "water_contact": False,
        "bypass_mode": BYPASS_MODE_NONE,
        "penalty_seconds": 0,
    },
    {
        "name": "Pond Crossing",
        "difficulty_rating": 5,
        "lane_count": 3,
        "service_rate_per_min": 2.50,
        "marshals_required": 2,
        "footprint_sqm": 1500,
        "water_contact": True,
        "bypass_mode": BYPASS_MODE_MANDATORY,
        "penalty_seconds": 120,
    },
    {
        "name": "Wall Climb",
        "difficulty_rating": 7,
        "lane_count": 3,
        "service_rate_per_min": 3.00,
        "marshals_required": 1,
        "footprint_sqm": 1000,
        "water_contact": False,
        "bypass_mode": BYPASS_MODE_TIMED_PENALTY,
        "penalty_seconds": 90,
    },
]


def _quarry_world(api, valid_until_utc: str = _PERMIT_VALID_UNTIL_UTC) -> dict:
    """An APPROVED permit over a PUBLISHED, fully covered three-station course.

    Station 3 needs exactly one marshal, stations 1 and 2 need two each, the
    single wet station carries its two swimmers and the course carries one
    medic, so `readiness_posture` reads `OPEN` before any test acts.
    """
    venue, permit = fx.permitted_venue(api, valid_until_utc=valid_until_utc)
    course, stations = fx.three_station_course(
        api,
        venue["id"],
        course_kwargs=_COURSE_KWARGS,
        station_kwargs=_STATION_KWARGS,
    )
    fx.published_course(api, course["id"])
    marshal_shifts = [
        fx.fully_marshal(api, course["id"], station) for station in stations
    ]
    fx.water_safety_shift(api, course["id"], stations[1]["id"], STAFF_SWIMMER_1)
    fx.water_safety_shift(api, course["id"], stations[1]["id"], STAFF_SWIMMER_2)
    fx.medic_shift(api, course["id"], STAFF_MEDIC_1)
    division = fx.division(
        api,
        name="Elite Competitive",
        division_type=DIVISION_COMPETITIVE,
        bypass_policy=BYPASS_POLICY_DQ_ON_BYPASS,
        scoring_mode=SCORING_CHIP_TIME,
        min_age=18,
        team_size_min=1,
        team_size_max=1,
    )
    return {
        "venue": venue,
        "permit": permit,
        "course": course,
        "stations": stations,
        "marshal_shifts": marshal_shifts,
        "division": division,
    }


# ─── transitive_cascade / the staffing origin ────────────────────────────


def test_vacating_the_only_marshal_cascades_staff_to_obstacle_to_course_to_wave(api):
    """PRD §3.3: "Link four, caused by link three leaving the posture `RESTRICTED`, moves every heat on that course whose `release_status` is `SCHEDULED` and whose `scheduled_start_utc` falls at or before the logical clock advanced by the 45-minute holdback window to `HELD`, with `hold_reason` set to the string `COURSE_RESTRICTED`."

    Design: Difficulty/transitive_cascade/vacating_the_only_marshal_cascades_staff_to_obstacle_to_course_to_wave
    """
    world = _quarry_world(api)
    course_id = world["course"]["id"]
    station_three = world["stations"][2]
    only_marshal = world["marshal_shifts"][2][0]

    heat = fx.wave(
        api,
        course_id,
        world["division"]["id"],
        wave_code="A1",
        scheduled_start_utc=_HEAT_A1_START_UTC,
        capacity=_HEAT_CAPACITY,
    )
    fx.checked_in_entry(api, heat["id"], bib_number=101, chip_start_offset_seconds=37)
    fx.lock_roster(api, heat["id"])
    fx.set_clock(api, _CLOCK_INSIDE_HOLDBACK_UTC)

    # The world is sound before the cascade: nothing here is under test.
    assert_course_capacities(
        fx.read_course(api, course_id),
        design_capacity_pph=_DESIGN_CAPACITY_PPH,
        bottleneck_capacity_pph=_BOTTLENECK_STAFFED_PPH,
        readiness_posture=READINESS_OPEN,
        status=COURSE_PUBLISHED,
    )
    assert_wave_state(
        fx.read_wave(api, heat["id"]),
        release_status=RELEASE_SCHEDULED,
        roster_status=ROSTER_LOCKED,
        hold_reason=None,
    )

    fx.vacate(api, only_marshal["id"], reason="Marshal withdrew with a sprained ankle")

    # Link one: the shift itself.
    vacated = validate_success(api.get_staff_assignment(only_marshal["id"], users.SAFETY))
    assert vacated["status"] == ASSIGNMENT_VACATED, vacated
    assert vacated["vacate_reason"] == "Marshal withdrew with a sprained ankle", vacated

    # Link two: the station it covered, and only that station.
    assert_obstacle_staffing(
        fx.read_obstacle(api, station_three["id"]),
        staffing_state=STAFFING_UNSTAFFED,
        confirmed_marshal_count=0,
        effective_rate=0.00,
    )
    for untouched in world["stations"][:2]:
        assert_obstacle_staffing(
            fx.read_obstacle(api, untouched["id"]),
            staffing_state=STAFFING_MARSHALED,
        )

    # Link three: the course posture, with the publication dimension untouched
    # and the paper design rate unmoved.
    assert_course_capacities(
        fx.read_course(api, course_id),
        design_capacity_pph=_DESIGN_CAPACITY_PPH,
        bottleneck_capacity_pph=0,
        readiness_posture=READINESS_RESTRICTED,
        status=COURSE_PUBLISHED,
    )

    # Link four: the imminent heat, with the orthogonal roster dimension intact.
    assert_wave_state(
        fx.read_wave(api, heat["id"]),
        release_status=RELEASE_HELD,
        roster_status=ROSTER_LOCKED,
        hold_reason=HOLD_REASON_COURSE_RESTRICTED,
    )


def test_the_staffing_cascade_leaves_a_heat_beyond_the_holdback_window_scheduled(api):
    """PRD §3.3: "Heats further out than three quarters of an hour are left alone, on the assumption that the gap can still be re-staffed."

    Design: Difficulty/transitive_cascade/vacating_the_only_marshal_cascades_staff_to_obstacle_to_course_to_wave
    """
    world = _quarry_world(api)
    course_id = world["course"]["id"]
    only_marshal = world["marshal_shifts"][2][0]

    imminent = fx.wave(
        api,
        course_id,
        world["division"]["id"],
        wave_code="A1",
        scheduled_start_utc=_HEAT_A1_START_UTC,
        capacity=_HEAT_CAPACITY,
    )
    distant = fx.wave(
        api,
        course_id,
        world["division"]["id"],
        wave_code="A2",
        scheduled_start_utc=_HEAT_A2_START_UTC,
        capacity=_HEAT_CAPACITY,
    )
    fx.set_clock(api, _CLOCK_INSIDE_HOLDBACK_UTC)

    fx.vacate(api, only_marshal["id"])

    # 08:00 sits at or before 07:30 + 45 minutes; 08:30 sits beyond it.
    assert_wave_state(
        fx.read_wave(api, imminent["id"]),
        release_status=RELEASE_HELD,
        hold_reason=HOLD_REASON_COURSE_RESTRICTED,
    )
    assert_wave_state(
        fx.read_wave(api, distant["id"]),
        release_status=RELEASE_SCHEDULED,
        roster_status=ROSTER_OPEN,
        hold_reason=None,
    )
    assert_course_capacities(
        fx.read_course(api, course_id),
        readiness_posture=READINESS_RESTRICTED,
        bottleneck_capacity_pph=0,
    )


def test_partial_staffing_lowers_the_bottleneck_without_restricting_the_course(api):
    """PRD §3.3: "Note carefully that `PARTIAL` staffing does **not** restrict a course — it only lowers `bottleneck_capacity_pph`."

    Design: Difficulty/transitive_cascade/vacating_the_only_marshal_cascades_staff_to_obstacle_to_course_to_wave
    """
    world = _quarry_world(api)
    course_id = world["course"]["id"]
    station_one = world["stations"][0]
    one_of_two_marshals = world["marshal_shifts"][0][0]

    heat = fx.wave(
        api,
        course_id,
        world["division"]["id"],
        wave_code="A1",
        scheduled_start_utc=_HEAT_A1_START_UTC,
        capacity=_HEAT_CAPACITY,
    )
    fx.set_clock(api, _CLOCK_INSIDE_HOLDBACK_UTC)

    fx.vacate(api, one_of_two_marshals["id"])

    # Link two stops at PARTIAL, so link three has nothing to restrict and
    # link four never fires — but the live throughput still collapses.
    assert_obstacle_staffing(
        fx.read_obstacle(api, station_one["id"]),
        staffing_state=STAFFING_PARTIAL,
        confirmed_marshal_count=1,
        effective_rate=_PARTIAL_STATION_RATE,
    )
    assert_course_capacities(
        fx.read_course(api, course_id),
        design_capacity_pph=_DESIGN_CAPACITY_PPH,
        bottleneck_capacity_pph=_BOTTLENECK_PARTIAL_PPH,
        readiness_posture=READINESS_OPEN,
        status=COURSE_PUBLISHED,
    )
    assert_wave_state(
        fx.read_wave(api, heat["id"]),
        release_status=RELEASE_SCHEDULED,
        hold_reason=None,
    )


# ─── transitive_cascade / the clock origin ───────────────────────────────


def _read_festival_service(api, venue_id: str, service_id: str) -> dict:
    rows, _meta = validate_paginated(api.list_festival_services(venue_id, users.OPS))
    matches = [row for row in rows if row["id"] == service_id]
    assert matches, f"festival service {service_id} is missing from {rows!r}"
    return matches[0]


def test_permit_expiry_at_the_clock_freezes_venue_courses_waves_and_festival_services(api):
    """PRD §2.10: "Link four, caused by link three, moves every `Wave` on those suspended courses whose `release_status` is `SCHEDULED` or `HELD` to `HELD` with `hold_reason` set to the string `VENUE_FROZEN`."

    Design: Difficulty/transitive_cascade/permit_expiry_at_the_clock_freezes_venue_courses_waves_and_festival_services
    """
    world = _quarry_world(api, valid_until_utc=_PERMIT_VALID_UNTIL_UTC)
    venue_id = world["venue"]["id"]
    permit_id = world["permit"]["id"]
    course_id = world["course"]["id"]

    heat = fx.wave(
        api,
        course_id,
        world["division"]["id"],
        wave_code="A1",
        scheduled_start_utc=_LATE_SEASON_HEAT_UTC,
        capacity=_HEAT_CAPACITY,
    )
    rinse = fx.festival_service(
        api,
        venue_id,
        service_type=SERVICE_RINSE_STATION,
        footprint_sqm=200,
        capacity=40,
        water_draw_lpm=0,
    )
    assert rinse["status"] == SERVICE_OPEN, rinse

    # Nobody acts on the parcel: the clock simply steps past 2026-09-15.
    moved = fx.set_clock(api, _CLOCK_PAST_EXPIRY_UTC)
    assert permit_id in moved["expired_permit_ids"], moved

    assert fx.read_permit(api, permit_id)["status"] == PERMIT_EXPIRED
    assert fx.read_venue(api, venue_id)["site_posture"] == SITE_POSTURE_FROZEN

    assert_course_capacities(
        fx.read_course(api, course_id),
        status=COURSE_SUSPENDED,
        readiness_posture=READINESS_FROZEN,
    )

    # The hold is unconditional here: 2026-09-20 is five days beyond the clock,
    # far outside the 45-minute staffing holdback window.
    assert_wave_state(
        fx.read_wave(api, heat["id"]),
        release_status=RELEASE_HELD,
        roster_status=ROSTER_OPEN,
        hold_reason=HOLD_REASON_VENUE_FROZEN,
    )

    # Sideways fan-out, and the physical footprint it must not touch.
    assert _read_festival_service(api, venue_id, rinse["id"])["status"] == SERVICE_CLOSED
    frozen_venue = fx.read_venue(api, venue_id)
    assert frozen_venue["disturbed_area_sqm"] == _DISTURBED_AREA_SQM, frozen_venue

    # Staffing rows are untouched; only the postures moved.
    assert_obstacle_staffing(
        fx.read_obstacle(api, world["stations"][2]["id"]),
        staffing_state=STAFFING_MARSHALED,
        confirmed_marshal_count=1,
    )


def test_a_clock_landing_exactly_on_valid_until_expires_nothing_and_freezes_nothing(api):
    """PRD §2.5: "Setting the clock is the only way an `APPROVED` permit reaches `EXPIRED`: every approved permit whose `valid_until_utc` is strictly before the new clock value expires, and each such expiry runs the full parcel-freeze cascade described in §2.10."

    Design: Difficulty/transitive_cascade/permit_expiry_at_the_clock_freezes_venue_courses_waves_and_festival_services
    """
    world = _quarry_world(api, valid_until_utc=_PERMIT_VALID_UNTIL_UTC)
    venue_id = world["venue"]["id"]
    permit_id = world["permit"]["id"]
    course_id = world["course"]["id"]

    heat = fx.wave(
        api,
        course_id,
        world["division"]["id"],
        wave_code="A1",
        scheduled_start_utc=_LATE_SEASON_HEAT_UTC,
        capacity=_HEAT_CAPACITY,
    )

    # Equality is not a strict excess, so no link of the chain may run.
    at_the_horizon = fx.set_clock(api, _CLOCK_AT_VALID_UNTIL_UTC)
    assert at_the_horizon["expired_permit_ids"] == [], at_the_horizon
    assert fx.read_permit(api, permit_id)["status"] == PERMIT_APPROVED
    assert fx.read_venue(api, venue_id)["site_posture"] == SITE_POSTURE_OPEN
    assert_course_capacities(
        fx.read_course(api, course_id),
        status=COURSE_PUBLISHED,
        readiness_posture=READINESS_OPEN,
    )
    assert_wave_state(
        fx.read_wave(api, heat["id"]),
        release_status=RELEASE_SCHEDULED,
        hold_reason=None,
    )

    # One second later the whole chain runs.
    one_second_past = fx.set_clock(api, _CLOCK_ONE_SECOND_PAST_UTC)
    assert permit_id in one_second_past["expired_permit_ids"], one_second_past
    assert fx.read_permit(api, permit_id)["status"] == PERMIT_EXPIRED
    assert fx.read_venue(api, venue_id)["site_posture"] == SITE_POSTURE_FROZEN
    assert_course_capacities(
        fx.read_course(api, course_id),
        status=COURSE_SUSPENDED,
        readiness_posture=READINESS_FROZEN,
    )
    assert_wave_state(
        fx.read_wave(api, heat["id"]),
        release_status=RELEASE_HELD,
        hold_reason=HOLD_REASON_VENUE_FROZEN,
    )


def test_the_freeze_rewrites_an_operator_hold_reason_to_venue_frozen(api):
    """PRD §2.10: "Every row touched anywhere in this chain has its `version` incremented by 1 and its `updated_at` refreshed."

    Design: Difficulty/transitive_cascade/permit_expiry_at_the_clock_freezes_venue_courses_waves_and_festival_services
    """
    world = _quarry_world(api, valid_until_utc=_PERMIT_VALID_UNTIL_UTC)
    permit_id = world["permit"]["id"]

    heat = fx.wave(
        api,
        world["course"]["id"],
        world["division"]["id"],
        wave_code="A1",
        scheduled_start_utc=_LATE_SEASON_HEAT_UTC,
        capacity=_HEAT_CAPACITY,
    )
    fx.hold(api, heat["id"], reason="Weather cell overhead")

    before = fx.read_wave(api, heat["id"])
    assert_wave_state(
        before, release_status=RELEASE_HELD, hold_reason="Weather cell overhead"
    )
    course_before = fx.read_course(api, world["course"]["id"])

    moved = fx.set_clock(api, _CLOCK_PAST_EXPIRY_UTC)
    assert permit_id in moved["expired_permit_ids"], moved

    # An already-HELD heat is in link four's scope too, and its operator-supplied
    # reason is overwritten by the system reason.
    after = fx.read_wave(api, heat["id"])
    assert_wave_state(
        after, release_status=RELEASE_HELD, hold_reason=HOLD_REASON_VENUE_FROZEN
    )
    assert after["version"] == before["version"] + 1, (before, after)

    course_after = fx.read_course(api, world["course"]["id"])
    assert course_after["version"] == course_before["version"] + 1, (
        course_before,
        course_after,
    )
