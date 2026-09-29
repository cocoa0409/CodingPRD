"""Two non-linear machines: the correction revision loop and the triage fork."""
from test_helpers import (
    GOVERNANCE_CORRECTION,
    assert_instant,
    assert_score,
    decide_correction,
    dimension_by_name,
    evaluate_governance_profile,
    file_complaint,
    make_public_headers,
    open_org_review,
    read_cycle,
    read_dimension_scores,
    read_governance_profile,
    read_organization,
    score_cycle,
    setup_bare_organization,
    setup_claimed_correction,
    triage_complaint,
    triage_complaint_payload,
    validate_error,
    validate_paginated,
)


def test_accepted_correction_rewinds_the_cycle_to_data_collection_and_stales_every_row(
    api, analyst_headers
):
    """Accepting the charity's governance dispute throws away the provisional figures
    it was shown and marks all four dimension rows out of date.

    PRD §3.7: "Hop two, caused by hop one, moves the cycle `CORRECTION_REQUESTED` → `DATA_COLLECTION`, recomputes `correction_round` — now one higher — and clears `review_opened_at`, `correction_deadline_at`, `appeal_deadline_at`, `weighted_sum_provisional`, `provisional_composite_score` and `provisional_grade` back to null."

    PRD §3.7: "In both cases every dimension row of the cycle that is `COMPUTED` or `OVERRIDDEN` moves to `STALE`."

    Design: Difficulty/non_linear_state_machine/rating_cycle_correction_revision_loop
    """
    scenario = setup_claimed_correction(correction_overrides=GOVERNANCE_CORRECTION)
    assert scenario["correction"]["round_number"] == 1
    assert scenario["cycle"]["status"] == "CORRECTION_REQUESTED"

    correction = decide_correction(
        scenario["correction"]["id"], "ACCEPT", headers=scenario["analyst_headers"]
    )
    assert correction["status"] == "ACCEPTED"

    cycle = read_cycle(scenario["cycle"]["id"])
    assert cycle["status"] == "DATA_COLLECTION"
    assert cycle["correction_round"] == 1
    assert cycle["weighted_sum_provisional"] is None
    assert cycle["provisional_composite_score"] is None
    assert cycle["provisional_grade"] is None
    assert cycle["review_opened_at"] is None
    assert cycle["correction_deadline_at"] is None

    rows = read_dimension_scores(cycle["id"], scenario["analyst_headers"])
    assert len(rows) == 4
    assert all(row["status"] == "STALE" for row in rows)


def test_accepted_governance_correction_returns_the_profile_to_pending_and_deletes_its_rows(
    api, analyst_headers
):
    """The disputed disclosure field is overwritten and the eight standard rows are
    removed, so the next evaluation re-mints them from the corrected disclosure.

    PRD §3.4: "When a correction whose `target_kind` is `GOVERNANCE_DISCLOSURE` is accepted — whether by the analyst's own decision or by a panel granting an appeal — the profile moves `EVALUATED` → `PENDING`: the field named by the correction's `target_field_name` is overwritten with its `proposed_value`, all eight `StandardEvaluation` rows are deleted so that the next evaluation re-mints them from the corrected disclosure, the four `standards_*_count` fields are zeroed, and the profile's `version` counter advances by one."

    Design: Difficulty/non_linear_state_machine/rating_cycle_correction_revision_loop
    """
    scenario = setup_claimed_correction(correction_overrides=GOVERNANCE_CORRECTION)
    decide_correction(
        scenario["correction"]["id"], "ACCEPT", headers=scenario["analyst_headers"]
    )

    profile = read_governance_profile(scenario["governance_profile"]["id"])
    assert profile["evaluation_status"] == "PENDING"
    assert profile["ceo_compensation_reviewed"] is True
    assert profile["standards_met_count"] == 0
    assert profile["standards_not_met_count"] == 0
    assert profile["standards_waived_count"] == 0
    assert profile["standards_not_applicable_count"] == 0

    rows, meta = validate_paginated(
        api.list_standard_evaluations(profile["id"], scenario["analyst_headers"])
    )
    assert meta["total_count"] == 0
    assert rows == []
    assert read_cycle(scenario["cycle"]["id"])["failed_standard_count"] == 0


def test_second_lap_of_the_correction_loop_rescores_the_cycle_and_reopens_review(
    api, analyst_headers
):
    """The corrected disclosure meets all eight standards, so the second lap scores
    87.75 with no penalty at all and organization review reopens 21 days out.

    PRD §3.5: "Because an accepted correction and a granted appeal both return the cycle to `DATA_COLLECTION`, a re-score is a fresh `DATA_COLLECTION` → `SCORED` traversal rather than a self-loop; on that re-score the four dimension rows already exist and travel `STALE` → `COMPUTED`, and **any override value previously written into a dimension row is discarded** in favour of a value recomputed from source data."

    PRD §3.7: "The transition stamps `review_opened_at` with the logical clock, derives `correction_deadline_at` as that instant plus 21 days, and advances the cycle's `version` counter by one."

    Design: Difficulty/non_linear_state_machine/rating_cycle_correction_revision_loop
    """
    scenario = setup_claimed_correction(correction_overrides=GOVERNANCE_CORRECTION)
    decide_correction(
        scenario["correction"]["id"], "ACCEPT", headers=scenario["analyst_headers"]
    )

    profile = evaluate_governance_profile(
        scenario["governance_profile"]["id"], scenario["analyst_headers"]
    )
    assert profile["standards_met_count"] == 8
    assert profile["standards_not_met_count"] == 0

    cycle = score_cycle(scenario["cycle"]["id"], scenario["analyst_headers"])
    assert cycle["failed_standard_count"] == 0
    assert_score(cycle["weighted_sum_provisional"], 87.75, "weighted_sum_provisional")
    assert_score(cycle["standards_penalty_points"], 0.00, "standards_penalty_points")
    assert_score(
        cycle["provisional_composite_score"], 87.75, "provisional_composite_score"
    )
    assert cycle["provisional_grade"] == "ACCREDITED"

    rows = read_dimension_scores(cycle["id"], scenario["analyst_headers"])
    assert all(row["status"] == "COMPUTED" for row in rows)
    accountability = dimension_by_name(rows, "ACCOUNTABILITY")
    assert accountability["raw_points"] == 24
    assert_score(
        accountability["normalized_score"], 100.00, "ACCOUNTABILITY normalized_score"
    )

    reopened = open_org_review(cycle["id"], scenario["analyst_headers"])
    assert reopened["status"] == "ORG_REVIEW"
    assert reopened["correction_round"] == 1
    assert_instant(
        reopened["correction_deadline_at"],
        "2026-09-22T00:00:00Z",
        "correction_deadline_at",
    )


def test_triage_to_investigate_arms_the_investigation_clock_and_scores_the_complaint(
    api, analyst_headers
):
    """Sending a donor's complaint to investigation is the only branch that leaves the
    complaint live, and it is the branch that starts the 30-day clock.

    PRD §3.8: "`INVESTIGATE` moves the complaint `INTAKE` → `INVESTIGATING`, computes `credibility_score` under the intake variant, sets `credibility_variant` to `INTAKE`, derives `severity_tier`, and arms `investigation_due_at` at the logical clock plus 30 days."

    Design: Difficulty/non_linear_state_machine/complaint_triage_three_way_fork_divergent_side_effects
    """
    scenario = setup_bare_organization()
    complaint = file_complaint(
        scenario["organization"]["id"],
        headers=make_public_headers("donor-1"),
        complainant_kind="DONOR",
        category="MISUSE_OF_FUNDS",
        narrative="restricted gift spent on overhead",
        corroborating_document_count=2,
    )
    triaged = triage_complaint(
        complaint["id"], "INVESTIGATE", triage_note="credible on its face"
    )

    assert triaged["status"] == "INVESTIGATING"
    assert_score(triaged["credibility_score"], 76.00, "credibility_score")
    assert triaged["credibility_variant"] == "INTAKE"
    assert triaged["severity_tier"] == "MEDIUM"
    assert_instant(
        triaged["investigation_due_at"], "2026-08-31T00:00:00Z", "investigation_due_at"
    )
    assert triaged["resolved_at"] is None
    assert triaged["penalty_points_applied"] == 0
    assert triaged["penalized_rating_cycle_id"] is None


def test_triage_to_close_no_action_terminates_the_complaint_entirely_unscored(
    api, analyst_headers
):
    """A complaint that alleges no standards breach is closed with no credibility
    figures of any kind — the one branch that scores nothing.

    PRD §3.8: "`CLOSE_NO_ACTION` moves it `INTAKE` → `CLOSED_NO_ACTION`, a terminal status with no scoring side effect at all: `resolved_at` is stamped from the logical clock, no `credibility_score` is computed and `investigation_due_at` stays null."

    Design: Difficulty/non_linear_state_machine/complaint_triage_three_way_fork_divergent_side_effects
    """
    scenario = setup_bare_organization()
    complaint = file_complaint(
        scenario["organization"]["id"],
        headers=make_public_headers("beneficiary-1"),
        complainant_kind="BENEFICIARY",
        category="GOVERNANCE",
        narrative="board never meets in public",
        corroborating_document_count=0,
    )
    triaged = triage_complaint(
        complaint["id"],
        "CLOSE_NO_ACTION",
        triage_note="no allegation of a standards breach",
    )

    assert triaged["status"] == "CLOSED_NO_ACTION"
    assert triaged["credibility_score"] is None
    assert triaged["credibility_variant"] is None
    assert triaged["severity_tier"] is None
    assert triaged["investigation_due_at"] is None
    assert_instant(triaged["resolved_at"], "2026-08-01T00:00:00Z", "resolved_at")
    assert triaged["penalty_points_applied"] == 0
    assert read_organization(scenario["organization"]["id"])["substantiated_complaint_count"] == 0


def test_triage_to_refer_out_scores_the_complaint_and_still_penalises_no_rating(
    api, analyst_headers
):
    """Referring an employment matter to an outside authority carries a severity with
    it, yet the referral is terminal and costs the charity nothing.

    PRD §3.8: "`REFER_OUT` moves it `INTAKE` → `REFERRED_OUT`, also terminal, and sits between the other two — it stores `referred_to` and `triage_note`, stamps `resolved_at`, and does compute the intake-variant `credibility_score` and `severity_tier` so the referral carries a severity for the external authority, but it never penalises a rating."

    Design: Difficulty/non_linear_state_machine/complaint_triage_three_way_fork_divergent_side_effects
    """
    scenario = setup_bare_organization()
    complaint = file_complaint(
        scenario["organization"]["id"],
        headers=make_public_headers("employee-1"),
        complainant_kind="EMPLOYEE",
        category="TRANSPARENCY",
        narrative="audited statements withheld from staff",
        corroborating_document_count=1,
    )
    triaged = triage_complaint(
        complaint["id"],
        "REFER_OUT",
        triage_note="employment matter",
        referred_to="State Attorney General - Charities Bureau",
    )

    assert triaged["status"] == "REFERRED_OUT"
    assert_score(triaged["credibility_score"], 58.00, "credibility_score")
    assert triaged["credibility_variant"] == "INTAKE"
    assert triaged["severity_tier"] == "MEDIUM"
    assert triaged["investigation_due_at"] is None
    assert triaged["referred_to"] == "State Attorney General - Charities Bureau"
    assert_instant(triaged["resolved_at"], "2026-08-01T00:00:00Z", "resolved_at")
    assert triaged["penalty_points_applied"] == 0
    assert triaged["penalized_rating_cycle_id"] is None


def test_retriaging_a_closed_complaint_is_refused_because_the_branch_was_terminal(
    api, analyst_headers
):
    """Two of the three branches leave no way back, so a second triage of a closed
    complaint is rejected rather than re-forking it.

    PRD §3.8: "A `RatingAnalyst` triages a complaint that is in `INTAKE`; any other status is `ERR_COMPLAINT_STATE_INVALID`."

    Design: Difficulty/non_linear_state_machine/complaint_triage_three_way_fork_divergent_side_effects
    """
    scenario = setup_bare_organization()
    complaint = file_complaint(
        scenario["organization"]["id"],
        headers=make_public_headers("beneficiary-1"),
        complainant_kind="BENEFICIARY",
        category="GOVERNANCE",
        narrative="board never meets in public",
    )
    triage_complaint(complaint["id"], "CLOSE_NO_ACTION")

    response = api.triage_complaint(
        complaint["id"], triage_complaint_payload("INVESTIGATE"), analyst_headers
    )
    validate_error(response, "ERR_COMPLAINT_STATE_INVALID", 409)
