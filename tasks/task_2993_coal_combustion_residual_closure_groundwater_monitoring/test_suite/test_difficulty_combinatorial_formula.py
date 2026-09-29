"""Multi-step formulas whose pinned rounding order and pinned band selection matter."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import assertions as a
from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    EVAL_VERDICT_SSI,
    METHOD_CLOSURE_IN_PLACE,
    PHASE_ASSESSMENT,
)
from test_helpers.test_users import COMPLIANCE_OFFICER_HEADERS, UTILITY_ADMIN_HEADERS

# The care-stream payload whose two present values are only reachable by
# discounting and rounding year by year before summing.
CARE_STREAM_PLAN = {
    "in_place_capital_usd_cents": 2050000000,
    "in_place_annual_care_usd_cents": 20000000,
    "removal_capital_usd_cents": 2450000000,
    "removal_annual_care_usd_cents": 2000000,
    "care_period_years": 30,
}


def case_program_in_assessment(api):
    """Escalate a program out of DETECTION so a remedy cost basis may be filed."""
    return fixtures.seed_ssi_escalation(api, "IMP-0004", "EV-1")


def test_each_care_year_is_rounded_to_whole_cents_before_the_years_are_summed(api):
    """Summing the exact fractions and rounding once lands two cents low on both methods.

    PRD: First, in the discounted closure cost, each individual care year's discounted payment is rounded to whole cents before any summation, and only the rounded per-year amounts are added together; summing the exact fractional amounts and rounding the total at the end is a different and incorrect figure.
    Design: Difficulty/combinatorial_formula/care_stream_pv_rounds_each_year_before_summation
    """
    unit = fixtures.create_unit(api, "IMP-0003")

    plan = get_success_data(
        api.create_closure_plan(
            factories.closure_plan_payload(
                unit["id"], "CP-0002", METHOD_CLOSURE_IN_PLACE, **CARE_STREAM_PLAN
            ),
            UTILITY_ADMIN_HEADERS,
        )
    )

    a.assert_cents(plan["in_place_pv_usd_cents"], 2442008829, "in_place_pv_usd_cents")
    a.assert_cents(plan["removal_pv_usd_cents"], 2489200885, "removal_pv_usd_cents")
    # The round-once-at-the-end figures, which the pinned order must not produce.
    assert plan["in_place_pv_usd_cents"] != 2442008827
    assert plan["removal_pv_usd_cents"] != 2489200883


def test_the_capital_outlay_is_a_year_zero_bucket_that_is_never_discounted(api):
    """Subtracting the capital leaves exactly the discounted 30-year care stream.

    PRD: The **discounted** variant treats the capital outlay as a payment made in year zero and never discounts it, then discounts each of the care years 1 through the care horizon at 3 percent per year.
    PRD: the capital outlay is added to that sum last and exactly.
    Design: Difficulty/combinatorial_formula/care_stream_pv_rounds_each_year_before_summation
    """
    unit = fixtures.create_unit(api, "IMP-0003")

    plan = get_success_data(
        api.create_closure_plan(
            factories.closure_plan_payload(
                unit["id"], "CP-0002", METHOD_CLOSURE_IN_PLACE, **CARE_STREAM_PLAN
            ),
            UTILITY_ADMIN_HEADERS,
        )
    )

    a.assert_cents(plan["in_place_capital_usd_cents"], 2050000000, "in_place_capital_usd_cents")
    discounted_care = plan["in_place_pv_usd_cents"] - plan["in_place_capital_usd_cents"]
    assert discounted_care == 392008829, (
        f"the discounted care stream should be 392008829 cents, got {discounted_care}"
    )
    a.assert_two_dp(plan["cost_variance_pct"], 1.90, "cost_variance_pct")


def test_the_contingency_band_is_chosen_from_the_base_cost_and_not_from_the_subtotal(api):
    """The base sits in the 20 percent band even though its subtotal does not.

    PRD: A contingency rate is selected by which band the base cost falls into: 20 percent when the base is below five million dollars, 15 percent when it is below twenty million dollars, and 10 percent at twenty million dollars or above.
    PRD: The band must be chosen from the base cost and never re-derived from the subtotal or the final amount: the total routinely lands in a higher band than the base it came from, and re-deriving it produces a smaller, incorrect assurance figure.
    Design: Difficulty/combinatorial_formula/assurance_contingency_tier_keyed_on_base_not_on_total
    """
    world = case_program_in_assessment(api)
    assert world["evaluation"]["verdict"] == EVAL_VERDICT_SSI

    program = get_success_data(
        api.file_corrective_action_assurance(
            world["program_id"],
            factories.assurance_payload(
                480000000,
                12,
                remedy_description="Pump-and-treat with source control and downgradient hydraulic containment",
            ),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )

    assert program["phase"] == PHASE_ASSESSMENT
    a.assert_cents(program["remedy_base_cost_usd_cents"], 480000000, "remedy_base_cost_usd_cents")
    # base 480,000,000 + 20% contingency = 576,000,000 subtotal, + 2.5% oversight.
    a.assert_cents(program["assurance_amount_usd_cents"], 590400000, "assurance_amount_usd_cents")
    # The figure a subtotal-derived 15 percent band would have produced.
    assert program["assurance_amount_usd_cents"] != 565800000


def test_the_remedy_cost_basis_cannot_be_filed_while_the_program_is_still_in_detection(api):
    """The assurance amount is null until an escalation makes the filing admissible.

    PRD: Filing it while the program is still in `DETECTION` is `ERR_INVALID_PROGRAM_PHASE`.
    PRD: Before the amount is filed, `assurance_amount_usd_cents` is null.
    Design: Difficulty/combinatorial_formula/assurance_contingency_tier_keyed_on_base_not_on_total
    """
    world = fixtures.seed_unit(api, "IMP-0004")
    program = fixtures.read_program(api, world["program_id"])
    assert program["assurance_amount_usd_cents"] is None

    response = api.file_corrective_action_assurance(
        world["program_id"],
        factories.assurance_payload(480000000, 12),
        COMPLIANCE_OFFICER_HEADERS,
    )

    validate_error(response, ApiErrorId.INVALID_PROGRAM_PHASE.value)
    unchanged = fixtures.read_program(api, world["program_id"])
    assert unchanged["assurance_amount_usd_cents"] is None
