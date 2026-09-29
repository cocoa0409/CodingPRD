"""Formulas whose answer depends on the order their stages compose in.

Cost is four independently rounded components summed and only then split; the
dwell requirement is a tier chosen first and a ratio taken second. Both are
wrong by a visible margin if the stages are folded together.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    LINE_OPERATOR_HEADERS,
    SANITATION_TECH_HEADERS,
    USER_QA_TECH_A,
    USER_SANITATION_TECH_B,
)

# The second line and the second run that share flume W1 with the standing run.
LINE_TWO_COMPONENTS = 10
RUN_B_PLANNED_START_AT = "2026-08-03T09:00:00Z"
RUN_B_PLANNED_END_AT = "2026-08-03T12:00:00Z"
RUN_B_CREW_SIZE = 4
RUN_B_READING_PPM = 21.0
RUN_B_CONSUMED_LB = 3000.00
RUN_B_CASES_PRODUCED = 90
RUN_B_SPIN_SECONDS = 30
RUN_B_WATER_GAL_USED = 3000.00

SHARED_LOAD_INDEX = 0.750
SHARED_TIER_PPM = 35.0
RUN_B_TOPUP_PPM = 14.0
RUN_B_REQUIRED_DWELL = 150
RUN_B_YIELD_PCT = 60.00
INDEX_AFTER_RUN_B = 0.825


def test_close_rounds_each_cost_component_to_whole_cents_before_summing_them(api):
    """The run total is reachable only by rounding the four components first.

    PRD: The run's cost is built from four components, and each is rounded half-up to whole cents *independently* before any of them are added together.
    PRD: The four rounded components are summed into `total_run_cost_cents`.
    PRD: `per_case_cost_cents` is the total divided by `cases_produced` with any fraction discarded, `cost_remainder_cents` is the total less the per-case figure multiplied by the case count, and the remainder is distributed as a waterfall over `case_sequence` ascending — each case whose `case_sequence` is less than or equal to `cost_remainder_cents` receives `per_case_cost_cents` plus one cent in its `allocated_cost_cents`, and every other case receives exactly `per_case_cost_cents`.

    Design: Difficulty/combinatorial_formula/run_cost_allocation_rounding_order_and_remainder_waterfall
    """
    world = fx.closed_world(api)
    run = world.run

    # water 4568 + sanitizer 337 + labour 83520 + energy 567.
    assert (
        c.BASE_WATER_COST_CENTS
        + c.BASE_SANITIZER_COST_CENTS
        + c.BASE_LABOUR_COST_CENTS
        + c.BASE_ENERGY_COST_CENTS
        == c.BASE_TOTAL_RUN_COST_CENTS
    )
    a.assert_cost_totals(
        run,
        total_run_cost_cents=c.BASE_TOTAL_RUN_COST_CENTS,
        per_case_cost_cents=c.BASE_PER_CASE_COST_CENTS,
        cost_remainder_cents=c.BASE_COST_REMAINDER_CENTS,
    )
    # Dividing and rounding half-up instead of flooring would bill 99 a case.
    assert run["per_case_cost_cents"] == 98
    assert run["cases_produced"] * 99 - run["total_run_cost_cents"] == 108


def test_the_remainder_waterfall_pays_one_extra_cent_to_the_lowest_case_sequences(api):
    """Case 792 carries the last extra cent and case 793 carries none.

    PRD: The sum of `allocated_cost_cents` across the run's cases therefore equals `total_run_cost_cents` exactly.
    PRD: The waterfall key is `case_sequence` and never a case identifier.

    Design: Difficulty/combinatorial_formula/run_cost_allocation_rounding_order_and_remainder_waterfall
    """
    world = fx.closed_world(api)

    boundary = fx.list_cases(api, world.run_id, {"limit": 2, "offset": 791})
    assert [row["case_sequence"] for row in boundary] == [792, 793]
    assert boundary[0]["allocated_cost_cents"] == 99
    assert boundary[1]["allocated_cost_cents"] == 98

    first = fx.list_cases(api, world.run_id, {"limit": c.MIN_LIMIT})[0]
    assert first["case_sequence"] == 1
    assert first["allocated_cost_cents"] == 99

    cases = fx.all_cases(api, world.run_id, c.CLOSE_CASES_PRODUCED)
    assert len(cases) == c.CLOSE_CASES_PRODUCED
    a.assert_cost_waterfall(
        cases, c.BASE_TOTAL_RUN_COST_CENTS, c.BASE_PER_CASE_COST_CENTS
    )
    assert (
        sum(row["allocated_cost_cents"] for row in cases) == c.BASE_TOTAL_RUN_COST_CENTS
    )


def _second_run_on_the_shared_flume(api):
    """A running standing run, plus a second run planned on L2 over the same water."""
    world = fx.running_world(api)

    second_line = fx.create_line(
        api,
        line_code="L2",
        required_disassembly_component_count=LINE_TWO_COMPONENTS,
        max_atp_rlu=c.LINE_MAX_ATP_RLU,
    )
    fx.validated_sanitation(
        api,
        second_line["id"],
        performed_by=USER_SANITATION_TECH_B,
        validated_by=USER_QA_TECH_A,
        schedule_overrides={"scheduled_for": "2026-08-03T06:00:00Z"},
        submit_overrides={
            "disassembled_component_count": LINE_TWO_COMPONENTS,
            "atp_rlu": 90,
        },
    )
    run_b = fx.plan_run(
        api,
        second_line["id"],
        world.product_id,
        world.spec_id,
        world.wash_system_id,
        planned_start_at=RUN_B_PLANNED_START_AT,
        planned_end_at=RUN_B_PLANNED_END_AT,
        crew_size=RUN_B_CREW_SIZE,
    )
    fx.set_clock(api, RUN_B_PLANNED_START_AT)
    reading = fx.create_reading(
        api,
        world.wash_system_id,
        RUN_B_PLANNED_START_AT,
        RUN_B_READING_PPM,
        headers=SANITATION_TECH_HEADERS,
        ph=6.6,
        orp_mv=680,
        turbidity_ntu=2.6,
    )
    return world, run_b, reading


def test_the_wash_tier_is_chosen_before_the_dwell_ratio_is_taken(api):
    """The dwell numerator is the tier target, never the measured concentration.

    PRD: The rounded index — not the raw quotient — then selects the tier, and all three breakpoints are inclusive on the lower side.
    PRD: Otherwise the required dwell in seconds is the greater of 90 seconds and the value obtained by multiplying 90 seconds by the tier target from step two, dividing by the latest reading's measured `free_chlorine_ppm`, and rounding that quotient *up* to the next whole second.
    PRD: A successful start stamps `started_at` from the logical clock and freezes two figures onto the run by running the four-step wash-water chemistry of §3.4 in its pinned step order: `target_ppm_at_start` receives the tier target from step two and `required_dwell_seconds_at_start` receives the dwell requirement from step three.

    Design: Difficulty/combinatorial_formula/wash_target_ppm_then_dwell_evaluation_order_pinned
    """
    world, run_b, reading = _second_run_on_the_shared_flume(api)

    # The other run's thirty thousand LEAFY pounds are the whole organic load.
    a.assert_reading_derivations(
        reading,
        organic_load_index_at_reading=SHARED_LOAD_INDEX,
        target_free_chlorine_ppm_at_reading=SHARED_TIER_PPM,
        topup_ppm_required=RUN_B_TOPUP_PPM,
        below_target=True,
    )

    started = fx.start_run(api, run_b["id"])
    assert started["run_status"] == c.RUN_RUNNING
    assert started["target_ppm_at_start"] == SHARED_TIER_PPM
    a.assert_one_decimal(started["target_ppm_at_start"], "target_ppm_at_start")
    assert started["required_dwell_seconds_at_start"] == RUN_B_REQUIRED_DWELL
    # Measured ppm on both sides of the ratio would have frozen the 90 second floor.
    assert started["required_dwell_seconds_at_start"] != c.DWELL_FLOOR_SECONDS


def test_the_frozen_dwell_requirement_is_the_gate_the_close_measures_against(api):
    """One second short of the composed dwell refuses the close.

    PRD: Then `actual_dwell_seconds` must be at least the greater of the product's `min_dwell_seconds` and the run's frozen `required_dwell_seconds_at_start`; exactly equal passes, and anything short is refused with `ERR_DWELL_TIME_INSUFFICIENT` (HTTP 422).
    PRD: Both are frozen for the life of the run and are never revised by consumption recorded later — and since the run's own consumptions are always created after `started_at`, they never contribute to the run's own frozen figures in the first place.

    Design: Difficulty/combinatorial_formula/wash_target_ppm_then_dwell_evaluation_order_pinned
    """
    world, run_b, _reading = _second_run_on_the_shared_flume(api)
    started = fx.start_run(api, run_b["id"])
    fx.consume(
        api,
        run_b["id"],
        world.receipt_id,
        started["version"],
        consumed_lb=RUN_B_CONSUMED_LB,
    )

    short_close = f.close_payload(
        actual_dwell_seconds=RUN_B_REQUIRED_DWELL - 1,
        spin_seconds=RUN_B_SPIN_SECONDS,
        water_gal_used=RUN_B_WATER_GAL_USED,
        cases_produced=RUN_B_CASES_PRODUCED,
    )
    validate_error(
        api.close_process_run(run_b["id"], short_close, LINE_OPERATOR_HEADERS),
        ApiErrorId.DWELL_TIME_INSUFFICIENT,
    )

    closed = fx.close_run(
        api,
        run_b["id"],
        actual_dwell_seconds=RUN_B_REQUIRED_DWELL,
        spin_seconds=RUN_B_SPIN_SECONDS,
        water_gal_used=RUN_B_WATER_GAL_USED,
        cases_produced=RUN_B_CASES_PRODUCED,
    )
    assert closed["run_status"] == c.RUN_CLOSED
    assert closed["yield_pct"] == RUN_B_YIELD_PCT
    a.assert_percentage(closed["yield_pct"], "yield_pct")
    assert closed["required_dwell_seconds_at_start"] == RUN_B_REQUIRED_DWELL

    # Its own pounds raise the flume's index afterwards, but not its frozen figures.
    system = fx.read_wash_system(api, world.wash_system_id)
    a.assert_wash_chemistry(
        system,
        weighted_load_lb=c.CONSUMED_LB + RUN_B_CONSUMED_LB,
        organic_load_index=INDEX_AFTER_RUN_B,
        target_free_chlorine_ppm=c.TARGET_PPM_TIER_MID,
        status=c.WASH_IN_SERVICE,
    )
