"""Difficulty/combinatorial_formula — one field, several operators, one answer.

Two instances live here, each a single stored figure produced by pushing four or
five inputs through a stack of operators that cannot be reordered:

* `obstacle_effective_rate_step_staffing_inside_nested_min_with_corral_cap` — a
  step function on marshal headcount, multiplied into the lane rate, then a
  capped relief term, then clamped by the course's corral release rate.
* `final_closeout_late_penalty_composes_ceil_days_min_cap_and_remainder` — one
  rounding of the gross share, a ceil() of fractional hours into late days, a
  min() cap of the per-day charge against the gross, and a signed remainder.
"""

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_bond_ledger_conserved,
    assert_course_capacities,
    assert_obstacle_staffing,
    assert_rate_equals,
    assert_whole_cents,
)
from test_helpers.constants import (
    ASSIGNMENT_VACATED,
    BYPASS_MODE_MANDATORY,
    BYPASS_MODE_NONE,
    BYPASS_MODE_TIMED_PENALTY,
    INSPECTION_VERIFIED,
    READINESS_OPEN,
    SERVICE_SPECTATOR_ZONE,
    SETTLEMENT_FINAL,
    SITE_POSTURE_CLOSED_OUT,
    STAFFING_MARSHALED,
    STAFFING_PARTIAL,
    STAFFING_UNSTAFFED,
    TASK_TYPE_DEBRIS_SWEEP,
    TASK_TYPE_DECOMPACT,
    TASK_TYPE_RESEED,
    TERRAIN_FIELD,
    WATER_ACCESS_NONE,
)

# ─── Private literals this file needs and constants.py does not name ─────

_VALID_UNTIL_UTC = "2026-12-31T00:00:00.000Z"
_DEADLINE_UTC = "2026-09-20T00:00:00.000Z"
_ONE_SECOND_EARLIER_DEADLINE_UTC = "2026-09-19T23:59:59.000Z"
_FIFTY_FOUR_HOURS_LATE_UTC = "2026-09-22T06:00:00.000Z"
_EXACTLY_ON_DEADLINE_UTC = "2026-09-20T00:00:00.000Z"

#: The index's canonical corral-clipped course: station 3's uncapped 13.50
#: exceeds the 12.00 corral rate and must be clipped to it.
_CORRAL_CLIPPED_STATIONS = [
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

#: Station 1 wants three marshals, which is what makes the 0.00 / 0.60 / 1.00
#: step visible one marshal at a time.
_THREE_MARSHAL_STATIONS = [
    {
        "name": "Rope Ladder",
        "difficulty_rating": 3,
        "lane_count": 4,
        "service_rate_per_min": 3.00,
        "marshals_required": 3,
        "footprint_sqm": 1200,
        "water_contact": False,
        "bypass_mode": BYPASS_MODE_NONE,
        "penalty_seconds": 0,
    },
    {
        "name": "Mud Pit",
        "difficulty_rating": 5,
        "lane_count": 3,
        "service_rate_per_min": 2.50,
        "marshals_required": 2,
        "footprint_sqm": 1500,
        "water_contact": False,
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

#: Station 1's lane rate is 16.00, so its half-relief of 8.00 sits exactly on the
#: relief cap while the course's corral rate of 100.00 clamps nothing.
_CAPPED_RELIEF_STATIONS = [
    {
        "name": "Monkey Bars",
        "difficulty_rating": 3,
        "lane_count": 4,
        "service_rate_per_min": 4.00,
        "marshals_required": 2,
        "footprint_sqm": 1000,
        "water_contact": False,
        "bypass_mode": BYPASS_MODE_TIMED_PENALTY,
        "penalty_seconds": 60,
    },
    {
        "name": "Sled Drag",
        "difficulty_rating": 5,
        "lane_count": 6,
        "service_rate_per_min": 5.00,
        "marshals_required": 1,
        "footprint_sqm": 1000,
        "water_contact": False,
        "bypass_mode": BYPASS_MODE_NONE,
        "penalty_seconds": 60,
    },
    {
        "name": "Wall Climb",
        "difficulty_rating": 7,
        "lane_count": 6,
        "service_rate_per_min": 5.00,
        "marshals_required": 1,
        "footprint_sqm": 1000,
        "water_contact": False,
        "bypass_mode": BYPASS_MODE_NONE,
        "penalty_seconds": 60,
    },
]


def _draft_course(api, corral_release_rate_per_min, station_kwargs):
    """A DRAFT course on a permitted parcel, stations placed, nobody rostered."""
    venue, _permit = fx.permitted_venue(
        api,
        venue_kwargs={"protected_acreage_sqm": 2000, "restoration_bond_cents": 500000},
        water_use_allowed=True,
        max_disturbed_area_sqm=5000,
        valid_until_utc=_VALID_UNTIL_UTC,
        restoration_deadline_utc=_DEADLINE_UTC,
    )
    course, stations = fx.three_station_course(
        api,
        venue["id"],
        course_kwargs={
            "total_distance_m": 10000,
            "corral_release_rate_per_min": corral_release_rate_per_min,
            "corral_throughput_capacity": 200,
        },
        station_kwargs=station_kwargs,
    )
    return venue, course, stations


def _bond_world(api, bond_cents, footprint_sqm, task_specs, deadline_utc, name="Cedar Flats"):
    """A parcel disturbed only by one spectator zone, with every task VERIFIED."""
    venue, _permit = fx.permitted_venue(
        api,
        venue_kwargs={
            "name": name,
            "terrain_type": TERRAIN_FIELD,
            "water_access": WATER_ACCESS_NONE,
            "land_use_zone": "RU-1",
            "protected_acreage_sqm": 0,
            "restoration_bond_cents": bond_cents,
        },
        water_use_allowed=False,
        max_disturbed_area_sqm=6000,
        valid_until_utc=_VALID_UNTIL_UTC,
        restoration_deadline_utc=deadline_utc,
    )
    fx.festival_service(
        api,
        venue["id"],
        service_type=SERVICE_SPECTATOR_ZONE,
        footprint_sqm=footprint_sqm,
        capacity=3000,
    )
    tasks = []
    for task_type, area_sqm in task_specs:
        task = fx.restoration_task(api, venue["id"], area_sqm, task_type=task_type)
        fx.inspect(api, task["id"], INSPECTION_VERIFIED, findings_note="Ground restored")
        tasks.append(task)
    return venue, tasks


_THREE_EQUAL_TASKS = [
    (TASK_TYPE_RESEED, 1500),
    (TASK_TYPE_DECOMPACT, 1500),
    (TASK_TYPE_DEBRIS_SWEEP, 1500),
]


# ─── combinatorial_formula / the effective clearance rate ─────────────────


def test_single_vacate_drops_one_station_through_the_step_inside_the_corral_clamp(api):
    """PRD §3.3: "Add the effective relief to the staffed lane rate, take whichever is smaller of that sum and the parent course's `corral_release_rate_per_min`, and round half up to two decimal places."

    Design: Difficulty/combinatorial_formula/obstacle_effective_rate_step_staffing_inside_nested_min_with_corral_cap
    """
    _venue, course, stations = _draft_course(api, 12.00, _CORRAL_CLIPPED_STATIONS)
    course_id = course["id"]
    station_1, station_2, station_3 = stations

    fx.fully_marshal(api, course_id, station_1)
    station_2_shifts = fx.fully_marshal(api, course_id, station_2)
    fx.fully_marshal(api, course_id, station_3)
    fx.water_safety_shift(api, course_id, station_2["id"], "swimmer-a")
    fx.water_safety_shift(api, course_id, station_2["id"], "swimmer-b")

    # Paper design: 12.00 at the corral ceiling, 7.50 with no relief for
    # MANDATORY, and 13.50 clipped down to the corral's 12.00.
    assert_obstacle_staffing(
        fx.read_obstacle(api, station_1["id"]), design_rate=12.00, effective_rate=12.00
    )
    assert_obstacle_staffing(
        fx.read_obstacle(api, station_2["id"]),
        staffing_state=STAFFING_MARSHALED,
        confirmed_marshal_count=2,
        design_rate=7.50,
        effective_rate=7.50,
    )
    assert_obstacle_staffing(
        fx.read_obstacle(api, station_3["id"]), design_rate=12.00, effective_rate=12.00
    )
    assert_course_capacities(
        fx.read_course(api, course_id),
        design_capacity_pph=450,
        bottleneck_capacity_pph=450,
        readiness_posture=READINESS_OPEN,
    )

    released = fx.vacate(
        api, station_2_shifts[1]["id"], reason="Marshal reassigned to the festival area"
    )
    assert released["status"] == ASSIGNMENT_VACATED

    # One marshal short of two: the 0.60 step multiplies the lanes first, so
    # 3 x 2.50 x 0.60 = 4.50 and MANDATORY still contributes no relief.
    assert_obstacle_staffing(
        fx.read_obstacle(api, station_2["id"]),
        staffing_state=STAFFING_PARTIAL,
        confirmed_marshal_count=1,
        design_rate=7.50,
        effective_rate=4.50,
    )
    # Station 3 is untouched and still pinned to the corral ceiling, not 13.50.
    assert_obstacle_staffing(
        fx.read_obstacle(api, station_3["id"]), effective_rate=12.00
    )
    assert_course_capacities(
        fx.read_course(api, course_id),
        design_capacity_pph=450,
        bottleneck_capacity_pph=270,
        readiness_posture=READINESS_OPEN,
    )


def test_staffing_factor_steps_zero_then_sixty_then_full_on_three_marshals(api):
    """PRD §3.3: "`effective_clearance_rate_per_min` starts from a **staffing factor** that steps on the confirmed marshal headcount: the factor is 1.00 when `confirmed_marshal_count` is `marshals_required` or greater; otherwise it is 0.60 when `confirmed_marshal_count` is at least half of `marshals_required` rounded up to a whole number *and* is also at least 1; and otherwise it is 0.00, which is the case whenever the station has no confirmed marshal at all."

    Design: Difficulty/combinatorial_formula/obstacle_effective_rate_step_staffing_inside_nested_min_with_corral_cap
    """
    _venue, course, stations = _draft_course(api, 20.00, _THREE_MARSHAL_STATIONS)
    course_id = course["id"]
    station_1 = stations[0]

    # The other two stations are filled first so the bottleneck tracks station 1.
    fx.fully_marshal(api, course_id, stations[1])
    fx.fully_marshal(api, course_id, stations[2])

    # Zero marshals: UNSTAFFED, factor 0.00, and the whole course reads 0 pph.
    assert_obstacle_staffing(
        fx.read_obstacle(api, station_1["id"]),
        staffing_state=STAFFING_UNSTAFFED,
        confirmed_marshal_count=0,
        design_rate=12.00,
        effective_rate=0.00,
    )
    assert_course_capacities(
        fx.read_course(api, course_id),
        design_capacity_pph=450,
        bottleneck_capacity_pph=0,
    )

    # One marshal of three: ceil(3 / 2) is 2, so 1 is still below the 0.60 rung
    # and the factor stays 0.00 even though the station now reads PARTIAL.
    fx.marshal_shift(api, course_id, station_1["id"], staff_person_id="rope-marshal-1")
    assert_obstacle_staffing(
        fx.read_obstacle(api, station_1["id"]),
        staffing_state=STAFFING_PARTIAL,
        confirmed_marshal_count=1,
        design_rate=12.00,
        effective_rate=0.00,
    )
    assert_course_capacities(fx.read_course(api, course_id), bottleneck_capacity_pph=0)

    # Two of three lands exactly on the 0.60 rung: 4 x 3.00 x 0.60 == 7.20.
    fx.marshal_shift(api, course_id, station_1["id"], staff_person_id="rope-marshal-2")
    assert_obstacle_staffing(
        fx.read_obstacle(api, station_1["id"]),
        staffing_state=STAFFING_PARTIAL,
        confirmed_marshal_count=2,
        effective_rate=7.20,
    )
    assert_course_capacities(
        fx.read_course(api, course_id),
        design_capacity_pph=450,
        bottleneck_capacity_pph=432,
    )

    # The third marshal takes the factor to 1.00 and the rate to its design value.
    fx.marshal_shift(api, course_id, station_1["id"], staff_person_id="rope-marshal-3")
    assert_obstacle_staffing(
        fx.read_obstacle(api, station_1["id"]),
        staffing_state=STAFFING_MARSHALED,
        confirmed_marshal_count=3,
        design_rate=12.00,
        effective_rate=12.00,
    )
    assert_course_capacities(
        fx.read_course(api, course_id),
        design_capacity_pph=450,
        bottleneck_capacity_pph=450,
    )


def test_bypass_relief_is_capped_at_eight_and_then_halved_by_the_step(api):
    """PRD §3.3: "Take an **effective relief** term that is 0.00 when `bypass_mode` is `NONE` or `MANDATORY`, and otherwise one half of the staffed lane rate capped at 8.00 participants per minute, whichever of the two is smaller."

    Design: Difficulty/combinatorial_formula/obstacle_effective_rate_step_staffing_inside_nested_min_with_corral_cap
    """
    _venue, course, stations = _draft_course(api, 100.00, _CAPPED_RELIEF_STATIONS)
    course_id = course["id"]
    station_1 = stations[0]

    shifts = fx.fully_marshal(api, course_id, station_1)
    fx.fully_marshal(api, course_id, stations[1])
    fx.fully_marshal(api, course_id, stations[2])

    # Lane rate 16.00, half of it is exactly the 8.00 cap, so design == 24.00 and
    # a generous corral rate of 100.00 clamps nothing.
    fully_staffed = fx.read_obstacle(api, station_1["id"])
    assert_obstacle_staffing(
        fully_staffed,
        staffing_state=STAFFING_MARSHALED,
        design_rate=24.00,
        effective_rate=24.00,
    )
    assert_rate_equals(fully_staffed["design_clearance_rate_per_min"], 24.00, "design")
    assert_course_capacities(
        fx.read_course(api, course_id),
        design_capacity_pph=1440,
        bottleneck_capacity_pph=1440,
    )

    fx.vacate(api, shifts[1]["id"], reason="Second marshal walked off the bars")

    # The 0.60 step hits the lanes first (16.00 -> 9.60) and only then is the
    # relief taken, so it falls under the cap to 4.80: 9.60 + 4.80 == 14.40.
    understaffed = fx.read_obstacle(api, station_1["id"])
    assert_obstacle_staffing(
        understaffed,
        staffing_state=STAFFING_PARTIAL,
        confirmed_marshal_count=1,
        design_rate=24.00,
        effective_rate=14.40,
    )
    assert_course_capacities(
        fx.read_course(api, course_id),
        design_capacity_pph=1440,
        bottleneck_capacity_pph=864,
    )


# ─── combinatorial_formula / the final closeout settlement ────────────────


def test_late_closeout_stacks_ceil_days_the_per_day_charge_and_the_remainder(api):
    """PRD §3.9: "When the clock has passed the deadline, take the whole seconds elapsed from the deadline to the clock, divide by 3600 to obtain hours, divide that by 24, and round up to a whole number of days — so any part of a day counts as a whole day."

    Design: Difficulty/combinatorial_formula/final_closeout_late_penalty_composes_ceil_days_min_cap_and_remainder
    """
    venue, tasks = _bond_world(
        api,
        bond_cents=1000000,
        footprint_sqm=4500,
        task_specs=_THREE_EQUAL_TASKS,
        deadline_utc=_DEADLINE_UTC,
    )
    venue_id = venue["id"]

    # Every task verified and rounded independently: 333333 x 3 == 999999.
    opening = fx.read_venue(api, venue_id)
    assert opening["bond_released_cents"] == 999999
    assert opening["bond_held_cents"] == 1

    # 2026-09-20T00:00:00Z to 2026-09-22T06:00:00Z is 194400s == 54h == 2.25 days.
    fx.set_clock(api, _FIFTY_FOUR_HOURS_LATE_UTC)
    fx.settle_bond(
        api, venue_id, fx.read_venue(api, venue_id)["version"], SETTLEMENT_FINAL
    )

    # ceil(2.25) is 3 late days, so 3 x 25000 == 75000 is charged and is well
    # under the 1000000 gross, leaving a net of 925000.
    ledger = fx.read_venue(api, venue_id)
    assert ledger["bond_forfeited_cents"] == 75000
    assert ledger["bond_released_cents"] == 925000
    assert ledger["bond_held_cents"] == 0
    assert_whole_cents(ledger["bond_forfeited_cents"], "bond_forfeited_cents")
    assert_whole_cents(ledger["bond_released_cents"], "bond_released_cents")
    assert_bond_ledger_conserved(ledger)
    assert ledger["site_posture"] == SITE_POSTURE_CLOSED_OUT

    # 925000 - 999999 == -74999, booked whole onto the earliest-created tied task.
    settled = [fx.read_task(api, task["id"])["bond_release_cents"] for task in tasks]
    assert settled == [258334, 333333, 333333], (
        f"the -74999 remainder must land on one task alone, got {settled}"
    )
    assert sum(settled) == 925000


def test_penalty_is_capped_at_the_gross_total_so_the_net_floors_at_zero(api):
    """PRD §3.9: "The late penalty is 25,000 cents (250 currency units) for each late day, capped so that it can never exceed the gross total: the penalty is whichever is smaller of the per-day charge multiplied by the late-day count, and the gross total itself."

    Design: Difficulty/combinatorial_formula/final_closeout_late_penalty_composes_ceil_days_min_cap_and_remainder
    """
    venue, tasks = _bond_world(
        api,
        # A small bond against a large late-day charge is what makes the min()
        # visible: 3 x 25000 == 75000 would otherwise overrun the whole bond.
        bond_cents=40000,
        footprint_sqm=4500,
        task_specs=[(TASK_TYPE_RESEED, 4500)],
        deadline_utc=_DEADLINE_UTC,
    )
    venue_id = venue["id"]

    opening = fx.read_venue(api, venue_id)
    assert opening["bond_released_cents"] == 40000
    assert opening["bond_held_cents"] == 0
    assert fx.read_task(api, tasks[0]["id"])["bond_release_cents"] == 40000

    fx.set_clock(api, _FIFTY_FOUR_HOURS_LATE_UTC)
    fx.settle_bond(
        api, venue_id, fx.read_venue(api, venue_id)["version"], SETTLEMENT_FINAL
    )

    # min(75000, 40000) == 40000, so the net is exactly 0 and never negative.
    ledger = fx.read_venue(api, venue_id)
    assert ledger["bond_forfeited_cents"] == 40000
    assert ledger["bond_released_cents"] == 0
    assert ledger["bond_held_cents"] == 0
    assert_bond_ledger_conserved(ledger)
    assert ledger["site_posture"] == SITE_POSTURE_CLOSED_OUT

    # The whole -40000 remainder is booked onto the sole verified task.
    assert fx.read_task(api, tasks[0]["id"])["bond_release_cents"] == 0


def test_one_second_past_the_deadline_already_costs_a_whole_late_day(api):
    """PRD §3.9: "When the clock reads at or before the deadline, the parcel is not late and the number of late days is 0."

    Design: Difficulty/combinatorial_formula/final_closeout_late_penalty_composes_ceil_days_min_cap_and_remainder
    """
    # Two parcels, one clock: A's deadline is the clock reading exactly, B's is
    # one second earlier, so only B is late and only by that one second.
    on_time_venue, on_time_tasks = _bond_world(
        api,
        bond_cents=1000000,
        footprint_sqm=4500,
        task_specs=_THREE_EQUAL_TASKS,
        deadline_utc=_DEADLINE_UTC,
        name="Cedar Flats North",
    )
    late_venue, late_tasks = _bond_world(
        api,
        bond_cents=1000000,
        footprint_sqm=4500,
        task_specs=_THREE_EQUAL_TASKS,
        deadline_utc=_ONE_SECOND_EARLIER_DEADLINE_UTC,
        name="Cedar Flats South",
    )

    fx.set_clock(api, _EXACTLY_ON_DEADLINE_UTC)
    fx.settle_bond(
        api,
        on_time_venue["id"],
        fx.read_venue(api, on_time_venue["id"])["version"],
        SETTLEMENT_FINAL,
    )
    fx.settle_bond(
        api,
        late_venue["id"],
        fx.read_venue(api, late_venue["id"])["version"],
        SETTLEMENT_FINAL,
    )

    # At the deadline exactly: 0 late days, no penalty, only the +1 remainder.
    on_time = fx.read_venue(api, on_time_venue["id"])
    assert on_time["bond_forfeited_cents"] == 0
    assert on_time["bond_released_cents"] == 1000000
    assert on_time["bond_held_cents"] == 0
    assert_bond_ledger_conserved(on_time)
    on_time_settled = [
        fx.read_task(api, task["id"])["bond_release_cents"] for task in on_time_tasks
    ]
    assert on_time_settled == [333334, 333333, 333333], (
        f"an on-time closeout books only the +1 drift, got {on_time_settled}"
    )

    # One second over: 1/3600/24 of a day rounds up to a whole day, 25000 cents.
    late = fx.read_venue(api, late_venue["id"])
    assert late["bond_forfeited_cents"] == 25000
    assert late["bond_released_cents"] == 975000
    assert late["bond_held_cents"] == 0
    assert_bond_ledger_conserved(late)
    assert late["site_posture"] == SITE_POSTURE_CLOSED_OUT
    late_settled = [
        fx.read_task(api, task["id"])["bond_release_cents"] for task in late_tasks
    ]
    assert late_settled == [308334, 333333, 333333], (
        f"975000 - 999999 == -24999 must land on one task, got {late_settled}"
    )
    assert sum(late_settled) == 975000
