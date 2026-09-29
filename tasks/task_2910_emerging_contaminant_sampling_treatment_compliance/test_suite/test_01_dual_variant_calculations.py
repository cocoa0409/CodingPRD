"""Paired calculation variants that disagree on identical evidence.

The concentration domain freezes a compliance average beside a planning average
on one determination; the money domain stores a uniform bill increase beside a
volumetric one on one capital project.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_decimal,
    assert_entry_point_posture,
    assert_equals,
    assert_money_cents,
    assert_rate_ladder,
    assert_status,
)
from test_helpers.fixtures import (
    accepted_quarter,
    build_registry,
    draft_determination,
    piloted_evaluation,
    project_of_evaluation,
    read_entry_point,
    read_lab_result,
    read_pilot,
    read_project,
    register_entry_point,
    select_technology,
)
from test_helpers.test_users import FINANCE_OFFICER_HEADERS, OFFICER_USER_ID


def _four_quarters_at_detection_limit_1_80(api):
    """PFOA over four quarters, two of them non-detects at a 1.80 detection limit."""
    registry = build_registry(
        api,
        contaminant_overrides={"hazard_index_member": False},
        laboratory_overrides={"lowest_achievable_dl_ng_per_l": 1.00, "daily_analysis_capacity": 5},
    )
    quarters = {}
    for period, reported in [
        ("2025Q3", 3.20),
        ("2025Q4", 1.20),
        ("2026Q1", 5.40),
        ("2026Q2", 1.60),
    ]:
        quarters[period] = accepted_quarter(
            api, registry, period, reported, detection_limit_ng_per_l=1.80
        )
    return registry, quarters


def test_determination_freezes_a_compliance_average_below_its_planning_average(api):
    """Two censored quarters split the two averages by exactly half a detection limit.

    Four accepted quarters reported 3.20, 1.20, 5.40 and 1.60 against a 1.80
    detection limit, so the two non-detects contribute 0.00 to the regulatory
    average and 0.90 each to the planning average: the determination freezes
    lraa_ng_per_l 2.15 and planning_lraa_ng_per_l 2.60, a delta of 0.45.

    PRD: "The average is 0.00 when no period is kept, and otherwise the sum of
    the values across the kept periods divided by the number of periods kept,
    rounded half-up to two decimal places."

    Design: Difficulty/dual_variant_calc/lraa_compliance_and_planning_variants_diverge_on_two_censored_quarters
    """
    registry, _ = _four_quarters_at_detection_limit_1_80(api)

    determination = draft_determination(
        api, registry["entry_point_id"], registry["contaminant_id"], period_end="2026Q2"
    )

    assert_decimal(determination["lraa_ng_per_l"], 2.15, label="lraa_ng_per_l")
    assert_decimal(determination["planning_lraa_ng_per_l"], 2.60, label="planning_lraa_ng_per_l")
    assert_decimal(
        determination["planning_lraa_ng_per_l"] - determination["lraa_ng_per_l"],
        0.45,
        label="planning minus compliance average",
    )
    assert_equals(determination, "quarters_used", 4)
    assert_decimal(determination["hazard_index"], 0.00, label="hazard_index")
    assert_equals(determination, "determination", "TRIGGER_EXCEEDED")
    assert_equals(determination, "violation_type", "NONE")
    assert_status(determination, "DRAFT")
    assert_equals(determination, "determined_by_user_id", OFFICER_USER_ID)


def test_only_the_compliance_variant_reaches_the_entry_point_ratio(api):
    """The censoring substitution is visible per result and only the regulatory side scores.

    The 1.20 reading is a non-detect against a 1.80 detection limit, so it
    carries compliance_value_ng_per_l 0.00 and planning_value_ng_per_l 0.90,
    while the 3.20 detect carries 3.20 in both. Only the compliance average
    feeds max_compliance_ratio, which lands on 0.5375 and a TRIGGERED posture.

    PRD: "`planning_value_ng_per_l` is the value the capital-planning average
    will use: half the achieved detection limit, rounded half-up to two decimal
    places, when the result is censored, and the reported concentration
    otherwise."

    Design: Difficulty/dual_variant_calc/lraa_compliance_and_planning_variants_diverge_on_two_censored_quarters
    """
    registry, quarters = _four_quarters_at_detection_limit_1_80(api)

    censored = read_lab_result(api, quarters["2025Q4"]["result_id"])
    assert_equals(censored, "censored", True)
    assert_decimal(censored["compliance_value_ng_per_l"], 0.00, label="compliance_value_ng_per_l")
    assert_decimal(censored["planning_value_ng_per_l"], 0.90, label="planning_value_ng_per_l")

    detected = read_lab_result(api, quarters["2025Q3"]["result_id"])
    assert_equals(detected, "censored", False)
    assert_decimal(detected["compliance_value_ng_per_l"], 3.20, label="compliance_value_ng_per_l")
    assert_decimal(detected["planning_value_ng_per_l"], 3.20, label="planning_value_ng_per_l")

    entry_point = read_entry_point(api, registry["entry_point_id"])
    assert_entry_point_posture(
        entry_point,
        posture="TRIGGERED",
        accepted_result_count=4,
        max_compliance_ratio=0.5375,
    )


def _selected_gac_project(api):
    """The GAC-versus-IX evaluation whose SELECT spawns one capital project."""
    entry_point = register_entry_point(api)
    piloted = piloted_evaluation(api, entry_point["id"], residuals_budget_cents=250000)
    return entry_point, piloted


def test_uniform_bill_increase_is_one_cent_above_the_volumetric_variant(api):
    """The intermediate whole-cent rate per kgal makes the two variants disagree.

    A final annual requirement of 73675367 cents divided straight across 18000
    accounts and twelve months is 341 cents, while rounding the per-thousand
    gallon rate to 68 cents first and only then converting to a monthly bill
    gives 340 cents. Selecting VOLUMETRIC makes the lower figure authoritative.

    PRD: "The intermediate rounding of the per-thousand-gallon rate is exactly
    why the two variants can differ by a cent or more on identical inputs, and
    it must not be skipped."

    Design: Difficulty/dual_variant_calc/bill_impact_uniform_and_volumetric_variants_diverge_on_one_capital_project
    """
    entry_point, piloted = _selected_gac_project(api)
    select_technology(api, piloted["evaluation_id"])
    project = project_of_evaluation(api, piloted["evaluation_id"])

    patched = validate_success(
        api.patch_capital_project(
            project["id"],
            f.project_patch_payload(rate_design="VOLUMETRIC"),
            FINANCE_OFFICER_HEADERS,
        )
    )

    assert_equals(patched, "rate_design", "VOLUMETRIC")
    assert_rate_ladder(
        patched,
        local_share_cents=680000000,
        borrowed_cents=680000000,
        annual_debt_service_cents=41586568,
        base_annual_requirement_cents=72586568,
        provisional_rate_impact_pct=7.07,
        surcharge_bp=150,
        final_annual_requirement_cents=73675367,
        rate_impact_pct=7.18,
        uniform_monthly_increase_cents=341,
        volumetric_rate_increase_cents_per_kgal=68,
        volumetric_monthly_increase_cents=340,
        monthly_bill_increase_cents=340,
    )
    assert patched["uniform_monthly_increase_cents"] != patched["volumetric_monthly_increase_cents"], (
        "The two bill variants must disagree on this project"
    )


def test_a_freshly_selected_project_reports_the_uniform_variant(api):
    """Selection seeds the project on UNIFORM, so the higher figure is authoritative.

    The winning GAC skid scores 80.14 against the IX skid's 76.20 and its
    capital and operating estimates seed the project, which arrives with
    rate_design UNIFORM and therefore reports the uniform 341 cents as its
    monthly bill increase before any rate-design change.

    PRD: "`monthly_bill_increase_cents` then reports whichever variant
    `rate_design` selects: the uniform figure under `UNIFORM` and the
    volumetric figure under `VOLUMETRIC`."

    Design: Difficulty/dual_variant_calc/bill_impact_uniform_and_volumetric_variants_diverge_on_one_capital_project
    """
    entry_point, piloted = _selected_gac_project(api)
    evaluation = select_technology(api, piloted["evaluation_id"])
    project = read_project(api, project_of_evaluation(api, piloted["evaluation_id"])["id"])

    assert_equals(evaluation, "selected_technology", "GAC")
    assert_equals(project, "rate_design", "UNIFORM")
    assert_money_cents(project["capital_cost_cents"], 680000000, "capital_cost_cents")
    assert_money_cents(project["annual_om_cost_cents"], 31000000, "annual_om_cost_cents")
    assert_rate_ladder(
        project,
        uniform_monthly_increase_cents=341,
        volumetric_monthly_increase_cents=340,
        monthly_bill_increase_cents=341,
    )

    gac = read_pilot(api, piloted["gac_id"])
    ix = read_pilot(api, piloted["ix_id"])
    assert_decimal(gac["technology_score"], 80.14, label="GAC technology_score")
    assert_decimal(ix["technology_score"], 76.20, label="IX technology_score")
    assert_equals(gac, "selected", True)
    assert_equals(ix, "selected", False)
