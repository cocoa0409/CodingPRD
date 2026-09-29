"""The three financial ladders, their winning filing, and the org-type adjustments."""
from test_helpers import (
    ALL_STANDARDS_MET_GOVERNANCE,
    FILING_FY2023,
    FILING_FY2024,
    FILING_FY2025,
    PERFECT_GOVERNANCE,
    assert_ratio,
    assert_score,
    dimension_by_name,
    read_dimension_scores,
    score_cycle,
    submit_filing,
    submit_validated_filing,
    setup_scored_cycle,
    three_years_of,
    validate_filing,
    validate_paginated,
    with_amounts,
)

# Program 8,500,000 of 10,000,000, fundraising 1,000,000 of 5,000,000 raised and
# net assets of 10,000,000 — one figure set that lands on all three boundaries.
ON_EVERY_BOUNDARY = {
    "total_expense_cents": 10000000,
    "program_expense_cents": 8500000,
    "fundraising_expense_cents": 1000000,
    "admin_expense_cents": 500000,
    "contributions_cents": 5000000,
    "total_revenue_cents": 11000000,
    "net_assets_cents": 10000000,
    "total_liabilities_cents": 2000000,
}

# The same three ladders probed one unit off each boundary, so that only the
# pinned rounding order can put two of them back on the right side of it.
ONE_UNIT_OFF_EVERY_BOUNDARY = {
    "total_expense_cents": 10000000,
    "program_expense_cents": 8499999,
    "fundraising_expense_cents": 1000001,
    "admin_expense_cents": 500000,
    "contributions_cents": 5000000,
    "total_revenue_cents": 11000000,
    "net_assets_cents": 9995000,
    "total_liabilities_cents": 2000000,
}


def test_the_selector_prefers_the_audited_statement_over_a_later_public_filing(
    api, analyst_headers
):
    """A later, perfectly validated public filing and a rejected organization submission
    are both decoys: precedence beats recency and only VALIDATED rows are candidates.

    PRD §3.3: "The candidate set is every filing for that organization and that fiscal year whose `status` is `VALIDATED`; filings in `RECEIVED`, `REJECTED` or `SUPERSEDED` are never read, no matter how recent they are or how authoritative their `source_kind` looks."

    PRD §3.3: "Candidates are ranked first by `source_precedence` ascending, so an audited statement beats a public filing and a public filing beats an organization submission, and then, among candidates of equal precedence, by `created_at` ascending, so the earliest surviving submission wins."

    PRD §3.5: "The source term is 8 points when the cycle's fiscal year has a `VALIDATED` filing whose `source_kind` is `AUDITED_STATEMENT`, otherwise 4 points when it has a `VALIDATED` filing whose `source_kind` is `PUBLIC_FILING`, otherwise 0 — the two are alternatives and are never added together, and an organization holding both an audited statement and a public filing scores 8."

    Design: Corner/calculations/winning_filing_selector_prefers_the_audited_source_over_a_later_form_990
    """
    scenario = setup_scored_cycle(score=False)
    organization_id = scenario["organization"]["id"]

    submit_validated_filing(
        organization_id,
        fiscal_year=2025,
        source_kind="PUBLIC_FILING",
        total_expense_cents=10000000,
        program_expense_cents=5000000,
        fundraising_expense_cents=3000000,
        admin_expense_cents=2000000,
        contributions_cents=9000000,
        total_revenue_cents=11000000,
        net_assets_cents=1000000,
        total_liabilities_cents=2000000,
    )
    rejected = submit_filing(
        organization_id,
        fiscal_year=2025,
        source_kind="ORG_SUBMISSION",
        total_expense_cents=10000000,
        program_expense_cents=9500000,
        fundraising_expense_cents=300000,
        admin_expense_cents=200000,
        contributions_cents=9000000,
        total_revenue_cents=11000000,
        net_assets_cents=20000000,
        total_liabilities_cents=2000000,
    )
    validate_filing(rejected["id"], "REJECT", rejection_code="COMPONENTS_UNRECONCILED")

    cycle = score_cycle(scenario["cycle"]["id"], analyst_headers)

    assert_ratio(cycle["program_expense_ratio"], 0.7500, "program_expense_ratio")
    assert_score(cycle["months_of_reserve"], 7.20, "months_of_reserve")
    assert_ratio(cycle["fundraising_efficiency"], 0.1867, "fundraising_efficiency")

    rows = read_dimension_scores(cycle["id"], analyst_headers)
    financial = dimension_by_name(rows, "FINANCIAL_HEALTH")
    assert financial["raw_points"] == 29
    assert financial["max_points"] == 40
    assert_score(financial["normalized_score"], 72.50, "FINANCIAL_HEALTH normalized_score")

    transparency = dimension_by_name(rows, "TRANSPARENCY")
    assert transparency["raw_points"] == 20
    assert transparency["max_points"] == 20

    assert_score(cycle["final_composite_score"], 83.13, "final_composite_score")
    assert cycle["grade"] == "MEETS_STANDARDS"

    filings, meta = validate_paginated(
        api.list_organization_filing_records(
            organization_id, analyst_headers, params={"fiscal_year": 2025}
        )
    )
    assert meta["total_count"] == 3
    by_kind = {row["source_kind"]: row["status"] for row in filings}
    assert by_kind == {
        "AUDITED_STATEMENT": "VALIDATED",
        "PUBLIC_FILING": "VALIDATED",
        "ORG_SUBMISSION": "REJECTED",
    }


def test_all_three_financial_ladders_are_inclusive_at_their_own_boundary(analyst_headers):
    """One figure set sits exactly on a >= boundary, a <= boundary and a second >=
    boundary at once, so an off-by-one on any single ladder is diagnosable.

    PRD §3.5: "The ratio ladder rewards larger values: 20 points when `program_expense_ratio` is at least 0.85, otherwise 15 at 0.75 or more, otherwise 10 at 0.65 or more, otherwise 5 at 0.50 or more, otherwise 0."

    PRD §3.5: "The efficiency ladder rewards smaller values: 12 points when `fundraising_efficiency` is at most 0.10, otherwise 9 at 0.20 or less, otherwise 5 at 0.35 or less, otherwise 0."

    PRD §3.5: "The reserve ladder rewards larger values again: 8 points when `months_of_reserve` is at least 12, otherwise 5 at 6 or more, otherwise 2 at 3 or more, otherwise 0."

    Design: Corner/calculations/financial_tier_ladders_are_inclusive_at_every_boundary
    """
    scenario = setup_scored_cycle(
        org_overrides={
            "legal_name": "Trailhead Youth Corps",
            "ein": "666666666",
            "contact_email": "ops@trailheadyouth.org",
        },
        filings=three_years_of(ON_EVERY_BOUNDARY),
        governance_overrides=PERFECT_GOVERNANCE,
    )
    cycle = scenario["cycle"]

    assert_ratio(cycle["program_expense_ratio"], 0.8500, "program_expense_ratio")
    assert_ratio(cycle["fundraising_efficiency"], 0.2000, "fundraising_efficiency")
    assert_score(cycle["months_of_reserve"], 12.00, "months_of_reserve")

    rows = scenario["dimension_scores"]
    financial = dimension_by_name(rows, "FINANCIAL_HEALTH")
    assert financial["raw_points"] == 37
    assert financial["max_points"] == 40
    assert_score(financial["normalized_score"], 92.50, "FINANCIAL_HEALTH normalized_score")
    for dimension, raw, ceiling in (
        ("ACCOUNTABILITY", 24, 24),
        ("TRANSPARENCY", 20, 20),
        ("IMPACT", 12, 12),
    ):
        row = dimension_by_name(rows, dimension)
        assert row["raw_points"] == raw, dimension
        assert row["max_points"] == ceiling, dimension
        assert_score(row["normalized_score"], 100.00, f"{dimension} normalized_score")

    assert cycle["failed_standard_count"] == 0
    assert_score(cycle["weighted_sum_final"], 97.00, "weighted_sum_final")
    assert_score(cycle["standards_penalty_points"], 0.00, "standards_penalty_points")
    assert_score(cycle["final_composite_score"], 97.00, "final_composite_score")
    assert cycle["grade"] == "ACCREDITED"
    assert_score(cycle["data_completeness_pct"], 100.00, "data_completeness_pct")


def test_two_ladders_clear_a_boundary_they_only_reach_after_rounding(analyst_headers):
    """Rounding is not cosmetic: 0.84999990 clears a 0.85 ladder and 0.20000020 clears a
    0.20 ladder, while the two-place reserve figure stays below its own boundary.

    PRD §3.5: "If the adjusted total is zero or below, the ratio is exactly 0.0000; otherwise it is the adjusted program figure divided by the adjusted total, rounded half up to four decimal places."

    PRD §3.5: "For each available year, the year's ratio is that filing's `fundraising_expense_cents` divided by its `contributions_cents`, rounded half up to four decimal places at this point — before any weighting — except that a year whose `contributions_cents` is exactly zero takes the worst possible ratio of 1.0000 rather than dividing by zero."

    PRD §3.5: "Otherwise it is that filing's `net_assets_cents` multiplied by the twelve months in a year and divided by `total_expense_cents`, rounded half up to two decimal places."

    Design: Corner/calculations/ratio_and_efficiency_round_to_four_places_before_the_tier_comparison
    """
    scenario = setup_scored_cycle(
        org_overrides={
            "legal_name": "Riverbend Arts Council",
            "ein": "777777777",
            "contact_email": "ops@riverbendarts.org",
        },
        filings=three_years_of(ONE_UNIT_OFF_EVERY_BOUNDARY),
        governance_overrides=PERFECT_GOVERNANCE,
    )
    cycle = scenario["cycle"]

    assert_ratio(cycle["program_expense_ratio"], 0.8500, "program_expense_ratio")
    assert_ratio(cycle["fundraising_efficiency"], 0.2000, "fundraising_efficiency")
    assert_score(cycle["months_of_reserve"], 11.99, "months_of_reserve")

    financial = dimension_by_name(scenario["dimension_scores"], "FINANCIAL_HEALTH")
    assert financial["raw_points"] == 34
    assert_score(financial["normalized_score"], 85.00, "FINANCIAL_HEALTH normalized_score")

    assert_score(cycle["weighted_sum_final"], 94.00, "weighted_sum_final")
    assert_score(cycle["standards_penalty_points"], 0.00, "standards_penalty_points")
    assert_score(cycle["final_composite_score"], 94.00, "final_composite_score")
    assert cycle["grade"] == "ACCREDITED"


def test_a_private_foundation_adds_grants_paid_to_both_sides_and_ignores_joint_costs(
    analyst_headers,
):
    """The two adjustment tables are not mirror images: grants paid move both the
    numerator and the denominator, while the reported joint costs change nothing.

    PRD §3.5: "On the numerator side: for a `PUBLIC_CHARITY` or a `DONOR_ADVISED_SPONSOR`, the adjusted program figure is `program_expense_cents` less `joint_cost_allocated_cents`, stripping joint fundraising costs back out of program services; for a `PRIVATE_FOUNDATION` it is `program_expense_cents` plus `grants_paid_cents`; for a `MEMBERSHIP_ASSOCIATION` it is `program_expense_cents` plus `membership_services_cents`; and for a `RELIGIOUS_CONGREGATION` it is `program_expense_cents` unchanged."

    PRD §3.5: "On the denominator side only two types adjust at all: for a `PRIVATE_FOUNDATION` the adjusted total is `total_expense_cents` plus `grants_paid_cents`, for a `DONOR_ADVISED_SPONSOR` it is `total_expense_cents` **less** `grants_paid_cents`, and for all three remaining types it is `total_expense_cents` unchanged."

    PRD §3.5: "A missing year therefore shrinks the pool rather than dragging the figure toward zero — and pooling all three years' fundraising expenses over all three years' contributions and dividing once, though defensible accounting, is not this methodology and produces a different number."

    Design: Corner/calculations/private_foundation_adds_grants_paid_to_both_sides_of_the_ratio
    """
    scenario = setup_scored_cycle(
        org_overrides={
            "legal_name": "Cedar Ridge Foundation",
            "ein": "222222222",
            "org_type": "PRIVATE_FOUNDATION",
            "contact_email": "grants@cedarridge.org",
        },
        filings=[(2025, with_amounts(FILING_FY2025, grants_paid_cents=2000000))],
        governance_overrides=ALL_STANDARDS_MET_GOVERNANCE,
    )
    cycle = scenario["cycle"]

    assert_ratio(cycle["program_expense_ratio"], 0.8333, "program_expense_ratio")
    assert_ratio(cycle["fundraising_efficiency"], 0.1333, "fundraising_efficiency")
    assert_score(cycle["months_of_reserve"], 7.20, "months_of_reserve")

    filing = scenario["filing_by_year"][2025]
    assert filing["grants_paid_cents"] == 2000000
    assert filing["joint_cost_allocated_cents"] == 500000

    rows = scenario["dimension_scores"]
    financial = dimension_by_name(rows, "FINANCIAL_HEALTH")
    assert financial["raw_points"] == 29
    assert_score(financial["normalized_score"], 72.50, "FINANCIAL_HEALTH normalized_score")
    accountability = dimension_by_name(rows, "ACCOUNTABILITY")
    assert accountability["raw_points"] == 24
    assert accountability["max_points"] == 24
    assert_score(accountability["normalized_score"], 100.00, "ACCOUNTABILITY normalized_score")

    assert cycle["failed_standard_count"] == 0
    assert_score(cycle["weighted_sum_final"], 87.75, "weighted_sum_final")
    assert_score(cycle["standards_penalty_points"], 0.00, "standards_penalty_points")
    assert_score(cycle["final_composite_score"], 87.75, "final_composite_score")
    assert cycle["grade"] == "ACCREDITED"
    assert_score(cycle["data_completeness_pct"], 73.33, "data_completeness_pct")


def test_religious_exemptions_shrink_the_accountability_denominator_not_its_numerator(
    api, analyst_headers
):
    """Three inapplicable standards leave five gradeable ones, an unreviewed chief
    executive costs nothing, and the same filing yields a higher ratio than a charity's.

    PRD §3.4: "An inapplicable standard is emphatically **not** a failure: a `RELIGIOUS_CONGREGATION` with no audit committee scores exactly as one with an audit committee does, because inapplicability shrinks the accountability denominator rather than the numerator, leaving five gradeable standards rather than eight."

    PRD §3.5: "Its `max_points` is the smaller of 24 and 3 points multiplied by the number of gradeable standards, that is eight less `standards_not_applicable_count`."

    Design: Corner/calculations/religious_congregation_exemptions_shrink_the_accountability_denominator
    """
    scenario = setup_scored_cycle(
        org_overrides={
            "legal_name": "Saint Elias Congregation",
            "ein": "333333333",
            "org_type": "RELIGIOUS_CONGREGATION",
            "contact_email": "office@stelias.org",
        },
        filings=[(2025, FILING_FY2025)],
    )
    cycle = scenario["cycle"]
    profile = scenario["governance_profile"]

    assert_ratio(cycle["program_expense_ratio"], 0.8000, "program_expense_ratio")

    inapplicable, inapplicable_meta = validate_paginated(
        api.list_standard_evaluations(
            profile["id"], analyst_headers, params={"result": "NOT_APPLICABLE"}
        )
    )
    assert inapplicable_meta["total_count"] == 3
    assert sorted(row["standard_code"] for row in inapplicable) == [
        "AUDIT_COMMITTEE",
        "CEO_COMP_REVIEW",
        "COI_POLICY_CURRENCY",
    ]
    ceo_row = [
        row for row in inapplicable if row["standard_code"] == "CEO_COMP_REVIEW"
    ][0]
    assert ceo_row["result"] == "NOT_APPLICABLE"
    assert profile["ceo_compensation_reviewed"] is False
    assert profile["standards_met_count"] == 5
    assert profile["standards_not_met_count"] == 0
    assert profile["standards_waived_count"] == 0
    assert profile["standards_not_applicable_count"] == 3
    assert cycle["failed_standard_count"] == 0

    accountability = dimension_by_name(scenario["dimension_scores"], "ACCOUNTABILITY")
    assert accountability["raw_points"] == 15
    assert accountability["max_points"] == 15
    assert_score(accountability["normalized_score"], 100.00, "ACCOUNTABILITY normalized_score")

    assert_score(cycle["weighted_sum_final"], 87.75, "weighted_sum_final")
    assert_score(cycle["standards_penalty_points"], 0.00, "standards_penalty_points")
    assert_score(cycle["final_composite_score"], 87.75, "final_composite_score")
    assert cycle["grade"] == "ACCREDITED"


def test_a_missing_third_year_shrinks_the_efficiency_weight_pool(analyst_headers):
    """Two available years renormalise to 0.6250 and 0.3750 rather than letting the
    absent year contribute a zero ratio at its declared 0.20.

    PRD §3.5: "Otherwise the declared weights of the available years are summed into a weight pool, and each available year's renormalised weight is its declared weight divided by that pool, rounded half up to four decimal places."

    PRD §3.5: "Each available year then contributes a term equal to its rounded ratio multiplied by its rounded renormalised weight, itself rounded half up to four decimal places; those terms are summed, and the sum is rounded half up to four decimal places one final time."

    PRD §3.5: "The aggregate figure is what gates the `UNRATED` grade; the per-dimension figures are what the final variant consults to decide which dimensions to exclude, and **only an exact 0.00 excludes**, so a 33.33 financial-health row still participates in the final variant."

    Design: Corner/calculations/two_year_filer_renormalises_the_efficiency_weight_pool
    """
    scenario = setup_scored_cycle(
        filings=[(2025, FILING_FY2025), (2024, FILING_FY2024)]
    )
    cycle = scenario["cycle"]

    assert_ratio(cycle["fundraising_efficiency"], 0.1583, "fundraising_efficiency")

    financial = dimension_by_name(scenario["dimension_scores"], "FINANCIAL_HEALTH")
    assert financial["raw_points"] == 29
    assert_score(
        financial["data_completeness_pct"], 66.67, "FINANCIAL_HEALTH data_completeness_pct"
    )
    assert_score(financial["normalized_score"], 72.50, "FINANCIAL_HEALTH normalized_score")
    assert_ratio(financial["weight_applied"], 0.4000, "FINANCIAL_HEALTH weight_applied")

    assert_score(cycle["data_completeness_pct"], 86.67, "data_completeness_pct")
    assert_score(cycle["weighted_sum_final"], 84.63, "weighted_sum_final")
    assert_score(cycle["standards_penalty_points"], 1.50, "standards_penalty_points")
    assert_score(cycle["final_composite_score"], 83.13, "final_composite_score")
    assert cycle["grade"] == "MEETS_STANDARDS"


def test_a_year_that_raised_nothing_takes_the_worst_possible_efficiency_ratio(
    analyst_headers,
):
    """The division-by-zero guard is a scoring decision: three zero-contribution years
    pin the efficiency at 1.0000 and forfeit all twelve efficiency points.

    PRD §3.5: "If no year at all has a winning filing, `fundraising_efficiency` is 1.0000, the worst possible value."

    PRD §3.6: "**Step three** derives a band from that **pre-penalty** weighted sum: band A when the weighted sum is at least 90, band B at 75 or more, band C at 60 or more, band D below that."

    Design: Corner/calculations/zero_contributions_year_pins_the_efficiency_ratio_to_the_worst_value
    """
    scenario = setup_scored_cycle(
        org_overrides={
            "legal_name": "Northgate Endowment Trust",
            "ein": "888888888",
            "contact_email": "ops@northgatetrust.org",
        },
        filings=[
            (2025, with_amounts(FILING_FY2025, contributions_cents=0)),
            (2024, with_amounts(FILING_FY2024, contributions_cents=0)),
            (2023, with_amounts(FILING_FY2023, contributions_cents=0)),
        ],
    )
    cycle = scenario["cycle"]

    assert_ratio(cycle["fundraising_efficiency"], 1.0000, "fundraising_efficiency")
    assert_ratio(cycle["program_expense_ratio"], 0.7500, "program_expense_ratio")
    assert_score(cycle["months_of_reserve"], 7.20, "months_of_reserve")

    financial = dimension_by_name(scenario["dimension_scores"], "FINANCIAL_HEALTH")
    assert financial["raw_points"] == 20
    assert_score(financial["normalized_score"], 50.00, "FINANCIAL_HEALTH normalized_score")

    assert_score(cycle["data_completeness_pct"], 100.00, "data_completeness_pct")
    assert_score(cycle["weighted_sum_final"], 75.63, "weighted_sum_final")
    assert_score(cycle["standards_penalty_points"], 1.50, "standards_penalty_points")
    assert_score(cycle["final_composite_score"], 74.13, "final_composite_score")
    assert cycle["grade"] == "MEETS_STANDARDS"
