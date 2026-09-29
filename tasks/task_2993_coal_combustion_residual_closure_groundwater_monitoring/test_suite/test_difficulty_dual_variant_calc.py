"""Two cost or statistical variants computed from one payload, ranking it oppositely."""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import assertions as a
from test_helpers import factories, fixtures
from test_helpers.constants import (
    BASIS_INTERWELL,
    BASIS_INTRAWELL,
    EVAL_VERDICT_NO_SSI,
    EVAL_VERDICT_SSI,
    EVENT_TYPE_BACKGROUND,
    EVENT_TYPE_DETECTION,
    FREQUENCY_QUARTERLY,
    FREQUENCY_SEMIANNUAL,
    METHOD_CLOSURE_IN_PLACE,
    METHOD_PARAMETRIC,
    PARAM_SULFATE,
    PHASE_ASSESSMENT,
    PHASE_DETECTION,
    PLAN_STATUS_DRAFT,
    POSTURE_RESTRICTED,
)
from test_helpers.test_users import UTILITY_ADMIN_HEADERS

# The four background rounds sit 91 days apart inside the 2025 window, and each
# one carries a value for the upgradient well and a value for the compliance
# well. Which of the two series the statistics read is the whole question.
WINDOW_ROUNDS = (
    ("BG-R1", "2025-02-10", 0.5000, 0.6800),
    ("BG-R2", "2025-05-12", 0.6000, 0.8200),
    ("BG-R3", "2025-08-11", 0.5500, 0.7400),
    ("BG-R4", "2025-11-10", 0.5800, 0.7800),
)


def case_two_series_one_measurement(api, basis=BASIS_INTRAWELL):
    """Build one program holding both an upgradient and an own-well background series.

    The compliance well DG-01 ends up with four in-window values of its own and
    one out-of-window detection value of 0.9000; the upgradient well BG-01 ends
    up with four in-window values only. Both series are complete before either
    variant is evaluated, so switching the basis switches nothing but the rule.
    """
    world = fixtures.seed_unit(api, "IMP-0001")
    world["wells"] = fixtures.install_standard_network(api, world["unit_id"], world["hydro_headers"])
    fixtures.configure_program(
        api, world["program_id"], world["hydro_headers"], comparison_basis=basis
    )
    fixtures.certify_network(api, world["program_id"], world["hydro_headers"], "2025-01-05")

    background_well = world["wells"]["BG-01"]["id"]
    compliance_well = world["wells"]["DG-01"]["id"]
    for code, sampled_on, bg_value, dg_value in WINDOW_ROUNDS:
        fixtures.validated_round(
            api,
            world["program_id"],
            world["hydro_headers"],
            code,
            sampled_on,
            [(background_well, bg_value), (compliance_well, dg_value)],
            EVENT_TYPE_BACKGROUND,
            PARAM_SULFATE,
        )
    fixtures.validated_round(
        api,
        world["program_id"],
        world["hydro_headers"],
        "DET-R1",
        "2026-06-15",
        [(compliance_well, 0.9000)],
        EVENT_TYPE_DETECTION,
        PARAM_SULFATE,
        validated_on="2026-06-16",
    )
    world["compliance_well_id"] = compliance_well
    world["background_well_id"] = background_well
    return world


def test_intrawell_basis_reads_the_compliance_wells_own_history_and_finds_no_increase(api):
    """The same 0.9000 measurement is no increase when the well is its own control.

    PRD: Under `INTRAWELL`, the contributing well set is exactly the compliance well itself: the upgradient background wells are excluded and the well is compared against its own historical record inside the window.
    PRD: If `comparison_value` is less than or equal to `background_upper_limit`, the verdict is `NO_SSI` - a value exactly equal to the limit is *not* an increase.
    Design: Difficulty/dual_variant_calc/interwell_vs_intrawell_limit_flips_ssi_verdict
    """
    world = case_two_series_one_measurement(api, BASIS_INTRAWELL)

    evaluation = fixtures.issue_evaluation(api, world, "EV-INTRA")

    assert evaluation["comparison_basis_used"] == BASIS_INTRAWELL
    assert evaluation["method_used"] == METHOD_PARAMETRIC
    assert evaluation["background_n"] == 4
    a.assert_four_dp(evaluation["background_mean"], 0.7550, "background_mean")
    a.assert_six_dp(evaluation["background_stdev"], 0.059722, "background_stdev")
    a.assert_four_dp(evaluation["background_upper_limit"], 0.9453, "background_upper_limit")
    a.assert_four_dp(evaluation["comparison_value"], 0.9000, "comparison_value")
    assert evaluation["verdict"] == EVAL_VERDICT_NO_SSI
    assert evaluation["asd_deadline_date"] is None

    # No increase means no escalation: the program stays where it was.
    program = fixtures.read_program(api, world["program_id"])
    assert program["phase"] == PHASE_DETECTION
    assert program["sampling_frequency"] == FREQUENCY_SEMIANNUAL


def test_interwell_basis_reads_the_upgradient_series_and_escalates_the_program(api):
    """The identical measurement becomes an increase against the upgradient limit.

    PRD: Under `INTERWELL`, the contributing wells are every well of the unit whose `well_role` is `BACKGROUND`, whether that well is still certified or has since been decommissioned, and the compliance well's own history is excluded entirely.
    PRD: Second, because that verdict is an increase, the program advances `DETECTION -> ASSESSMENT`, stamps `assessment_entered_on` with the current date, escalates `sampling_frequency` to `QUARTERLY`, and re-derives `next_sampling_due_date` at the shorter 91-day interval.
    Design: Difficulty/dual_variant_calc/interwell_vs_intrawell_limit_flips_ssi_verdict
    """
    world = case_two_series_one_measurement(api, BASIS_INTERWELL)

    evaluation = fixtures.issue_evaluation(api, world, "EV-INTER")

    assert evaluation["comparison_basis_used"] == BASIS_INTERWELL
    assert evaluation["background_n"] == 4
    a.assert_four_dp(evaluation["background_mean"], 0.5575, "background_mean")
    a.assert_six_dp(evaluation["background_stdev"], 0.043493, "background_stdev")
    a.assert_four_dp(evaluation["background_upper_limit"], 0.6961, "background_upper_limit")
    a.assert_four_dp(evaluation["comparison_value"], 0.9000, "comparison_value")
    assert evaluation["verdict"] == EVAL_VERDICT_SSI
    # determined_on is the logical clock's 2026-08-01; the window closes 90 days later.
    a.assert_date(evaluation["asd_deadline_date"], "2026-10-30", "asd_deadline_date")

    program = fixtures.read_program(api, world["program_id"])
    assert program["phase"] == PHASE_ASSESSMENT
    assert program["sampling_frequency"] == FREQUENCY_QUARTERLY
    unit = fixtures.read_unit(api, world["unit_id"])
    assert unit["compliance_posture"] == POSTURE_RESTRICTED


def test_nominal_and_discounted_cost_variants_rank_the_two_methods_oppositely(api):
    """One payload; the undiscounted totals favour removal and the present values do not.

    PRD: The **nominal** variant applies no discounting at all: each method's nominal total is its capital outlay plus its annual care cost multiplied by the number of care years, reported as `in_place_nominal_usd_cents` and `removal_nominal_usd_cents`.
    PRD: The spread between the two methods is reported as `cost_variance_pct`, computed always from the **discounted** figures and never the nominal ones.
    Design: Difficulty/dual_variant_calc/nominal_vs_discounted_cost_flips_recommended_method
    """
    unit = fixtures.create_unit(api, "IMP-0002")

    plan = get_success_data(
        api.create_closure_plan(
            factories.closure_plan_payload(
                unit["id"],
                "CP-0001",
                METHOD_CLOSURE_IN_PLACE,
                in_place_capital_usd_cents=2050000000,
                in_place_annual_care_usd_cents=20000000,
                removal_capital_usd_cents=2450000000,
                removal_annual_care_usd_cents=2000000,
                care_period_years=30,
            ),
            UTILITY_ADMIN_HEADERS,
        )
    )

    # Undiscounted, closure in place is the dearer of the two.
    a.assert_cents(plan["in_place_nominal_usd_cents"], 2650000000, "in_place_nominal_usd_cents")
    a.assert_cents(plan["removal_nominal_usd_cents"], 2510000000, "removal_nominal_usd_cents")
    assert plan["in_place_nominal_usd_cents"] > plan["removal_nominal_usd_cents"]

    # Discounted, the ordering reverses because the care stream is what is discounted.
    a.assert_cents(plan["in_place_pv_usd_cents"], 2442008829, "in_place_pv_usd_cents")
    a.assert_cents(plan["removal_pv_usd_cents"], 2489200885, "removal_pv_usd_cents")
    assert plan["in_place_pv_usd_cents"] < plan["removal_pv_usd_cents"]

    a.assert_two_dp(plan["cost_variance_pct"], 1.90, "cost_variance_pct")
    assert plan["status"] == PLAN_STATUS_DRAFT


def test_the_recommendation_follows_the_discounted_variance_into_the_tie_band(api):
    """A 1.90 percent discounted spread is inside the tie band, so capping wins.

    PRD: Otherwise, if `cost_variance_pct` is less than or equal to 5.00 the two methods are treated as economically indistinguishable and the recommendation is `CLOSURE_IN_PLACE`; the tie band is inclusive, so a variance of exactly 5.00 prefers closure in place while 5.01 falls through.
    PRD: That comparison reads the discounted fields only; comparing the nominal fields instead returns the opposite method whenever the care stream is large enough to reverse the ordering.
    Design: Difficulty/dual_variant_calc/nominal_vs_discounted_cost_flips_recommended_method
    """
    unit = fixtures.create_unit(api, "IMP-0002")

    response = api.create_closure_plan(
        factories.closure_plan_payload(
            unit["id"],
            "CP-0001",
            METHOD_CLOSURE_IN_PLACE,
            in_place_capital_usd_cents=2050000000,
            in_place_annual_care_usd_cents=20000000,
            removal_capital_usd_cents=2450000000,
            removal_annual_care_usd_cents=2000000,
            care_period_years=30,
        ),
        UTILITY_ADMIN_HEADERS,
    )
    plan = validate_success(response, expected_status=201)

    a.assert_two_dp(plan["cost_variance_pct"], 1.90, "cost_variance_pct")
    assert plan["recommended_method"] == METHOD_CLOSURE_IN_PLACE
    # The selection matches the recommendation, so no justification was required.
    assert plan["selection_justification"] is None
