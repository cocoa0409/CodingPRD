"""Both interval rules probed one unit either side of their exact edge.

Every test in this module translates exactly one instance of the
`boundary_precision_check` rule of the difficulty design index. The two
geometries are deliberately opposite: the corral budget is an aggregate,
half-open, same-course interval, while the staff travel buffer is a pairwise,
closed, buffer-inflated interval evaluated across every course in the system.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_course_capacities,
    assert_instant_equals,
    assert_wave_state,
)
from test_helpers.constants import (
    ASSIGNMENT_CONFIRMED,
    ASSIGNMENT_VACATED,
    BYPASS_MODE_MANDATORY,
    BYPASS_MODE_NONE,
    BYPASS_MODE_TIMED_PENALTY,
    BYPASS_POLICY_DQ_ON_BYPASS,
    CERT_PARAMEDIC,
    DIVISION_COMPETITIVE,
    RELEASE_SCHEDULED,
    SCORING_CHIP_TIME,
    STAFF_MEDIC_1,
    STAFF_MEDIC_2,
    STAFF_ROLE_MEDIC,
)

# ─── The corral grid (PRD §3.4) ──────────────────────────────────────────

_A1_START_UTC = "2026-09-12T08:00:00.000Z"
#: Inside A1's half-open window [08:00:00, 08:06:00).
_INSIDE_START_UTC = "2026-09-12T08:04:00.000Z"
_ALSO_INSIDE_START_UTC = "2026-09-12T08:05:00.000Z"
#: One second before the window closes, so still overlapping.
_ONE_SECOND_INSIDE_START_UTC = "2026-09-12T08:05:59.000Z"
#: Exactly CORRAL_OCCUPANCY_MINUTES after A1's start, so free of A1.
_EXACTLY_ADJACENT_START_UTC = "2026-09-12T08:06:00.000Z"

_CORRAL_THROUGHPUT_CAPACITY = 200
#: floor(min(12.00, 7.50, 12.00) * 60) on the three canonical stations.
_DESIGN_CAPACITY_PPH = 450
#: floor(450 * 15 / 60), the §3.4 design ceiling every heat below respects.
_HEAT_CEILING = 112
#: 112 + 88 == 200 exactly.
_EQUALITY_CAPACITY = 88
#: 112 + 100 == 212, one step over the budget.
_OVERSHOOT_CAPACITY = 100

_COURSE_KWARGS = {
    "name": "Quarry Gauntlet",
    "total_distance_m": 10000,
    "corral_release_rate_per_min": 12.00,
    "corral_throughput_capacity": _CORRAL_THROUGHPUT_CAPACITY,
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


# ─── The staffing grid (PRD §3.3) ────────────────────────────────────────

_PEER_SHIFT_START_UTC = "2026-09-12T06:00:00.000Z"
_PEER_SHIFT_END_UTC = "2026-09-12T11:00:00.000Z"
#: Five minutes inside the 15-minute travel buffer that trails the peer.
_INSIDE_BUFFER_START_UTC = "2026-09-12T11:10:00.000Z"
#: One second inside it.
_ONE_SECOND_INSIDE_BUFFER_START_UTC = "2026-09-12T11:14:59.000Z"
#: Exactly STAFF_TRAVEL_BUFFER_MINUTES after the peer's end.
_EXACT_BUFFER_START_UTC = "2026-09-12T11:15:00.000Z"
_LATE_SHIFT_END_UTC = "2026-09-12T15:00:00.000Z"

#: A shift ending exactly 15 minutes before the peer's start clears it.
_EARLY_SHIFT_START_UTC = "2026-09-12T02:00:00.000Z"
_EARLY_SHIFT_END_UTC = "2026-09-12T05:45:00.000Z"
#: One second later, and the mirrored comparison bites.
_EARLY_SHIFT_END_ONE_SECOND_LATE_UTC = "2026-09-12T05:45:01.000Z"

_PEER_COURSE_KWARGS = _COURSE_KWARGS
_CANDIDATE_COURSE_KWARGS = {
    "name": "Quarry Sprint",
    "total_distance_m": 5000,
    "corral_release_rate_per_min": 10.00,
    "corral_throughput_capacity": 150,
}


def _corral_grid(api) -> dict:
    """A DRAFT three-station course carrying one 112-strong heat at 08:00.

    No `LandUsePermit` exists on the parcel, so the priority-19 quiet-hours
    rule is skipped entirely and only the corral rule can bind.
    """
    venue = fx.venue(api)
    course, stations = fx.three_station_course(
        api,
        venue["id"],
        course_kwargs=_COURSE_KWARGS,
        station_kwargs=_STATION_KWARGS,
    )
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
    first_heat = fx.wave(
        api,
        course["id"],
        division["id"],
        wave_code="A1",
        scheduled_start_utc=_A1_START_UTC,
        capacity=_HEAT_CEILING,
    )
    return {
        "venue": venue,
        "course": course,
        "stations": stations,
        "division": division,
        "heat": first_heat,
    }


def _schedule_heat(api, course_id: str, division_id: str, code: str, start: str, capacity: int):
    """POST one heat and hand back the raw response, refusal and all."""
    return api.create_wave(
        course_id,
        f.wave_payload(division_id, wave_code=code, scheduled_start_utc=start, capacity=capacity),
        users.DIRECTOR,
    )


def _two_course_venue(api) -> dict:
    """One parcel carrying a peer course and a candidate course.

    `STAFF_MEDIC_1` holds one `CONFIRMED` `MEDIC` shift on the peer course from
    06:00 to 11:00. A medic shift names no `obstacle_id`, so the priority-16
    division-shape rule is satisfied and only the travel buffer can bind.
    """
    venue = fx.venue(api)
    peer_course = fx.course(api, venue["id"], **_PEER_COURSE_KWARGS)
    candidate_course = fx.course(api, venue["id"], **_CANDIDATE_COURSE_KWARGS)
    peer_shift = fx.medic_shift(
        api,
        peer_course["id"],
        STAFF_MEDIC_1,
        shift_start_utc=_PEER_SHIFT_START_UTC,
        shift_end_utc=_PEER_SHIFT_END_UTC,
    )
    assert peer_shift["status"] == ASSIGNMENT_CONFIRMED, peer_shift
    return {
        "venue": venue,
        "peer_course": peer_course,
        "candidate_course": candidate_course,
        "peer_shift": peer_shift,
    }


def _post_medic_shift(
    api,
    course_id: str,
    shift_start_utc: str,
    shift_end_utc: str,
    staff_person_id: str = STAFF_MEDIC_1,
):
    """POST one medic shift and hand back the raw response, refusal and all."""
    return api.create_staff_assignment(
        course_id,
        f.staff_payload(
            STAFF_ROLE_MEDIC,
            None,
            staff_person_id=staff_person_id,
            certification_level=CERT_PARAMEDIC,
            shift_start_utc=shift_start_utc,
            shift_end_utc=shift_end_utc,
        ),
        users.SAFETY,
    )


# ─── boundary_precision_check / the corral occupancy budget ──────────────


def test_corral_occupancy_exact_adjacency_is_free_and_the_equality_sum_passes(api):
    """PRD §3.4: "Sum the `capacity` of the overlapping peers, add the candidate's own `capacity`, and require that total to be at most the course's `corral_throughput_capacity`; exceeding it is refused with `ERR_CORRAL_WINDOW_CONFLICT`."

    Design: Difficulty/boundary_precision_check/corral_occupancy_exact_adjacency_is_free_and_the_equality_sum_passes
    """
    grid = _corral_grid(api)
    course_id = grid["course"]["id"]
    division_id = grid["division"]["id"]

    assert_course_capacities(
        fx.read_course(api, course_id),
        design_capacity_pph=_DESIGN_CAPACITY_PPH,
    )

    # 112 + 100 == 212, one step past the 200 budget.
    validate_error(
        _schedule_heat(
            api, course_id, division_id, "A9", _INSIDE_START_UTC, _OVERSHOOT_CAPACITY
        ),
        ApiErrorId.ERR_CORRAL_WINDOW_CONFLICT.value,
        expected_status=409,
    )

    # 112 + 88 == 200, and equality is admitted.
    equal = validate_success(
        _schedule_heat(
            api,
            course_id,
            division_id,
            "A2",
            _ALSO_INSIDE_START_UTC,
            _EQUALITY_CAPACITY,
        ),
        expected_status=201,
    )
    assert equal["capacity"] == _EQUALITY_CAPACITY, equal

    # Exactly 6 minutes after A1's start, A1 has vacated the corral, so the sum
    # is 88 + 100 == 188 rather than the 300 a closed-interval test would find.
    adjacent = validate_success(
        _schedule_heat(
            api,
            course_id,
            division_id,
            "A3",
            _EXACTLY_ADJACENT_START_UTC,
            _OVERSHOOT_CAPACITY,
        ),
        expected_status=201,
    )
    assert adjacent["capacity"] == _OVERSHOOT_CAPACITY, adjacent

    # The refused call left no heat behind and the incumbent is untouched.
    assert_wave_state(fx.read_wave(api, grid["heat"]["id"]), release_status=RELEASE_SCHEDULED)
    assert fx.read_wave(api, grid["heat"]["id"])["capacity"] == _HEAT_CEILING


def test_a_heat_exactly_six_minutes_out_ignores_a_peer_it_could_not_fit_beside(api):
    """PRD §3.4: "Two half-open windows overlap when the peer's start falls strictly before the candidate's end and the candidate's start falls strictly before the peer's end; windows that merely touch at an endpoint do not overlap, so a heat scheduled exactly 6 minutes after a peer is always free of it."

    Design: Difficulty/boundary_precision_check/corral_occupancy_exact_adjacency_is_free_and_the_equality_sum_passes
    """
    grid = _corral_grid(api)

    # 112 + 112 == 224 would be a refusal if the two windows touched, and the
    # candidate sits exactly on the endpoint they share.
    accepted = validate_success(
        _schedule_heat(
            api,
            grid["course"]["id"],
            grid["division"]["id"],
            "B1",
            _EXACTLY_ADJACENT_START_UTC,
            _HEAT_CEILING,
        ),
        expected_status=201,
    )
    assert accepted["capacity"] == _HEAT_CEILING, accepted
    assert_instant_equals(
        accepted["scheduled_start_utc"],
        _EXACTLY_ADJACENT_START_UTC,
        "scheduled_start_utc",
    )
    assert accepted["assigned_count"] == 0, accepted

    # Both heats now count toward the course's scheduled capacity, which proves
    # they really do share the course rather than dodging the rule some other way.
    assert_course_capacities(
        fx.read_course(api, grid["course"]["id"]),
        scheduled_capacity_total=_HEAT_CEILING * 2,
    )


def test_a_heat_one_second_short_of_the_adjacency_still_overlaps_the_peer(api):
    """PRD §3.4: "Each heat occupies the corral for a half-open window of 6 minutes beginning at its `scheduled_start_utc` and ending just before the instant 6 minutes later."

    Design: Difficulty/boundary_precision_check/corral_occupancy_exact_adjacency_is_free_and_the_equality_sum_passes
    """
    grid = _corral_grid(api)

    # 08:05:59 falls strictly before A1's window closes at 08:06:00, so the sum
    # is 112 + 112 == 224 and the budget of 200 is exceeded.
    validate_error(
        _schedule_heat(
            api,
            grid["course"]["id"],
            grid["division"]["id"],
            "B2",
            _ONE_SECOND_INSIDE_START_UTC,
            _HEAT_CEILING,
        ),
        ApiErrorId.ERR_CORRAL_WINDOW_CONFLICT.value,
        expected_status=409,
    )

    # The refusal changed nothing: only A1 is on the grid.
    assert_course_capacities(
        fx.read_course(api, grid["course"]["id"]),
        scheduled_capacity_total=_HEAT_CEILING,
    )


# ─── boundary_precision_check / the staff travel buffer ──────────────────


def test_staff_travel_buffer_accepts_an_exact_fifteen_minute_gap_and_rejects_one_second_less(api):
    """PRD §3.3: "The boundary is exact: a shift beginning exactly 15 minutes after a peer's shift ends is accepted, and one beginning one second earlier than that is rejected."

    Design: Difficulty/boundary_precision_check/staff_travel_buffer_accepts_an_exact_fifteen_minute_gap_and_rejects_one_second_less
    """
    world = _two_course_venue(api)
    candidate_course_id = world["candidate_course"]["id"]

    # Five minutes short of the buffer.
    validate_error(
        _post_medic_shift(
            api, candidate_course_id, _INSIDE_BUFFER_START_UTC, _LATE_SHIFT_END_UTC
        ),
        ApiErrorId.ERR_STAFF_SHIFT_CONFLICT.value,
        expected_status=409,
    )

    # One second short of it: instants are compared at second resolution.
    validate_error(
        _post_medic_shift(
            api,
            candidate_course_id,
            _ONE_SECOND_INSIDE_BUFFER_START_UTC,
            _LATE_SHIFT_END_UTC,
        ),
        ApiErrorId.ERR_STAFF_SHIFT_CONFLICT.value,
        expected_status=409,
    )

    # Exactly on it, and the comparison being strict admits the shift.
    accepted = validate_success(
        _post_medic_shift(
            api, candidate_course_id, _EXACT_BUFFER_START_UTC, _LATE_SHIFT_END_UTC
        ),
        expected_status=201,
    )
    assert accepted["status"] == ASSIGNMENT_CONFIRMED, accepted
    assert accepted["course_id"] == candidate_course_id, accepted
    assert_instant_equals(
        accepted["shift_start_utc"], _EXACT_BUFFER_START_UTC, "shift_start_utc"
    )

    # The peer is untouched and each course counts its own medic.
    peer = validate_success(
        api.get_staff_assignment(world["peer_shift"]["id"], users.SAFETY)
    )
    assert peer["status"] == ASSIGNMENT_CONFIRMED, peer
    assert fx.read_course(api, world["peer_course"]["id"])["medic_headcount"] == 1
    assert fx.read_course(api, candidate_course_id)["medic_headcount"] == 1


def test_the_travel_buffer_is_mirrored_on_the_side_before_the_peer(api):
    """PRD §3.3: "A collision exists with such a peer when both of the following hold: the candidate's `shift_start_utc` falls strictly before the peer's `shift_end_utc` advanced by 15 minutes, and the peer's `shift_start_utc` falls strictly before the candidate's `shift_end_utc` advanced by 15 minutes."

    Design: Difficulty/boundary_precision_check/staff_travel_buffer_accepts_an_exact_fifteen_minute_gap_and_rejects_one_second_less
    """
    world = _two_course_venue(api)
    candidate_course_id = world["candidate_course"]["id"]

    # A shift ending at 05:45:01 puts the peer's 06:00:00 start strictly before
    # 06:00:01, so the second half of the conjunction holds and both do.
    validate_error(
        _post_medic_shift(
            api,
            candidate_course_id,
            _EARLY_SHIFT_START_UTC,
            _EARLY_SHIFT_END_ONE_SECOND_LATE_UTC,
        ),
        ApiErrorId.ERR_STAFF_SHIFT_CONFLICT.value,
        expected_status=409,
    )

    # One second earlier the inflated end lands exactly on the peer's start, and
    # equality is not a strict precedence.
    accepted = validate_success(
        _post_medic_shift(
            api, candidate_course_id, _EARLY_SHIFT_START_UTC, _EARLY_SHIFT_END_UTC
        ),
        expected_status=201,
    )
    assert accepted["status"] == ASSIGNMENT_CONFIRMED, accepted
    assert_instant_equals(
        accepted["shift_end_utc"], _EARLY_SHIFT_END_UTC, "shift_end_utc"
    )
    assert fx.read_course(api, candidate_course_id)["medic_headcount"] == 1


def test_the_buffer_is_keyed_on_the_person_and_ignores_vacated_peers(api):
    """PRD §3.3: "Gather every shift already reading `CONFIRMED` for the same `staff_person_id`, across every course and every obstacle in the system — shifts reading `VACATED` are ignored entirely, which is precisely what makes a vacated slot immediately re-bookable."

    Design: Difficulty/boundary_precision_check/staff_travel_buffer_accepts_an_exact_fifteen_minute_gap_and_rejects_one_second_less
    """
    world = _two_course_venue(api)
    candidate_course_id = world["candidate_course"]["id"]

    # A different human may stand in the same buffered interval.
    other_person = validate_success(
        _post_medic_shift(
            api,
            candidate_course_id,
            _INSIDE_BUFFER_START_UTC,
            _LATE_SHIFT_END_UTC,
            staff_person_id=STAFF_MEDIC_2,
        ),
        expected_status=201,
    )
    assert other_person["staff_person_id"] == STAFF_MEDIC_2, other_person

    # The same human still may not, which proves the interval is genuinely live.
    validate_error(
        _post_medic_shift(
            api, candidate_course_id, _INSIDE_BUFFER_START_UTC, _LATE_SHIFT_END_UTC
        ),
        ApiErrorId.ERR_STAFF_SHIFT_CONFLICT.value,
        expected_status=409,
    )

    vacated = fx.vacate(api, world["peer_shift"]["id"], reason="Called to the pond")
    assert vacated["status"] == ASSIGNMENT_VACATED, vacated
    assert fx.read_course(api, world["peer_course"]["id"])["medic_headcount"] == 0

    # The slot is immediately re-bookable by the very person who left it.
    rebooked = validate_success(
        _post_medic_shift(
            api, candidate_course_id, _INSIDE_BUFFER_START_UTC, _LATE_SHIFT_END_UTC
        ),
        expected_status=201,
    )
    assert rebooked["status"] == ASSIGNMENT_CONFIRMED, rebooked
    assert rebooked["staff_person_id"] == STAFF_MEDIC_1, rebooked
    assert fx.read_course(api, candidate_course_id)["medic_headcount"] == 2
