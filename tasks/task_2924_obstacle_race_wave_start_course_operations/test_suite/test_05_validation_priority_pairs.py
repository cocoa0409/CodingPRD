"""Requests that violate two or more rungs of the §2.6 ladder at once.

Every test in this module translates exactly one instance of the
`priority_pair_validation_conflict` rule of the difficulty design index: a
single request whose several complaints are all genuinely live, where only the
lowest-numbered rung may be reported. Each pair is proved live from both sides
— once masked, once on its own.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_course_capacities, assert_wave_state
from test_helpers.constants import (
    BYPASS_MODE_MANDATORY,
    BYPASS_MODE_NONE,
    BYPASS_MODE_TIMED_PENALTY,
    BYPASS_POLICY_DQ_ON_BYPASS,
    CLEARANCE_CLEARED,
    COURSE_PUBLISHED,
    DIVISION_COMPETITIVE,
    HOLD_REASON_COURSE_RESTRICTED,
    READINESS_OPEN,
    READINESS_RESTRICTED,
    RELEASE_HELD,
    RELEASE_SCHEDULED,
    ROSTER_LOCKED,
    SCORING_CHIP_TIME,
    STAFF_MEDIC_1,
    STAFF_SWIMMER_1,
    STAFF_SWIMMER_2,
)

# ─── The canonical quarry parcel of the design index ─────────────────────

_PERMIT_VALID_UNTIL_UTC = "2026-09-15T00:00:00.000Z"
_CLOCK_INSIDE_HOLDBACK_UTC = "2026-09-12T07:30:00.000Z"
_HEAT_A1_START_UTC = "2026-09-12T08:00:00.000Z"
_HEAT_B1_START_UTC = "2026-09-12T09:00:00.000Z"

#: floor(min(12.00, 7.50, 12.00) * 60) on the three-station course.
_DESIGN_CAPACITY_PPH = 450
#: floor(450 * 15 / 60), the §3.4 design-capacity ceiling on one heat.
_HEAT_CAPACITY = 112
#: Station 1 at a 0.60 staffing factor: floor(4 * 3.00 * 0.60 * 60).
_BOTTLENECK_PARTIAL_PPH = 432
#: floor(720 * 15 / 60) on the single-station course, so a capacity-1 heat is
#: nowhere near the priority-30 design gate.
_SINGLE_STATION_DESIGN_PPH = 720

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


def _elite_division(api) -> dict:
    return fx.division(
        api,
        name="Elite Competitive",
        division_type=DIVISION_COMPETITIVE,
        bypass_policy=BYPASS_POLICY_DQ_ON_BYPASS,
        scoring_mode=SCORING_CHIP_TIME,
        min_age=18,
        team_size_min=1,
        team_size_max=1,
    )


def _release_ready_heat(api) -> dict:
    """A locked, entered, SCHEDULED heat on a PUBLISHED, OPEN, fully covered course.

    Every release rung above the readiness rung is satisfied: the course is
    published, one medic covers a 112-strong scheduled total, the roster is
    locked and one entry is checked in.
    """
    venue, permit = fx.permitted_venue(api, valid_until_utc=_PERMIT_VALID_UNTIL_UTC)
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
    division = _elite_division(api)
    heat = fx.wave(
        api,
        course["id"],
        division["id"],
        wave_code="A1",
        scheduled_start_utc=_HEAT_A1_START_UTC,
        capacity=_HEAT_CAPACITY,
    )
    fx.checked_in_entry(api, heat["id"], bib_number=101, chip_start_offset_seconds=37)
    fx.lock_roster(api, heat["id"])
    return {
        "venue": venue,
        "permit": permit,
        "course": course,
        "stations": stations,
        "marshal_shifts": marshal_shifts,
        "division": division,
        "heat": heat,
    }


def _full_single_slot_heat(api, capacity: int = 1) -> dict:
    """A DRAFT course carrying one station, and one heat on it already full.

    No permit exists on the parcel, so the priority-19 quiet-hours rung is
    skipped entirely and nothing between the state rungs and the waiver rung
    can mask a registration refusal.
    """
    venue = fx.venue(api)
    course = fx.course(api, venue["id"], **_COURSE_KWARGS)
    fx.obstacle(api, course["id"], 1, **_STATION_KWARGS[0])
    division = _elite_division(api)
    heat = fx.wave(
        api,
        course["id"],
        division["id"],
        wave_code="B1",
        scheduled_start_utc=_HEAT_B1_START_UTC,
        capacity=capacity,
    )
    occupant = fx.cleared_participant(api, birth_year=2008)
    fx.entry(api, heat["id"], occupant["id"], bib_number=201)
    return {
        "venue": venue,
        "course": course,
        "division": division,
        "heat": heat,
        "occupant": occupant,
    }


# ─── priority_pair_validation_conflict / release-time rungs 9, 12 and 32 ──


def test_held_wave_returns_state_error_not_the_course_safety_or_bottleneck_error(api):
    """PRD §3.6: "The heat's `release_status` must be `SCHEDULED`; a heat that is `HELD`, `RELEASED`, `STARTED` or `CLOSED` is refused with `ERR_WAVE_NOT_RELEASABLE`."

    Design: Difficulty/priority_pair_validation_conflict/held_wave_returns_state_error_not_the_course_safety_or_bottleneck_error
    """
    world = _release_ready_heat(api)
    heat_id = world["heat"]["id"]

    fx.set_clock(api, _CLOCK_INSIDE_HOLDBACK_UTC)
    fx.vacate(
        api,
        world["marshal_shifts"][2][0]["id"],
        reason="Marshal withdrew with a sprained ankle",
    )

    # All three complaints are now live on the same request: the heat is HELD,
    # the course is RESTRICTED, and capacity 112 exceeds floor(0 * 15 / 60).
    held = fx.read_wave(api, heat_id)
    assert_wave_state(
        held,
        release_status=RELEASE_HELD,
        roster_status=ROSTER_LOCKED,
        hold_reason=HOLD_REASON_COURSE_RESTRICTED,
    )
    assert_course_capacities(
        fx.read_course(api, world["course"]["id"]),
        bottleneck_capacity_pph=0,
        readiness_posture=READINESS_RESTRICTED,
        status=COURSE_PUBLISHED,
    )
    assert held["capacity"] == _HEAT_CAPACITY, held
    version_before = held["version"]

    # Rung 9 wins: neither ERR_COURSE_UNSAFE (12) nor
    # ERR_BOTTLENECK_CAPACITY_EXCEEDED (32) may surface.
    validate_error(
        api.release_wave(heat_id, users.DIRECTOR),
        ApiErrorId.ERR_WAVE_NOT_RELEASABLE.value,
        expected_status=409,
    )

    # The control: on the un-hold endpoint the state rung is satisfied, which
    # proves the priority-12 readiness rule was genuinely violated all along.
    validate_error(
        api.hold_wave(heat_id, f.hold_payload(False), users.DIRECTOR),
        ApiErrorId.ERR_COURSE_UNSAFE.value,
        expected_status=409,
    )

    after = fx.read_wave(api, heat_id)
    assert_wave_state(
        after,
        release_status=RELEASE_HELD,
        roster_status=ROSTER_LOCKED,
        hold_reason=HOLD_REASON_COURSE_RESTRICTED,
    )
    assert after["version"] == version_before, (held, after)


def test_a_scheduled_heat_on_a_restricted_course_reports_the_readiness_error(api):
    """PRD §3.6: "The course's `readiness_posture` must read `OPEN`, or the release is refused with `ERR_COURSE_UNSAFE`."

    Design: Difficulty/priority_pair_validation_conflict/held_wave_returns_state_error_not_the_course_safety_or_bottleneck_error
    """
    world = _release_ready_heat(api)
    heat_id = world["heat"]["id"]

    # The clock is left at its default reading, so the 08:00 heat on 2026-09-12
    # is far outside the holdback window and link four never holds it.
    fx.vacate(api, world["marshal_shifts"][2][0]["id"])

    assert_wave_state(
        fx.read_wave(api, heat_id),
        release_status=RELEASE_SCHEDULED,
        roster_status=ROSTER_LOCKED,
        hold_reason=None,
    )
    assert_course_capacities(
        fx.read_course(api, world["course"]["id"]),
        bottleneck_capacity_pph=0,
        readiness_posture=READINESS_RESTRICTED,
    )

    # Rung 12 now outranks rung 32, which is violated just as hard.
    validate_error(
        api.release_wave(heat_id, users.DIRECTOR),
        ApiErrorId.ERR_COURSE_UNSAFE.value,
        expected_status=409,
    )
    assert_wave_state(fx.read_wave(api, heat_id), release_status=RELEASE_SCHEDULED)


def test_the_bottleneck_ceiling_surfaces_once_readiness_is_satisfied(api):
    """PRD §3.6: "And the heat's `capacity` must be at most the live bottleneck ceiling: the course's `bottleneck_capacity_pph` multiplied by 15 and divided by 60, with any fractional part discarded, exceeding which is refused with `ERR_BOTTLENECK_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/held_wave_returns_state_error_not_the_course_safety_or_bottleneck_error
    """
    world = _release_ready_heat(api)
    heat_id = world["heat"]["id"]

    # One of station 1's two marshals leaves: PARTIAL staffing does not restrict
    # the course, so the readiness rung passes and the fiscal rung is exposed.
    fx.vacate(api, world["marshal_shifts"][0][0]["id"])

    assert_course_capacities(
        fx.read_course(api, world["course"]["id"]),
        design_capacity_pph=_DESIGN_CAPACITY_PPH,
        bottleneck_capacity_pph=_BOTTLENECK_PARTIAL_PPH,
        readiness_posture=READINESS_OPEN,
        status=COURSE_PUBLISHED,
    )

    # floor(432 * 15 / 60) == 108, and the heat carries 112.
    validate_error(
        api.release_wave(heat_id, users.DIRECTOR),
        ApiErrorId.ERR_BOTTLENECK_CAPACITY_EXCEEDED.value,
        expected_status=409,
    )
    assert_wave_state(
        fx.read_wave(api, heat_id),
        release_status=RELEASE_SCHEDULED,
        roster_status=ROSTER_LOCKED,
    )


# ─── priority_pair_validation_conflict / registration rungs 13, 26 and 31 ──


def test_unsigned_waiver_outranks_the_full_roster_on_the_same_registration(api):
    """PRD §3.5: "The participant must have signed the waiver, or the registration is refused with `ERR_WAIVER_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/unsigned_waiver_outranks_the_full_roster_on_the_same_registration
    """
    world = _full_single_slot_heat(api, capacity=1)
    heat_id = world["heat"]["id"]

    # A grown adult who never signed, arriving at a heat that is already full:
    # the waiver rung and the roster-capacity rung are violated at once.
    candidate = fx.participant(api, birth_year=2000)
    assert candidate["waiver_signed"] is False, candidate
    full = fx.read_wave(api, heat_id)
    assert full["assigned_count"] == 1, full
    assert full["capacity"] == 1, full

    # Rung 13 wins over rung 31.
    validate_error(
        api.create_entry(
            heat_id, f.entry_payload(candidate["id"], 202), users.OPS
        ),
        ApiErrorId.ERR_WAIVER_REQUIRED.value,
        expected_status=409,
    )

    # Clear the higher rung without touching anything else about the request.
    signed = validate_success(
        api.sign_waiver(
            candidate["id"],
            f.waiver_payload(),
            users.participant_headers(candidate["id"]),
        )
    )
    assert signed["waiver_signed"] is True, signed
    assert signed["clearance_status"] == CLEARANCE_CLEARED, signed

    # The identical request now falls through to rung 31.
    validate_error(
        api.create_entry(
            heat_id, f.entry_payload(candidate["id"], 202), users.OPS
        ),
        ApiErrorId.ERR_WAVE_CAPACITY_EXCEEDED.value,
        expected_status=409,
    )

    # Neither refusal enrolled anybody.
    after = fx.read_wave(api, heat_id)
    assert after["assigned_count"] == 1, after


def test_the_waiver_rung_also_outranks_the_age_rung_between_it_and_capacity(api):
    """PRD §2.6: "When a single request violates more than one rule, the response is decided by the *first* violated rule in the following fixed ladder, evaluated from the top."

    Design: Difficulty/priority_pair_validation_conflict/unsigned_waiver_outranks_the_full_roster_on_the_same_registration
    """
    world = _full_single_slot_heat(api, capacity=1)
    heat_id = world["heat"]["id"]

    # An unsigned eleven-year-old on a full heat violates three rungs at once:
    # the waiver (13), the calendar-year age gate (26) and the roster (31).
    child = fx.participant(api, birth_year=2015)
    validate_error(
        api.create_entry(heat_id, f.entry_payload(child["id"], 203), users.OPS),
        ApiErrorId.ERR_WAIVER_REQUIRED.value,
        expected_status=409,
    )

    validate_success(
        api.sign_waiver(
            child["id"], f.waiver_payload(), users.participant_headers(child["id"])
        )
    )

    # 2026 minus 2015 is 11, short of the division's min_age of 18, and the age
    # rung sits above the roster rung.
    validate_error(
        api.create_entry(heat_id, f.entry_payload(child["id"], 203), users.OPS),
        ApiErrorId.ERR_AGE_INELIGIBLE.value,
        expected_status=409,
    )
    assert fx.read_wave(api, heat_id)["assigned_count"] == 1


def test_the_roster_capacity_rung_admits_the_exact_equality_and_refuses_one_more(api):
    """PRD §3.5: "Finally the heat must have room: the heat's `assigned_count` plus one must be at most its `capacity`, or the registration is refused with `ERR_WAVE_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/unsigned_waiver_outranks_the_full_roster_on_the_same_registration
    """
    world = _full_single_slot_heat(api, capacity=2)
    heat_id = world["heat"]["id"]

    # floor(720 * 15 / 60) is 180 on this single-station course, so the §3.4
    # design ceiling is nowhere near the two-slot roster under test.
    assert_course_capacities(
        fx.read_course(api, world["course"]["id"]),
        design_capacity_pph=_SINGLE_STATION_DESIGN_PPH,
    )

    # 1 + 1 is at most 2, so the second registration is accepted.
    second = fx.cleared_participant(api)
    accepted = validate_success(
        api.create_entry(heat_id, f.entry_payload(second["id"], 202), users.OPS),
        expected_status=201,
    )
    assert accepted["bib_number"] == 202, accepted
    assert fx.read_wave(api, heat_id)["assigned_count"] == 2

    # 2 + 1 is not.
    third = fx.cleared_participant(api)
    validate_error(
        api.create_entry(heat_id, f.entry_payload(third["id"], 203), users.OPS),
        ApiErrorId.ERR_WAVE_CAPACITY_EXCEEDED.value,
        expected_status=409,
    )
    assert fx.read_wave(api, heat_id)["assigned_count"] == 2
