"""Queue A - rule ``dual_variant_calc``.

Three instances, each of which drives the *same* input interval through two
different declared variants of one calculation and pins both answers plus the
delta between them.
"""

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_charge_money_invariant,
    assert_instant_eq,
    assert_subset_equal,
)
from test_helpers.constants import (
    BASIS_ACTUAL,
    BASIS_STORAGE_CALENDAR,
    BASIS_STORAGE_HOURLY,
    CHARGE_FINAL,
    CHARGE_KIND_DEMURRAGE,
    CHARGE_KIND_STORAGE,
    CHARGE_PROVISIONAL,
    CLAIM_DENIED,
    CLAIM_PARTIALLY_GRANTED,
    CYCLE_A_ACTUAL_EXPIRY,
    FACILITY_KIND_INTERMODAL_TERMINAL,
    FACILITY_KIND_RAIL_YARD,
    METHOD_ORDERED_VS_CAPACITY,
    METHOD_ROLLING_AVERAGE_BASELINE,
    MOVEMENT_RELEASED,
    REASON_YARD_ARRIVAL,
    STORAGE_CLOCK_CALENDAR,
    STORAGE_CLOCK_HOURLY,
)

# --- instance 1 literals ---------------------------------------------------
# The logical clock is parked at the gate-close hour of the release date so
# that the provisional walk and the final walk share one reference instant.
CLOCK_AT_GATE_CLOSE = "2026-08-11T16:00:00.000Z"
RELEASE_AT_GATE_CLOSE = "2026-08-11T16:00:00.000Z"
PROVISIONAL_DAYS = 3
PROVISIONAL_GROSS = 47550  # 2 x 12550 + 1 x 22450
FINAL_DAYS = 4
FINAL_GROSS = 70000  # 2 x 12550 + 2 x 22450
TIER2_DELTA_CENTS = 22450

# --- instance 2 literals ---------------------------------------------------
STORAGE_ARRIVAL_AT = "2026-08-03T08:00:00.000Z"
STORAGE_RELEASE_AT = "2026-08-11T09:00:00.000Z"
STORAGE_FREE_HOURS = 48
STORAGE_DAILY_RATE_CENTS = 9000
CALENDAR_STORAGE_DAYS = 5  # 08-05..08-11 skipping the 08-08/08-09 weekend
CALENDAR_STORAGE_GROSS = 45000
HOURLY_STORAGE_DAYS = 7  # ceil((8d1h - 48h) / 24h)
HOURLY_STORAGE_GROSS = 63000

# --- instance 3 literals ---------------------------------------------------
CLUSTER_CLOCK = "2026-08-20T12:00:00.000Z"
CLUSTER_DATE = "2026-08-03"
CLUSTER_CP_INSTANTS = (
    "2026-08-03T08:00:00.000Z",
    "2026-08-03T09:00:00.000Z",
    "2026-08-03T10:00:00.000Z",
)
CLUSTER_NOTICE_INSTANTS = (
    "2026-08-03T09:00:00.000Z",
    "2026-08-03T10:00:00.000Z",
    "2026-08-03T11:00:00.000Z",
)
CLUSTER_CAPACITY = 3
UNEXEMPTED_DAYS = 14
UNEXEMPTED_GROSS = 407900  # 2 x 12550 + 3 x 22450 + 9 x 35050
CLUSTER_CHARGEABLE_DAYS = 42  # 3 x 14
ROLLING_GRANTED_DAYS = 6  # 1 + 2 + 3
ROLLING_BILLABLE_DAYS = (13, 12, 11)
ROLLING_GROSSES = (372850, 337800, 302750)


# ===========================================================================
# instance: chargeable_days_provisional_vs_final_on_industry_track_charge
# ===========================================================================
def test_provisional_chargeable_days_never_charge_the_reference_date(api):
    """The provisional variant, walked against the logical clock.

    PRD 3.5: "In the **provisional** variant, used while the cycle is still
    `CONSTRUCTIVELY_PLACED` or `ACTUALLY_PLACED` and recomputed on every notice,
    spot and refusal, the reference instant is the current logical clock and the
    reference date is *never* charged, because today is still running."

    Design: Difficulty/dual_variant_calc/chargeable_days_provisional_vs_final_on_industry_track_charge
    """
    world = fx.reference_world(api, clock=CLOCK_AT_GATE_CLOSE)
    cycle = fx.actually_placed_cycle(api, world)

    assert_instant_eq(
        cycle["free_time_expires_at"], CYCLE_A_ACTUAL_EXPIRY, "free_time_expires_at"
    )
    assert cycle["clock_basis"] == BASIS_ACTUAL

    charge = fx.charge_of_cycle(api, cycle["id"])
    assert_subset_equal(
        charge,
        {
            "status": CHARGE_PROVISIONAL,
            "charge_kind": CHARGE_KIND_DEMURRAGE,
            "chargeable_days": PROVISIONAL_DAYS,
            "billable_days": PROVISIONAL_DAYS,
            "bunching_exempt_days": 0,
            "gross_amount_cents": PROVISIONAL_GROSS,
            "credit_applied_cents": 0,
            "net_amount_cents": PROVISIONAL_GROSS,
        },
    )
    assert_charge_money_invariant(charge)


def test_final_chargeable_days_charge_the_release_date_at_gate_close(api):
    """The final variant, walked against ``released_at`` at the gate-close hour.

    PRD 3.5: "In the **final** variant, used once the cycle is `RELEASED`, the
    reference instant is `released_at`, and the release date itself counts as a
    chargeable day exactly when the time-of-day component of `released_at` is at
    or after the facility's `gate_close_hour` on the hour - that is, at or after
    `gate_close_hour` hours, 0 minutes, 0 seconds and 0 milliseconds."

    Design: Difficulty/dual_variant_calc/chargeable_days_provisional_vs_final_on_industry_track_charge
    """
    world = fx.reference_world(api, clock=CLOCK_AT_GATE_CLOSE)
    cycle = fx.actually_placed_cycle(api, world)
    provisional = fx.charge_of_cycle(api, cycle["id"])
    assert provisional["chargeable_days"] == PROVISIONAL_DAYS
    assert provisional["gross_amount_cents"] == PROVISIONAL_GROSS

    fx.release_cycle(api, cycle["id"], RELEASE_AT_GATE_CLOSE, world["customer_id"])
    released = fx.get_cycle(api, cycle["id"])

    assert released["movement_status"] == MOVEMENT_RELEASED
    assert released["chargeable_days"] == FINAL_DAYS
    assert released["early_release_days"] == 0
    # The expiry is a property of the elected clock, not of the release.
    assert_instant_eq(
        released["free_time_expires_at"], CYCLE_A_ACTUAL_EXPIRY, "free_time_expires_at"
    )

    final = fx.charge_of_cycle(api, cycle["id"])
    assert_subset_equal(
        final,
        {
            "status": CHARGE_FINAL,
            "computation_basis": BASIS_ACTUAL,
            "chargeable_days": FINAL_DAYS,
            "billable_days": FINAL_DAYS,
            "gross_amount_cents": FINAL_GROSS,
            "net_amount_cents": FINAL_GROSS,
        },
    )
    assert_charge_money_invariant(final)

    # The one day the two variants disagree about is a tier-two day.
    assert final["chargeable_days"] - provisional["chargeable_days"] == 1
    assert (
        final["gross_amount_cents"] - provisional["gross_amount_cents"]
        == TIER2_DELTA_CENTS
    )


def _storage_facility(api, kind, storage_clock_mode, operates_weekends):
    return fx.make_facility(
        api,
        kind=kind,
        storage_clock_mode=storage_clock_mode,
        operates_weekends=operates_weekends,
        storage_free_hours=STORAGE_FREE_HOURS,
        storage_daily_rate_cents=STORAGE_DAILY_RATE_CENTS,
        car_spot_capacity=3,
        switch_buffer_minutes=0,
    )


def _storage_dwell(api, world, facility):
    """Arrive, and release straight off the hold track.

    No notice is sent at all: PRD 3.5 permits the yard path from
    ``CONSTRUCTIVELY_PLACED`` and storage never reads the notice history.
    """
    cycle = fx.make_cycle(api, world, facility_id=facility["id"])
    fx.place_constructively(
        api, cycle["id"], STORAGE_ARRIVAL_AT, reason_code=REASON_YARD_ARRIVAL
    )
    fx.release_cycle(api, cycle["id"], STORAGE_RELEASE_AT, world["customer_id"])
    return fx.get_cycle(api, cycle["id"])


# ===========================================================================
# instance: storage_clock_calendar_vs_hourly_on_same_dwell_interval
# ===========================================================================
def test_calendar_storage_clock_skips_the_weekend_it_does_not_operate(api):
    """``CALENDAR_DAY_MIDNIGHT`` over the reference dwell yields five days.

    PRD 3.5: "Under `CALENDAR_DAY_MIDNIGHT`, first find the first chargeable date
    by taking the calendar date of `constructive_placement_at` and advancing it by
    `storage_free_hours` divided by 24 calendar days - two days at the default of
    48 free hours."

    Design: Difficulty/dual_variant_calc/storage_clock_calendar_vs_hourly_on_same_dwell_interval
    """
    world = fx.reference_world(api, clock=CLUSTER_CLOCK)
    yard = _storage_facility(
        api, FACILITY_KIND_RAIL_YARD, STORAGE_CLOCK_CALENDAR, False
    )
    cycle = _storage_dwell(api, world, yard)

    assert cycle["movement_status"] == MOVEMENT_RELEASED
    assert cycle["chargeable_days"] == CALENDAR_STORAGE_DAYS
    assert_instant_eq(cycle["constructive_placement_at"], STORAGE_ARRIVAL_AT)
    assert_instant_eq(cycle["released_at"], STORAGE_RELEASE_AT)

    charge = fx.charge_of_cycle(api, cycle["id"])
    assert_subset_equal(
        charge,
        {
            "status": CHARGE_FINAL,
            "charge_kind": CHARGE_KIND_STORAGE,
            "computation_basis": BASIS_STORAGE_CALENDAR,
            "chargeable_days": CALENDAR_STORAGE_DAYS,
            "billable_days": CALENDAR_STORAGE_DAYS,
            "gross_amount_cents": CALENDAR_STORAGE_GROSS,
            "net_amount_cents": CALENDAR_STORAGE_GROSS,
        },
    )
    assert_charge_money_invariant(charge)
    # PRD 3.5: storage is flat-rate, so the tariff's tier ladder is never walked.
    assert (
        charge["gross_amount_cents"]
        == CALENDAR_STORAGE_DAYS * STORAGE_DAILY_RATE_CENTS
    )


def test_hourly_storage_clock_never_stops_and_outruns_the_calendar_clock(api):
    """``HOURLY_FROM_ARRIVAL`` over the identical dwell yields seven days.

    PRD 3.5: "Under `HOURLY_FROM_ARRIVAL`, take the whole-millisecond dwell from
    `constructive_placement_at` to `released_at`, subtract `storage_free_hours`
    converted to milliseconds by multiplying by 3,600,000, floor the result at
    zero, then divide by 86,400,000 - the milliseconds in a day - and round **up**
    to the next whole number."

    Design: Difficulty/dual_variant_calc/storage_clock_calendar_vs_hourly_on_same_dwell_interval
    """
    world = fx.reference_world(api, clock=CLUSTER_CLOCK)
    terminal = _storage_facility(
        api, FACILITY_KIND_INTERMODAL_TERMINAL, STORAGE_CLOCK_HOURLY, True
    )
    hourly_cycle = _storage_dwell(api, world, terminal)

    assert hourly_cycle["chargeable_days"] == HOURLY_STORAGE_DAYS
    hourly = fx.charge_of_cycle(api, hourly_cycle["id"])
    assert_subset_equal(
        hourly,
        {
            "status": CHARGE_FINAL,
            "charge_kind": CHARGE_KIND_STORAGE,
            "computation_basis": BASIS_STORAGE_HOURLY,
            "chargeable_days": HOURLY_STORAGE_DAYS,
            "billable_days": HOURLY_STORAGE_DAYS,
            "gross_amount_cents": HOURLY_STORAGE_GROSS,
            "net_amount_cents": HOURLY_STORAGE_GROSS,
        },
    )
    assert_charge_money_invariant(hourly)
    assert (
        hourly["gross_amount_cents"] == HOURLY_STORAGE_DAYS * STORAGE_DAILY_RATE_CENTS
    )

    # The same dwell interval under the calendar clock: the two modes disagree.
    yard = _storage_facility(
        api, FACILITY_KIND_RAIL_YARD, STORAGE_CLOCK_CALENDAR, False
    )
    calendar_cycle = _storage_dwell(api, world, yard)
    calendar = fx.charge_of_cycle(api, calendar_cycle["id"])

    assert_instant_eq(
        calendar_cycle["constructive_placement_at"],
        hourly_cycle["constructive_placement_at"],
    )
    assert_instant_eq(calendar_cycle["released_at"], hourly_cycle["released_at"])
    assert calendar["chargeable_days"] == CALENDAR_STORAGE_DAYS
    assert calendar["gross_amount_cents"] == CALENDAR_STORAGE_GROSS
    assert hourly["chargeable_days"] - calendar["chargeable_days"] == 2


def _cluster_world(api):
    """Three cars all held on one date, noticed, and never spotted.

    Every provisional line is recomputed on its notice against the logical clock
    parked at ``CLUSTER_CLOCK``, which is what makes all three accrue the same
    14 chargeable days.
    """
    world = fx.reference_world(
        api,
        clock=CLUSTER_CLOCK,
        customer_overrides={"normal_daily_placement_capacity": CLUSTER_CAPACITY},
    )
    cycles = []
    for held_at, noticed_at in zip(CLUSTER_CP_INSTANTS, CLUSTER_NOTICE_INSTANTS):
        cycle = fx.make_cycle(api, world)
        fx.place_constructively(api, cycle["id"], held_at)
        fx.send_notice(api, cycle["id"], noticed_at)
        cycles.append(fx.get_cycle(api, cycle["id"]))
    for cycle in cycles:
        charge = fx.charge_of_cycle(api, cycle["id"])
        assert charge["chargeable_days"] == UNEXEMPTED_DAYS
        assert charge["gross_amount_cents"] == UNEXEMPTED_GROSS
    return world, cycles


# ===========================================================================
# instance: bunching_baseline_ordered_capacity_vs_rolling_average
# ===========================================================================
def test_ordered_vs_capacity_baseline_absorbs_the_whole_cluster_and_denies(api):
    """A capacity of exactly 3 against 3 arrivals leaves no excess at all.

    PRD 3.6: "Under `ORDERED_VS_CAPACITY`, `baseline_per_day` is simply the
    consignee's `normal_daily_placement_capacity`."  And: "When
    `exempt_days_granted` is zero the claim is `DENIED`, and no charge line is
    touched at all: `exempted_cycle_ids` stays empty and every
    `gross_amount_cents` in the cluster is left exactly where it was."

    Design: Difficulty/dual_variant_calc/bunching_baseline_ordered_capacity_vs_rolling_average
    """
    world, cycles = _cluster_world(api)
    claim = fx.file_bunching_claim(
        api,
        world["customer_id"],
        CLUSTER_DATE,
        CLUSTER_DATE,
        method=METHOD_ORDERED_VS_CAPACITY,
    )
    analyzed = fx.analyze_claim(api, claim["id"], "adj-bunching-a")

    assert_subset_equal(
        analyzed,
        {
            "status": CLAIM_DENIED,
            "method": METHOD_ORDERED_VS_CAPACITY,
            "baseline_per_day": CLUSTER_CAPACITY,
            "delivered_car_count": 3,
            "cluster_chargeable_days": CLUSTER_CHARGEABLE_DAYS,
            "exempt_days_granted": 0,
            "exempted_cycle_ids": [],
        },
    )
    assert analyzed["version"] == claim["version"] + 1

    for cycle in cycles:
        charge = fx.charge_of_cycle(api, cycle["id"])
        assert charge["bunching_exempt_days"] == 0
        assert charge["billable_days"] == UNEXEMPTED_DAYS
        assert charge["gross_amount_cents"] == UNEXEMPTED_GROSS
        assert charge["status"] == CHARGE_PROVISIONAL

    # PRD 3.6: a claim that was DENIED blocks nothing, so the window is free.
    refiled = fx.file_bunching_claim(
        api,
        world["customer_id"],
        CLUSTER_DATE,
        CLUSTER_DATE,
        method=METHOD_ROLLING_AVERAGE_BASELINE,
    )
    assert refiled["id"] != claim["id"]


def test_rolling_average_baseline_of_zero_exempts_every_car_in_the_cluster(api):
    """A brand-new consignee has no history, so the baseline is zero.

    PRD 3.6: "Under `ROLLING_AVERAGE_BASELINE`, count the consignee's placement
    cycles whose `movement_status` is not `VOIDED` and whose
    `constructive_placement_at` falls on one of the seven calendar dates
    immediately preceding the date of `cluster_window_start`, then divide that
    count by 7 and discard any remainder."

    Design: Difficulty/dual_variant_calc/bunching_baseline_ordered_capacity_vs_rolling_average
    """
    world, cycles = _cluster_world(api)
    claim = fx.file_bunching_claim(
        api,
        world["customer_id"],
        CLUSTER_DATE,
        CLUSTER_DATE,
        method=METHOD_ROLLING_AVERAGE_BASELINE,
    )
    analyzed = fx.analyze_claim(api, claim["id"], "adj-bunching-b")

    assert_subset_equal(
        analyzed,
        {
            "status": CLAIM_PARTIALLY_GRANTED,
            "baseline_per_day": 0,
            "delivered_car_count": 3,
            "cluster_chargeable_days": CLUSTER_CHARGEABLE_DAYS,
            "exempt_days_granted": ROLLING_GRANTED_DAYS,
        },
    )
    # Dates ascending, then constructive_placement_at ascending within the date.
    assert analyzed["exempted_cycle_ids"] == [cycle["id"] for cycle in cycles]

    for position, cycle in enumerate(cycles, start=1):
        charge = fx.charge_of_cycle(api, cycle["id"])
        expected_gross = ROLLING_GROSSES[position - 1]
        assert_subset_equal(
            charge,
            {
                "chargeable_days": UNEXEMPTED_DAYS,
                "bunching_exempt_days": position,
                "billable_days": ROLLING_BILLABLE_DAYS[position - 1],
                "gross_amount_cents": expected_gross,
                "net_amount_cents": expected_gross,
            },
        )
        assert_charge_money_invariant(charge)
