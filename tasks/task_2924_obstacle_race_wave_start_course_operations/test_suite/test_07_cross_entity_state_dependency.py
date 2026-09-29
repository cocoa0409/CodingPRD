"""Cross-entity state dependencies: the defect lives on a neighbour, not on the row.

Two dependencies are exercised here. The first runs two levels up the hierarchy:
a heat that is release-ready in every one of its own properties is still refused
because its parent course has not been published. The second runs sideways: a
participant's clearance state decides an entry's fate at check-in and again at
the gun.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_course_capacities,
    assert_entry_state,
    assert_instant_equals,
    assert_wave_state,
)
from test_helpers.constants import (
    BYPASS_MODE_MANDATORY,
    BYPASS_MODE_NONE,
    BYPASS_MODE_TIMED_PENALTY,
    BYPASS_POLICY_DQ_ON_BYPASS,
    CLEARANCE_MEDICALLY_HELD,
    COURSE_PUBLISHED,
    COURSE_VALIDATED,
    DIVISION_COMPETITIVE,
    MEDICAL_FLAG_CARDIAC,
    PROGRESS_CHECKED_IN,
    PROGRESS_DNS,
    PROGRESS_REGISTERED,
    PROGRESS_STARTED,
    READINESS_OPEN,
    RELEASE_HELD,
    RELEASE_RELEASED,
    RELEASE_SCHEDULED,
    RELEASE_STARTED,
    RESULT_NOT_CLASSIFIED,
    ROSTER_LOCKED,
    ROSTER_OPEN,
    ROSTER_SEALED,
    SCORING_CHIP_TIME,
    STAFF_MEDIC_1,
    STAFF_SWIMMER_1,
    STAFF_SWIMMER_2,
)

# ─── The canonical race-day world of this design slice ───────────────────

#: The planned gun instant of heat A1.
_GUN_UTC = "2026-09-12T08:00:00.000Z"

#: The mat crossing of the one checked-in runner: the gun plus 37 seconds.
_CHIP_START_UTC = "2026-09-12T08:00:37.000Z"

#: A single heat of 112, which is exactly the ceiling both the design gate
#: (design_capacity_pph 450) and the live gate (bottleneck_capacity_pph 450)
#: allow on a 15-minute grid.
_WAVE_CAPACITY = 112

_COURSE_KWARGS = {
    "name": "Quarry Gauntlet",
    "total_distance_m": 10000,
    "corral_release_rate_per_min": 12.00,
    "corral_throughput_capacity": 200,
}

#: Three ascending primary stations. The wet middle station is the bottleneck at
#: 3 lanes x 2.50 = 7.50 clearances per minute, so both course capacities read
#: 7.50 * 60 = 450 participants per hour once it is fully marshaled.
_STATIONS = [
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


def _staffed_world(api, publish: bool = False) -> dict:
    """A parcel, a governing permit, and one fully staffed three-station course
    carrying one empty heat A1 of capacity 112.

    Every staffing minimum is met: 2 + 2 + 1 marshals, two lifeguards on the wet
    station and one medic, so `readiness_posture` reads `OPEN`. The course is
    left `VALIDATED` unless `publish` is set — that one property is the only
    thing the caller varies.
    """
    parcel, permit = fx.permitted_venue(api)
    laid, stations = fx.three_station_course(
        api,
        parcel["id"],
        course_kwargs=_COURSE_KWARGS,
        station_kwargs=_STATIONS,
    )
    course = (
        fx.published_course(api, laid["id"])
        if publish
        else fx.validated_course(api, laid["id"])
    )
    for station in stations:
        fx.fully_marshal(api, course["id"], station)
    fx.water_safety_shift(
        api, course["id"], stations[1]["id"], staff_person_id=STAFF_SWIMMER_1
    )
    fx.water_safety_shift(
        api, course["id"], stations[1]["id"], staff_person_id=STAFF_SWIMMER_2
    )
    fx.medic_shift(api, course["id"], staff_person_id=STAFF_MEDIC_1)
    division = fx.division(
        api,
        name="Elite Competitive",
        division_type=DIVISION_COMPETITIVE,
        bypass_policy=BYPASS_POLICY_DQ_ON_BYPASS,
        scoring_mode=SCORING_CHIP_TIME,
        min_age=18,
    )
    heat = fx.wave(
        api,
        course["id"],
        division["id"],
        wave_code="A1",
        scheduled_start_utc=_GUN_UTC,
        capacity=_WAVE_CAPACITY,
    )
    return {
        "venue": parcel,
        "permit": permit,
        "course": course,
        "stations": stations,
        "division": division,
        "wave": heat,
    }


# ─── The publication state two levels up ─────────────────────────────────


def test_release_is_refused_while_the_parent_course_is_only_validated(api):
    """PRD §3.6: "The course's `status` must be `PUBLISHED`, or the release is refused with `ERR_COURSE_NOT_PUBLISHED`."

    Design: Difficulty/cross_entity_state_dependency/wave_release_blocked_by_the_courses_publication_state_two_levels_up
    """
    world = _staffed_world(api)
    heat = world["wave"]
    entry = fx.checked_in_entry(
        api, heat["id"], bib_number=101, chip_start_offset_seconds=37
    )
    assert_entry_state(entry, progress_status=PROGRESS_CHECKED_IN)
    locked = fx.lock_roster(api, heat["id"])
    assert_wave_state(
        locked, release_status=RELEASE_SCHEDULED, roster_status=ROSTER_LOCKED
    )

    # Every property of the heat itself is release-ready, and the course clears
    # the readiness, medical and live-capacity gates. Only publication is missing.
    course = fx.read_course(api, world["course"]["id"])
    assert_course_capacities(
        course,
        status=COURSE_VALIDATED,
        readiness_posture=READINESS_OPEN,
        design_capacity_pph=450,
        bottleneck_capacity_pph=450,
        scheduled_capacity_total=_WAVE_CAPACITY,
    )
    assert course["medic_headcount"] == 1
    assert course["water_safety_headcount"] == 2

    refused = api.release_wave(heat["id"], users.DIRECTOR)
    validate_error(
        refused, ApiErrorId.ERR_COURSE_NOT_PUBLISHED.value, expected_status=409
    )

    unmoved = fx.read_wave(api, heat["id"])
    assert_wave_state(
        unmoved, release_status=RELEASE_SCHEDULED, roster_status=ROSTER_LOCKED
    )
    assert unmoved["actual_start_utc"] is None


def test_publishing_the_parent_lets_the_identical_release_succeed(api):
    """PRD §3.2: "Publication is the `RaceDirector`'s move and advances `VALIDATED → PUBLISHED`, which is the state a course must be in before any of its heats can be released."

    Design: Difficulty/cross_entity_state_dependency/wave_release_blocked_by_the_courses_publication_state_two_levels_up
    """
    world = _staffed_world(api)
    heat = world["wave"]
    fx.checked_in_entry(api, heat["id"], bib_number=101, chip_start_offset_seconds=37)
    fx.lock_roster(api, heat["id"])

    first = api.release_wave(heat["id"], users.DIRECTOR)
    validate_error(
        first, ApiErrorId.ERR_COURSE_NOT_PUBLISHED.value, expected_status=409
    )

    published = validate_success(
        api.publish_course(world["course"]["id"], users.DIRECTOR)
    )
    assert_course_capacities(
        published, status=COURSE_PUBLISHED, readiness_posture=READINESS_OPEN
    )

    released = validate_success(api.release_wave(heat["id"], users.DIRECTOR))
    # The release dimension advances on its own; the roster dimension is
    # untouched by it and still reads LOCKED.
    assert_wave_state(
        released, release_status=RELEASE_RELEASED, roster_status=ROSTER_LOCKED
    )
    reread = fx.read_wave(api, heat["id"])
    assert_wave_state(
        reread, release_status=RELEASE_RELEASED, roster_status=ROSTER_LOCKED
    )


def test_a_held_heat_on_an_unpublished_course_reports_the_state_rung(api):
    """PRD §2.6: "A heat that is `HELD` rather than `SCHEDULED`, on an unpublished course, with an empty roster, reports `ERR_WAVE_NOT_RELEASABLE` — the state rung sits above the cross-entity and capacity rungs."

    Design: Difficulty/cross_entity_state_dependency/wave_release_blocked_by_the_courses_publication_state_two_levels_up
    """
    world = _staffed_world(api)
    heat = world["wave"]
    held = fx.hold(api, heat["id"], reason="Weather cell overhead")
    assert_wave_state(held, release_status=RELEASE_HELD, roster_status=ROSTER_OPEN)
    assert held["assigned_count"] == 0

    refused = api.release_wave(heat["id"], users.DIRECTOR)
    validate_error(
        refused, ApiErrorId.ERR_WAVE_NOT_RELEASABLE.value, expected_status=409
    )

    course = fx.read_course(api, world["course"]["id"])
    assert_course_capacities(course, status=COURSE_VALIDATED)
    unmoved = fx.read_wave(api, heat["id"])
    assert_wave_state(unmoved, release_status=RELEASE_HELD, roster_status=ROSTER_OPEN)


# ─── The clearance state sideways ────────────────────────────────────────


def test_a_medically_held_runner_registers_but_is_refused_at_check_in(api):
    """PRD §3.5: "The participant's `clearance_status` must read `CLEARED` — a `PENDING` or `MEDICALLY_HELD` human is refused with `ERR_PARTICIPANT_NOT_CLEARED`."

    Design: Difficulty/cross_entity_state_dependency/entry_fate_at_the_gun_is_decided_by_the_participants_clearance_state
    """
    world = _staffed_world(api, publish=True)
    heat = world["wave"]

    held = fx.held_participant(
        api,
        [MEDICAL_FLAG_CARDIAC],
        full_name="Bo Stone",
        birth_year=2000,
        email="bo@example.com",
        chip_id="CHIP-002",
    )
    # The waiver IS signed, so the priority-13 rung is satisfied; only the
    # clearance dimension went the other way.
    assert held["waiver_signed"] is True
    assert held["clearance_status"] == CLEARANCE_MEDICALLY_HELD

    registered = fx.entry(api, heat["id"], held["id"], bib_number=102)
    assert_entry_state(registered, progress_status=PROGRESS_REGISTERED)

    refused = api.check_in_entry(
        registered["id"],
        f.check_in_payload(12, bag_tag_code="BAG-102"),
        users.OPS,
    )
    validate_error(
        refused, ApiErrorId.ERR_PARTICIPANT_NOT_CLEARED.value, expected_status=409
    )

    unmoved = fx.read_entry(api, registered["id"])
    assert_entry_state(unmoved, progress_status=PROGRESS_REGISTERED)
    assert unmoved["bag_tag_code"] is None
    assert unmoved["chip_start_offset_seconds"] == 0


def test_registration_without_any_waiver_is_refused_a_rung_earlier(api):
    """PRD §3.5: "The participant must have signed the waiver, or the registration is refused with `ERR_WAIVER_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/entry_fate_at_the_gun_is_decided_by_the_participants_clearance_state
    """
    world = _staffed_world(api, publish=True)
    heat = world["wave"]

    unsigned = fx.participant(
        api,
        full_name="Cy Fern",
        birth_year=2000,
        email="cy@example.com",
        chip_id="CHIP-003",
    )
    refused = api.create_entry(
        heat["id"], f.entry_payload(unsigned["id"], 103), users.OPS
    )
    validate_error(refused, ApiErrorId.ERR_WAIVER_REQUIRED.value, expected_status=409)

    # A medically held human clears this same rung, because signing always sets
    # waiver_signed to true whichever way the clearance dimension resolves.
    held = fx.held_participant(
        api,
        [MEDICAL_FLAG_CARDIAC],
        full_name="Bo Stone",
        birth_year=2000,
        email="bo@example.com",
        chip_id="CHIP-002",
    )
    accepted = fx.entry(api, heat["id"], held["id"], bib_number=102)
    assert_entry_state(accepted, progress_status=PROGRESS_REGISTERED)
    assert fx.read_wave(api, heat["id"])["assigned_count"] == 1


def test_the_gun_sorts_the_roster_by_each_entrys_own_progress_status(api):
    """PRD §3.6: "And it advances every entry still reading `REGISTERED` — those who never showed at bag check — to `DNS`, setting their `result_status` to `NOT_CLASSIFIED`."

    Design: Difficulty/cross_entity_state_dependency/entry_fate_at_the_gun_is_decided_by_the_participants_clearance_state
    """
    world = _staffed_world(api, publish=True)
    heat = world["wave"]

    cleared = fx.cleared_participant(
        api,
        full_name="Ada Rock",
        birth_year=2000,
        email="ada@example.com",
        chip_id="CHIP-001",
    )
    runner = fx.entry(api, heat["id"], cleared["id"], bib_number=101)
    runner = fx.check_in(api, runner["id"], 37, bag_tag_code="BAG-101")
    assert_entry_state(runner, progress_status=PROGRESS_CHECKED_IN)

    held = fx.held_participant(
        api,
        [MEDICAL_FLAG_CARDIAC],
        full_name="Bo Stone",
        birth_year=2000,
        email="bo@example.com",
        chip_id="CHIP-002",
    )
    absentee = fx.entry(api, heat["id"], held["id"], bib_number=102)
    validate_error(
        api.check_in_entry(absentee["id"], f.check_in_payload(12), users.OPS),
        ApiErrorId.ERR_PARTICIPANT_NOT_CLEARED.value,
        expected_status=409,
    )

    fx.lock_roster(api, heat["id"])
    fx.release(api, heat["id"])
    fx.set_clock(api, _GUN_UTC)
    started = fx.start(api, heat["id"])

    assert_wave_state(
        started, release_status=RELEASE_STARTED, roster_status=ROSTER_SEALED
    )
    assert_instant_equals(started["actual_start_utc"], _GUN_UTC, "actual_start_utc")
    # The non-starter is not removed from the roster.
    assert started["assigned_count"] == 2

    ran = fx.read_entry(api, runner["id"])
    assert_entry_state(ran, progress_status=PROGRESS_STARTED)
    assert_instant_equals(ran["chip_start_utc"], _CHIP_START_UTC, "chip_start_utc")

    missed = fx.read_entry(api, absentee["id"])
    assert_entry_state(
        missed,
        progress_status=PROGRESS_DNS,
        result_status=RESULT_NOT_CLASSIFIED,
    )
    assert missed["chip_start_utc"] is None
