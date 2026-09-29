"""Governance thresholds, credibility clamping and the penalty-target selector."""
from test_helpers import (
    assert_instant,
    assert_ratio,
    assert_score,
    assert_standards_partition,
    add_cycle_for_year,
    create_cycle,
    create_organization,
    create_governance_profile,
    dimension_by_name,
    evaluate_governance_profile,
    file_complaint,
    read_cycle,
    read_dimension_scores,
    read_organization,
    read_standard_evaluations,
    resolve_complaint,
    set_clock,
    setup_scored_cycle,
    standard_by_code,
    triage_complaint,
    validate_paginated,
    validate_success,
)

# A board of eight with four independent members sits exactly on the 0.5000
# independence threshold, and a review 730 days old sits exactly on the horizon.
ON_BOTH_BOUNDARIES = {
    "board_member_count": 8,
    "independent_board_member_count": 4,
    "coi_policy_reviewed_at": "2024-09-01T00:00:00Z",
    "ceo_compensation_reviewed": True,
}

# One member fewer and one second older, which is enough to fail both.
JUST_BELOW_BOTH_BOUNDARIES = {
    "board_member_count": 7,
    "independent_board_member_count": 3,
    "coi_policy_reviewed_at": "2024-08-31T23:59:59Z",
    "ceo_compensation_reviewed": True,
}


def test_independence_and_policy_currency_are_both_inclusive_at_their_threshold(
    analyst_headers,
):
    """Two thresholds of different kinds — one arithmetic and rounded, one temporal and
    measured backwards from the logical clock — are probed one unit apart.

    PRD §3.4: "`BOARD_INDEPENDENCE` — observed is the computed `independence_ratio`, required is "0.5000", and the standard is met when that ratio is at least 0.5000."

    PRD §3.4: "`COI_POLICY_CURRENCY` — observed is `coi_policy_reviewed_at` or the literal "null" when it is absent, required is "reviewed within 730 days", and the standard is met when `coi_policy_reviewed_at` is present and falls at or after the logical clock less 730 days."

    PRD §3.4: "It first computes `independence_ratio` as `independent_board_member_count` divided by `board_member_count`, rounded half up to four decimal places, defined as 0.0000 when `board_member_count` is zero."

    PRD §3.4: "Evaluation then sets `standards_met_count` to the number of `MET` rows, `standards_not_met_count` to the number of `NOT_MET` rows, `standards_waived_count` to zero, and `standards_not_applicable_count` to the number of `NOT_APPLICABLE` rows — the four counts always partition eight — copies `standards_not_met_count` onto the owning cycle's `failed_standard_count`, advances that cycle's `version` counter by one, moves the profile `PENDING` → `EVALUATED`, stamps `evaluated_at`, and advances the profile's own `version` counter by one."

    Design: Corner/calculations/coi_currency_and_board_independence_boundaries_are_both_inclusive
    """
    scenario = setup_scored_cycle(evaluate=False, score=False)
    cycle_on_boundary = scenario["cycle"]
    cycle_below_boundary = create_cycle(
        scenario["organization"]["id"],
        scenario["methodology"]["id"],
        headers=analyst_headers,
        fiscal_year=2024,
        period_start="2024-01-01T00:00:00Z",
        period_end="2025-01-01T00:00:00Z",
    )

    profile_on_boundary = create_governance_profile(
        cycle_on_boundary["id"], headers=analyst_headers, **ON_BOTH_BOUNDARIES
    )
    profile_below_boundary = create_governance_profile(
        cycle_below_boundary["id"], headers=analyst_headers, **JUST_BELOW_BOTH_BOUNDARIES
    )

    evaluated_on_boundary = evaluate_governance_profile(
        profile_on_boundary["id"], analyst_headers
    )
    evaluated_below_boundary = evaluate_governance_profile(
        profile_below_boundary["id"], analyst_headers
    )

    assert_ratio(
        evaluated_on_boundary["independence_ratio"], 0.5000, "independence_ratio"
    )
    assert evaluated_on_boundary["standards_met_count"] == 8
    assert evaluated_on_boundary["standards_not_met_count"] == 0
    assert_standards_partition(evaluated_on_boundary)

    rows_on_boundary = read_standard_evaluations(
        profile_on_boundary["id"], analyst_headers
    )
    independence = standard_by_code(rows_on_boundary, "BOARD_INDEPENDENCE")
    assert independence["result"] == "MET"
    assert_ratio(independence["observed_value"], 0.5000, "observed independence ratio")
    assert_ratio(independence["required_value"], 0.5000, "required independence ratio")
    currency = standard_by_code(rows_on_boundary, "COI_POLICY_CURRENCY")
    assert currency["result"] == "MET"
    for row in rows_on_boundary:
        assert_instant(row["evaluated_at"], "2026-09-01T00:00:00Z", "evaluated_at")

    assert_ratio(
        evaluated_below_boundary["independence_ratio"], 0.4286, "independence_ratio"
    )
    assert evaluated_below_boundary["standards_met_count"] == 6
    assert evaluated_below_boundary["standards_not_met_count"] == 2
    assert_standards_partition(evaluated_below_boundary)

    rows_below_boundary = read_standard_evaluations(
        profile_below_boundary["id"], analyst_headers
    )
    independence_below = standard_by_code(rows_below_boundary, "BOARD_INDEPENDENCE")
    assert independence_below["result"] == "NOT_MET"
    assert_ratio(
        independence_below["observed_value"], 0.4286, "observed independence ratio"
    )
    assert standard_by_code(rows_below_boundary, "COI_POLICY_CURRENCY")["result"] == "NOT_MET"

    assert read_cycle(cycle_on_boundary["id"], analyst_headers)["failed_standard_count"] == 0
    assert read_cycle(cycle_below_boundary["id"], analyst_headers)["failed_standard_count"] == 2


def test_the_investigated_credibility_score_is_clamped_to_one_hundred_before_rounding(
    api, analyst_headers, public_headers
):
    """An employee alleging misuse with five documents overshoots the ceiling once the
    pattern and finding terms land, and the pattern term counts other complaints only.

    PRD §3.8: "The base is the complainant's standing — `DONOR` 30 points, `BENEFICIARY` 25, `EMPLOYEE` 35, `ANONYMOUS` 10 — plus the category — `MISUSE_OF_FUNDS` 30, `GOVERNANCE` 25, `SOLICITATION_PRACTICE` 20, `TRANSPARENCY` 15, `OTHER` 5 — plus 8 points for each corroborating document, counting at most 3 of them, so documentary support contributes at most 24 points however many files arrive."

    PRD §3.8: "The investigated variant adds two further terms — 5 points for each **other** complaint of the same organization already in `SUBSTANTIATED`, capped at 20 points in total, and then either 10 points when the finding is `SUBSTANTIATED` or a subtraction of 15 points when it is `UNSUBSTANTIATED`."

    PRD §3.8: "The result is clamped to the 0.00–100.00 range and only then rounded to 2 decimal places, so a clamped score is exactly `100.00`."

    PRD §3.8: "When that candidate set is empty the field stays null, hops two through four are simply skipped, and **no error is raised** — a substantiated complaint against a charity with no open cycle is recorded, counts toward future pattern scoring, and penalises nothing."

    Design: Corner/calculations/complaint_credibility_ceiling_clamps_before_rounding
    """
    set_clock("2026-09-01T00:00:00Z")
    organization = create_organization()

    prior = triage_complaint(
        file_complaint(
            organization["id"],
            headers=public_headers,
            narrative="Restricted gift spent on overhead",
        )["id"],
        "INVESTIGATE",
        triage_note="Worth a look",
    )
    prior = resolve_complaint(
        prior["id"], "SUBSTANTIATED", 5, finding_note="Partially confirmed"
    )
    assert prior["status"] == "SUBSTANTIATED"
    assert prior["penalized_rating_cycle_id"] is None

    complaint = file_complaint(
        organization["id"],
        headers=public_headers,
        complainant_kind="EMPLOYEE",
        category="MISUSE_OF_FUNDS",
        narrative="Program funds routed to an affiliate",
        corroborating_document_count=5,
    )
    at_intake = triage_complaint(
        complaint["id"], "INVESTIGATE", triage_note="Documents attached"
    )
    assert_score(at_intake["credibility_score"], 89.00, "intake credibility_score")
    assert at_intake["credibility_variant"] == "INTAKE"
    assert at_intake["severity_tier"] == "HIGH"

    resolved = resolve_complaint(
        complaint["id"], "SUBSTANTIATED", 15, finding_note="Confirmed in full"
    )
    assert_score(resolved["credibility_score"], 100.00, "investigated credibility_score")
    assert resolved["credibility_variant"] == "INVESTIGATED"
    assert resolved["severity_tier"] == "HIGH"
    assert resolved["penalty_points_applied"] == 15
    assert resolved["penalized_rating_cycle_id"] is None
    assert_instant(resolved["resolved_at"], "2026-09-01T00:00:00Z", "resolved_at")

    untouched = validate_success(api.get_complaint(prior["id"], analyst_headers))
    assert_score(untouched["credibility_score"], 70.00, "prior credibility_score")
    assert untouched["severity_tier"] == "MEDIUM"
    assert untouched["penalty_points_applied"] == 5

    assert read_organization(organization["id"])["substantiated_complaint_count"] == 2


def test_a_substantiated_finding_penalises_the_highest_fiscal_year_open_cycle(
    api, analyst_headers, public_headers
):
    """The FY2024 cycle was created first, yet the selector ranks by fiscal year
    descending, so the penalty lands on the FY2025 cycle that was created second.

    PRD §3.8: "Hop one writes the finding: the recomputed credibility figures, `penalty_points_applied`, `finding_note` and `resolved_at`, plus the choice of victim — `penalized_rating_cycle_id` is set by the penalty-target selector, which considers the rating cycles of the complained-about organization whose `status` is neither `PUBLISHED` nor `WITHDRAWN`, ranks them by `fiscal_year` descending so the most recent open cycle absorbs the penalty, breaks ties by `created_at` ascending and never consults `id`, and takes the first."

    PRD §3.8: "Hop two, caused by hop one naming a cycle, adds `penalty_points` to the `penalty_points` field of that cycle's `ACCOUNTABILITY` dimension row, recomputes its `raw_points` as the base points less the accumulated penalty floored at 0 so the row can never go negative, and moves the row `COMPUTED` or `OVERRIDDEN` → `STALE`."

    PRD §3.6: "When a row goes stale the parent cycle immediately recomputes its **provisional** figures from the adjusted rows, while its final figures stand as last written until the next score."

    Design: Corner/calculations/complaint_penalty_target_prefers_the_most_recent_open_cycle
    """
    scenario = setup_scored_cycle(
        evaluate=False,
        score=False,
        cycle_overrides={
            "fiscal_year": 2024,
            "period_start": "2024-01-01T00:00:00Z",
            "period_end": "2025-01-01T00:00:00Z",
        },
    )
    earlier_cycle = scenario["cycle"]
    scored = add_cycle_for_year(
        scenario,
        fiscal_year=2025,
        period_start="2025-01-01T00:00:00Z",
        period_end="2026-01-01T00:00:00Z",
    )
    later_cycle = scored["cycle"]
    assert_score(later_cycle["final_composite_score"], 83.13, "final_composite_score")

    complaint = triage_complaint(
        file_complaint(
            scenario["organization"]["id"],
            headers=public_headers,
            narrative="Appeal mailing paid from a restricted program fund",
        )["id"],
        "INVESTIGATE",
        triage_note="Opening an investigation",
    )
    resolved = resolve_complaint(
        complaint["id"], "SUBSTANTIATED", 5, finding_note="Confirmed by the grant agreement"
    )

    assert resolved["penalized_rating_cycle_id"] == later_cycle["id"]
    assert_score(resolved["credibility_score"], 70.00, "credibility_score")
    assert resolved["severity_tier"] == "MEDIUM"

    penalised = read_cycle(later_cycle["id"], analyst_headers)
    assert penalised["accountability_penalty_points"] == 5
    assert_score(penalised["weighted_sum_provisional"], 79.42, "weighted_sum_provisional")
    assert_score(
        penalised["provisional_composite_score"], 77.92, "provisional_composite_score"
    )
    assert penalised["provisional_grade"] == "MEETS_STANDARDS"
    assert_score(penalised["weighted_sum_final"], 84.63, "weighted_sum_final")
    assert_score(penalised["final_composite_score"], 83.13, "final_composite_score")

    rows = read_dimension_scores(later_cycle["id"], analyst_headers)
    accountability = dimension_by_name(rows, "ACCOUNTABILITY")
    assert accountability["status"] == "STALE"
    assert accountability["penalty_points"] == 5
    assert accountability["raw_points"] == 16
    assert_score(accountability["normalized_score"], 66.67, "ACCOUNTABILITY normalized_score")
    for dimension in ("FINANCIAL_HEALTH", "TRANSPARENCY", "IMPACT"):
        assert dimension_by_name(rows, dimension)["status"] == "COMPUTED", dimension

    untouched = read_cycle(earlier_cycle["id"], analyst_headers)
    assert untouched["status"] == "DATA_COLLECTION"
    assert untouched["accountability_penalty_points"] == 0
    assert untouched["failed_standard_count"] == 0
    _rows, earlier_meta = validate_paginated(
        api.list_dimension_scores(earlier_cycle["id"], analyst_headers)
    )
    assert earlier_meta["total_count"] == 0

    _complaints, complaint_meta = validate_paginated(
        api.list_complaints(
            analyst_headers, params={"penalized_rating_cycle_id": later_cycle["id"]}
        )
    )
    assert complaint_meta["total_count"] == 1
