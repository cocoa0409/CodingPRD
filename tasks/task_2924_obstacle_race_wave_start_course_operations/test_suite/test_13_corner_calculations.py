"""Corner-case coverage of the PRD's computed quantities.

Every test in this file translates exactly one live instance of the
`section: calculations` slice of `SCAFFOLD_CORNER_DESIGN.yaml`, and names that
instance on the final `Design:` line of its docstring. Nothing else is probed
here: the design index is the only source of tests.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_bond_ledger_conserved,
    assert_course_capacities,
    assert_entry_state,
    assert_obstacle_staffing,
    assert_rate_equals,
    assert_whole_cents,
)

# ─── Private builders for the recipes' canonical parcel and course ───────
#
# The three stations below are the corner index's canonical dry course: lane
# rates of 12.00, 7.50 and 9.00 with bypass NONE / MANDATORY / TIMED_PENALTY,
# footprints of 1200, 1500 and 1000 sqm, and ratings 3, 5, 7.

_STATION_SPECS = (
    dict(
        name="Cargo Net",
        difficulty_rating=3,
        lane_count=4,
        service_rate_per_min=3.00,
        marshals_required=1,
        footprint_sqm=1200,
        water_contact=False,
        bypass_mode=c.BYPASS_MODE_NONE,
        penalty_seconds=0,
    ),
    dict(
        name="Mud Trench",
        difficulty_rating=5,
        lane_count=3,
        service_rate_per_min=2.50,
        marshals_required=1,
        footprint_sqm=1500,
        water_contact=False,
        bypass_mode=c.BYPASS_MODE_MANDATORY,
        penalty_seconds=120,
    ),
    dict(
        name="Wall Climb",
        difficulty_rating=7,
        lane_count=3,
        service_rate_per_min=3.00,
        marshals_required=1,
        footprint_sqm=1000,
        water_contact=False,
        bypass_mode=c.BYPASS_MODE_TIMED_PENALTY,
        penalty_seconds=90,
    ),
)

_VENUE_KWARGS = dict(protected_acreage_sqm=2000, restoration_bond_cents=1000000)


def _unpermitted_parcel(api, **overrides):
    """A registered parcel carrying no land-use application at all."""
    return fx.venue(api, **dict(_VENUE_KWARGS, **overrides))


def _permitted_parcel(api, venue_overrides=None, **permit_overrides):
    """A parcel with exactly one governing permit. Returns (venue, permit)."""
    return fx.permitted_venue(
        api,
        dict(_VENUE_KWARGS, **(venue_overrides or {})),
        **dict(
            dict(
                water_use_allowed=False,
                max_disturbed_area_sqm=5000,
                quiet_hours_start_hour_utc=22,
                quiet_hours_end_hour_utc=6,
            ),
            **permit_overrides,
        ),
    )


def _canonical_course(api, venue_id, **overrides):
    return fx.course(
        api,
        venue_id,
        **dict(
            dict(
                name="Quarry Gauntlet",
                total_distance_m=10000,
                corral_release_rate_per_min=12.00,
                corral_throughput_capacity=200,
            ),
            **overrides,
        ),
    )


def _canonical_stations(api, course_id, overrides=None):
    """Place the three canonical stations, in ascending station order."""
    per_station = overrides or [{}, {}, {}]
    return [
        fx.obstacle(api, course_id, index + 1, **dict(spec, **extra))
        for index, (spec, extra) in enumerate(zip(_STATION_SPECS, per_station))
    ]


def _open_division(api, **overrides):
    return fx.division(
        api,
        **dict(
            dict(
                name="Open Wave",
                division_type=c.DIVISION_OPEN,
                bypass_policy=c.BYPASS_POLICY_ALLOWED_WITH_PENALTY,
                scoring_mode=c.SCORING_GUN_TIME,
                min_age=16,
                team_size_min=1,
                team_size_max=1,
            ),
            **overrides,
        ),
    )


def test_three_stations_land_on_twelve_seven_fifty_and_a_corral_capped_twelve(api):
    """PRD §3.2: "Add the design relief to the lane rate, take whichever is smaller of that sum and the parent course's `corral_release_rate_per_min`, and round the result half up to two decimal places."

    Design: Corner/calculations/design_rates_land_on_twelve_seven_fifty_and_a_corral_capped_twelve
    """
    parcel = _unpermitted_parcel(api)
    laid = _canonical_course(api, parcel["id"])
    stations = _canonical_stations(api, laid["id"])

    # Station 1: lane rate 4 x 3.00 = 12.00, bypass NONE so no relief, and the
    # corral rate is exactly 12.00 — the minimum is a tie, not a clip.
    assert_obstacle_staffing(
        fx.read_obstacle(api, stations[0]["id"]), design_rate=12.00
    )
    # Station 2: lane rate 3 x 2.50 = 7.50, MANDATORY so no relief either.
    assert_obstacle_staffing(
        fx.read_obstacle(api, stations[1]["id"]), design_rate=7.50
    )
    # Station 3: lane rate 3 x 3.00 = 9.00 plus a relief of 4.50 is 13.50, which
    # the corral rate of 12.00 clips back down.
    assert_obstacle_staffing(
        fx.read_obstacle(api, stations[2]["id"]), design_rate=12.00
    )

    course = fx.read_course(api, laid["id"])
    assert course["obstacle_count"] == 3
    assert_course_capacities(course, design_capacity_pph=450)


def test_the_design_capacity_ceiling_admits_exactly_one_hundred_twelve(api):
    """PRD §3.4: "Heats are planned on a 15-minute grid, so the most a single heat may carry is the course's `design_capacity_pph` scaled from an hour down to a quarter of an hour — that is, multiplied by 15 and divided by 60, with any fractional part discarded."

    Design: Corner/calculations/design_rates_land_on_twelve_seven_fifty_and_a_corral_capped_twelve
    """
    parcel = _unpermitted_parcel(api)
    laid = _canonical_course(api, parcel["id"])
    _canonical_stations(api, laid["id"])
    heat_division = _open_division(api)

    # 450 x 15 / 60 is 112.5, so the ceiling is 112 and 113 is one too many.
    refused = api.create_wave(
        laid["id"],
        f.wave_payload(
            heat_division["id"], wave_code="S1", scheduled_start_utc=f.GUN_UTC,
            capacity=113,
        ),
        users.DIRECTOR,
    )
    validate_error(
        refused, ApiErrorId.ERR_DESIGN_CAPACITY_EXCEEDED.value, expected_status=409
    )

    accepted = api.create_wave(
        laid["id"],
        f.wave_payload(
            heat_division["id"], wave_code="S1", scheduled_start_utc=f.GUN_UTC,
            capacity=112,
        ),
        users.DIRECTOR,
    )
    heat = validate_success(accepted, expected_status=201)
    assert heat["capacity"] == 112

    course = fx.read_course(api, laid["id"])
    assert_course_capacities(
        course,
        design_capacity_pph=450,
        scheduled_capacity_total=112,
        bottleneck_capacity_pph=0,
    )


def test_only_the_verified_task_releases_bond_over_the_whole_disturbed_area(api):
    """PRD §3.9: "It computes that task's provisional bond share and writes it to `bond_release_cents`: the parcel's `restoration_bond_cents` multiplied by the task's `area_sqm`, divided by the parcel's `disturbed_area_sqm`, and rounded half up to whole cents."

    Design: Corner/calculations/only_verified_tasks_release_bond_and_the_denominator_stays_the_disturbed_area
    """
    parcel = _unpermitted_parcel(api)
    laid = _canonical_course(api, parcel["id"])
    _canonical_stations(api, laid["id"])
    # 1200 + 1500 + 1000 of obstacle footprint plus 800 of festival footprint:
    # the denominator is the whole 4500 sqm of disturbed ground.
    fx.festival_service(
        api,
        parcel["id"],
        service_type=c.SERVICE_BAG_CHECK,
        footprint_sqm=800,
        capacity=500,
        water_draw_lpm=0,
    )
    first = fx.restoration_task(api, parcel["id"], 1500, task_type=c.TASK_TYPE_RESEED)
    second = fx.restoration_task(
        api, parcel["id"], 1500, task_type=c.TASK_TYPE_DECOMPACT
    )
    third = fx.restoration_task(
        api, parcel["id"], 1500, task_type=c.TASK_TYPE_DEBRIS_SWEEP
    )

    passed = fx.inspect(
        api, first["id"], c.INSPECTION_VERIFIED, findings_note="Cover established"
    )
    assert passed["status"] == c.TASK_VERIFIED
    # 1000000 x 1500 / 4500 is 333333.33..., which rounds half up to 333333.
    assert_whole_cents(passed["bond_release_cents"], "bond_release_cents")
    assert passed["bond_release_cents"] == 333333
    assert passed["inspection_rounds"] == 1

    for untouched in (second, third):
        still_pending = fx.read_task(api, untouched["id"])
        assert still_pending["status"] == c.TASK_PENDING
        assert still_pending["bond_release_cents"] == 0
        assert still_pending["inspection_rounds"] == 0

    ledger = fx.read_venue(api, parcel["id"])
    assert ledger["disturbed_area_sqm"] == 4500
    assert ledger["bond_released_cents"] == 333333
    assert ledger["bond_held_cents"] == 666667
    assert ledger["bond_forfeited_cents"] == 0
    assert_bond_ledger_conserved(ledger)
    assert ledger["site_posture"] == c.SITE_POSTURE_OPEN


def test_the_two_hundred_fifty_first_scheduled_runner_demands_a_second_medic(api):
    """PRD §3.3: "Failing that, it reads `RESTRICTED` when any of three conditions holds: the course's `medic_headcount` is below the required medic count, which is the course's `scheduled_capacity_total` divided by 250 participants per medic and rounded up to a whole number; or its `water_safety_headcount` is below the required water-safety count, which is 2 swimmers for each obstacle on the course whose `water_contact` is true, counting every obstacle including bypass lanes; or any obstacle of the course, again including bypass lanes, has a `staffing_state` of `UNSTAFFED`."

    Design: Corner/calculations/the_two_hundred_fifty_medic_constant_bites_at_the_two_hundred_fifty_first_runner
    """
    parcel, _permit = _permitted_parcel(api, {"water_access": c.WATER_ACCESS_NONE})
    laid = _canonical_course(api, parcel["id"], corral_throughput_capacity=400)
    stations = _canonical_stations(api, laid["id"])
    fx.published_course(api, laid["id"])
    for person, station in zip(
        (c.STAFF_PERSON_1, c.STAFF_PERSON_2, c.STAFF_PERSON_3), stations
    ):
        fx.marshal_shift(api, laid["id"], station["id"], staff_person_id=person)
    fx.medic_shift(api, laid["id"], staff_person_id=c.STAFF_MEDIC_1)
    heat_division = _open_division(api)
    fx.wave(
        api, laid["id"], heat_division["id"], wave_code="S1",
        scheduled_start_utc="2026-09-12T08:00:00.000Z", capacity=112,
    )
    fx.wave(
        api, laid["id"], heat_division["id"], wave_code="S2",
        scheduled_start_utc="2026-09-12T08:15:00.000Z", capacity=112,
    )

    # 224 scheduled runners need one medic, and one medic is rostered.
    staffed = fx.read_course(api, laid["id"])
    assert staffed["medic_headcount"] == 1
    assert_course_capacities(
        staffed, scheduled_capacity_total=224, readiness_posture=c.READINESS_OPEN
    )

    # One more heat of 27 pushes the total to 251, and 251 / 250 rounds up to 2.
    fx.wave(
        api, laid["id"], heat_division["id"], wave_code="S3",
        scheduled_start_utc="2026-09-12T08:30:00.000Z", capacity=27,
    )
    stretched = fx.read_course(api, laid["id"])
    assert stretched["medic_headcount"] == 1
    assert_course_capacities(
        stretched,
        scheduled_capacity_total=251,
        readiness_posture=c.READINESS_RESTRICTED,
    )

    relief = fx.medic_shift(api, laid["id"], staff_person_id=c.STAFF_MEDIC_2)
    assert relief["status"] == c.ASSIGNMENT_CONFIRMED
    restored = fx.read_course(api, laid["id"])
    assert restored["medic_headcount"] == 2
    assert restored["water_safety_headcount"] == 0
    assert_course_capacities(
        restored,
        scheduled_capacity_total=251,
        readiness_posture=c.READINESS_OPEN,
    )


def test_five_rises_over_eight_pairs_round_half_up_to_zero_point_six_three(api):
    """PRD §3.2: "Sum those rises, divide by the number of consecutive pairs (one fewer than the number of primary stations), and round half up to two decimal places."

    Design: Corner/calculations/progression_score_rounds_five_eighths_up_to_zero_point_six_three
    """
    parcel, _permit = _permitted_parcel(api, {"water_access": c.WATER_ACCESS_NONE})
    laid = fx.course(
        api,
        parcel["id"],
        name="Nine Station Ladder",
        total_distance_m=9000,
        corral_release_rate_per_min=12.00,
        corral_throughput_capacity=200,
    )
    # Ratings 2,2,2,3,4,5,6,7,7 give rises 0,0,1,1,1,1,1,0 — five rises over the
    # eight consecutive pairs, so the raw mean is exactly 0.625.
    for index, rating in enumerate([2, 2, 2, 3, 4, 5, 6, 7, 7], start=1):
        fx.obstacle(
            api,
            laid["id"],
            index,
            name=f"Rung {index}",
            difficulty_rating=rating,
            lane_count=4,
            service_rate_per_min=3.00,
            marshals_required=1,
            footprint_sqm=500,
            water_contact=False,
            bypass_mode=c.BYPASS_MODE_NONE,
            penalty_seconds=0,
        )

    validated = validate_success(api.validate_course(laid["id"], users.DESIGNER))
    assert validated["status"] == c.COURSE_VALIDATED
    assert_rate_equals(
        validated["difficulty_progression_score"], 0.63,
        "difficulty_progression_score",
    )

    course = fx.read_course(api, laid["id"])
    assert_rate_equals(
        course["difficulty_progression_score"], 0.63,
        "difficulty_progression_score",
    )
    assert course["obstacle_count"] == 9
    assert_course_capacities(
        course, design_capacity_pph=720, status=c.COURSE_VALIDATED
    )
    assert fx.read_venue(api, parcel["id"])["disturbed_area_sqm"] == 4500


def test_stations_created_out_of_order_score_in_station_index_order(api):
    """PRD §3.2: "List the `difficulty_rating` values of the primary obstacles in ascending `station_index` order — the index is unique per course, so this ordering is total and needs no tie-break."

    Design: Corner/calculations/stations_created_out_of_order_still_score_in_station_index_order
    """
    parcel = _unpermitted_parcel(api)
    laid = _canonical_course(api, parcel["id"])
    # Placed 3, 1, 2: in creation order the ratings read 7, 3, 5 and would score
    # 1.00, but in station-index order they read 3, 5, 7 and score 2.00.
    third = fx.obstacle(api, laid["id"], 3, **_STATION_SPECS[2])
    first = fx.obstacle(api, laid["id"], 1, **_STATION_SPECS[0])
    second = fx.obstacle(api, laid["id"], 2, **_STATION_SPECS[1])

    course = fx.read_course(api, laid["id"])
    assert_rate_equals(
        course["difficulty_progression_score"], 2.00,
        "difficulty_progression_score",
    )
    assert course["obstacle_count"] == 3
    assert_course_capacities(course, design_capacity_pph=450)

    rows, meta = validate_paginated(
        api.list_obstacles(users.DESIGNER, {"course_id": laid["id"]})
    )
    assert meta["total_count"] == 3
    assert {row["station_index"]: row["id"] for row in rows} == {
        1: first["id"], 2: second["id"], 3: third["id"],
    }


def _competitive_heat(api):
    """A DRAFT single-station course carrying one COMPETITIVE heat of ten."""
    parcel = _unpermitted_parcel(api)
    laid = _canonical_course(api, parcel["id"])
    fx.obstacle(api, laid["id"], 1, **_STATION_SPECS[0])
    strict = fx.division(
        api,
        name="Elite Wave",
        division_type=c.DIVISION_COMPETITIVE,
        bypass_policy=c.BYPASS_POLICY_DQ_ON_BYPASS,
        scoring_mode=c.SCORING_CHIP_TIME,
        min_age=18,
        team_size_min=1,
        team_size_max=1,
    )
    return fx.wave(
        api, laid["id"], strict["id"], wave_code="E1",
        scheduled_start_utc="2026-09-12T08:00:00.000Z", capacity=10,
    )


def test_calendar_year_age_admits_the_runner_who_turns_eighteen_this_year(api):
    """PRD §3.5: "Age eligibility is computed as a pure calendar-year difference — the calendar year of the heat's `scheduled_start_utc` minus the participant's `birth_year`, with month and day deliberately ignored so that the boundary is exact and independent of the clock — and that age must be at least the division's `min_age`, or the registration is refused with `ERR_AGE_INELIGIBLE`."

    Design: Corner/calculations/calendar_year_age_admits_eighteen_and_refuses_seventeen
    """
    heat = _competitive_heat(api)
    # The heat is run in 2026, so 2026 - 2007 = 19 and 2026 - 2008 = 18: the
    # minimum age of 18 is inclusive, month and day never enter the arithmetic.
    older = fx.cleared_participant(api, birth_year=2007)
    exact = fx.cleared_participant(api, birth_year=2008)

    for bib, human in ((19, older), (18, exact)):
        created = validate_success(
            api.create_entry(
                heat["id"], f.entry_payload(human["id"], bib), users.OPS
            ),
            expected_status=201,
        )
        assert_entry_state(
            created,
            progress_status=c.PROGRESS_REGISTERED,
            result_status=c.RESULT_PENDING,
        )

    assert fx.read_wave(api, heat["id"])["assigned_count"] == 2


def test_calendar_year_age_refuses_the_runner_who_turns_seventeen_this_year(api):
    """PRD §3.5: "Age eligibility is computed as a pure calendar-year difference — the calendar year of the heat's `scheduled_start_utc` minus the participant's `birth_year`, with month and day deliberately ignored so that the boundary is exact and independent of the clock — and that age must be at least the division's `min_age`, or the registration is refused with `ERR_AGE_INELIGIBLE`."

    Design: Corner/calculations/calendar_year_age_admits_eighteen_and_refuses_seventeen
    """
    heat = _competitive_heat(api)
    # 2026 - 2009 = 17, one year short of the division's minimum of 18.
    young = fx.cleared_participant(api, birth_year=2009)

    refused = api.create_entry(
        heat["id"], f.entry_payload(young["id"], 17), users.OPS
    )
    validate_error(refused, ApiErrorId.ERR_AGE_INELIGIBLE.value, expected_status=409)

    assert fx.read_wave(api, heat["id"])["assigned_count"] == 0


_SLOWEST_STATION = {"service_rate_per_min": 2.51}


def test_a_seven_point_five_three_bottleneck_floors_the_hourly_capacity_to_451(api):
    """PRD §3.2: "`design_capacity_pph` is the staffing-independent throughput of the course in participants per hour: consider only the primary obstacles, take the smallest `design_clearance_rate_per_min` among them, multiply by 60 to convert per-minute into per-hour, and discard any fractional part; when the course has no primary obstacle at all the value is 0."

    Design: Corner/calculations/the_capacity_aggregate_floors_twice_and_discards_both_fractions
    """
    parcel = _unpermitted_parcel(api)
    laid = _canonical_course(api, parcel["id"])
    stations = _canonical_stations(api, laid["id"], [{}, dict(_SLOWEST_STATION), {}])

    # 3 lanes x 2.51 = 7.53, and MANDATORY bypass adds no relief.
    assert_obstacle_staffing(
        fx.read_obstacle(api, stations[1]["id"]), design_rate=7.53
    )
    course = fx.read_course(api, laid["id"])
    # 7.53 x 60 = 451.8, and the fraction is discarded rather than rounded.
    assert_course_capacities(course, design_capacity_pph=451)
    assert course["obstacle_count"] == 3


def test_the_heat_ceiling_discards_a_second_fraction_and_stops_at_112(api):
    """PRD §2.9: "Throughput capacities in participants per hour — `design_capacity_pph` and `bottleneck_capacity_pph` — and every capacity ceiling derived from them are **integers obtained by discarding any fractional part** (rounding down)."

    Design: Corner/calculations/the_capacity_aggregate_floors_twice_and_discards_both_fractions
    """
    parcel = _unpermitted_parcel(api)
    laid = _canonical_course(api, parcel["id"])
    _canonical_stations(api, laid["id"], [{}, dict(_SLOWEST_STATION), {}])
    heat_division = _open_division(api)

    # 451 x 15 / 60 = 112.75, so the ceiling floors to 112 and refuses 113.
    refused = api.create_wave(
        laid["id"],
        f.wave_payload(
            heat_division["id"], wave_code="S1", scheduled_start_utc=f.GUN_UTC,
            capacity=113,
        ),
        users.DIRECTOR,
    )
    validate_error(
        refused, ApiErrorId.ERR_DESIGN_CAPACITY_EXCEEDED.value, expected_status=409
    )

    accepted = api.create_wave(
        laid["id"],
        f.wave_payload(
            heat_division["id"], wave_code="S1", scheduled_start_utc=f.GUN_UTC,
            capacity=112,
        ),
        users.DIRECTOR,
    )
    assert validate_success(accepted, expected_status=201)["capacity"] == 112

    assert_course_capacities(
        fx.read_course(api, laid["id"]),
        design_capacity_pph=451,
        scheduled_capacity_total=112,
    )


def _partially_staffed_course(api):
    """The canonical course with two marshals on station 1 and one on each of
    the others, then the second marshal of station 1 walked off.

    Returns (course_id, station_one_id) after the vacate.
    """
    parcel, _permit = _permitted_parcel(api, {"water_access": c.WATER_ACCESS_NONE})
    laid = _canonical_course(api, parcel["id"])
    stations = _canonical_stations(api, laid["id"], [{"marshals_required": 2}, {}, {}])
    fx.marshal_shift(
        api, laid["id"], stations[0]["id"], staff_person_id=c.STAFF_PERSON_1
    )
    doubled = fx.marshal_shift(
        api, laid["id"], stations[0]["id"], staff_person_id=c.STAFF_PERSON_2
    )
    fx.marshal_shift(
        api, laid["id"], stations[1]["id"], staff_person_id=c.STAFF_PERSON_3
    )
    fx.marshal_shift(
        api, laid["id"], stations[2]["id"], staff_person_id=c.STAFF_PERSON_4
    )

    fully_staffed = fx.read_course(api, laid["id"])
    assert_course_capacities(
        fully_staffed,
        design_capacity_pph=450,
        bottleneck_capacity_pph=450,
        readiness_posture=c.READINESS_OPEN,
    )

    walked_off = fx.vacate(api, doubled["id"], "Reassigned to the festival gate")
    assert walked_off["status"] == c.ASSIGNMENT_VACATED
    return laid["id"], stations[0]["id"]


def test_one_marshal_of_two_cuts_the_station_rate_to_seven_point_two(api):
    """PRD §3.3: "`effective_clearance_rate_per_min` starts from a **staffing factor** that steps on the confirmed marshal headcount: the factor is 1.00 when `confirmed_marshal_count` is `marshals_required` or greater; otherwise it is 0.60 when `confirmed_marshal_count` is at least half of `marshals_required` rounded up to a whole number *and* is also at least 1; and otherwise it is 0.00, which is the case whenever the station has no confirmed marshal at all."

    Design: Corner/calculations/partial_staffing_lowers_the_bottleneck_without_restricting_the_course
    """
    _course_id, station_one_id = _partially_staffed_course(api)

    # One marshal of the two required is half, rounded up, and at least one, so
    # the factor is 0.60: 4 lanes x 3.00 x 0.60 = 7.20, with no bypass relief.
    assert_obstacle_staffing(
        fx.read_obstacle(api, station_one_id),
        staffing_state=c.STAFFING_PARTIAL,
        confirmed_marshal_count=1,
        effective_rate=7.20,
        design_rate=12.00,
    )


def test_partial_staffing_lowers_the_bottleneck_without_restricting_the_course(api):
    """PRD §3.3: "Note carefully that `PARTIAL` staffing does **not** restrict a course — it only lowers `bottleneck_capacity_pph`."

    Design: Corner/calculations/partial_staffing_lowers_the_bottleneck_without_restricting_the_course
    """
    course_id, _station_one_id = _partially_staffed_course(api)

    # The slowest effective rate is now station 1's 7.20, and 7.20 x 60 = 432.
    assert_course_capacities(
        fx.read_course(api, course_id),
        design_capacity_pph=450,
        bottleneck_capacity_pph=432,
        readiness_posture=c.READINESS_OPEN,
    )
