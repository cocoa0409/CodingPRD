"""Capacity, demand, waterfall and impact-score arithmetic.

Every figure asserted here is recomputed from the PRD's own rules through
`test_helpers.assertions`, and the PRD's worked examples are additionally pinned as
exact literals wherever a test reproduces the acreage, roster or index set the PRD
itself works through.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import CONSULTANT, STAFF, STATE

# The PRD's reference acreage row: "On a reference inventory of 400 vacant acres,
# 250 underutilized acres, 60 infrastructure-constrained acres and 18 allowed units
# per acre".
REF_VACANT = 400
REF_UNDERUTILIZED = 250
REF_CONSTRAINED = 60
REF_DENSITY = 18

# The five-respondent roster used by both weighting variants: three
# underrepresented respondents, two of whom used an interpreter.
ROSTER_FIVE = [
    {"respondent_ref": "r-1", "demographic_group": C.GROUP_LOW_INCOME,
     "interpreter_used": True},
    {"respondent_ref": "r-2", "demographic_group": C.GROUP_LIMITED_ENGLISH,
     "interpreter_used": True},
    {"respondent_ref": "r-3", "demographic_group": C.GROUP_RENTER,
     "interpreter_used": False},
    {"respondent_ref": "r-4", "demographic_group": C.GROUP_GENERAL,
     "interpreter_used": False},
    {"respondent_ref": "r-5", "demographic_group": C.GROUP_SENIOR,
     "interpreter_used": False},
]


def _plan_with_certified_land_use(api):
    """A DRAFTING plan plus one CERTIFIED land-use dataset on the reference acreage."""
    plan = fx.create_plan(api)
    dataset = fx.create_land_use_inventory(
        api,
        plan["id"],
        vacant_acres=REF_VACANT,
        underutilized_acres=REF_UNDERUTILIZED,
        infrastructure_constrained_acres=REF_CONSTRAINED,
        allowed_density_units_per_acre=REF_DENSITY,
    )
    certified = fx.certify_inventory(api, dataset["id"])
    return plan, certified


# ------------------------------------------------------- gross vs net capacity
def test_trend_scenario_reads_the_reference_acreage_as_gross_capacity(api):
    """A TREND scenario counts every vacant and underutilized acre at full density.

    PRD: "Under `GROSS_CAPACITY`, `land_capacity_units` is the vacant acreage plus
    the underutilized acreage, multiplied by the allowed density per acre, and that
    single product is rounded half up to whole units."

    Design: Difficulty/dual_variant_calc/land_capacity_gross_vs_net_variant_divergence
    """
    plan, dataset = _plan_with_certified_land_use(api)

    scenario = fx.create_scenario(
        api, plan["id"], dataset["id"], method=C.METHOD_TREND, label="Trend 2045"
    )

    assert scenario["capacity_variant"] == C.CAPACITY_VARIANT_GROSS
    expected = a.expected_gross_capacity(REF_VACANT, REF_UNDERUTILIZED, REF_DENSITY)
    assert scenario["land_capacity_units"] == expected
    assert scenario["land_capacity_units"] == 11700
    a.assert_whole_units(scenario["land_capacity_units"], "land_capacity_units")


def test_policy_scenario_reads_the_same_acreage_as_net_capacity(api):
    """A POLICY scenario applies the three discounts to the identical acreage row.

    PRD: "Under `NET_CAPACITY` three discounts apply. The infrastructure-constrained
    acreage is first subtracted from the vacant acreage; to that is added one half of
    the underutilized acreage, because only half of the redevelopable land is
    expected to be realized within the horizon; the resulting acreage is multiplied
    by the allowed density per acre; and the whole product is then discounted to 85
    percent to reflect market softness before being rounded half up to whole units."

    Design: Difficulty/dual_variant_calc/land_capacity_gross_vs_net_variant_divergence
    """
    plan, dataset = _plan_with_certified_land_use(api)

    scenario = fx.create_scenario(
        api, plan["id"], dataset["id"], method=C.METHOD_POLICY, label="Policy 2045"
    )

    assert scenario["capacity_variant"] == C.CAPACITY_VARIANT_NET
    expected = a.expected_net_capacity(
        REF_VACANT, REF_UNDERUTILIZED, REF_CONSTRAINED, REF_DENSITY
    )
    assert scenario["land_capacity_units"] == expected
    # 465 acres * 18 u/ac * 0.85 = 7114.5, rounded half up once at the very end.
    assert scenario["land_capacity_units"] == 7115
    a.assert_whole_units(scenario["land_capacity_units"], "land_capacity_units")


def test_one_acreage_row_yields_both_capacities_and_two_references(api):
    """The two methods diverge by 4585 units off a single certified dataset.

    PRD: "On a reference inventory of 400 vacant acres, 250 underutilized acres, 60
    infrastructure-constrained acres and 18 allowed units per acre, `GROSS_CAPACITY`
    yields 11700 units while `NET_CAPACITY` yields 7115: the same inventory row, two
    legitimately different capacities."

    Design: Difficulty/dual_variant_calc/land_capacity_gross_vs_net_variant_divergence
    """
    plan, dataset = _plan_with_certified_land_use(api)

    trend = fx.create_scenario(
        api, plan["id"], dataset["id"], method=C.METHOD_TREND, label="Trend 2045"
    )
    policy = fx.create_scenario(
        api, plan["id"], dataset["id"], method=C.METHOD_POLICY, label="Policy 2045"
    )

    assert trend["land_use_inventory_id"] == dataset["id"]
    assert policy["land_use_inventory_id"] == dataset["id"]
    assert trend["land_capacity_units"] == 11700
    assert policy["land_capacity_units"] == 7115
    assert trend["land_capacity_units"] - policy["land_capacity_units"] == 4585

    reread = validate_success(api.get_inventory_dataset(dataset["id"], STAFF))
    assert reread["referencing_scenario_count"] == 2


# --------------------------------------------- standard vs outreach weighting
def _plan_with_equity_venue(api):
    """A DRAFTING plan plus a transit-served, step-free room with no turnover buffer."""
    plan = fx.create_plan(api)
    venue = fx.create_equity_venue(api, turnover_buffer_minutes=0)
    return plan, venue


def test_workshop_share_collapses_to_a_head_count_under_standard_weighting(api):
    """Five workshop records weigh 1.0 each, so three of five reads 60.0 percent.

    PRD: "Under `STANDARD`, every record weighs 1.0, so the share collapses to a head
    count: four underrepresented respondents out of ten records gives exactly 40.0."

    Design: Difficulty/dual_variant_calc/activity_equity_standard_vs_outreach_weighted_divergence
    """
    plan, venue = _plan_with_equity_venue(api)
    activity = fx.create_activity(
        api,
        plan["id"],
        activity_type=C.ACTIVITY_WORKSHOP,
        title="Draft Vision Workshop",
        venue_id=venue["id"],
        start_at=fx.T_ACTIVITY_START,
        end_at=fx.T_ACTIVITY_END,
        interpretation_offered=True,
    )
    assert activity["weighting_variant"] == C.VARIANT_STANDARD
    fx.add_roster(api, activity["id"], ROSTER_FIVE)

    completed = fx.complete_activity(api, activity["id"])

    expected = a.expected_activity_totals(ROSTER_FIVE, C.VARIANT_STANDARD)
    assert completed["record_count"] == 5
    assert completed["underrepresented_record_count"] == 3
    assert completed["total_weighted_count"] == expected["total_weighted_count"] == 5.0
    assert (
        completed["underrepresented_weighted_count"]
        == expected["underrepresented_weighted_count"]
        == 3.0
    )
    assert completed["equity_share_pct"] == expected["equity_share_pct"] == 60.0
    a.assert_one_decimal(completed["equity_share_pct"], "equity_share_pct")


def test_outreach_share_doubles_interpreter_records_to_seven_weighted_units(api):
    """The same roster on a targeted-outreach session reads 5.0 of 7.0, or 71.4.

    PRD: "Under `OUTREACH_WEIGHTED`, interpreter-using respondents count double, so
    five records that would give 60.0 under standard weighting — three of five
    underrepresented — instead give 71.4 when the two interpreter-using respondents
    are both underrepresented, because the arithmetic is 5.0 of 7.0 weighted units."

    Design: Difficulty/dual_variant_calc/activity_equity_standard_vs_outreach_weighted_divergence
    """
    plan, venue = _plan_with_equity_venue(api)
    activity = fx.create_activity(
        api,
        plan["id"],
        activity_type=C.ACTIVITY_TARGETED_OUTREACH,
        title="Renter Outreach Session",
        venue_id=venue["id"],
        start_at=fx.T_ACTIVITY_2_START,
        end_at=fx.T_ACTIVITY_2_END,
        interpretation_offered=True,
    )
    assert activity["weighting_variant"] == C.VARIANT_OUTREACH_WEIGHTED
    fx.add_roster(api, activity["id"], ROSTER_FIVE)

    completed = fx.complete_activity(api, activity["id"])

    expected = a.expected_activity_totals(ROSTER_FIVE, C.VARIANT_OUTREACH_WEIGHTED)
    assert completed["record_count"] == 5
    assert completed["underrepresented_record_count"] == 3
    assert completed["total_weighted_count"] == expected["total_weighted_count"] == 7.0
    assert (
        completed["underrepresented_weighted_count"]
        == expected["underrepresented_weighted_count"]
        == 5.0
    )
    assert completed["equity_share_pct"] == expected["equity_share_pct"] == 71.4
    a.assert_one_decimal(completed["equity_share_pct"], "equity_share_pct")


def test_identical_rosters_diverge_only_by_the_weighting_variant(api):
    """Head counts match on both activities while the weighted shares diverge.

    PRD: "The record's `weight` is 2.0 when the parent activity's `weighting_variant`
    is `OUTREACH_WEIGHTED` and the respondent's `interpreter_used` is true, and 1.0 in
    every other case — an interpreter changes nothing at a workshop or a survey."

    Design: Difficulty/dual_variant_calc/activity_equity_standard_vs_outreach_weighted_divergence
    """
    plan, venue = _plan_with_equity_venue(api)
    workshop = fx.create_activity(
        api,
        plan["id"],
        activity_type=C.ACTIVITY_WORKSHOP,
        title="Draft Vision Workshop",
        venue_id=venue["id"],
        start_at=fx.T_ACTIVITY_START,
        end_at=fx.T_ACTIVITY_END,
        interpretation_offered=True,
    )
    outreach = fx.create_activity(
        api,
        plan["id"],
        activity_type=C.ACTIVITY_TARGETED_OUTREACH,
        title="Renter Outreach Session",
        venue_id=venue["id"],
        start_at=fx.T_ACTIVITY_2_START,
        end_at=fx.T_ACTIVITY_2_END,
        interpretation_offered=True,
    )
    for activity_id in (workshop["id"], outreach["id"]):
        fx.add_roster(api, activity_id, ROSTER_FIVE)

    closed_workshop = fx.complete_activity(api, workshop["id"])
    closed_outreach = fx.complete_activity(api, outreach["id"])

    assert closed_workshop["record_count"] == closed_outreach["record_count"] == 5
    assert (
        closed_workshop["underrepresented_record_count"]
        == closed_outreach["underrepresented_record_count"]
        == 3
    )
    assert closed_workshop["total_weighted_count"] == 5.0
    assert closed_outreach["total_weighted_count"] == 7.0
    assert closed_workshop["equity_share_pct"] == 60.0
    assert closed_outreach["equity_share_pct"] == 71.4


# ------------------------------------------------------------ projected demand
def test_trend_demand_takes_household_growth_alone(api):
    """A TREND projection ignores the larger job-driven pressure entirely.

    PRD: "A `TREND` scenario takes household growth alone as its demand driver; a
    `POLICY` scenario takes whichever of the two pressures is larger, household growth
    or job-driven households."

    Design: Difficulty/combinatorial_formula/projected_demand_policy_max_driver_non_linear_branch
    """
    plan, dataset = _plan_with_certified_land_use(api)

    scenario = fx.create_scenario(
        api,
        plan["id"],
        dataset["id"],
        method=C.METHOD_TREND,
        label="Trend 2045",
        base_households=60000,
        annual_household_growth_rate=0.008,
        job_growth_total=31000,
        demolition_replacement_units=1200,
    )

    expected = a.expected_projected_demand(
        C.METHOD_TREND, 60000, 0.008, f.REF_HORIZON_YEAR, f.REF_BASE_YEAR, 31000, 1200
    )
    assert scenario["projected_demand_units"] == expected
    assert scenario["projected_demand_units"] == 12144
    assert scenario["capacity_gap_units"] == a.expected_capacity_gap(12144, 11700)
    assert scenario["capacity_gap_units"] == 444


def test_policy_demand_takes_the_larger_job_driven_pressure(api):
    """From identical drivers the POLICY branch selects 31000 / 1.45 households.

    PRD: "Job-driven household demand is `job_growth_total` divided by 1.45, the
    assumed number of jobs supported per household."

    Design: Difficulty/combinatorial_formula/projected_demand_policy_max_driver_non_linear_branch
    """
    plan, dataset = _plan_with_certified_land_use(api)

    trend = fx.create_scenario(
        api,
        plan["id"],
        dataset["id"],
        method=C.METHOD_TREND,
        label="Trend 2045",
        base_households=60000,
        annual_household_growth_rate=0.008,
        job_growth_total=31000,
        demolition_replacement_units=1200,
    )
    policy = fx.create_scenario(
        api,
        plan["id"],
        dataset["id"],
        method=C.METHOD_POLICY,
        label="Policy 2045",
        base_households=60000,
        annual_household_growth_rate=0.008,
        job_growth_total=31000,
        demolition_replacement_units=1200,
    )

    expected = a.expected_projected_demand(
        C.METHOD_POLICY, 60000, 0.008, f.REF_HORIZON_YEAR, f.REF_BASE_YEAR, 31000, 1200
    )
    assert policy["projected_demand_units"] == expected
    assert policy["projected_demand_units"] == 23708
    assert policy["projected_demand_units"] > trend["projected_demand_units"]
    assert policy["capacity_gap_units"] == a.expected_capacity_gap(23708, 7115)
    assert policy["capacity_gap_units"] == 16593


def test_household_growth_is_carried_at_full_precision_into_the_vacancy_margin(api):
    """Rounding the growth increment first would report 2595 rather than 2594.

    PRD: "Household growth, job-driven households and the selected driver are all
    carried at full precision; rounding any of them first changes the answer."

    Design: Difficulty/combinatorial_formula/projected_demand_policy_max_driver_non_linear_branch
    """
    plan, dataset = _plan_with_certified_land_use(api)

    scenario = fx.create_scenario(
        api,
        plan["id"],
        dataset["id"],
        method=C.METHOD_TREND,
        label="Modest Trend 2045",
        base_households=10000,
        annual_household_growth_rate=0.006,
        job_growth_total=31000,
        demolition_replacement_units=1200,
    )

    # Growth increment 1270.9264...; (1270.9264... + 1200) * 1.05 = 2594.47 -> 2594,
    # while (1271 + 1200) * 1.05 = 2594.55 -> 2595.
    expected = a.expected_projected_demand(
        C.METHOD_TREND, 10000, 0.006, f.REF_HORIZON_YEAR, f.REF_BASE_YEAR, 31000, 1200
    )
    assert scenario["projected_demand_units"] == expected
    assert scenario["projected_demand_units"] == 2594
    assert scenario["projected_demand_units"] != 2595
    # Demand well below the 11700-unit gross capacity, so the gap floors at zero.
    assert scenario["capacity_gap_units"] == a.expected_capacity_gap(2594, 11700)
    assert scenario["capacity_gap_units"] == 0


# --------------------------------------------------------- the capacity waterfall
WATERFALL_ASSIGNED = {
    C.TIER_VERY_LOW: 2500,
    C.TIER_LOW: 1000,
    C.TIER_MODERATE: 1200,
    C.TIER_ABOVE_MODERATE: 3000,
}
# Recorded out of statutory order on purpose: MODERATE first, LOW last.
WATERFALL_CREATION_ORDER = [
    C.TIER_MODERATE,
    C.TIER_ABOVE_MODERATE,
    C.TIER_VERY_LOW,
    C.TIER_LOW,
]


def _plan_with_net_pool_and_four_allocations(api):
    """A plan whose adopted POLICY scenario supplies a 7115-unit pool, with one
    allocation row per income tier recorded out of statutory order."""
    ctx = fx.plan_with_adopted_scenario(api, method=C.METHOD_POLICY)
    for tier in WATERFALL_CREATION_ORDER:
        fx.create_allocation(api, ctx["plan_id"], tier, WATERFALL_ASSIGNED[tier])
    rows, _meta = validate_paginated(
        api.list_plan_housing_allocations(ctx["plan_id"], STATE)
    )
    ctx["rows"] = {row["income_tier"]: row for row in rows}
    return ctx


def test_each_tier_share_is_rounded_before_the_waterfall_consumes_it(api):
    """The 7115-unit pool splits into 2135 / 1423 / 1423 / 2135 whole units.

    PRD: "Otherwise, the tier's `tier_capacity_units` is the pool multiplied by that
    tier's suitability share, rounded half up to whole units. The shares are 30 percent
    for `VERY_LOW`, 20 percent for `LOW`, 20 percent for `MODERATE` and 30 percent for
    `ABOVE_MODERATE`."

    Design: Difficulty/combinatorial_formula/housing_waterfall_per_tier_rounding_before_allocation
    """
    ctx = _plan_with_net_pool_and_four_allocations(api)
    assert ctx["scenario"]["land_capacity_units"] == 7115

    expected = a.expected_waterfall(7115, WATERFALL_ASSIGNED)
    for tier in C.TIER_ORDER:
        row = ctx["rows"][tier]
        for field in (
            "tier_capacity_units",
            "carryover_in_units",
            "accommodated_units",
            "shortfall_units",
        ):
            assert row[field] == expected[tier][field], (
                f"{tier}.{field}: expected {expected[tier][field]}, got {row[field]}"
            )

    assert ctx["rows"][C.TIER_VERY_LOW]["tier_capacity_units"] == 2135
    assert ctx["rows"][C.TIER_LOW]["tier_capacity_units"] == 1423
    assert ctx["rows"][C.TIER_MODERATE]["tier_capacity_units"] == 1423
    assert ctx["rows"][C.TIER_ABOVE_MODERATE]["tier_capacity_units"] == 2135


def test_rounded_tier_capacities_exceed_the_pool_by_one_unit(api):
    """Per-tier rounding hands ABOVE_MODERATE 2781 units, not 2780.

    PRD: "With a pool of 7115 units, per-tier rounding yields 2135, 1423, 1423 and
    2135, which is 7116 allocated units in total, one more than the pool itself; under
    that pinned reading the `ABOVE_MODERATE` tier can accommodate 2781 units where the
    alternative reading would have allowed only 2780."

    Design: Difficulty/combinatorial_formula/housing_waterfall_per_tier_rounding_before_allocation
    """
    ctx = _plan_with_net_pool_and_four_allocations(api)

    total_tier_capacity = sum(
        ctx["rows"][tier]["tier_capacity_units"] for tier in C.TIER_ORDER
    )
    assert total_tier_capacity == 7116
    assert total_tier_capacity == ctx["scenario"]["land_capacity_units"] + 1

    above = ctx["rows"][C.TIER_ABOVE_MODERATE]
    assert above["carryover_in_units"] == 646
    assert above["accommodated_units"] == 2781
    assert above["accommodated_units"] != 2780
    assert above["shortfall_units"] == 219


def test_plan_shortfall_total_sums_the_tiers_and_holds_the_posture(api):
    """365 plus 219 leaves the plan 584 units short and therefore on capacity hold.

    PRD: "The plan's `housing_shortfall_total` is then the sum of `shortfall_units`
    across the four tiers, counting zero for any tier that has no row."

    Design: Difficulty/combinatorial_formula/housing_waterfall_per_tier_rounding_before_allocation
    """
    ctx = _plan_with_net_pool_and_four_allocations(api)

    plan = fx.read_plan(api, ctx["plan_id"])
    assert plan["housing_shortfall_total"] == a.expected_shortfall_total(
        7115, WATERFALL_ASSIGNED
    )
    assert plan["housing_shortfall_total"] == 584
    assert ctx["rows"][C.TIER_VERY_LOW]["shortfall_units"] == 365
    assert ctx["rows"][C.TIER_LOW]["shortfall_units"] == 0
    assert ctx["rows"][C.TIER_MODERATE]["shortfall_units"] == 0
    assert ctx["rows"][C.TIER_ABOVE_MODERATE]["shortfall_units"] == 219

    assert plan["compliance_posture"] == C.POSTURE_CAPACITY_HOLD
    a.assert_posture_consistent(plan)


# --------------------------------------------------- impact scores and mitigation
def _draft_review(api):
    """A DRAFTING plan plus one DRAFT environmental document to score against."""
    plan = fx.create_plan(api)
    review = fx.create_review(api, plan["id"], C.DOC_EIR)
    return plan, review


def test_mitigation_tier_is_keyed_on_the_raw_score_at_the_high_threshold(api):
    """All four indices at 70 earn the high-tier credit of 10.50 and a net of 59.50.

    PRD: "An alternative with all four indices at 70 illustrates why the tier key
    matters: its raw score is 70.00, which lands in the high tier, giving a credit of
    10.50 and a net score of 59.50 — had the tier been keyed on the net score, the mid
    tier would have applied instead and produced a credit of 7.00 and a net of 63.00."

    Design: Difficulty/combinatorial_formula/alternative_mitigation_credit_keyed_on_raw_not_net_score
    """
    _plan, review = _draft_review(api)

    alt = fx.add_alternative(
        api,
        review["id"],
        label="Threshold Boundary Alternative",
        traffic_vmt_index=70,
        ghg_index=70,
        habitat_index=70,
        water_index=70,
    )

    assert alt["status"] == C.ALTERNATIVE_STATUS_EVALUATED
    assert alt["raw_impact_score"] == 70.00
    assert alt["mitigation_credit"] == 10.50
    assert alt["net_impact_score"] == 59.50
    # The rejected reading keys the tier on the net score and reports 7.00 / 63.00.
    assert alt["mitigation_credit"] != 7.00
    assert alt["net_impact_score"] != 63.00
    a.assert_alternative_scores(alt)


def test_the_four_impact_weights_are_unequal(api):
    """Indices 100 / 50 / 20 / 30 weight up to 57.50, not the unweighted mean 50.00.

    PRD: "First, `raw_impact_score` is the weighted sum of the four indices — 35
    percent of the traffic index, 25 percent of the greenhouse-gas index, 20 percent of
    the habitat index and 20 percent of the water index, weights that sum to exactly
    one — rounded half up to two decimal places."

    Design: Difficulty/combinatorial_formula/alternative_mitigation_credit_keyed_on_raw_not_net_score
    """
    _plan, review = _draft_review(api)

    alt = fx.add_alternative(
        api,
        review["id"],
        label="Auto-Oriented Alternative",
        traffic_vmt_index=100,
        ghg_index=50,
        habitat_index=20,
        water_index=30,
    )

    assert alt["raw_impact_score"] == 57.50
    assert alt["raw_impact_score"] != 50.00
    # 57.50 sits at or above 50 but below 70, so the mid tier credits 10 percent.
    assert alt["mitigation_credit"] == 5.75
    assert alt["net_impact_score"] == 51.75
    a.assert_alternative_scores(alt)


def test_a_raw_score_below_fifty_earns_no_credit_at_all(api):
    """Indices at 49 score 49.00 raw, take no credit and stay at 49.00 net.

    PRD: "Second, `mitigation_credit` is looked up from a tier keyed **on the raw score
    and never on the net score**: a raw score of 70 or more earns a credit of 15 percent
    of the raw score, a raw score of at least 50 but below 70 earns 10 percent of the
    raw score, and anything below 50 earns no credit at all, that is, 0.00."

    Design: Difficulty/combinatorial_formula/alternative_mitigation_credit_keyed_on_raw_not_net_score
    """
    _plan, review = _draft_review(api)

    fx.add_alternative(
        api,
        review["id"],
        label="Threshold Boundary Alternative",
        traffic_vmt_index=70,
        ghg_index=70,
        habitat_index=70,
        water_index=70,
    )
    fx.add_alternative(
        api,
        review["id"],
        label="Auto-Oriented Alternative",
        traffic_vmt_index=100,
        ghg_index=50,
        habitat_index=20,
        water_index=30,
    )
    low = fx.add_alternative(
        api,
        review["id"],
        label="Low Impact Alternative",
        traffic_vmt_index=49,
        ghg_index=49,
        habitat_index=49,
        water_index=49,
    )

    assert low["raw_impact_score"] == 49.00
    assert low["mitigation_credit"] == 0.00
    assert low["net_impact_score"] == 49.00
    a.assert_alternative_scores(low)

    reread = validate_success(api.get_environmental_review(review["id"], CONSULTANT))
    assert reread["alternative_count"] == 3
