"""Valuation and scoring arithmetic: the two variant pairs and the formula order."""

from test_helpers import (
    COMPLIANCE,
    CandidateStatus,
    Category,
    ReportStatus,
    ScoringVariant,
    Subgroup,
    ValuationBasis,
    assert_close,
    assert_cost_based_posting,
    assert_report_totals,
    build_scenario,
    create_cycle,
    finalize_report,
    open_report,
    post_charge_based,
    post_cost_based,
    validate_success,
)
from test_helpers import constants as C


def test_finalization_revalues_charge_based_postings_under_the_audited_ratio(api):
    """PRD §3.9: "each charge-based posting's `valued_cents` becomes its
    `charges_cents` multiplied by the audited ratio, rounded half up to whole
    cents, with `ratio_applied` updated to the audited ratio; cost-based
    postings are unaffected, since no ratio ever entered their valuation."

    Design: Difficulty/dual_variant_calc/posting_valuation_provisional_vs_final_ratio_diverges
    """
    cycle = create_cycle(api)
    report = open_report(api, cycle["id"])
    assert report["valuation_basis"] == ValuationBasis.PROVISIONAL
    assert_close(report["cost_to_charge_ratio"], C.PRIOR_YEAR_RATIO, "cost_to_charge_ratio")

    fa = post_charge_based(api, report["id"], 1234567, category=Category.FINANCIAL_ASSISTANCE)
    ss = post_charge_based(api, report["id"], 2222222, category=Category.SUBSIDIZED_SERVICES)
    chi = post_cost_based(api, report["id"], 850000, category=Category.COMMUNITY_HEALTH_IMPROVEMENT)

    # 1234567 * 0.32 = 395061.44 -> 395061; 2222222 * 0.32 = 711111.04 -> 711111.
    assert fa["valued_cents"] == 395061
    assert ss["valued_cents"] == 711111
    assert chi["valued_cents"] == 850000

    locked = validate_success(
        api.finalize_report(report["id"], C.AUDITED_RATIO, headers=COMPLIANCE)
    )
    assert locked["status"] == ReportStatus.LOCKED
    assert locked["valuation_basis"] == ValuationBasis.FINAL
    assert_close(locked["audited_cost_to_charge_ratio"], C.AUDITED_RATIO, "audited ratio")
    assert_close(locked["cost_to_charge_ratio"], C.AUDITED_RATIO, "working ratio")

    # 1234567 * 0.28 = 345678.76 -> 345679; 2222222 * 0.28 = 622222.16 -> 622222.
    fa_after = validate_success(api.get_posting(fa["id"]))
    ss_after = validate_success(api.get_posting(ss["id"]))
    assert fa_after["valued_cents"] == 345679
    assert_close(fa_after["ratio_applied"], C.AUDITED_RATIO, "ratio_applied")
    assert ss_after["valued_cents"] == 622222
    assert_close(ss_after["ratio_applied"], C.AUDITED_RATIO, "ratio_applied")


def test_finalization_leaves_the_cost_based_posting_and_its_null_ratio_untouched(api):
    """PRD §3.9: "For a cost-based posting, `valued_cents` is simply the
    posting's `direct_cost_cents` unchanged, and `ratio_applied` is null — no
    ratio was involved and none is recorded."

    Design: Difficulty/dual_variant_calc/posting_valuation_provisional_vs_final_ratio_diverges
    """
    cycle = create_cycle(api)
    report = open_report(api, cycle["id"])
    post_charge_based(api, report["id"], 1234567, category=Category.FINANCIAL_ASSISTANCE)
    post_charge_based(api, report["id"], 2222222, category=Category.SUBSIDIZED_SERVICES)
    chi = post_cost_based(api, report["id"], 850000, category=Category.COMMUNITY_HEALTH_IMPROVEMENT)
    assert_cost_based_posting(chi, 850000)

    finalize_report(api, report["id"], C.AUDITED_RATIO)

    chi_after = validate_success(api.get_posting(chi["id"]))
    assert_cost_based_posting(chi_after, 850000)
    # The freeze is at posting time: the basis stamped on the row records what
    # the report's basis was when the row was entered, not what it became.
    assert chi_after["valuation_basis_at_posting"] == ValuationBasis.PROVISIONAL


def test_finalization_recomputes_every_report_total_from_the_revalued_postings(api):
    """PRD §3.9: "Both aggregations then run again over the revalued postings —
    the five category totals and `total_valued_cents` first, then the tier
    selection, `indirect_allocation_cents`, `grand_total_cents` and
    `benefit_pct_of_expense`, in that order, because the tier depends on the new
    base."

    Design: Difficulty/dual_variant_calc/posting_valuation_provisional_vs_final_ratio_diverges
    """
    cycle = create_cycle(api)
    report = open_report(api, cycle["id"])
    post_charge_based(api, report["id"], 1234567, category=Category.FINANCIAL_ASSISTANCE)
    post_charge_based(api, report["id"], 2222222, category=Category.SUBSIDIZED_SERVICES)
    post_cost_based(api, report["id"], 850000, category=Category.COMMUNITY_HEALTH_IMPROVEMENT)

    provisional = validate_success(api.get_report(report["id"]))
    assert_report_totals(
        provisional,
        FINANCIAL_ASSISTANCE=395061,
        SUBSIDIZED_SERVICES=711111,
        COMMUNITY_HEALTH_IMPROVEMENT=850000,
    )
    assert provisional["total_valued_cents"] == 1956172
    assert provisional["indirect_allocation_cents"] == 97809
    assert provisional["grand_total_cents"] == 2053981
    assert_close(provisional["benefit_pct_of_expense"], 1.71, "benefit_pct_of_expense")

    finalize_report(api, report["id"], C.AUDITED_RATIO)

    final = validate_success(api.get_report(report["id"]))
    assert_report_totals(
        final,
        FINANCIAL_ASSISTANCE=345679,
        SUBSIDIZED_SERVICES=622222,
        COMMUNITY_HEALTH_IMPROVEMENT=850000,
    )
    assert final["total_valued_cents"] == 1817901
    assert final["indirect_allocation_cents"] == 90895
    assert final["grand_total_cents"] == 1908796
    assert_close(final["benefit_pct_of_expense"], 1.59, "benefit_pct_of_expense")


def test_rescoring_under_community_weighted_diverges_from_the_equal_weight_run(api):
    """PRD §3.4: "Under the `COMMUNITY_WEIGHTED` variant — the equity reading, in
    which community concern and disparities outrank hospital capacity — the
    weights differ by term: the severity term carries a weight of 0.20, the
    disparity term 0.30, the concern term 0.35 and the capacity term 0.15, and
    the composite score is the sum of those four weighted terms."

    Design: Difficulty/dual_variant_calc/candidate_composite_equal_weight_vs_community_weighted_diverges
    """
    sc = build_scenario(api, stage="CANDIDATE_SCORED")

    equal_weight = sc.candidate()
    assert equal_weight["scoring_variant"] == ScoringVariant.EQUAL_WEIGHT
    # 0.25 * (77.50 + 60.00 + 100.00 + 70) = 76.875 -> 76.88.
    assert_close(equal_weight["composite_score"], 76.88, "composite_score")

    rescored = validate_success(
        api.score_candidate(sc.candidate_id, ScoringVariant.COMMUNITY_WEIGHTED)
    )
    assert rescored["scoring_variant"] == ScoringVariant.COMMUNITY_WEIGHTED
    assert_close(rescored["severity_input"], 77.50, "severity_input")
    assert_close(rescored["disparity_points"], 60.00, "disparity_points")
    assert_close(rescored["community_concern_index"], 100.00, "community_concern_index")
    # 0.20*77.50 + 0.30*60.00 + 0.35*100.00 + 0.15*70 = 79.00.
    assert_close(rescored["composite_score"], 79.00, "composite_score")
    assert rescored["status"] == CandidateStatus.SCORED


def test_rescoring_a_candidate_leaves_the_indicators_own_derived_fields_alone(api):
    """PRD §3.4: "The severity term is the indicator's current `severity_score`,
    snapshotted onto the candidate as `severity_input`."

    Design: Difficulty/dual_variant_calc/candidate_composite_equal_weight_vs_community_weighted_diverges
    """
    sc = build_scenario(api, stage="CANDIDATE_SCORED")
    before = sc.indicator()

    validate_success(api.score_candidate(sc.candidate_id, ScoringVariant.COMMUNITY_WEIGHTED))

    after = sc.indicator()
    assert_close(after["severity_score"], 77.50, "severity_score")
    assert_close(after["disparity_ratio"], 1.60, "disparity_ratio")
    assert after["version"] == before["version"]


def test_three_identical_charge_postings_round_per_posting_before_summing(api):
    """PRD §3.9: "each posting's `valued_cents` is rounded to a whole number of
    cents when the posting is valued, and the totals are sums of those
    already-rounded integers."

    Design: Difficulty/combinatorial_formula/report_total_rounds_per_posting_before_summing
    """
    cycle = create_cycle(api)
    report = open_report(api, cycle["id"])

    postings = [
        post_charge_based(api, report["id"], 1005, category=Category.FINANCIAL_ASSISTANCE)
        for _ in range(3)
    ]
    # 1005 * 0.32 = 321.6 -> 322 on each row.
    for posting in postings:
        assert posting["valued_cents"] == 322

    stored = validate_success(api.get_report(report["id"]))
    # 322 * 3 = 966; the sum-then-round reading would give 965.
    assert stored["financial_assistance_cents"] == 966
    assert stored["total_valued_cents"] == 966
    assert_close(stored["overhead_rate"], 0.05, "overhead_rate")
    assert stored["indirect_allocation_cents"] == 48
    assert stored["grand_total_cents"] == 1014


def test_a_single_charge_posting_rounds_half_up_at_the_cent(api):
    """PRD §3.9: "For a charge-based posting, `valued_cents` is the posting's
    `charges_cents` multiplied by the report's current `cost_to_charge_ratio`,
    rounded half up to a whole number of cents, and `ratio_applied` stores the
    exact ratio used."

    Design: Difficulty/combinatorial_formula/report_total_rounds_per_posting_before_summing
    """
    cycle = create_cycle(api)
    report = open_report(api, cycle["id"])

    posting = post_charge_based(api, report["id"], 1005, category=Category.FINANCIAL_ASSISTANCE)
    assert posting["valued_cents"] == 322
    assert_close(posting["ratio_applied"], C.PRIOR_YEAR_RATIO, "ratio_applied")

    stored = validate_success(api.get_report(report["id"]))
    assert stored["financial_assistance_cents"] == 322
    assert stored["total_valued_cents"] == 322


def test_overhead_tier_is_keyed_on_total_valued_and_not_on_the_grand_total(api):
    """PRD §3.9: "The base for indirect allocation is `total_valued_cents` — the
    sum of the five direct category totals, never `grand_total_cents`, which is
    derived from the allocation and would make the calculation circular."

    Design: Difficulty/combinatorial_formula/report_overhead_tier_keyed_on_direct_benefit_not_grand_total
    """
    cycle = create_cycle(api)
    report = open_report(api, cycle["id"])

    posting = post_cost_based(
        api, report["id"], 4900000, category=Category.COMMUNITY_HEALTH_IMPROVEMENT
    )
    assert_cost_based_posting(posting, 4900000)

    stored = validate_success(api.get_report(report["id"]))
    assert stored["total_valued_cents"] == 4900000
    # The base is under 5,000,000 so the rate is 0.05, not the 0.08 a
    # grand-total-keyed reading would reach.
    assert_close(stored["overhead_rate"], 0.05, "overhead_rate")
    assert stored["indirect_allocation_cents"] == 245000
    assert stored["grand_total_cents"] == 5145000
    assert_close(stored["benefit_pct_of_expense"], 4.29, "benefit_pct_of_expense")


def test_overhead_tier_boundary_belongs_to_the_higher_tier(api):
    """PRD §3.9: "The tier boundaries belong to the higher tier, so a base of
    exactly 5,000,000 cents selects 0.08 while 4,999,999 selects 0.05, and a base
    of exactly 25,000,000 selects 0.11."

    Design: Difficulty/combinatorial_formula/report_overhead_tier_keyed_on_direct_benefit_not_grand_total
    """
    cycle = create_cycle(api)
    report = open_report(api, cycle["id"])

    post_cost_based(api, report["id"], 4999999, category=Category.COMMUNITY_HEALTH_IMPROVEMENT)
    below = validate_success(api.get_report(report["id"]))
    assert below["total_valued_cents"] == 4999999
    assert_close(below["overhead_rate"], 0.05, "overhead_rate")

    post_cost_based(api, report["id"], 1, category=Category.CASH_AND_INKIND)
    at_boundary = validate_success(api.get_report(report["id"]))
    assert at_boundary["total_valued_cents"] == 5000000
    assert_close(at_boundary["overhead_rate"], 0.08, "overhead_rate")
    assert at_boundary["indirect_allocation_cents"] == 400000
    assert at_boundary["grand_total_cents"] == 5400000


def test_disparity_points_are_capped_at_one_hundred(api):
    """PRD §3.4: "otherwise it is the `disparity_ratio` less 1, multiplied by
    100, rounded half up to two decimal places, and then capped at 100.00 — so an
    indicator whose worst-off subgroup fares 1.4 times worse than its best-off
    subgroup contributes 40.00 disparity points, and any ratio at or beyond 2
    contributes the full 100.00."

    Design: Difficulty/combinatorial_formula/candidate_disparity_points_capped_by_min_at_100
    """
    sc = build_scenario(api, stage="PRIORITIZATION", high_value=27.5, low_value=10.0)

    indicator = sc.indicator()
    # 27.5 / 10.0 = 2.75.
    assert_close(indicator["disparity_ratio"], 2.75, "disparity_ratio")
    assert indicator["subgroup_count"] == 2

    scored = validate_success(api.score_candidate(sc.candidate_id, ScoringVariant.EQUAL_WEIGHT))
    # The uncapped term would be 175.00.
    assert_close(scored["disparity_points"], 100.00, "disparity_points")


def test_composite_score_uses_the_capped_disparity_term(api):
    """PRD §3.4: "In both variants a single round-half-up to two decimal places is
    applied to the finished weighted sum and never to the individual terms, and
    both variants therefore produce different composites from identical inputs
    whenever the four terms are not all equal."

    Design: Difficulty/combinatorial_formula/candidate_disparity_points_capped_by_min_at_100
    """
    sc = build_scenario(api, stage="PRIORITIZATION", high_value=27.5, low_value=10.0)

    scored = validate_success(api.score_candidate(sc.candidate_id, ScoringVariant.EQUAL_WEIGHT))
    assert_close(scored["severity_input"], 77.50, "severity_input")
    assert_close(scored["community_concern_index"], 100.00, "community_concern_index")
    # 0.25 * (77.50 + 100.00 + 100.00 + 70) = 86.875 -> 86.88; an uncapped
    # disparity term would have given 105.63.
    assert_close(scored["composite_score"], 86.88, "composite_score")
