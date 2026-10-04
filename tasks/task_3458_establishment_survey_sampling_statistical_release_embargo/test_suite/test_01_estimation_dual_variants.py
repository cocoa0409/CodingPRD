"""Depth tests: dual-variant calculations.

Each instance pins two valid estimator variants that must produce different
published numbers from the same microdata: imputation passes (LINK_RELATIVE
vs STRATUM_MEAN), response-rate definitions (weighted vs unweighted), and
seasonal adjustment vintages (concurrent vs revised).
"""
from test_helpers import (
    TEST_USERS,
    api_client,
    certify_cycle,
    collect_cycle,
    compute_estimates,
    create_factor_set,
    create_stratum,
    finalize_factor_set,
    get_single_cell,
    publish_release,
    reopen_revision,
    set_clock,
    setup_certified_cycle,
    setup_embargoed_release,
    setup_enrolled_panel,
    setup_program_with_frozen_frame,
    validate_paginated,
)

METHODOLOGIST = TEST_USERS["survey_methodologist_headers"]


def test_imputation_link_relative_vs_stratified_mean_revision(api):
    """PRD §3.5: "During the preliminary pass the variant is `LINK_RELATIVE`."
    PRD §3.5: "During a revision pass the variant is `STRATUM_MEAN` throughout: each nonrespondent is imputed at the weighted mean of the cell's respondents — the sum over respondents of `base_weight` times reported employment, divided by the sum of respondent weights — rounded half up to a whole person."
    PRD §3.5: "Once the cycle is `REVISION_OPEN`, each recomputation moves recomputed cells from `PRELIMINARY` to `REVISED`, or keeps them `REVISED` if already there, and increments `revision_no` by 1 on every cell it touches."

    Design: Difficulty/dual_variant_calc/imputation_link_relative_vs_stratified_mean_revision
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3,
                                    annual_burden_budget_minutes=500)
    panel = setup_enrolled_panel("CES", count=3)
    en1, en2, en3 = panel["enrollments"]

    # September: all three report (9, 11, 8) — matched pairs for October.
    setup_certified_cycle("CES", "2026-09", panel["enrollments"],
                          {en1["id"]: 9, en2["id"]: 11, en3["id"]: 8})

    # October: E1=10, E2=12 accepted; E3 silent. Preliminary pass.
    cyc_oct = collect_cycle("CES", "2026-10", panel["enrollments"],
                            {en1["id"]: 10, en2["id"]: 12})
    prelim = get_single_cell(cyc_oct["id"], "MANUFACTURING", "SMALL")
    assert prelim["employment_estimate"] == 1033, (
        f"E3 imputed 9 via matched-pair link relative 22/20; "
        f"33.333333 x 31 = 1033.333323 -> 1033, got "
        f"{prelim['employment_estimate']}")
    assert prelim["imputation_variant"] == "LINK_RELATIVE"

    # Certify, publish, then reopen for revision and recompute.
    certify_cycle(cyc_oct["id"])
    staged = setup_embargoed_release(cyc_oct["id"], "2026-10-25T13:30:00Z")
    publish_release(staged["release"]["id"])
    reopen_revision(cyc_oct["id"])
    compute_estimates(cyc_oct["id"])

    revised = get_single_cell(cyc_oct["id"], "MANUFACTURING", "SMALL")
    assert revised["employment_estimate"] == 1100, (
        f"E3 imputed 11 via stratum weighted mean; 33.333333 x 33 = "
        f"1099.999989 -> 1100, got {revised['employment_estimate']}")
    assert revised["imputation_variant"] == "STRATUM_MEAN"
    assert revised["revision_no"] == 2
    assert revised["estimate_status"] == "REVISED"
    assert prelim["employment_estimate"] != revised["employment_estimate"], (
        "identical microdata, two valid estimators, different results")


def test_response_rate_weighted_vs_unweighted_diverge(api):
    """PRD §3.5: "`weighted_response_rate` is the sum of `base_weight` over enrollments with an `ACCEPTED` report this cycle divided by the sum over the denominator set, rounded half up to 6 decimal places, and serves as the certification gate and official quality measure"
    PRD §3.5: "`unweighted_response_rate` is the plain count ratio — acceptances over the denominator count, 6 decimal places — published alongside as the raw measure."

    Design: Difficulty/dual_variant_calc/response_rate_weighted_vs_unweighted_diverge
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(
        code="CES", sample_budget=14,
        strata=[create_stratum("MANUFACTURING", "SMALL", 100),
                create_stratum("RETAIL", "MEDIUM", 90)],
        annual_burden_budget_minutes=500)
    panel = setup_enrolled_panel(
        "CES", specs=[("MANUFACTURING", "SMALL", 3),
                      ("RETAIL", "MEDIUM", 2)])
    en_a1, en_a2, en_a3, en_b1, en_b2 = panel["enrollments"]

    # weights: 100/3 = 33.333333 (A stratum), 90/11 = 8.181818 (B stratum).
    cycle = collect_cycle("CES", "2026-09", panel["enrollments"],
                          {en_a1["id"]: 10, en_a2["id"]: 20,
                           en_b1["id"]: 5, en_b2["id"]: 15})
    assert cycle["weighted_response_rate"] == 0.713542, (
        "(2x33.333333 + 2x8.181818) / (3x33.333333 + 2x8.181818) = "
        f"83.030302 / 116.363635 = 0.71354166..., got "
        f"{cycle['weighted_response_rate']}")
    assert cycle["unweighted_response_rate"] == 0.800000, (
        f"4 of 5 enrollments responded, got "
        f"{cycle['unweighted_response_rate']}")
    assert cycle["weighted_response_rate"] != cycle["unweighted_response_rate"], (
        "identical response pattern, two valid rate definitions")


def test_seasonal_concurrent_vs_revised_factor_snapshots(api):
    """PRD §3.6: "That value lands in `seasonally_adjusted_concurrent` and never changes afterward, no matter how factors are later revised; when no factor set existed at compute time, the field stays null."
    PRD §3.6: "the system recomputes `seasonally_adjusted_revised` on every cell estimate of the same program and series whose cycle `reference_month` falls within the factor year, dividing each cell's current `employment_estimate` by the new `FINAL` factor for that month and rounding half up to a whole person."
    PRD §3.6: "A new set is born `PROVISIONAL`, and creating one for a series and year that already has a set — whether `PROVISIONAL` or `FINAL` — moves the previous set to the terminal `SUPERSEDED`."

    Design: Difficulty/dual_variant_calc/seasonal_concurrent_vs_revised_factor_snapshots
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3,
                                    annual_burden_budget_minutes=500)
    panel = setup_enrolled_panel("CES", count=3)
    en1, en2, en3 = panel["enrollments"]

    # PROVISIONAL factor set with September factor 1.05, before estimation.
    s1 = create_factor_set("CES", year=2026, month_overrides={1: 0.95, 9: 1.05})
    cycle = collect_cycle("CES", "2026-09", panel["enrollments"],
                          {en1["id"]: 10, en2["id"]: 11, en3["id"]: 12})

    cell = get_single_cell(cycle["id"], "MANUFACTURING", "SMALL")
    assert cell["employment_estimate"] == 1100
    assert cell["seasonally_adjusted_concurrent"] == 1048, (
        f"round_half_up(1100 / 1.05) = 1048 frozen from PROVISIONAL S1, got "
        f"{cell['seasonally_adjusted_concurrent']}")

    # New set (September factor 1.02) supersedes S1; finalize recomputes.
    set_clock("2027-01-02T00:00:00Z")
    s2 = create_factor_set("CES", year=2026, month_overrides={1: 0.98, 9: 1.02})
    finalize_factor_set(s2["id"], at="2027-01-02T00:00:00Z")

    cell = get_single_cell(cycle["id"], "MANUFACTURING", "SMALL")
    assert cell["seasonally_adjusted_revised"] == 1078, (
        f"round_half_up(1100 / 1.02) = 1078 recomputed at S2 finalize, got "
        f"{cell['seasonally_adjusted_revised']}")
    assert cell["seasonally_adjusted_concurrent"] == 1048, (
        "concurrent snapshot does not change when factors are later revised")

    rows, _meta = validate_paginated(api_client.list_factor_sets(
        METHODOLOGIST, params={"program_code": "CES", "year": 2026,
                               "set_status": "SUPERSEDED"}))
    assert len(rows) == 1 and rows[0]["id"] == s1["id"], (
        "creating S2 superseded S1")
