"""The ledger's change classification, its variant handover, and the impact projection."""
from test_helpers import (
    NO_IMPACT_GOVERNANCE,
    PERFECT_GOVERNANCE,
    add_cycle_for_year,
    assert_instant,
    assert_ratio,
    assert_score,
    dimension_by_name,
    open_org_review,
    override_dimensions,
    publish_cycle,
    read_cycle,
    read_dimension_scores,
    read_organization,
    read_publication_records,
    set_clock,
    setup_published_cycle,
    setup_transition_grant,
    validate_paginated,
)

# Figures that earn all forty FINANCIAL_HEALTH points on both cycle years.
BEACON_FY2025 = {
    "total_expense_cents": 10000000,
    "program_expense_cents": 8600000,
    "fundraising_expense_cents": 900000,
    "admin_expense_cents": 500000,
    "contributions_cents": 9000000,
    "total_revenue_cents": 11000000,
    "net_assets_cents": 10000000,
    "total_liabilities_cents": 2000000,
}
BEACON_FY2024 = {
    "total_expense_cents": 6000000,
    "program_expense_cents": 5200000,
    "fundraising_expense_cents": 500000,
    "admin_expense_cents": 300000,
    "contributions_cents": 5000000,
    "total_revenue_cents": 6500000,
    "net_assets_cents": 6000000,
    "total_liabilities_cents": 1000000,
}
BEACON_FY2023 = {
    "total_expense_cents": 4000000,
    "program_expense_cents": 3400000,
    "fundraising_expense_cents": 400000,
    "admin_expense_cents": 200000,
    "contributions_cents": 4000000,
    "total_revenue_cents": 4200000,
    "net_assets_cents": 4000000,
    "total_liabilities_cents": 800000,
}


def test_a_ten_point_fall_notifies_the_press_while_the_first_publication_did_not(
    api, analyst_headers, reviewer_headers, public_headers
):
    """The second record lands exactly on the media threshold, and the predecessor it
    measures itself against is found by sequence number rather than by creation order.

    PRD §3.9: "It populates `notified_recipient_kinds` as an ordered list that always begins with `RATED_ORGANIZATION` and appends `MEDIA` only when `change_direction` is not `FIRST_PUBLICATION` and the absolute value of `score_delta` is at least `10.00`."

    PRD §3.9: "The media threshold is symmetric, so a rise of `+10.00` notifies exactly as a fall of `-10.00` does, and inclusive at ten, so a delta of `8.75` does not notify; a first publication never notifies media however extreme its score."

    PRD §3.9: "Otherwise the predecessor is the row of the same organization whose `sequence_number` is exactly one lower — identified by sequence number, never by `created_at` ordering — `previous_published_score` is that row's `published_score`, `score_delta` is this publication's `published_score` minus it rounded to 2 decimal places, and `change_direction` is `IMPROVED` when the delta is positive, `DECLINED` when negative and `UNCHANGED` when exactly zero."

    Design: Corner/calculations/media_notification_fires_at_exactly_ten_points_of_decline
    """
    scenario = setup_published_cycle(
        org_overrides={
            "legal_name": "Beacon Literacy Alliance",
            "ein": "444444444",
            "contact_email": "ops@beaconliteracy.org",
        },
        filings=[
            (2025, BEACON_FY2025),
            (2024, BEACON_FY2024),
            (2023, BEACON_FY2023),
        ],
        governance_overrides=PERFECT_GOVERNANCE,
    )
    assert_score(scenario["cycle"]["final_composite_score"], 100.00, "first published score")

    second = add_cycle_for_year(
        scenario,
        fiscal_year=2024,
        period_start="2024-01-01T00:00:00Z",
        period_end="2025-01-01T00:00:00Z",
        governance_overrides=PERFECT_GOVERNANCE,
    )
    second_cycle = second["cycle"]
    financial = dimension_by_name(
        read_dimension_scores(second_cycle["id"], analyst_headers), "FINANCIAL_HEALTH"
    )
    override_dimensions(
        second_cycle["id"],
        [{"dimension_score_id": financial["id"], "raw_points": 30}],
        second_cycle["version"],
        override_reason="Analyst discount for a restated FY2024 schedule",
    )
    in_review = open_org_review(second_cycle["id"], analyst_headers)
    set_clock(in_review["correction_deadline_at"])
    published = publish_cycle(
        second_cycle["id"],
        reviewer_headers,
        publishing_reviewer_note="FY2024 released after the analyst discount",
    )

    assert_score(published["final_composite_score"], 90.00, "second published score")
    assert_score(published["data_completeness_pct"], 86.67, "data_completeness_pct")

    records = read_publication_records(
        public_headers, organization_id=scenario["organization"]["id"]
    )
    assert len(records) == 2
    first_record, second_record = records

    assert first_record["sequence_number"] == 1
    assert first_record["score_delta"] is None
    assert first_record["previous_published_score"] is None
    assert first_record["change_direction"] == "FIRST_PUBLICATION"
    assert first_record["notified_recipient_kinds"] == ["RATED_ORGANIZATION"]

    assert second_record["sequence_number"] == 2
    assert_score(second_record["score_delta"], -10.00, "score_delta")
    assert second_record["change_direction"] == "DECLINED"
    assert second_record["notified_recipient_kinds"] == ["RATED_ORGANIZATION", "MEDIA"]
    assert_score(
        second_record["previous_published_score"], 100.00, "previous_published_score"
    )
    assert second_record["published_grade"] == "ACCREDITED"

    organization = read_organization(scenario["organization"]["id"])
    assert_score(organization["latest_published_score"], 90.00, "latest_published_score")
    assert organization["latest_published_grade"] == "ACCREDITED"
    assert organization["published_cycle_count"] == 2
    assert organization["trend_direction"] == "DECLINED"


def test_the_ledger_copies_the_final_variant_and_not_the_figure_shown_during_review(
    api, analyst_headers, public_headers
):
    """The charity's review window shows 69.88 and NEEDS_IMPROVEMENT while the record the
    donor reads carries 81.88 and MEETS_STANDARDS, twelve points and two grades apart.

    PRD §3.6: "The provisional family — `weighted_sum_provisional`, `provisional_composite_score` and `provisional_grade` — is rewritten at every score and every recompute, and it is the only figure the rated organization sees during its review window and the only figure an appeal can contest."

    PRD §3.9: "It copies `published_score` from the cycle's `final_composite_score`, `published_grade` from its `grade`, `weighted_sum_final` and `standards_penalty_points` from the cycle's like-named fields, `methodology_version_label` from the `version_label` of the methodology version pinned on the cycle, and `published_at` from the cycle."

    PRD §3.9: "Note that the final family is (re)computed here, at publication, from whatever the inputs then are; the provisional family the organization saw during review is not what gets published."

    Design: Corner/calculations/publication_record_copies_the_final_variant_not_the_provisional
    """
    scenario = setup_published_cycle(governance_overrides=NO_IMPACT_GOVERNANCE)
    cycle = read_cycle(scenario["cycle"]["id"], analyst_headers)

    assert_score(cycle["data_completeness_pct"], 85.00, "data_completeness_pct")
    assert_score(cycle["weighted_sum_provisional"], 70.88, "weighted_sum_provisional")
    assert_score(
        cycle["provisional_composite_score"], 69.88, "provisional_composite_score"
    )
    assert cycle["provisional_grade"] == "NEEDS_IMPROVEMENT"
    assert_score(cycle["weighted_sum_final"], 83.38, "weighted_sum_final")
    assert_score(cycle["final_composite_score"], 81.88, "final_composite_score")
    assert cycle["grade"] == "MEETS_STANDARDS"

    rows = read_dimension_scores(cycle["id"], analyst_headers)
    impact = dimension_by_name(rows, "IMPACT")
    assert_score(impact["normalized_score"], 0.00, "IMPACT normalized_score")
    assert_score(impact["data_completeness_pct"], 0.00, "IMPACT data_completeness_pct")
    assert_ratio(impact["weight_applied"], 0.0000, "IMPACT weight_applied")
    assert_score(impact["weighted_contribution"], 0.00, "IMPACT weighted_contribution")
    financial = dimension_by_name(rows, "FINANCIAL_HEALTH")
    assert_ratio(financial["weight_applied"], 0.4706, "FINANCIAL_HEALTH weight_applied")
    assert_score(
        financial["weighted_contribution"], 34.12, "FINANCIAL_HEALTH weighted_contribution"
    )

    records = read_publication_records(public_headers, rating_cycle_id=cycle["id"])
    assert len(records) == 1
    record = records[0]
    assert_score(record["published_score"], 81.88, "published_score")
    assert record["published_grade"] == "MEETS_STANDARDS"
    assert_score(record["weighted_sum_final"], 83.38, "record weighted_sum_final")
    assert "weighted_sum_provisional" not in record
    assert "provisional_composite_score" not in record
    assert "provisional_grade" not in record

    organization = read_organization(scenario["organization"]["id"])
    assert_score(organization["latest_published_score"], 81.88, "latest_published_score")
    assert organization["latest_published_grade"] == "MEETS_STANDARDS"


def test_a_five_point_projected_fall_earns_transition_relief_on_the_threshold(
    api, admin_headers, analyst_headers, public_headers
):
    """The projection replays the stored dimension rows under the successor's weights and
    lands exactly 5.00 points below the published figure, which is inclusive.

    PRD §3.2: "Against those stored rows it evaluates the composite calculation of §3.6 in its final variant, but with the **new** version's four weights and the **new** version's `dimension_floor_score`, reusing the published cycle's own `failed_standard_count` and `data_completeness_pct`."

    PRD §3.2: "When that delta is at most negative 5.00 — the threshold is inclusive, so a delta of exactly negative 5.00 qualifies — the organization receives one `TransitionGrant` with `status` `ACTIVE`, its `organization_id` and its `methodology_version_id` set to the newly adopted version, its `superseded_version_label` set to the retiring version's `version_label`, its `grace_until` set to `adopted_at` plus the adopting version's `transition_period_days`, its `projected_score_delta` recorded, and its `trigger_reason` set to `WEIGHT_CHANGE` when any of the four weights differs from the retiring version's corresponding weight and to `THRESHOLD_TIGHTENED` otherwise, which in practice means the floor score was raised."

    PRD §3.2: "In the same hop, the methodology version that was `ADOPTED` — the one named by `supersedes_version_id` — moves `ADOPTED` → `RETIRED`, its `retired_at` takes the logical clock and its `effective_until` is closed at the new version's `effective_from`."

    PRD §3.2: "**Hop three**, caused by hop two's grant creation, propagates the grace."

    Design: Corner/calculations/methodology_projection_grants_transition_relief_at_exactly_minus_five
    """
    scenario = setup_transition_grant(effective_until="2026-12-31T00:00:00Z")

    assert scenario["successor_methodology"]["status"] == "ADOPTED"
    assert_instant(
        scenario["successor_methodology"]["effective_from"],
        "2027-01-30T00:00:00Z",
        "successor effective_from",
    )

    retired = scenario["methodology"]
    assert retired["status"] == "RETIRED"
    assert_instant(retired["retired_at"], "2026-09-22T00:00:00Z", "retired_at")
    assert_instant(retired["effective_until"], "2027-01-30T00:00:00Z", "effective_until")

    grants, grant_meta = validate_paginated(
        api.list_transition_grants(
            admin_headers, params={"organization_id": scenario["organization"]["id"]}
        )
    )
    assert grant_meta["total_count"] == 1
    grant = grants[0]
    assert grant["status"] == "ACTIVE"
    assert_score(grant["projected_score_delta"], -5.00, "projected_score_delta")
    assert grant["superseded_version_label"] == "M1"
    assert grant["trigger_reason"] == "WEIGHT_CHANGE"
    assert_instant(grant["grace_until"], "2026-12-21T00:00:00Z", "grace_until")
    assert_instant(
        scenario["organization"]["transition_grace_until"],
        "2026-12-21T00:00:00Z",
        "transition_grace_until",
    )

    published = read_cycle(scenario["cycle"]["id"], analyst_headers)
    assert published["status"] == "PUBLISHED"
    assert_score(published["final_composite_score"], 83.13, "final_composite_score")
    rows = read_dimension_scores(published["id"], analyst_headers)
    assert all(row["status"] == "COMPUTED" for row in rows)
    for dimension, weight in (
        ("FINANCIAL_HEALTH", 0.4000),
        ("ACCOUNTABILITY", 0.2500),
        ("TRANSPARENCY", 0.2000),
        ("IMPACT", 0.1500),
    ):
        assert_ratio(
            dimension_by_name(rows, dimension)["weight_applied"],
            weight,
            f"{dimension} weight_applied",
        )

    records = read_publication_records(public_headers, rating_cycle_id=published["id"])
    assert len(records) == 1
    assert records[0]["sequence_number"] == 1
    assert_score(records[0]["published_score"], 83.13, "published_score")
