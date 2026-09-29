"""Breakpoints one tenth of a unit apart, and a tolerance one case wide.

Both receiving breakpoints are strictly greater-than, and the yield tolerance is
compared against the two-decimal rounded percentage, so each of these tests
pins the value on the boundary and the value one step past it.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    LINE_OPERATOR_HEADERS,
    QA_MANAGER_HEADERS,
    QA_TECHNICIAN_HEADERS,
)

# The lot whose four loads straddle both temperature breakpoints.
BOUNDARY_LOT_OVERRIDES = {
    "grower_code": "GRW-400",
    "ranch_block": "B1",
    "harvest_datetime": "2026-08-01T22:00:00Z",
    "water_source": c.WATER_MUNICIPAL,
}
BOUNDARY_LOAD_GROSS_LB = 10000.00
BOUNDARY_LOAD_TRIM_LB = 1000.00
BOUNDARY_LOAD_ACCEPTED_LB = 9000.00
WARM_LOAD_JUSTIFICATION = (
    "Load tempered to 3.1 C in 20 minutes under CCP-2 deviation log 9107"
)
TRAILING_AFTER_ONE_OUT_OF_SPEC_LOAD = 90

# The yield boundary: 824 cases fall 0.07 points short, 825 land exactly on it.
CASES_BELOW_TOLERANCE = 824
CASES_AT_TOLERANCE = 825
OUTPUT_AT_TOLERANCE_LB = 16500.00


def _four_loads_across_both_breakpoints(api):
    """One approved lot and its four loads at 3.3, 3.4, 4.4 and 4.5 degrees."""
    fx.set_clock(api, c.CLOCK_MASTER_DATA)
    lot = fx.approved_grower_lot(api, **BOUNDARY_LOT_OVERRIDES)
    a.assert_risk_scores(lot, preharvest=c.RISK_START, trailing=c.RISK_START,
                         status=c.LOT_APPROVED)

    loads = []
    for minute, pulp_temp_c in enumerate((3.3, 3.4, 4.4, 4.5), start=1):
        loads.append(
            fx.create_receipt(
                api,
                lot["id"],
                received_at=f"2026-08-02T05:0{minute}:00Z",
                pulp_temp_c=pulp_temp_c,
                gross_weight_lb=BOUNDARY_LOAD_GROSS_LB,
                tare_weight_lb=0.00,
            )
        )
    return lot, loads


def test_both_pulp_temperature_breakpoints_are_strictly_greater_than(api):
    """3.3 is in spec, 3.4 is marginal, 4.4 is still marginal, 4.5 is out.

    PRD: A pulp temperature greater than 4.4 degrees Celsius grades the load `OUT_OF_SPEC`. Otherwise, a pulp temperature greater than 3.3 degrees Celsius grades it `MARGINAL`. Otherwise the load grades `IN_SPEC`.
    PRD: Both comparisons are strict, so a load arriving at exactly 4.4 degrees is `MARGINAL` rather than `OUT_OF_SPEC`, and a load at exactly 3.3 degrees is `IN_SPEC` rather than `MARGINAL`.
    PRD: The resulting grade is written to `temp_grade` and immediately frozen onto the load as a day count in `shelf_life_deduction_days`: zero days for `IN_SPEC`, one day for `MARGINAL`, and two days for `OUT_OF_SPEC`.

    Design: Difficulty/boundary_precision_check/receipt_pulp_temp_at_exact_max_is_marginal
    """
    _lot, loads = _four_loads_across_both_breakpoints(api)
    at_warn, past_warn, at_max, past_max = loads

    assert at_warn["temp_grade"] == c.TEMP_IN_SPEC
    assert at_warn["shelf_life_deduction_days"] == c.SHELF_LIFE_DEDUCTION_IN_SPEC
    assert past_warn["temp_grade"] == c.TEMP_MARGINAL
    assert past_warn["shelf_life_deduction_days"] == c.SHELF_LIFE_DEDUCTION_MARGINAL
    assert at_max["temp_grade"] == c.TEMP_MARGINAL
    assert at_max["shelf_life_deduction_days"] == c.SHELF_LIFE_DEDUCTION_MARGINAL
    assert past_max["temp_grade"] == c.TEMP_OUT_OF_SPEC
    assert past_max["shelf_life_deduction_days"] == c.SHELF_LIFE_DEDUCTION_OUT_OF_SPEC

    for load in loads:
        a.assert_one_decimal(load["pulp_temp_c"], "pulp_temp_c")
        assert load["net_weight_lb"] == BOUNDARY_LOAD_GROSS_LB
        assert load["status"] == c.RECEIPT_PENDING_INSPECTION


def test_only_the_load_past_the_maximum_needs_a_manager_override(api):
    """The 4.4 load is accepted plainly; the 4.5 load costs the grower ten points.

    PRD: First, a load graded `OUT_OF_SPEC` may not be accepted at all unless the acting `X-User-Role` is `QAManager` *and* `override_justification` is a non-empty string; otherwise the acceptance is refused with `ERR_RECEIPT_TEMP_OUT_OF_SPEC` (HTTP 422).
    PRD: The server sets `accepted_lb` to the net weight less the declared trim loss, rounded half-up to two decimal places, sets `remaining_lb` to that same figure — the load's full drawable balance — and stamps `dispositioned_by_user_id` with the acting `X-User-ID`.
    PRD: `out_of_spec_receipt_count` is the number of this lot's loads whose `temp_grade` is `OUT_OF_SPEC` and whose `status` is not `REJECTED`; a rejected load never counts against the grower, however warm it arrived.

    Design: Difficulty/boundary_precision_check/receipt_pulp_temp_at_exact_max_is_marginal
    """
    lot, loads = _four_loads_across_both_breakpoints(api)
    at_max, past_max = loads[2], loads[3]

    marginal = fx.disposition_receipt(
        api, at_max["id"], c.DECISION_ACCEPT, trim_loss_lb=BOUNDARY_LOAD_TRIM_LB
    )
    assert marginal["status"] == c.RECEIPT_ACCEPTED
    assert marginal["accepted_lb"] == BOUNDARY_LOAD_ACCEPTED_LB
    assert marginal["remaining_lb"] == BOUNDARY_LOAD_ACCEPTED_LB

    validate_error(
        api.disposition_raw_receipt(
            past_max["id"],
            f.disposition_payload(
                c.DECISION_ACCEPT, trim_loss_lb=BOUNDARY_LOAD_TRIM_LB
            ),
            QA_TECHNICIAN_HEADERS,
        ),
        ApiErrorId.RECEIPT_TEMP_OUT_OF_SPEC,
    )
    assert (
        fx.read_receipt(api, past_max["id"])["status"] == c.RECEIPT_PENDING_INSPECTION
    )

    overridden = fx.disposition_receipt(
        api,
        past_max["id"],
        c.DECISION_ACCEPT,
        trim_loss_lb=BOUNDARY_LOAD_TRIM_LB,
        override_justification=WARM_LOAD_JUSTIFICATION,
        headers=QA_MANAGER_HEADERS,
    )
    assert overridden["status"] == c.RECEIPT_ACCEPTED
    assert overridden["accepted_lb"] == BOUNDARY_LOAD_ACCEPTED_LB

    scored = fx.read_grower_lot(api, lot["id"])
    assert scored["out_of_spec_receipt_count"] == 1
    a.assert_risk_scores(
        scored,
        preharvest=c.RISK_START,
        trailing=TRAILING_AFTER_ONE_OUT_OF_SPEC_LOAD,
        status=c.LOT_APPROVED,
    )


def test_one_case_short_of_the_minimum_yield_refuses_the_close(api):
    """824 cases round to 54.93 per cent, which is below the product floor.

    PRD: Finally the computed yield must fall within tolerance, as described below, or the close is refused with `ERR_YIELD_OUT_OF_TOLERANCE` (HTTP 422).
    PRD: The tolerance test is then made against that rounded percentage, never against the unrounded quotient: `yield_pct` must be at least the product's `min_yield_pct` and at most 100.00.

    Design: Difficulty/boundary_precision_check/yield_at_exact_product_minimum_passes
    """
    world = fx.build_world(api, stop_after=fx.STOP_CLOCK_AT_CLOSE)
    assert world.product["min_yield_pct"] == c.PRODUCT_MIN_YIELD_PCT
    assert fx.read_run(api, world.run_id)["input_lb"] == c.CONSUMED_LB

    validate_error(
        api.close_process_run(
            world.run_id,
            f.close_payload(cases_produced=CASES_BELOW_TOLERANCE),
            LINE_OPERATOR_HEADERS,
        ),
        ApiErrorId.YIELD_OUT_OF_TOLERANCE,
    )

    # A refused close leaves the run running, unpacked and uncosted.
    refused = fx.read_run(api, world.run_id)
    assert refused["run_status"] == c.RUN_RUNNING
    assert refused["closed_at"] is None
    assert refused["cases_produced"] is None
    assert refused["output_lb"] is None
    assert refused["yield_pct"] is None
    assert refused["total_run_cost_cents"] is None
    assert fx.list_cases(api, world.run_id) == [], "no case was packed"


def test_a_yield_of_exactly_the_product_minimum_closes_the_run(api):
    """825 cases give exactly 55.00 per cent, and exactly equal passes.

    PRD: A yield exactly equal to the product minimum passes, and a yield of exactly 100.00 passes; a yield above 100.00 cannot be physical, since a run cannot pack more finished pounds than the raw pounds it consumed.
    PRD: `output_lb` is `cases_produced` multiplied by the specification's `case_net_weight_lb`, rounded half-up to two decimal places. `yield_pct` is the output pounds divided by the run's `input_lb`, multiplied by 100, rounded half-up to exactly two decimal places.

    Design: Difficulty/boundary_precision_check/yield_at_exact_product_minimum_passes
    """
    world = fx.build_world(api, stop_after=fx.STOP_CLOCK_AT_CLOSE)

    closed = fx.close_run(api, world.run_id, cases_produced=CASES_AT_TOLERANCE)
    assert closed["run_status"] == c.RUN_CLOSED
    assert closed["cases_produced"] == CASES_AT_TOLERANCE
    assert closed["output_lb"] == OUTPUT_AT_TOLERANCE_LB
    assert closed["yield_pct"] == c.PRODUCT_MIN_YIELD_PCT
    a.assert_pounds(closed["output_lb"], "output_lb")
    a.assert_percentage(closed["yield_pct"], "yield_pct")

    # The pack really exists: one case per unit of cases_produced.
    cases = fx.all_cases(api, world.run_id, CASES_AT_TOLERANCE)
    assert len(cases) == CASES_AT_TOLERANCE
    assert cases[-1]["case_sequence"] == CASES_AT_TOLERANCE
    a.assert_cost_waterfall(
        cases, closed["total_run_cost_cents"], closed["per_case_cost_cents"]
    )
