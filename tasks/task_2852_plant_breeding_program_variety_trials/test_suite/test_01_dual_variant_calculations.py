"""
Dual-variant divergence: the two series-analysis inclusion rules, and the two
advancement-index policies, computed over one and the same fixture.
"""

from typing import Any, Dict, List, Optional

from test_helpers import (
    ANALYST_HEADERS,
    DIRECTOR_HEADERS,
    AnalysisVariant,
    DecisionType,
    PipelineStage,
    SeriesStatus,
    StabilityClass,
    approx2,
    approx4,
    assert_ordered_desc,
    fixtures,
    validate_success,
)


def row_for_line(rows: List[Dict[str, Any]], line_id: str) -> Dict[str, Any]:
    """The single `entry_means` row belonging to one breeding line."""
    matches = [row for row in rows if row["line_id"] == line_id]
    assert len(matches) == 1, f"expected one entry_means row for {line_id}, got {matches}"
    return matches[0]


def row_for_site(rows: List[Dict[str, Any]], site_id: str) -> Optional[Dict[str, Any]]:
    """The `environment_index` row for one site, or None when the site was excluded."""
    matches = [row for row in rows if row["trial_site_id"] == site_id]
    assert len(matches) <= 1, f"expected at most one environment_index row for {site_id}"
    return matches[0] if matches else None


def test_unbalanced_inclusive_keeps_every_location_and_weights_by_valid_reps(api):
    """
    The whole candidate pool is included, and each line's mean is weighted by
    replications rather than by locations.

    PRD 3.7: "Under `UNBALANCED_INCLUSIVE` the included set is the whole
    candidate pool: every harvested entry at every location, including locations
    where some lines of the series were never tested — a view under which a line
    tested mainly at a stress site is dragged down relative to its peers."
    PRD 3.7: "For each breeding line with at least one included entry,
    `adjusted_mean_kg_per_ha` is a replication-weighted mean: the sum, over that
    line's included entries, of each entry's `yield_kg_per_ha` multiplied by its
    `valid_rep_count`, divided by the sum of those same `valid_rep_count`
    values, rounded half up to two decimals."
    PRD 3.6: "Every recorded observation re-derives the entry's
    `valid_rep_count`, which counts only this entry's observations whose
    `trait_code` is `YIELD_KG_PLOT`, whose `qc_status` is `ACCEPTED` and whose
    `is_outlier` is false."

    Design: Difficulty/dual_variant_calc/series_mean_variant_divergence_balanced_core_vs_unbalanced_inclusive
    """
    net = fixtures.three_site_data_complete(api)

    entry_a1 = validate_success(api.get_entry(net.entry_a1_id, ANALYST_HEADERS))
    assert entry_a1["valid_rep_count"] == 3
    assert entry_a1["yield_kg_per_ha"] == approx2(12000.00)
    for entry_id, expected in (
        (net.entry_a2_id, 10000.00),
        (net.entry_a3_id, 7200.00),
        (net.entry_b1_id, 11200.00),
        (net.entry_b2_id, 8800.00),
    ):
        entry = validate_success(api.get_entry(entry_id, ANALYST_HEADERS))
        assert entry["valid_rep_count"] == 4
        assert entry["yield_kg_per_ha"] == approx2(expected)

    analysis = fixtures.run_analysis(
        api, net.series_id, AnalysisVariant.UNBALANCED_INCLUSIVE
    )
    assert analysis["variant"] == AnalysisVariant.UNBALANCED_INCLUSIVE
    assert analysis["included_location_count"] == 3
    assert analysis["included_line_count"] == 2

    # A weighs 12000.00*3 + 10000.00*4 + 7200.00*4 over 11 reps; B weighs
    # 11200.00*4 + 8800.00*4 over 8 reps.
    means = analysis["entry_means"]
    assert len(means) == 2
    assert row_for_line(means, net.line_a_id)["adjusted_mean_kg_per_ha"] == approx2(9527.27)
    assert row_for_line(means, net.line_b_id)["adjusted_mean_kg_per_ha"] == approx2(10000.00)
    assert row_for_line(means, net.line_a_id)["included_location_count"] == 3
    assert row_for_line(means, net.line_b_id)["included_location_count"] == 2


def test_environment_index_is_an_unweighted_site_mean_ordered_descending(api):
    """
    The x-axis of the stability regression averages entries per site without
    replication weights, and the published array is sorted by that index.

    PRD 3.7: "For each included location, `index_kg_per_ha` is an **unweighted**
    site mean: the sum of `yield_kg_per_ha` over the included entries at that
    site divided by the number of those entries, rounded half up to two
    decimals."
    PRD 3.7: "`environment_index` holds one object per included location, each
    carrying `trial_site_id`, that site's `environment_class` and its
    `index_kg_per_ha`; the array is ordered by `index_kg_per_ha` descending,
    with ties broken by the site's `created_at` ascending."

    Design: Difficulty/dual_variant_calc/series_mean_variant_divergence_balanced_core_vs_unbalanced_inclusive
    """
    net = fixtures.three_site_data_complete(api)
    analysis = fixtures.run_analysis(
        api, net.series_id, AnalysisVariant.UNBALANCED_INCLUSIVE
    )

    index_rows = analysis["environment_index"]
    assert len(index_rows) == 3
    # S1 averages 12000.00 and 11200.00 with no rep weighting at all.
    assert row_for_site(index_rows, net.site1_id)["index_kg_per_ha"] == approx2(11600.00)
    assert row_for_site(index_rows, net.site2_id)["index_kg_per_ha"] == approx2(9400.00)
    assert row_for_site(index_rows, net.site3_id)["index_kg_per_ha"] == approx2(7200.00)
    assert row_for_site(index_rows, net.site1_id)["environment_class"] == "HIGH_YIELD_IRRIGATED"
    assert row_for_site(index_rows, net.site3_id)["environment_class"] == "DROUGHT_STRESS"
    assert_ordered_desc([row["index_kg_per_ha"] for row in index_rows], "environment_index")


def test_balanced_core_drops_the_site_no_line_shares_and_moves_the_mean(api):
    """
    Site S3 leaves the inclusion set because line B was never tested there, and
    the surviving rep weights 3 and 4 keep A's mean off the unweighted midpoint.

    PRD 3.7: "Under `BALANCED_CORE` the server first identifies the core
    locations: a site qualifies as core when **every** breeding line that has at
    least one harvested entry anywhere in this series also has a harvested entry
    at that site."
    PRD 3.7: "The included set is then the candidate pool restricted to those
    core locations."

    Design: Difficulty/dual_variant_calc/series_mean_variant_divergence_balanced_core_vs_unbalanced_inclusive
    """
    net = fixtures.three_site_data_complete(api)
    analysis = fixtures.run_analysis(api, net.series_id, AnalysisVariant.BALANCED_CORE)

    assert analysis["included_location_count"] == 2
    assert analysis["included_line_count"] == 2
    assert row_for_site(analysis["environment_index"], net.site3_id) is None

    means = analysis["entry_means"]
    core_a = row_for_line(means, net.line_a_id)
    # 12000.00*3 + 10000.00*4 over 7 reps: not the unweighted two-site 11000.00.
    assert core_a["adjusted_mean_kg_per_ha"] == approx2(10857.14)
    assert core_a["adjusted_mean_kg_per_ha"] != approx2(11000.00)
    assert core_a["included_location_count"] == 2
    # B sits at every core site, so its mean is untouched by the variant.
    assert row_for_line(means, net.line_b_id)["adjusted_mean_kg_per_ha"] == approx2(10000.00)


def test_stability_fit_and_mse_follow_the_variants_point_count(api):
    """
    Line A is fitted over three points under the inclusive variant and only two
    under the core variant, which is what makes `deviation_mse` appear and
    vanish while the classification stays STABLE.

    PRD 3.7: "When n is 3 or more, `deviation_mse` is the sum over the points of
    the squared residual — the entry yield minus the value the fitted line
    predicts at that site, that prediction being the mean entry yield plus the
    unrounded coefficient multiplied by (the site index minus the mean site
    index) — divided by n minus 2, rounded half up to two decimals; when n is
    exactly 2 there are no degrees of freedom left and `deviation_mse` is null."
    PRD 3.7: "Classification reads the rounded four-decimal
    `stability_regression_b`: `STABLE` when it lies between 0.80 and 1.20
    inclusive, `RESPONSIVE` when it is greater than 1.20, and `BUFFERED` in
    every other case, meaning a coefficient below 0.80."

    Design: Difficulty/dual_variant_calc/series_mean_variant_divergence_balanced_core_vs_unbalanced_inclusive
    """
    net = fixtures.three_site_data_complete(api)

    inclusive = fixtures.run_analysis(
        api, net.series_id, AnalysisVariant.UNBALANCED_INCLUSIVE
    )
    inc_a = row_for_line(inclusive["entry_means"], net.line_a_id)
    assert inc_a["stability_regression_b"] == approx4(1.0909)
    assert inc_a["deviation_mse"] == approx2(106666.67)
    assert inc_a["stability_class"] == StabilityClass.STABLE
    inc_b = row_for_line(inclusive["entry_means"], net.line_b_id)
    assert inc_b["stability_regression_b"] == approx4(1.0909)
    assert inc_b["deviation_mse"] is None
    assert inc_b["stability_class"] == StabilityClass.STABLE

    core = fixtures.run_analysis(api, net.series_id, AnalysisVariant.BALANCED_CORE)
    core_a = row_for_line(core["entry_means"], net.line_a_id)
    assert core_a["stability_regression_b"] == approx4(0.9091)
    assert core_a["deviation_mse"] is None
    assert core_a["stability_class"] == StabilityClass.STABLE


def test_the_two_variants_never_supersede_each_other(api):
    """
    Publishing the second variant leaves the first current, and the series is
    ANALYZED either way.

    PRD 3.7: "Every earlier analysis of this series with the **same** `variant`
    has its `is_superseded` set to true, so at most one analysis of each variant
    is ever current — analyses of the other variant are untouched."
    PRD 3.7: "The series moves to `ANALYZED` (from `DATA_COMPLETE`, or remaining
    there if it was already `ANALYZED`) and its `version` increments by one,
    which is why a second analyst working from a stale read is turned away."

    Design: Difficulty/dual_variant_calc/series_mean_variant_divergence_balanced_core_vs_unbalanced_inclusive
    """
    net = fixtures.three_site_data_complete(api)
    inclusive = fixtures.run_analysis(
        api, net.series_id, AnalysisVariant.UNBALANCED_INCLUSIVE
    )
    core = fixtures.run_analysis(api, net.series_id, AnalysisVariant.BALANCED_CORE)

    assert inclusive["is_superseded"] is False
    assert core["is_superseded"] is False
    listed = validate_success(api.list_analyses(net.series_id, ANALYST_HEADERS))
    by_id = {row["id"]: row for row in listed}
    assert by_id[inclusive["id"]]["is_superseded"] is False
    assert by_id[core["id"]]["is_superseded"] is False

    series = validate_success(api.get_series(net.series_id, ANALYST_HEADERS))
    assert series["status"] == SeriesStatus.ANALYZED


def test_provisional_index_imputes_the_missing_component_at_sixty(api):
    """
    Line B has no quality measurements at all, so the optimistic variant credits
    it 60 for the component and applies no stage discount.

    PRD 3.8: "The **quality component** is MISSING when the line's
    `quality_trait_values` map is empty."
    PRD 3.8: "The **PROVISIONAL** variant is optimistic: every MISSING component
    is imputed at 60, no stage-confidence factor is applied, and the result is
    the weighted base itself."
    PRD 3.8: "The component is 100 multiplied by that source figure divided by
    the objective's `target_yield_kg_per_ha`, rounded half up to two decimals,
    and then capped at 120 — a line cannot bank more than a twenty-percent
    overshoot of its market's yield target."

    Design: Difficulty/dual_variant_calc/line_index_variant_divergence_provisional_vs_cumulative
    """
    net = fixtures.single_site_analyzed(api)

    line_b = validate_success(api.get_line(net.line_b_id, DIRECTOR_HEADERS))
    # yield 101.82 at 0.50, disease 50.00 at 0.30, imputed quality 60 at 0.20.
    assert line_b["advancement_index_provisional"] == approx2(77.91)

    line_a = validate_success(api.get_line(net.line_a_id, DIRECTOR_HEADERS))
    # A's 109.09 yield component is below the cap of 120, so nothing is clipped.
    assert line_a["advancement_index_provisional"] == approx2(101.55)


def test_cumulative_index_zeroes_the_missing_component_and_discounts_by_stage(api):
    """
    The frozen decision index is strictly below the provisional one for the same
    line at the same moment: the missing component drops to 0.00 and the base is
    multiplied by the NURSERY confidence factor.

    PRD 3.8: "The **CUMULATIVE** variant is pessimistic and is the one the gate
    actually enforces: every MISSING component is forced to 0.00, and the
    weighted base is multiplied by a stage-confidence factor that depends on the
    line's current `pipeline_stage` — 0.90 at `NURSERY`, 0.95 at `STAGE_1`, and
    1.00 at `STAGE_2`, `STAGE_3` and `PRE_COMMERCIAL` — with the product rounded
    half up to two decimals."
    PRD 3.8: "The server computes the CUMULATIVE index at decision time and
    freezes it as `decision_index_value`, records `from_stage` as the line's
    `pipeline_stage` immediately before the decision and `to_stage` as its stage
    immediately after, stamps `decided_by_user_id` with the acting `X-User-ID`,
    and sets `is_superseded` false."

    Design: Difficulty/dual_variant_calc/line_index_variant_divergence_provisional_vs_cumulative
    """
    net = fixtures.single_site_analyzed(api)
    decision = fixtures.record_decision(
        api,
        net.line_b_id,
        net.series_id,
        decision=DecisionType.HOLD,
        granted_plots=0,
        rationale="quality panel not yet run",
    )

    # 0.50*101.82 + 0.30*50.00 + 0.20*0.00 = 65.91, then 65.91 * 0.90.
    assert decision["decision_index_value"] == approx2(59.32)
    line_b = validate_success(api.get_line(net.line_b_id, DIRECTOR_HEADERS))
    assert decision["decision_index_value"] != approx2(
        line_b["advancement_index_provisional"]
    )
    assert line_b["advancement_index_provisional"] == approx2(77.91)


def test_hold_records_both_stages_as_nursery_and_commits_no_plots(api):
    """
    A HOLD freezes the cumulative index without moving the line or drawing on
    the programme's plot budget.

    PRD 3.8: "The line's `pipeline_stage` is unchanged, so `from_stage` and
    `to_stage` both record the current stage; `granted_plots` must be 0; the
    cited series must be `ANALYZED`; the line must not already be `DISCARDED`;
    and the supersession, plot release and version bump described above all
    still apply."

    Design: Difficulty/dual_variant_calc/line_index_variant_divergence_provisional_vs_cumulative
    """
    net = fixtures.single_site_analyzed(api)
    decision = fixtures.record_decision(
        api, net.line_b_id, net.series_id, decision=DecisionType.HOLD, granted_plots=0
    )

    assert decision["from_stage"] == PipelineStage.NURSERY
    assert decision["to_stage"] == PipelineStage.NURSERY
    assert decision["granted_plots"] == 0
    assert decision["is_superseded"] is False
    line_b = validate_success(api.get_line(net.line_b_id, DIRECTOR_HEADERS))
    assert line_b["pipeline_stage"] == PipelineStage.NURSERY

    program = validate_success(api.get_program(net.program_id, DIRECTOR_HEADERS))
    # Two planted entries of 8 plots each and nothing granted by the hold.
    assert program["committed_plot_count"] == 16
