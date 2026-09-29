"""Two quantities conserved across an action and its compensating inverse."""
from test_helpers import (
    assert_score,
    dimension_by_name,
    file_complaint,
    make_public_headers,
    read_cycle,
    read_dimension_scores,
    read_governance_profile,
    read_organization,
    read_standard_evaluations,
    resolve_complaint,
    reverse_complaint_finding,
    revoke_standard_waiver,
    setup_scored_cycle,
    triage_complaint,
    waive_standard,
)


def _partition_total(profile):
    return (
        profile["standards_met_count"]
        + profile["standards_not_met_count"]
        + profile["standards_waived_count"]
        + profile["standards_not_applicable_count"]
    )


def _failed_standard(scenario):
    failed = [
        row for row in read_standard_evaluations(scenario["governance_profile"]["id"])
        if row["result"] == "NOT_MET"
    ]
    assert len(failed) == 1
    return failed[0]


def test_waiving_the_failed_standard_moves_one_unit_between_buckets_without_resizing_them(
    api, admin_headers
):
    """The eight standards still partition eight after the waiver, but a waived standard
    is worth two points where a met one is worth three, so the score moves.

    PRD §3.4: "The waiver ripples upward: the profile's `standards_not_met_count` falls by one while its `standards_waived_count` rises by one and its `version` counter advances; the cycle's `failed_standard_count` falls by one and its `version` counter advances; and when the cycle's `ACCOUNTABILITY` dimension row is currently `COMPUTED` or `OVERRIDDEN`, that row's `raw_points`, `normalized_score` and `weighted_contribution` are recomputed and the cycle's provisional and final figures are rewritten."

    PRD §3.4: "The recomputation matters because a `WAIVED` standard is worth 2 accountability points where a `MET` standard is worth 3 — waiving a failure improves the score without pretending the shortfall never happened."

    Design: Difficulty/compensating_invariant/standards_partition_conserved_across_waive_and_revoke
    """
    scenario = setup_scored_cycle()
    before_profile = read_governance_profile(scenario["governance_profile"]["id"])
    assert _partition_total(before_profile) == 8
    assert before_profile["standards_met_count"] == 7
    assert before_profile["standards_not_met_count"] == 1
    failed = _failed_standard(scenario)
    assert failed["standard_code"] == "CEO_COMP_REVIEW"

    waived = waive_standard(
        failed["id"],
        waiver_reason="compensation review documented outside the filing window",
    )
    assert waived["result"] == "WAIVED"

    profile = read_governance_profile(before_profile["id"])
    assert _partition_total(profile) == 8
    assert profile["standards_met_count"] == 7
    assert profile["standards_not_met_count"] == 0
    assert profile["standards_waived_count"] == 1
    assert profile["standards_not_applicable_count"] == 0

    accountability = dimension_by_name(
        read_dimension_scores(scenario["cycle"]["id"], scenario["analyst_headers"]),
        "ACCOUNTABILITY",
    )
    assert accountability["raw_points"] == 23
    assert accountability["max_points"] == 24
    assert_score(accountability["normalized_score"], 95.83, "ACCOUNTABILITY normalized_score")

    cycle = read_cycle(scenario["cycle"]["id"])
    assert cycle["failed_standard_count"] == 0
    assert_score(cycle["weighted_sum_provisional"], 86.71, "weighted_sum_provisional")
    assert_score(cycle["standards_penalty_points"], 0.00, "standards_penalty_points")
    assert_score(
        cycle["provisional_composite_score"], 86.71, "provisional_composite_score"
    )
    assert cycle["provisional_grade"] == "ACCREDITED"


def test_revoking_the_waiver_restores_every_figure_and_advances_only_the_version_counters(
    api, admin_headers
):
    """The waiver and its revocation leave no residue: each figure returns to its
    pre-waiver value and only the three version counters record that anything happened.

    PRD §3.4: "The profile's `standards_waived_count` falls by one while `standards_not_met_count` rises by one and its `version` counter advances; the cycle's `failed_standard_count` rises by one and its `version` counter advances; the `ACCOUNTABILITY` dimension row's `raw_points` and the cycle's provisional and final figures return to precisely their pre-waiver values; and the standard evaluation's own `version` counter advances by one."

    PRD §3.4: "After any waiver and revocation pair the four `standards_*_count` fields still sum to eight and no figure carries residual drift."

    Design: Difficulty/compensating_invariant/standards_partition_conserved_across_waive_and_revoke
    """
    scenario = setup_scored_cycle()
    failed = _failed_standard(scenario)
    profile_before = read_governance_profile(scenario["governance_profile"]["id"])
    cycle_before = read_cycle(scenario["cycle"]["id"])

    waive_standard(failed["id"])
    restored = revoke_standard_waiver(
        failed["id"], revocation_note="waiver granted in error"
    )

    assert restored["result"] == "NOT_MET"
    assert restored["waiver_reason"] is None
    assert restored["waived_by_user_id"] is None
    assert restored["version"] == failed["version"] + 2

    profile_after = read_governance_profile(profile_before["id"])
    assert _partition_total(profile_after) == 8
    assert profile_after["standards_met_count"] == 7
    assert profile_after["standards_not_met_count"] == 1
    assert profile_after["standards_waived_count"] == 0
    assert profile_after["version"] == profile_before["version"] + 2

    accountability = dimension_by_name(
        read_dimension_scores(cycle_before["id"], scenario["analyst_headers"]),
        "ACCOUNTABILITY",
    )
    assert accountability["raw_points"] == 21
    assert_score(accountability["normalized_score"], 87.50, "ACCOUNTABILITY normalized_score")

    cycle_after = read_cycle(cycle_before["id"])
    assert cycle_after["failed_standard_count"] == 1
    assert_score(cycle_after["weighted_sum_provisional"], 84.63, "weighted_sum_provisional")
    assert_score(cycle_after["standards_penalty_points"], 1.50, "standards_penalty_points")
    assert_score(
        cycle_after["provisional_composite_score"], 83.13, "provisional_composite_score"
    )
    assert cycle_after["provisional_grade"] == "MEETS_STANDARDS"
    assert cycle_after["version"] == cycle_before["version"] + 2


def _substantiate_twelve(scenario):
    complaint = file_complaint(
        scenario["organization"]["id"],
        headers=make_public_headers("donor-1"),
        complainant_kind="DONOR",
        category="MISUSE_OF_FUNDS",
        narrative="restricted gift spent on unrelated overhead",
        corroborating_document_count=2,
    )
    triage_complaint(complaint["id"], "INVESTIGATE", triage_note="documents attached")
    return resolve_complaint(
        complaint["id"],
        "SUBSTANTIATED",
        penalty_points=12,
        finding_note="bank records confirm diversion",
    )


def test_a_substantiated_finding_charges_twelve_points_to_the_accountability_ledger(
    api, analyst_headers
):
    """The penalty ledger runs from zero to twelve and the accountability row is left
    stale at a much lower figure.

    PRD §3.8: "Hop three, caused by that stale row, has the cycle recompute `accountability_penalty_points`, `weighted_sum_provisional`, `standards_penalty_points`, `provisional_composite_score` and `provisional_grade`; and if the cycle was anywhere on the review track — `ORG_REVIEW`, `CORRECTION_REQUESTED` or `APPEAL_OPEN` — it is dragged back to `SCORED`, clearing `review_opened_at`, `correction_deadline_at` and `appeal_deadline_at`."

    Design: Difficulty/compensating_invariant/accountability_penalty_ledger_conserved_across_substantiate_and_reverse
    """
    scenario = setup_scored_cycle()
    assert scenario["cycle"]["accountability_penalty_points"] == 0
    complaint = _substantiate_twelve(scenario)
    assert complaint["penalty_points_applied"] == 12

    cycle = read_cycle(scenario["cycle"]["id"])
    assert cycle["status"] == "SCORED"
    assert cycle["accountability_penalty_points"] == 12
    assert_score(cycle["weighted_sum_provisional"], 72.13, "weighted_sum_provisional")
    assert_score(
        cycle["provisional_composite_score"], 71.13, "provisional_composite_score"
    )
    assert cycle["provisional_grade"] == "NEEDS_IMPROVEMENT"

    accountability = dimension_by_name(
        read_dimension_scores(cycle["id"], analyst_headers), "ACCOUNTABILITY"
    )
    assert accountability["penalty_points"] == 12
    assert accountability["raw_points"] == 9
    assert_score(accountability["normalized_score"], 37.50, "ACCOUNTABILITY normalized_score")
    assert accountability["status"] == "STALE"


def test_reversing_the_finding_returns_the_ledger_to_zero_with_no_residue(
    api, analyst_headers, admin_headers
):
    """The reversal is the exact inverse of the cascade: the row returns to COMPUTED at
    its original points and the complaint keeps the credibility it earned.

    PRD §3.8: "The complaint returns `SUBSTANTIATED` → `INVESTIGATING`, stores the `reversal_reason`, sets `penalty_points_applied` back to 0 and clears `resolved_at` and `penalized_rating_cycle_id` to null."

    PRD §3.8: "The penalised cycle's `ACCOUNTABILITY` row has the reversed points removed from its `penalty_points`, recomputes `raw_points` from source data and moves `STALE` → `COMPUTED`."

    PRD §3.8: "The accountability point ledger returns to exactly where it stood before the finding, with zero drift."

    Design: Difficulty/compensating_invariant/accountability_penalty_ledger_conserved_across_substantiate_and_reverse
    """
    scenario = setup_scored_cycle()
    complaint = _substantiate_twelve(scenario)
    reversed_complaint = reverse_complaint_finding(
        complaint["id"],
        reversal_reason="the bank records were misread; the transfer was an approved program advance",
    )

    assert reversed_complaint["status"] == "INVESTIGATING"
    assert reversed_complaint["penalty_points_applied"] == 0
    assert reversed_complaint["penalized_rating_cycle_id"] is None
    assert reversed_complaint["resolved_at"] is None
    assert_score(reversed_complaint["credibility_score"], 86.00, "credibility_score")
    assert reversed_complaint["credibility_variant"] == "INVESTIGATED"

    accountability = dimension_by_name(
        read_dimension_scores(scenario["cycle"]["id"], analyst_headers), "ACCOUNTABILITY"
    )
    assert accountability["penalty_points"] == 0
    assert accountability["raw_points"] == 21
    assert_score(accountability["normalized_score"], 87.50, "ACCOUNTABILITY normalized_score")
    assert accountability["status"] == "COMPUTED"

    cycle = read_cycle(scenario["cycle"]["id"])
    assert cycle["status"] == "SCORED"
    assert cycle["accountability_penalty_points"] == 0
    assert_score(cycle["weighted_sum_provisional"], 84.63, "weighted_sum_provisional")
    assert_score(cycle["standards_penalty_points"], 1.50, "standards_penalty_points")
    assert_score(
        cycle["provisional_composite_score"], 83.13, "provisional_composite_score"
    )
    assert cycle["provisional_grade"] == "MEETS_STANDARDS"
    assert read_organization(scenario["organization"]["id"])["substantiated_complaint_count"] == 0
