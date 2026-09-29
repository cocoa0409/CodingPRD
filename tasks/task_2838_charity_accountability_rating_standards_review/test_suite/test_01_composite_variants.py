"""The two composite variants a rating cycle carries at all times."""
from test_helpers import (
    NO_IMPACT_GOVERNANCE,
    assert_ratio,
    assert_score,
    dimension_by_name,
    read_dimension_scores,
    read_score_breakdown,
    setup_scored_cycle,
)


def test_provisional_variant_counts_the_zero_data_impact_dimension_at_its_declared_weight():
    """A charity that published no impact evidence at all still carries the impact
    dimension in the figure its review window shows, at the full declared weight.

    PRD §3.6: "The **provisional** variant includes all four dimensions at their declared weights with no renormalisation, even when a dimension's `data_completeness_pct` is 0.00 — a dimension with no data drags the provisional score down at its full declared weight."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_composite_diverge_on_zero_completeness_impact
    """
    scenario = setup_scored_cycle(governance_overrides=NO_IMPACT_GOVERNANCE)
    cycle = scenario["cycle"]

    assert cycle["status"] == "SCORED"
    assert_score(cycle["weighted_sum_provisional"], 70.88, "weighted_sum_provisional")
    assert_score(
        cycle["provisional_composite_score"], 69.88, "provisional_composite_score"
    )
    assert cycle["provisional_grade"] == "NEEDS_IMPROVEMENT"

    impact = dimension_by_name(scenario["dimension_scores"], "IMPACT")
    assert_score(impact["normalized_score"], 0.00, "IMPACT normalized_score")
    assert_score(impact["data_completeness_pct"], 0.00, "IMPACT data_completeness_pct")


def test_final_variant_excludes_the_zero_completeness_dimension_and_renormalises_weights():
    """The published figure drops the empty impact dimension and rescales the three
    surviving weights so they again sum to one.

    PRD §3.6: "The **final** variant excludes every dimension whose `data_completeness_pct` is exactly 0.00 and renormalises the surviving declared weights, each becoming its declared weight divided by the sum of the surviving declared weights, rounded half up to four decimal places before it multiplies anything."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_composite_diverge_on_zero_completeness_impact
    """
    scenario = setup_scored_cycle(governance_overrides=NO_IMPACT_GOVERNANCE)
    cycle = scenario["cycle"]
    breakdown = read_score_breakdown(cycle["id"], scenario["analyst_headers"])

    assert_score(cycle["weighted_sum_final"], 83.38, "weighted_sum_final")
    assert_score(cycle["final_composite_score"], 81.88, "final_composite_score")
    assert cycle["grade"] == "MEETS_STANDARDS"
    assert breakdown["final_included_dimensions"] == [
        "FINANCIAL_HEALTH",
        "ACCOUNTABILITY",
        "TRANSPARENCY",
    ]

    rows = scenario["dimension_scores"]
    financial = dimension_by_name(rows, "FINANCIAL_HEALTH")
    accountability = dimension_by_name(rows, "ACCOUNTABILITY")
    transparency = dimension_by_name(rows, "TRANSPARENCY")

    assert_ratio(financial["weight_applied"], 0.4706, "FINANCIAL_HEALTH weight_applied")
    assert_ratio(accountability["weight_applied"], 0.2941, "ACCOUNTABILITY weight_applied")
    assert_ratio(transparency["weight_applied"], 0.2353, "TRANSPARENCY weight_applied")
    assert_score(financial["normalized_score"], 72.50, "FINANCIAL_HEALTH normalized_score")
    assert_score(
        accountability["normalized_score"], 87.50, "ACCOUNTABILITY normalized_score"
    )
    assert_score(transparency["normalized_score"], 100.00, "TRANSPARENCY normalized_score")
    assert_score(
        financial["weighted_contribution"], 34.12, "FINANCIAL_HEALTH weighted_contribution"
    )
    assert_score(
        accountability["weighted_contribution"],
        25.73,
        "ACCOUNTABILITY weighted_contribution",
    )
    assert_score(
        transparency["weighted_contribution"], 23.53, "TRANSPARENCY weighted_contribution"
    )


def test_excluding_the_zero_data_dimension_promotes_the_band_and_raises_the_penalty_rate():
    """One identical set of four dimension rows, one failed standard, and two
    different per-standard penalty rates — because the two variants band differently.

    PRD §3.6: "One consequence deserves emphasis: because step three's band comes from the renormalised weighted sum, excluding a weak dimension can **promote** the band and therefore **raise** the per-standard penalty rate, so the final score is not monotonically kinder than the provisional one."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_composite_diverge_on_zero_completeness_impact
    """
    scenario = setup_scored_cycle(governance_overrides=NO_IMPACT_GOVERNANCE)
    breakdown = read_score_breakdown(
        scenario["cycle"]["id"], scenario["analyst_headers"]
    )

    assert breakdown["failed_standard_count"] == 1
    assert breakdown["provisional_band"] == "C"
    assert_score(breakdown["provisional_penalty"], 1.00, "provisional_penalty")
    assert breakdown["final_band"] == "B"
    assert_score(breakdown["final_penalty"], 1.50, "final_penalty")
    assert breakdown["provisional_grade"] == "NEEDS_IMPROVEMENT"
    assert breakdown["grade"] == "MEETS_STANDARDS"


def test_dimension_rows_mirror_the_final_variant_even_where_the_provisional_variant_counted_them():
    """The stored impact row reads zero weight and zero contribution, because a
    dimension row always reports the published variant's arithmetic.

    PRD §3.5: "A row's `weight_applied` and `weighted_contribution` **always** mirror the final composite variant, because that is the published figure: a dimension the final variant excludes carries a `weight_applied` of 0.0000 and a `weighted_contribution` of 0.00 even though the provisional variant still counted it at its full declared weight."

    PRD §3.5: "The cycle's own `data_completeness_pct` is the sum, over the four dimensions, of each dimension's completeness multiplied by that dimension's **declared** weight from the pinned methodology version — never the renormalised final-variant weight — with the total rounded half up to two decimal places."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_composite_diverge_on_zero_completeness_impact
    """
    scenario = setup_scored_cycle(governance_overrides=NO_IMPACT_GOVERNANCE)
    rows = read_dimension_scores(scenario["cycle"]["id"], scenario["analyst_headers"])
    impact = dimension_by_name(rows, "IMPACT")

    assert_ratio(impact["weight_applied"], 0.0000, "IMPACT weight_applied")
    assert_score(impact["weighted_contribution"], 0.00, "IMPACT weighted_contribution")
    assert_score(
        scenario["cycle"]["data_completeness_pct"], 85.00, "cycle data_completeness_pct"
    )
