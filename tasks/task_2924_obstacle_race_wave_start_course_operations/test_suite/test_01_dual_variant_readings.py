"""Difficulty/dual_variant_calc — the two readings that diverge on the same row.

Two instances live here, both cases where one stored quantity exists twice over
and the two copies are produced by *different* recipes over identical inputs:

* `entry_elapsed_provisional_gun_reading_vs_official_chip_reading` — the same
  attempt card yields a provisional reading measured from the gun and charging
  every penalty, and an official reading measured from the runner's own mat
  crossing that suppresses the `SKIPPED_UNMARSHALED` penalty.
* `restoration_bond_per_task_rounding_vs_final_closeout_rounding` — the same
  money and the same areas, rounded per task and then summed, versus summed and
  then rounded once, with the drift booked onto a single task at closeout.
"""

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_bond_ledger_conserved,
    assert_course_capacities,
    assert_entry_state,
    assert_instant_equals,
    assert_timing,
    assert_wave_state,
    assert_whole_cents,
)
from test_helpers.constants import (
    BYPASS_MODE_MANDATORY,
    BYPASS_MODE_NONE,
    BYPASS_MODE_TIMED_PENALTY,
    BYPASS_POLICY_ALLOWED_WITH_PENALTY,
    BYPASS_POLICY_DQ_ON_BYPASS,
    COURSE_COMPLETED,
    DIVISION_COMPETITIVE,
    DIVISION_OPEN,
    INSPECTION_VERIFIED,
    OUTCOME_COMPLETED,
    OUTCOME_FAILED_PENALTY,
    OUTCOME_SKIPPED_UNMARSHALED,
    PROGRESS_FINISHED,
    RELEASE_CLOSED,
    RESULT_OFFICIAL,
    SCORING_CHIP_TIME,
    SCORING_GUN_TIME,
    SERVICE_SPECTATOR_ZONE,
    SETTLEMENT_FINAL,
    SETTLEMENT_PROGRESSIVE,
    SITE_POSTURE_CLOSED_OUT,
    SITE_POSTURE_OPEN,
    TASK_TYPE_DEBRIS_SWEEP,
    TASK_TYPE_DECOMPACT,
    TASK_TYPE_RESEED,
    TERRAIN_FIELD,
    WATER_ACCESS_NONE,
)

# ─── Private literals this file needs and constants.py does not name ─────

_VALID_UNTIL_UTC = "2026-12-31T00:00:00.000Z"
_RESTORATION_DEADLINE_UTC = "2026-09-20T00:00:00.000Z"
_GUN_UTC = "2026-09-12T08:00:00.000Z"
_CHIP_START_UTC = "2026-09-12T08:00:37.000Z"
_STATION_1_UTC = "2026-09-12T08:05:00.000Z"
_STATION_2_UTC = "2026-09-12T08:20:00.000Z"
_STATION_3_UTC = "2026-09-12T08:35:00.000Z"
_FINISH_UTC = "2026-09-12T08:47:12.000Z"

#: The three stations of the difficulty index's canonical course. Ratings 3, 5
#: and 7 rise by 2 twice, so the progression score is 2.00 and no pair drops.
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


def _published_staffed_course(api):
    """A PUBLISHED 3-station course, fully marshaled 2+2+1, 2 swimmers, 1 medic.

    Returns (venue, course, stations, marshal_shifts_by_station_index).
    """
    venue, _permit = fx.permitted_venue(
        api,
        venue_kwargs={"protected_acreage_sqm": 2000, "restoration_bond_cents": 1000000},
        water_use_allowed=True,
        max_disturbed_area_sqm=5000,
        quiet_hours_start_hour_utc=22,
        quiet_hours_end_hour_utc=6,
        valid_until_utc=_VALID_UNTIL_UTC,
        restoration_deadline_utc=_RESTORATION_DEADLINE_UTC,
    )
    course, stations = fx.three_station_course(
        api,
        venue["id"],
        course_kwargs={
            "total_distance_m": 10000,
            "corral_release_rate_per_min": 12.00,
            "corral_throughput_capacity": 200,
        },
        station_kwargs=_STATIONS,
    )
    fx.published_course(api, course["id"])
    shifts = {
        station["station_index"]: fx.fully_marshal(api, course["id"], station)
        for station in stations
    }
    fx.water_safety_shift(api, course["id"], stations[1]["id"], "swimmer-a")
    fx.water_safety_shift(api, course["id"], stations[1]["id"], "swimmer-b")
    fx.medic_shift(api, course["id"], "medic-a")
    return venue, course, stations, shifts


def _started_wave(api, course_id, division_type, scoring_mode, bypass_policy, offset):
    """Schedule, lock, release and fire one 112-strong heat at exactly the gun.

    Returns (wave, entry) with the entry advanced to STARTED and its
    `chip_start_utc` computed from `offset`.
    """
    division = fx.division(
        api,
        name="Elite Competitive",
        division_type=division_type,
        bypass_policy=bypass_policy,
        scoring_mode=scoring_mode,
        min_age=18,
        team_size_min=1,
        team_size_max=1,
    )
    wave = fx.wave(
        api,
        course_id,
        division["id"],
        scheduled_start_utc=_GUN_UTC,
        capacity=112,
    )
    entry = fx.checked_in_entry(
        api, wave["id"], bib_number=101, chip_start_offset_seconds=offset
    )
    fx.lock_roster(api, wave["id"])
    fx.release(api, wave["id"])
    fx.set_clock(api, _GUN_UTC)
    fx.start(api, wave["id"])
    return wave, entry


def _bond_world(api, bond_cents, footprint_sqm, task_specs, deadline_utc):
    """A parcel whose only disturbance is one spectator zone, plus VERIFIED tasks.

    `task_specs` is a list of (task_type, area_sqm) pairs opened and inspected in
    order, so the first-created task is also the earliest `created_at`.
    """
    venue, _permit = fx.permitted_venue(
        api,
        venue_kwargs={
            "name": "Cedar Flats",
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


# ─── dual_variant_calc / entry elapsed: gun reading vs chip reading ───────


def test_official_chip_reading_diverges_from_the_provisional_gun_reading(api):
    """PRD §3.8: "When the division's `scoring_mode` is `CHIP_TIME`, the base is the **chip base**: the exact number of whole seconds between the entry's own `chip_start_utc` and its `finish_recorded_utc`, so a runner who crossed the start mat forty seconds behind the gun is not charged for those forty seconds."

    Design: Difficulty/dual_variant_calc/entry_elapsed_provisional_gun_reading_vs_official_chip_reading
    """
    _venue, course, stations, shifts = _published_staffed_course(api)
    wave, entry = _started_wave(
        api,
        course["id"],
        DIVISION_COMPETITIVE,
        SCORING_CHIP_TIME,
        BYPASS_POLICY_DQ_ON_BYPASS,
        offset=37,
    )
    entry_id = entry["id"]

    # The gun fired at 08:00:00 and this runner's mat crossing is 37s behind it.
    started = fx.read_entry(api, entry_id)
    assert_instant_equals(started["chip_start_utc"], _CHIP_START_UTC, "chip_start_utc")

    fx.set_clock(api, _STATION_1_UTC)
    fx.attempt(api, entry_id, stations[0]["id"], OUTCOME_COMPLETED)
    fx.set_clock(api, _STATION_2_UTC)
    fx.attempt(api, entry_id, stations[1]["id"], OUTCOME_FAILED_PENALTY)

    # Station 3 loses its only marshal, so the field is waved through it.
    fx.vacate(api, shifts[3][0]["id"], reason="Marshal pulled for heat illness")
    fx.set_clock(api, _STATION_3_UTC)
    fx.attempt(api, entry_id, stations[2]["id"], OUTCOME_SKIPPED_UNMARSHALED)

    fx.set_clock(api, _FINISH_UTC)
    finished = fx.finish(api, entry_id)

    # The provisional reading: gun base 2832s plus all three penalties (0+120+90).
    assert_timing(
        finished,
        provisional_penalty_seconds=210,
        provisional_elapsed_seconds=3042,
    )

    fx.close(api, wave["id"])
    official = fx.read_entry(api, entry_id)

    # The official reading: chip base 2795s plus only the FAILED_PENALTY 120s.
    assert_timing(
        official,
        provisional_penalty_seconds=210,
        provisional_elapsed_seconds=3042,
        official_penalty_seconds=120,
        official_elapsed_seconds=2915,
    )
    assert (
        official["provisional_elapsed_seconds"] - official["official_elapsed_seconds"]
        == 127
    ), "the two readings must diverge by the 37s mat offset plus the 90s waved-through penalty"
    assert_entry_state(
        official, progress_status=PROGRESS_FINISHED, result_status=RESULT_OFFICIAL
    )
    assert_wave_state(fx.read_wave(api, wave["id"]), release_status=RELEASE_CLOSED)
    assert_course_capacities(fx.read_course(api, course["id"]), status=COURSE_COMPLETED)


def test_gun_time_division_anchors_the_official_reading_on_the_gun_instead(api):
    """PRD §3.8: "When the division's `scoring_mode` is `GUN_TIME`, the base is the gun base, measured from the heat's `actual_start_utc` exactly as in the provisional reading."

    Design: Difficulty/dual_variant_calc/entry_elapsed_provisional_gun_reading_vs_official_chip_reading
    """
    _venue, course, stations, shifts = _published_staffed_course(api)
    wave, entry = _started_wave(
        api,
        course["id"],
        DIVISION_OPEN,
        SCORING_GUN_TIME,
        BYPASS_POLICY_ALLOWED_WITH_PENALTY,
        offset=37,
    )
    entry_id = entry["id"]

    fx.set_clock(api, _STATION_1_UTC)
    fx.attempt(api, entry_id, stations[0]["id"], OUTCOME_COMPLETED)
    fx.set_clock(api, _STATION_2_UTC)
    fx.attempt(api, entry_id, stations[1]["id"], OUTCOME_FAILED_PENALTY)
    fx.vacate(api, shifts[3][0]["id"], reason="Marshal pulled for heat illness")
    fx.set_clock(api, _STATION_3_UTC)
    fx.attempt(api, entry_id, stations[2]["id"], OUTCOME_SKIPPED_UNMARSHALED)
    fx.set_clock(api, _FINISH_UTC)
    fx.finish(api, entry_id)
    fx.close(api, wave["id"])

    official = fx.read_entry(api, entry_id)
    # The mat offset is still recorded, but a GUN_TIME division does not credit
    # it: the official base is the same 2832s gun base the provisional used.
    assert_instant_equals(official["chip_start_utc"], _CHIP_START_UTC, "chip_start_utc")
    assert_timing(
        official,
        provisional_penalty_seconds=210,
        provisional_elapsed_seconds=3042,
        official_penalty_seconds=120,
        official_elapsed_seconds=2952,
    )
    assert (
        official["provisional_elapsed_seconds"] - official["official_elapsed_seconds"]
        == 90
    ), "on a shared gun base the readings may diverge only by the suppressed penalty"
    assert_entry_state(official, result_status=RESULT_OFFICIAL)


def test_waved_through_penalty_is_the_only_divergence_at_a_zero_mat_offset(api):
    """PRD §3.8: "An attempt whose `outcome` is `SKIPPED_UNMARSHALED` also contributes 0 seconds, on the principle that the producer cannot penalise a runner for a station it failed to marshal."

    Design: Difficulty/dual_variant_calc/entry_elapsed_provisional_gun_reading_vs_official_chip_reading
    """
    _venue, course, stations, shifts = _published_staffed_course(api)
    wave, entry = _started_wave(
        api,
        course["id"],
        DIVISION_COMPETITIVE,
        SCORING_CHIP_TIME,
        BYPASS_POLICY_DQ_ON_BYPASS,
        offset=0,
    )
    entry_id = entry["id"]

    # A zero offset collapses the chip base onto the gun base, so the penalty
    # set is the only remaining difference between the two variants.
    started = fx.read_entry(api, entry_id)
    assert_instant_equals(started["chip_start_utc"], _GUN_UTC, "chip_start_utc")

    fx.set_clock(api, _STATION_1_UTC)
    fx.attempt(api, entry_id, stations[0]["id"], OUTCOME_COMPLETED)
    fx.set_clock(api, _STATION_2_UTC)
    fx.attempt(api, entry_id, stations[1]["id"], OUTCOME_FAILED_PENALTY)
    fx.vacate(api, shifts[3][0]["id"], reason="Station 3 left unattended")
    fx.set_clock(api, _STATION_3_UTC)
    fx.attempt(api, entry_id, stations[2]["id"], OUTCOME_SKIPPED_UNMARSHALED)
    fx.set_clock(api, _FINISH_UTC)
    fx.finish(api, entry_id)
    fx.close(api, wave["id"])

    official = fx.read_entry(api, entry_id)
    assert_timing(
        official,
        provisional_penalty_seconds=210,
        provisional_elapsed_seconds=3042,
        official_penalty_seconds=120,
        official_elapsed_seconds=2952,
    )
    assert (
        official["provisional_penalty_seconds"] - official["official_penalty_seconds"]
        == 90
    ), "the official penalty set must drop exactly the 90s SKIPPED_UNMARSHALED charge"


# ─── dual_variant_calc / bond: per-task rounding vs closeout rounding ─────


def test_final_closeout_rounds_once_and_books_the_stranded_cent_on_one_task(api):
    """PRD §3.9: "It then computes the settlement in a deliberately different rounding order from the per-task computation: sum the `area_sqm` of the verified tasks first, multiply the parcel's `restoration_bond_cents` by that summed verified area, divide by the parcel's `disturbed_area_sqm`, and round half up to whole cents *once*."

    Design: Difficulty/dual_variant_calc/restoration_bond_per_task_rounding_vs_final_closeout_rounding
    """
    venue, tasks = _bond_world(
        api,
        bond_cents=1000000,
        footprint_sqm=4500,
        task_specs=[
            (TASK_TYPE_RESEED, 1500),
            (TASK_TYPE_DECOMPACT, 1500),
            (TASK_TYPE_DEBRIS_SWEEP, 1500),
        ],
        deadline_utc=_RESTORATION_DEADLINE_UTC,
    )
    venue_id = venue["id"]

    # The per-task variant: each 1/3 share rounds to 333333 independently, so the
    # rounded shares sum to 999999 and one cent is stranded in bond_held_cents.
    before = fx.read_venue(api, venue_id)
    assert before["disturbed_area_sqm"] == 4500
    assert before["bond_released_cents"] == 999999
    assert before["bond_held_cents"] == 1
    assert before["bond_forfeited_cents"] == 0
    assert_bond_ledger_conserved(before)
    for task in tasks:
        share = fx.read_task(api, task["id"])["bond_release_cents"]
        assert_whole_cents(share, "bond_release_cents")
        assert share == 333333, f"per-task share: expected 333333, got {share}"

    fx.settle_bond(api, venue_id, before["version"], SETTLEMENT_FINAL)

    # The closeout variant: 1000000 * 4500 / 4500 rounds once to 1000000, and the
    # +1 remainder lands on the largest-area task, tie-broken by created_at.
    after = fx.read_venue(api, venue_id)
    assert after["bond_released_cents"] == 1000000
    assert after["bond_forfeited_cents"] == 0
    assert after["bond_held_cents"] == 0
    assert_bond_ledger_conserved(after)
    assert after["site_posture"] == SITE_POSTURE_CLOSED_OUT

    settled = [fx.read_task(api, task["id"])["bond_release_cents"] for task in tasks]
    assert settled == [333334, 333333, 333333], (
        f"the remainder must land on the earliest-created tied task, got {settled}"
    )
    assert sum(settled) == 1000000


def test_progressive_settlement_keeps_the_per_task_rounding_order(api):
    """PRD §3.9: "It recomputes the parcel's `bond_released_cents` as the sum of `bond_release_cents` over the remediation tasks currently reading `VERIFIED` — tasks reading `PENDING` or `REMEDIATION_REQUIRED` contribute nothing — leaves `bond_forfeited_cents` as it stands, and sets `bond_held_cents` to `restoration_bond_cents` minus `bond_released_cents` minus `bond_forfeited_cents`."

    Design: Difficulty/dual_variant_calc/restoration_bond_per_task_rounding_vs_final_closeout_rounding
    """
    venue, tasks = _bond_world(
        api,
        bond_cents=1000000,
        footprint_sqm=4500,
        task_specs=[
            (TASK_TYPE_RESEED, 1500),
            (TASK_TYPE_DECOMPACT, 1500),
            (TASK_TYPE_DEBRIS_SWEEP, 1500),
        ],
        deadline_utc=_RESTORATION_DEADLINE_UTC,
    )
    venue_id = venue["id"]

    first = fx.settle_bond(
        api, venue_id, fx.read_venue(api, venue_id)["version"], SETTLEMENT_PROGRESSIVE
    )
    # A progressive snapshot sums the already-rounded per-task figures, so it
    # reproduces the 999999 drift rather than reconciling it away.
    assert first["bond_released_cents"] == 999999
    assert first["bond_held_cents"] == 1
    assert first["bond_forfeited_cents"] == 0
    assert first["site_posture"] == SITE_POSTURE_OPEN
    assert_bond_ledger_conserved(first)

    # Repeating it is a valid operation and must not move the drift either.
    second = fx.settle_bond(api, venue_id, first["version"], SETTLEMENT_PROGRESSIVE)
    assert second["bond_released_cents"] == 999999
    assert second["bond_held_cents"] == 1
    assert second["site_posture"] == SITE_POSTURE_OPEN
    for task in tasks:
        assert fx.read_task(api, task["id"])["bond_release_cents"] == 333333


def test_closeout_remainder_lands_on_the_greatest_area_task_not_the_oldest(api):
    """PRD §3.9: "The remainder is added to the `bond_release_cents` of exactly one task: the verified task with the greatest `area_sqm`, and where two or more tie on area, the one with the earliest `created_at`."

    Design: Difficulty/dual_variant_calc/restoration_bond_per_task_rounding_vs_final_closeout_rounding
    """
    venue, tasks = _bond_world(
        api,
        bond_cents=1000000,
        footprint_sqm=4500,
        # The greatest area is opened last, so "greatest area" and "earliest
        # created_at" point at different rows and only one of them can win.
        task_specs=[
            (TASK_TYPE_RESEED, 1500),
            (TASK_TYPE_DECOMPACT, 1000),
            (TASK_TYPE_DEBRIS_SWEEP, 2000),
        ],
        deadline_utc=_RESTORATION_DEADLINE_UTC,
    )
    venue_id = venue["id"]

    before = [fx.read_task(api, task["id"])["bond_release_cents"] for task in tasks]
    assert before == [333333, 222222, 444444], (
        f"independent per-task rounding: expected [333333, 222222, 444444], got {before}"
    )
    assert sum(before) == 999999

    fx.settle_bond(
        api, venue_id, fx.read_venue(api, venue_id)["version"], SETTLEMENT_FINAL
    )

    after = [fx.read_task(api, task["id"])["bond_release_cents"] for task in tasks]
    assert after == [333333, 222222, 444445], (
        f"the +1 remainder must land on the 2000 sqm task, got {after}"
    )
    ledger = fx.read_venue(api, venue_id)
    assert ledger["bond_released_cents"] == 1000000
    assert ledger["bond_held_cents"] == 0
    assert ledger["bond_forfeited_cents"] == 0
    assert_bond_ledger_conserved(ledger)
    assert ledger["site_posture"] == SITE_POSTURE_CLOSED_OUT
