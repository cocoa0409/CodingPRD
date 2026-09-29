"""Two contended resources with opposite overlap semantics.

A human being is a pairwise resource: one travel-buffered collision anywhere in
the system is fatal, headcount is irrelevant, and releasing the person is what
frees the slot. A start corral is an aggregate resource: many heats share one
6-minute window so long as their summed capacity fits the budget, and the window
rolls forward as the oldest heat leaves it.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_course_capacities,
    assert_instant_equals,
    assert_obstacle_staffing,
    assert_wave_state,
)
from test_helpers.constants import (
    ASSIGNMENT_CONFIRMED,
    ASSIGNMENT_VACATED,
    BYPASS_MODE_MANDATORY,
    BYPASS_MODE_NONE,
    BYPASS_MODE_TIMED_PENALTY,
    BYPASS_POLICY_ALLOWED_WITH_PENALTY,
    CERT_BASIC,
    DIVISION_OPEN,
    RELEASE_SCHEDULED,
    SCORING_GUN_TIME,
    STAFF_PERSON_1,
    STAFF_PERSON_2,
    STAFF_ROLE_MARSHAL,
    STAFFING_MARSHALED,
    STAFFING_UNSTAFFED,
)

# ─── The contended human ─────────────────────────────────────────────────

#: The one person rostered onto both courses of the same parcel.
_SHARED_PERSON = STAFF_PERSON_1

#: A second, distinct human used to prove the resource is the person.
_OTHER_PERSON = STAFF_PERSON_2

#: The peer shift on course C1 — a six-hour block.
_PEER_SHIFT_START = "2026-09-12T06:00:00.000Z"
_PEER_SHIFT_END = "2026-09-12T12:00:00.000Z"

#: The candidate shift on course C2, strictly contained inside the peer window
#: rather than merely touching it.
_CANDIDATE_SHIFT_START = "2026-09-12T08:00:00.000Z"
_CANDIDATE_SHIFT_END = "2026-09-12T10:00:00.000Z"


def _marshal_payload(obstacle_id: str, staff_person_id: str, start: str, end: str):
    """One MARSHAL shift payload with an explicit window."""
    return f.staff_payload(
        STAFF_ROLE_MARSHAL,
        obstacle_id,
        staff_person_id=staff_person_id,
        certification_level=CERT_BASIC,
        shift_start_utc=start,
        shift_end_utc=end,
    )


def _two_courses_one_parcel(api):
    """One parcel carrying two independent DRAFT courses, each with a single
    primary station needing exactly one marshal.

    C1's station clears 4 lanes x 3.00 = 12.00 per minute (its corral rate is
    also 12.00, so nothing is clipped) and C2's clears 2 lanes x 4.00 = 8.00.
    Returns (parcel, course_c1, station_x1, course_c2, station_y1).
    """
    parcel = fx.venue(api)
    course_c1 = fx.course(
        api,
        parcel["id"],
        name="Quarry Gauntlet",
        total_distance_m=10000,
        corral_release_rate_per_min=12.00,
        corral_throughput_capacity=200,
    )
    station_x1 = fx.obstacle(
        api,
        course_c1["id"],
        1,
        name="Cargo Net",
        difficulty_rating=3,
        lane_count=4,
        service_rate_per_min=3.00,
        marshals_required=1,
        footprint_sqm=1200,
        water_contact=False,
        bypass_mode=BYPASS_MODE_NONE,
        penalty_seconds=0,
    )
    course_c2 = fx.course(
        api,
        parcel["id"],
        name="Quarry Sprint",
        total_distance_m=5000,
        corral_release_rate_per_min=10.00,
        corral_throughput_capacity=150,
    )
    station_y1 = fx.obstacle(
        api,
        course_c2["id"],
        1,
        name="Tyre Drag",
        difficulty_rating=4,
        lane_count=2,
        service_rate_per_min=4.00,
        marshals_required=1,
        footprint_sqm=400,
        water_contact=False,
        bypass_mode=BYPASS_MODE_NONE,
        penalty_seconds=0,
    )
    return parcel, course_c1, station_x1, course_c2, station_y1


# ─── One person, two courses ─────────────────────────────────────────────


def test_a_marshal_collides_with_a_peer_shift_on_a_different_course(api):
    """PRD §3.3: "A single collision with a single peer is fatal and yields `ERR_STAFF_SHIFT_CONFLICT`; there is no notion of aggregate capacity here."

    Design: Difficulty/resource_temporal_overlap/one_marshal_cannot_hold_overlapping_shifts_on_two_courses_until_the_first_is_vacated
    """
    parcel, course_c1, station_x1, course_c2, station_y1 = _two_courses_one_parcel(api)
    peer = fx.marshal_shift(
        api,
        course_c1["id"],
        station_x1["id"],
        staff_person_id=_SHARED_PERSON,
        certification_level=CERT_BASIC,
        shift_start_utc=_PEER_SHIFT_START,
        shift_end_utc=_PEER_SHIFT_END,
    )
    assert peer["status"] == ASSIGNMENT_CONFIRMED

    refused = api.create_staff_assignment(
        course_c2["id"],
        _marshal_payload(
            station_y1["id"],
            _SHARED_PERSON,
            _CANDIDATE_SHIFT_START,
            _CANDIDATE_SHIFT_END,
        ),
        users.SAFETY,
    )
    validate_error(
        refused, ApiErrorId.ERR_STAFF_SHIFT_CONFLICT.value, expected_status=409
    )

    # Nothing landed on the second course, and the first is unaffected.
    assert_obstacle_staffing(
        fx.read_obstacle(api, station_y1["id"]),
        staffing_state=STAFFING_UNSTAFFED,
        confirmed_marshal_count=0,
        effective_rate=0.00,
    )
    assert_obstacle_staffing(
        fx.read_obstacle(api, station_x1["id"]),
        staffing_state=STAFFING_MARSHALED,
        confirmed_marshal_count=1,
        effective_rate=12.00,
    )
    assert_course_capacities(
        fx.read_course(api, course_c1["id"]), bottleneck_capacity_pph=720
    )
    assert_course_capacities(
        fx.read_course(api, course_c2["id"]), bottleneck_capacity_pph=0
    )


def test_vacating_the_peer_makes_the_identical_shift_bookable(api):
    """PRD §3.3: "Gather every shift already reading `CONFIRMED` for the same `staff_person_id`, across every course and every obstacle in the system — shifts reading `VACATED` are ignored entirely, which is precisely what makes a vacated slot immediately re-bookable."

    Design: Difficulty/resource_temporal_overlap/one_marshal_cannot_hold_overlapping_shifts_on_two_courses_until_the_first_is_vacated
    """
    parcel, course_c1, station_x1, course_c2, station_y1 = _two_courses_one_parcel(api)
    peer = fx.marshal_shift(
        api,
        course_c1["id"],
        station_x1["id"],
        staff_person_id=_SHARED_PERSON,
        certification_level=CERT_BASIC,
        shift_start_utc=_PEER_SHIFT_START,
        shift_end_utc=_PEER_SHIFT_END,
    )
    candidate = _marshal_payload(
        station_y1["id"],
        _SHARED_PERSON,
        _CANDIDATE_SHIFT_START,
        _CANDIDATE_SHIFT_END,
    )
    validate_error(
        api.create_staff_assignment(course_c2["id"], candidate, users.SAFETY),
        ApiErrorId.ERR_STAFF_SHIFT_CONFLICT.value,
        expected_status=409,
    )

    released = fx.vacate(api, peer["id"], reason="Reassigned to the sprint course")
    assert released["status"] == ASSIGNMENT_VACATED

    booked = validate_success(
        api.create_staff_assignment(course_c2["id"], candidate, users.SAFETY),
        expected_status=201,
    )
    assert booked["status"] == ASSIGNMENT_CONFIRMED
    assert booked["course_id"] == course_c2["id"]
    assert booked["obstacle_id"] == station_y1["id"]
    assert_instant_equals(
        booked["shift_start_utc"], _CANDIDATE_SHIFT_START, "shift_start_utc"
    )
    assert_instant_equals(booked["shift_end_utc"], _CANDIDATE_SHIFT_END, "shift_end_utc")

    # The staffing consequences move in opposite directions on the two courses.
    assert_obstacle_staffing(
        fx.read_obstacle(api, station_y1["id"]),
        staffing_state=STAFFING_MARSHALED,
        confirmed_marshal_count=1,
        effective_rate=8.00,
    )
    assert_obstacle_staffing(
        fx.read_obstacle(api, station_x1["id"]),
        staffing_state=STAFFING_UNSTAFFED,
        confirmed_marshal_count=0,
        effective_rate=0.00,
    )
    assert_course_capacities(
        fx.read_course(api, course_c2["id"]), bottleneck_capacity_pph=480
    )
    assert_course_capacities(
        fx.read_course(api, course_c1["id"]), bottleneck_capacity_pph=0
    )


def test_the_collision_is_pairwise_and_symmetric_in_both_directions(api):
    """PRD §3.3: "A collision exists with such a peer when both of the following hold: the candidate's `shift_start_utc` falls strictly before the peer's `shift_end_utc` advanced by 15 minutes, and the peer's `shift_start_utc` falls strictly before the candidate's `shift_end_utc` advanced by 15 minutes."

    Design: Difficulty/resource_temporal_overlap/one_marshal_cannot_hold_overlapping_shifts_on_two_courses_until_the_first_is_vacated
    """
    parcel, course_c1, station_x1, course_c2, station_y1 = _two_courses_one_parcel(api)

    # Book the *shorter* window first, then offer the enclosing one: the same
    # pair of intervals collides whichever of the two arrives second.
    inner = fx.marshal_shift(
        api,
        course_c2["id"],
        station_y1["id"],
        staff_person_id=_SHARED_PERSON,
        certification_level=CERT_BASIC,
        shift_start_utc=_CANDIDATE_SHIFT_START,
        shift_end_utc=_CANDIDATE_SHIFT_END,
    )
    assert inner["status"] == ASSIGNMENT_CONFIRMED

    refused = api.create_staff_assignment(
        course_c1["id"],
        _marshal_payload(
            station_x1["id"], _SHARED_PERSON, _PEER_SHIFT_START, _PEER_SHIFT_END
        ),
        users.SAFETY,
    )
    validate_error(
        refused, ApiErrorId.ERR_STAFF_SHIFT_CONFLICT.value, expected_status=409
    )
    assert_obstacle_staffing(
        fx.read_obstacle(api, station_x1["id"]),
        staffing_state=STAFFING_UNSTAFFED,
        confirmed_marshal_count=0,
    )

    # A different human takes the very same enclosing window without complaint:
    # the contended resource is the person, not the station or the window.
    other = validate_success(
        api.create_staff_assignment(
            course_c1["id"],
            _marshal_payload(
                station_x1["id"], _OTHER_PERSON, _PEER_SHIFT_START, _PEER_SHIFT_END
            ),
            users.SAFETY,
        ),
        expected_status=201,
    )
    assert other["staff_person_id"] == _OTHER_PERSON
    assert_obstacle_staffing(
        fx.read_obstacle(api, station_x1["id"]),
        staffing_state=STAFFING_MARSHALED,
        confirmed_marshal_count=1,
        effective_rate=12.00,
    )


# ─── One corral, many heats ──────────────────────────────────────────────

#: The shared corral budget declared on the course.
_CORRAL_BUDGET = 200

#: Every candidate heat below carries exactly this capacity, so only the moving
#: interval arithmetic can tell the refused one from the accepted one.
_HEAT_CAPACITY = 60

_W1_START = "2026-09-12T08:00:00.000Z"
_W2_START = "2026-09-12T08:02:00.000Z"
_W3_START = "2026-09-12T08:04:00.000Z"
_W4_START = "2026-09-12T08:05:00.000Z"
_W5_START = "2026-09-12T08:06:00.000Z"

_CORRAL_COURSE_KWARGS = {
    "name": "Quarry Gauntlet",
    "total_distance_m": 10000,
    "corral_release_rate_per_min": 12.00,
    "corral_throughput_capacity": _CORRAL_BUDGET,
}

#: The three canonical stations: the wet middle station is the bottleneck at
#: 7.50 per minute, so design_capacity_pph is 450 and the per-heat design
#: ceiling is 112 — far above the 60 every candidate asks for.
_CORRAL_STATIONS = [
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


def _three_staggered_heats(api):
    """A DRAFT course with no permit — so the quiet window is skipped entirely —
    carrying heats W1, W2 and W3 of 60 at 08:00, 08:02 and 08:04.

    Their 6-minute corral windows all overlap, giving running occupancy sums of
    60, 120 and 180 against a budget of 200. Returns (course, division, heats).
    """
    parcel = fx.venue(api)
    course, _stations = fx.three_station_course(
        api,
        parcel["id"],
        course_kwargs=_CORRAL_COURSE_KWARGS,
        station_kwargs=_CORRAL_STATIONS,
    )
    division = fx.division(
        api,
        name="Open Wave",
        division_type=DIVISION_OPEN,
        bypass_policy=BYPASS_POLICY_ALLOWED_WITH_PENALTY,
        scoring_mode=SCORING_GUN_TIME,
        min_age=16,
    )
    heats = [
        fx.wave(
            api,
            course["id"],
            division["id"],
            wave_code=code,
            scheduled_start_utc=start,
            capacity=_HEAT_CAPACITY,
        )
        for code, start in (("W1", _W1_START), ("W2", _W2_START), ("W3", _W3_START))
    ]
    return course, division, heats


def _schedule(api, course_id: str, division_id: str, wave_code: str, start: str):
    """Offer one more heat of the same capacity to the corral."""
    return api.create_wave(
        course_id,
        f.wave_payload(
            division_id,
            wave_code=wave_code,
            scheduled_start_utc=start,
            capacity=_HEAT_CAPACITY,
        ),
        users.DIRECTOR,
    )


def test_three_heats_share_the_corral_and_the_fourth_bursts_the_budget(api):
    """PRD §3.4: "Sum the `capacity` of the overlapping peers, add the candidate's own `capacity`, and require that total to be at most the course's `corral_throughput_capacity`; exceeding it is refused with `ERR_CORRAL_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/three_overlapping_heats_share_the_corral_budget_and_the_window_rolls_forward
    """
    course, division, heats = _three_staggered_heats(api)

    # All three coexist happily at 60 + 60 + 60 = 180 of 200.
    for heat in heats:
        assert heat["capacity"] == _HEAT_CAPACITY
        assert_wave_state(heat, release_status=RELEASE_SCHEDULED)
    assert_course_capacities(
        fx.read_course(api, course["id"]),
        design_capacity_pph=450,
        scheduled_capacity_total=180,
    )

    # W4 at 08:05 still overlaps W1's window, so the sum reaches 240.
    refused = _schedule(api, course["id"], division["id"], "W4", _W4_START)
    validate_error(
        refused, ApiErrorId.ERR_CORRAL_WINDOW_CONFLICT.value, expected_status=409
    )


def test_the_corral_window_rolls_forward_and_admits_a_later_identical_heat(api):
    """PRD §3.4: "Two half-open windows overlap when the peer's start falls strictly before the candidate's end and the candidate's start falls strictly before the peer's end; windows that merely touch at an endpoint do not overlap, so a heat scheduled exactly 6 minutes after a peer is always free of it."

    Design: Difficulty/resource_temporal_overlap/three_overlapping_heats_share_the_corral_budget_and_the_window_rolls_forward
    """
    course, division, heats = _three_staggered_heats(api)
    validate_error(
        _schedule(api, course["id"], division["id"], "W4", _W4_START),
        ApiErrorId.ERR_CORRAL_WINDOW_CONFLICT.value,
        expected_status=409,
    )

    # W5 starts exactly 6 minutes after W1, so W1 has rolled out of the window
    # and only W2 and W3 still count: 60 + 60 + 60 == 180.
    accepted = validate_success(
        _schedule(api, course["id"], division["id"], "W5", _W5_START),
        expected_status=201,
    )
    assert accepted["capacity"] == _HEAT_CAPACITY
    assert_instant_equals(
        accepted["scheduled_start_utc"], _W5_START, "scheduled_start_utc"
    )
    assert_wave_state(accepted, release_status=RELEASE_SCHEDULED)

    rows, meta = validate_paginated(
        api.list_waves(users.DIRECTOR, {"course_id": course["id"]})
    )
    assert meta["total_count"] == 4
    assert sorted(row["wave_code"] for row in rows) == ["W1", "W2", "W3", "W5"]


def test_the_refused_heat_leaves_the_corral_ledger_exactly_where_it_was(api):
    """PRD §3.4: "Creating a heat recomputes the course's `scheduled_capacity_total` — the sum of `capacity` over the heats of that course whose `release_status` is `SCHEDULED`, `HELD`, `RELEASED` or `STARTED` — and therefore also recomputes the course's `readiness_posture`, because the medic requirement scales with that total."

    Design: Difficulty/resource_temporal_overlap/three_overlapping_heats_share_the_corral_budget_and_the_window_rolls_forward
    """
    course, division, heats = _three_staggered_heats(api)
    assert_course_capacities(
        fx.read_course(api, course["id"]), scheduled_capacity_total=180
    )

    validate_error(
        _schedule(api, course["id"], division["id"], "W4", _W4_START),
        ApiErrorId.ERR_CORRAL_WINDOW_CONFLICT.value,
        expected_status=409,
    )
    assert_course_capacities(
        fx.read_course(api, course["id"]), scheduled_capacity_total=180
    )

    validate_success(
        _schedule(api, course["id"], division["id"], "W5", _W5_START),
        expected_status=201,
    )
    assert_course_capacities(
        fx.read_course(api, course["id"]), scheduled_capacity_total=240
    )
