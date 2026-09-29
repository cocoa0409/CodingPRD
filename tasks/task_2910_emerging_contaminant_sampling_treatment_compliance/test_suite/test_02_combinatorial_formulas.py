"""Multi-input formulas whose answer depends on where the rounding sits.

The mixture hazard index accumulates unrounded quotients and rounds once; a
pilot's technology score rounds each weighted term first; the rate-impact ladder
fixes its surcharge tier from an intermediate figure and never revisits it.
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
    accept_result,
    complete_pilot,
    open_evaluation,
    piloted_evaluation,
    project_of_evaluation,
    read_entry_point,
    read_evaluation,
    read_sample,
    received_sample,
    register_entry_point,
    register_hazard_member,
    register_laboratory,
    register_pilot,
    select_technology,
    start_pilot,
    submit_result,
)
from test_helpers.test_users import FINANCE_OFFICER_HEADERS


# ---------------------------------------------------------------------------
# (a) hazard index: three unrounded quotients, one final rounding
# ---------------------------------------------------------------------------
def _three_member_mixture(api, panel_size: int = 3):
    """Three hazard-index members at 3.35 against an hbwc of 10.0.

    All three compounds are registered as hazard-index members; the sample's panel
    covers only the first `panel_size` of them, so the members beyond the panel have
    no accepted result anywhere at the entry point. A result is submitted for every
    panelled compound, which keeps the sample one acceptance short of `ANALYZED`
    until the last of them is accepted.
    """
    members = [
        register_hazard_member(
            api,
            code,
            10.0,
            mcl_ng_per_l=20.00,
            trigger_level_ng_per_l=10.00,
            required_mrl_ng_per_l=2.00,
        )
        for code in ("PFHXS", "PFNA", "HFPO_DA")
    ]
    panelled = members[:panel_size]
    laboratory = register_laboratory(api, certified_methods=["METHOD_1633"])
    entry_point = register_entry_point(api)
    sample = received_sample(
        api,
        entry_point["id"],
        [member["id"] for member in panelled],
        laboratory["id"],
        monitoring_period="2026Q2",
        preservative_lot="LOT-HI",
    )
    results = [
        submit_result(
            api,
            laboratory["id"],
            sample["id"],
            member["id"],
            method="METHOD_1633",
            reported_ng_per_l=3.35,
            detection_limit_ng_per_l=1.00,
            analyzed_at="2026-05-20T08:00:00.000Z",
        )
        for member in panelled
    ]
    return {
        "entry_point_id": entry_point["id"],
        "sample_id": sample["id"],
        "result_ids": [result["id"] for result in results],
    }


def test_hazard_index_of_three_equal_members_lands_on_one_point_zero_one(api):
    """Three quotients of 0.335 sum to 1.005 at full precision and round once to 1.01.

    Accepting the third result of the panel closes the sample and re-derives the
    mixture index over all three members: 3.35 / 10.0 three times is 1.005
    unrounded, so hazard_index is 1.01 and the posture escalates to
    VIOLATION_PENDING even though every compound sits at a sixth of its own
    maximum contaminant level.

    PRD: "Rounding each term before adding would produce a different and wrong
    answer, and this is deliberately the opposite of how a pilot technology
    score accumulates."

    Design: Difficulty/combinatorial_formula/hazard_index_sums_three_unrounded_ratios_before_one_final_rounding
    """
    mixture = _three_member_mixture(api)
    for result_id in mixture["result_ids"][:2]:
        accept_result(api, result_id)

    last = accept_result(api, mixture["result_ids"][2])

    assert_status(last, "ACCEPTED")
    assert_decimal(last["compliance_value_ng_per_l"], 3.35, label="compliance_value_ng_per_l")
    assert_decimal(last["planning_value_ng_per_l"], 3.35, label="planning_value_ng_per_l")
    assert_status(read_sample(api, mixture["sample_id"]), "ANALYZED")

    entry_point = read_entry_point(api, mixture["entry_point_id"])
    assert_entry_point_posture(
        entry_point,
        posture="VIOLATION_PENDING",
        accepted_result_count=3,
        max_compliance_ratio=0.1675,
        hazard_index=1.01,
    )
    assert entry_point["hazard_index"] != 1.02, (
        "1.02 is the answer produced by rounding each term before summing"
    )


def test_a_member_without_an_accepted_result_contributes_no_term(api):
    """Two accepted members make the index 0.67, and the unsampled third adds nothing.

    The third hazard-index member is registered but never panelled, so it has no
    accepted result at the entry point at all. The two members that were measured
    complete their panel and are both accepted, and the mixture index is the sum of
    exactly those two quotients — 0.67 — rather than a three-term sum in which the
    unmeasured member contributes a zero.

    PRD: "The mixture `hazard_index` is computed over contaminants whose
    `hazard_index_member` is true and which have at least one accepted result at
    the entry point; a member contaminant with no accepted result is absent from
    the sum entirely rather than contributing a zero term."

    Design: Difficulty/combinatorial_formula/hazard_index_sums_three_unrounded_ratios_before_one_final_rounding
    """
    mixture = _three_member_mixture(api, panel_size=2)
    for result_id in mixture["result_ids"]:
        accept_result(api, result_id)

    assert_status(read_sample(api, mixture["sample_id"]), "ANALYZED")

    entry_point = read_entry_point(api, mixture["entry_point_id"])
    assert_entry_point_posture(
        entry_point,
        posture="COMPLIANT",
        accepted_result_count=2,
        max_compliance_ratio=0.1675,
        hazard_index=0.67,
    )


# ---------------------------------------------------------------------------
# (b) technology score: five weighted terms, each rounded first
# ---------------------------------------------------------------------------
def _running_gac_pilot(api, **pilot_overrides):
    entry_point = register_entry_point(api)
    evaluation = open_evaluation(api, entry_point["id"])
    pilot = register_pilot(api, f.gac_pilot_payload(evaluation["id"], **pilot_overrides))
    start_pilot(api, pilot["id"])
    return evaluation, pilot


def test_technology_score_of_the_gac_skid_is_eighty_point_one_four(api):
    """Two terms carry a half-hundredth each, so the rounded sum beats the unrounded one.

    A GAC skid removing 96.30 percent on a 2550000000 cent lifecycle scores
    33.705 and 18.625 on its first two terms; rounding each product first gives
    33.71 + 18.63 + 12.40 + 7.10 + 8.30 = 80.14, while summing at full precision
    and rounding once would give 80.13.

    PRD: "`technology_score` is the weighted composite, and its accumulation
    rule is exact and deliberate: the five terms are `removal_pct` multiplied by
    0.35, `lifecycle_cost_score` multiplied by 0.25, `residuals_burden_score`
    multiplied by 0.20, `footprint_score` multiplied by 0.10 and
    `om_complexity_score` multiplied by 0.10; **each of the five products is
    rounded half-up to two decimal places individually, and the five rounded
    products are then added with no further rounding of the sum**."

    Design: Difficulty/combinatorial_formula/technology_score_rounds_each_weighted_term_before_summing_them
    """
    evaluation, pilot = _running_gac_pilot(api)

    completed = complete_pilot(
        api,
        pilot["id"],
        influent_ng_per_l=50.00,
        effluent_ng_per_l=1.85,
        bed_volumes_treated=25000.00,
        spent_media_kg=800.00,
    )

    assert_status(completed, "COMPLETED")
    assert_decimal(completed["removal_pct"], 96.30, label="removal_pct")
    assert_decimal(completed["lifecycle_cost_score"], 74.50, label="lifecycle_cost_score")
    assert_decimal(completed["technology_score"], 80.14, label="technology_score")
    assert completed["technology_score"] != 80.13, (
        "80.13 is the answer produced by rounding the sum instead of the terms"
    )
    assert_decimal(completed["spent_media_kg"], 800.00, label="spent_media_kg")
    assert_decimal(completed["unmanifested_media_kg"], 800.00, label="unmanifested_media_kg")
    assert_equals(completed, "selected", False)
    assert_status(read_evaluation(api, evaluation["id"]), "PILOTING")


def test_four_half_hundredth_terms_push_the_score_two_hundredths_higher(api):
    """Rounding four of the five products up separates the two accumulation orders by 0.02.

    A skid whose footprint and complexity scores are 71.05 and 83.05 produces
    weighted products of 7.105 and 8.305 beside the 33.705 and 18.625 of the
    first two terms: rounding each first sums to 80.16, whereas accumulating at
    full precision and rounding once would report 80.14.

    PRD: "This is the exact opposite of the mixture hazard index, which
    accumulates unrounded terms and rounds once at the end; the two accumulation
    orders can differ in the final hundredth, and each is required where it is
    specified."

    Design: Difficulty/combinatorial_formula/technology_score_rounds_each_weighted_term_before_summing_them
    """
    _, pilot = _running_gac_pilot(api, footprint_score=71.05, om_complexity_score=83.05)

    completed = complete_pilot(
        api,
        pilot["id"],
        influent_ng_per_l=50.00,
        effluent_ng_per_l=1.85,
        bed_volumes_treated=25000.00,
        spent_media_kg=800.00,
    )

    assert_decimal(completed["removal_pct"], 96.30, label="removal_pct")
    assert_decimal(completed["lifecycle_cost_score"], 74.50, label="lifecycle_cost_score")
    assert_decimal(completed["technology_score"], 80.16, label="technology_score")
    assert completed["technology_score"] != 80.14, (
        "80.14 is the answer produced by rounding the sum instead of the terms"
    )


# ---------------------------------------------------------------------------
# (c) rate-impact ladder: the surcharge tier is pinned to the provisional figure
# ---------------------------------------------------------------------------
def _planned_project(api):
    entry_point = register_entry_point(api)
    piloted = piloted_evaluation(api, entry_point["id"])
    select_technology(api, piloted["evaluation_id"])
    return project_of_evaluation(api, piloted["evaluation_id"])


def _patch_capital_cost(api, project, capital_cost_cents):
    return validate_success(
        api.patch_capital_project(
            project["id"],
            f.project_patch_payload(capital_cost_cents=capital_cost_cents),
            FINANCE_OFFICER_HEADERS,
        )
    )


def test_final_rate_impact_may_cross_fifteen_percent_on_a_hundred_and_fifty_bp_surcharge(api):
    """The tier chosen at 14.90 survives a final impact of 15.12.

    Raising the capital cost to 1993000000 cents produces a provisional impact
    of 14.90 percent, which selects 150 basis points; the surcharge that tier
    implies then pushes the final requirement to 155178619 cents and the final
    impact to 15.12 percent, and the tier is not re-chosen from that higher
    figure.

    PRD: "A project whose provisional impact sits just under 15.00 percent will
    therefore report a final `rate_impact_pct` above 15.00 percent while still
    carrying only 150 basis points of surcharge, and that is the correct
    result."

    Design: Difficulty/combinatorial_formula/rate_impact_ladder_keeps_the_provisional_surcharge_tier_after_a_capital_cost_patch
    """
    project = _planned_project(api)

    patched = _patch_capital_cost(api, project, 1993000000)

    assert_money_cents(patched["capital_cost_cents"], 1993000000, "capital_cost_cents")
    assert_rate_ladder(
        patched,
        local_share_cents=1993000000,
        borrowed_cents=1993000000,
        annual_debt_service_cents=121885339,
        base_annual_requirement_cents=152885339,
        provisional_rate_impact_pct=14.90,
        surcharge_bp=150,
        final_annual_requirement_cents=155178619,
        rate_impact_pct=15.12,
        uniform_monthly_increase_cents=718,
        volumetric_rate_increase_cents_per_kgal=144,
        volumetric_monthly_increase_cents=720,
        monthly_bill_increase_cents=718,
    )
    assert patched["rate_impact_pct"] > 15.00, "The final impact must exceed the tier boundary"
    assert patched["surcharge_bp"] != 400, "The tier must not be re-chosen from the final impact"
    assert_equals(patched, "rate_design", "UNIFORM")
    assert_equals(patched, "construction_status", "PLANNED")


def test_the_top_surcharge_tier_is_reached_only_when_the_provisional_figure_reaches_it(api):
    """A provisional impact of 16.13 percent is what buys 400 basis points.

    Raising the capital cost to 2200000000 cents lifts the provisional impact
    itself to 16.13 percent — 16554478000 divided by the frozen 1026000000-cent
    revenue base — and only then does the ladder select the top tier: 400 basis
    points on a base of 165544780 cents gives a final requirement of 172166571
    cents.

    PRD: "`surcharge_bp` is selected from the provisional figure alone: 0 basis
    points when the provisional impact is strictly below 5.00 percent, 150 basis
    points when it is at least 5.00 and strictly below 15.00 percent, and 400
    basis points when it is at least 15.00 percent."

    Design: Difficulty/combinatorial_formula/rate_impact_ladder_keeps_the_provisional_surcharge_tier_after_a_capital_cost_patch
    """
    project = _planned_project(api)

    patched = _patch_capital_cost(api, project, 2200000000)

    assert_rate_ladder(
        patched,
        borrowed_cents=2200000000,
        annual_debt_service_cents=134544780,
        base_annual_requirement_cents=165544780,
        provisional_rate_impact_pct=16.13,
        surcharge_bp=400,
        final_annual_requirement_cents=172166571,
        rate_impact_pct=16.78,
    )
