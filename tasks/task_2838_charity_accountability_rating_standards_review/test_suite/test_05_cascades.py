"""Two four-hop cascades: one driven from a complaint, one from an appeal."""
from test_helpers import (
    GOVERNANCE_CORRECTION,
    PANELIST_USER_IDS,
    assert_instant,
    assert_number,
    assert_score,
    decide_appeal,
    dimension_by_name,
    file_complaint,
    make_public_headers,
    read_correction,
    read_cycle,
    read_dimension_scores,
    read_organization,
    read_organization_filings,
    resolve_complaint,
    score_cycle,
    setup_claimed_correction,
    setup_panel_assigned_appeal,
    triage_complaint,
)


def _substantiate_twelve_points(scenario):
    """A well-documented donor complaint substantiated at twelve penalty points."""
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


def test_substantiating_a_complaint_names_a_victim_cycle_and_penalises_its_accountability_row(
    api, analyst_headers
):
    """The finding picks the charity's only open cycle by itself and drives twelve
    penalty points into that cycle's accountability row, staling it.

    PRD §3.8: "Hop one writes the finding: the recomputed credibility figures, `penalty_points_applied`, `finding_note` and `resolved_at`, plus the choice of victim — `penalized_rating_cycle_id` is set by the penalty-target selector, which considers the rating cycles of the complained-about organization whose `status` is neither `PUBLISHED` nor `WITHDRAWN`, ranks them by `fiscal_year` descending so the most recent open cycle absorbs the penalty, breaks ties by `created_at` ascending and never consults `id`, and takes the first."

    PRD §3.8: "Hop two, caused by hop one naming a cycle, adds `penalty_points` to the `penalty_points` field of that cycle's `ACCOUNTABILITY` dimension row, recomputes its `raw_points` as the base points less the accumulated penalty floored at 0 so the row can never go negative, and moves the row `COMPUTED` or `OVERRIDDEN` → `STALE`."

    Design: Difficulty/transitive_cascade/substantiated_complaint_four_hop_accountability_cascade
    """
    scenario = setup_claimed_correction(correction_overrides=GOVERNANCE_CORRECTION)
    complaint = _substantiate_twelve_points(scenario)

    assert complaint["status"] == "SUBSTANTIATED"
    assert_score(complaint["credibility_score"], 86.00, "credibility_score")
    assert complaint["credibility_variant"] == "INVESTIGATED"
    assert complaint["severity_tier"] == "HIGH"
    assert complaint["penalty_points_applied"] == 12
    assert complaint["penalized_rating_cycle_id"] == scenario["cycle"]["id"]

    rows = read_dimension_scores(scenario["cycle"]["id"], scenario["analyst_headers"])
    accountability = dimension_by_name(rows, "ACCOUNTABILITY")
    assert accountability["penalty_points"] == 12
    assert accountability["raw_points"] == 9
    assert_score(accountability["normalized_score"], 37.50, "ACCOUNTABILITY normalized_score")
    assert accountability["status"] == "STALE"

    for name in ("FINANCIAL_HEALTH", "TRANSPARENCY", "IMPACT"):
        assert dimension_by_name(rows, name)["status"] == "COMPUTED", (
            f"{name} should not have been staled by an accountability penalty"
        )
    assert read_organization(scenario["organization"]["id"])["substantiated_complaint_count"] == 1


def test_the_penalised_row_drags_the_cycle_off_the_review_track_back_to_scored(
    api, analyst_headers
):
    """A cycle sitting in the correction window is pulled back to SCORED with its
    review timers cleared and its provisional figures rewritten downward.

    PRD §3.8: "Hop three, caused by that stale row, has the cycle recompute `accountability_penalty_points`, `weighted_sum_provisional`, `standards_penalty_points`, `provisional_composite_score` and `provisional_grade`; and if the cycle was anywhere on the review track — `ORG_REVIEW`, `CORRECTION_REQUESTED` or `APPEAL_OPEN` — it is dragged back to `SCORED`, clearing `review_opened_at`, `correction_deadline_at` and `appeal_deadline_at`."

    Design: Difficulty/transitive_cascade/substantiated_complaint_four_hop_accountability_cascade
    """
    scenario = setup_claimed_correction(correction_overrides=GOVERNANCE_CORRECTION)
    assert scenario["cycle"]["status"] == "CORRECTION_REQUESTED"
    _substantiate_twelve_points(scenario)

    cycle = read_cycle(scenario["cycle"]["id"])
    assert cycle["status"] == "SCORED"
    assert cycle["accountability_penalty_points"] == 12
    assert cycle["review_opened_at"] is None
    assert cycle["correction_deadline_at"] is None
    assert cycle["appeal_deadline_at"] is None
    assert_score(cycle["weighted_sum_provisional"], 72.13, "weighted_sum_provisional")
    assert_score(
        cycle["provisional_composite_score"], 71.13, "provisional_composite_score"
    )
    assert cycle["provisional_grade"] == "NEEDS_IMPROVEMENT"


def test_leaving_the_review_track_rejects_the_in_flight_correction_with_no_decider(
    api, analyst_headers
):
    """The claimed correction is swept aside by the re-score rather than decided, so it
    carries no decider and does not spend a correction round.

    PRD §3.8: "Hop four, caused by that departure from the review track, tidies up what the review track had in flight: appeals of the cycle in `FILED` or `PANEL_ASSIGNED` move to `DISMISSED` and corrections in `SUBMITTED` or `UNDER_ANALYST_REVIEW` move to `REJECTED`, both carrying `decision_note` `cycle re-scored after substantiated complaint` and a null `decided_by_user_id`."

    Design: Difficulty/transitive_cascade/substantiated_complaint_four_hop_accountability_cascade
    """
    scenario = setup_claimed_correction(correction_overrides=GOVERNANCE_CORRECTION)
    assert scenario["correction"]["status"] == "UNDER_ANALYST_REVIEW"
    _substantiate_twelve_points(scenario)

    correction = read_correction(
        scenario["correction"]["id"], scenario["analyst_headers"]
    )
    assert correction["status"] == "REJECTED"
    assert correction["decided_by_user_id"] is None
    assert_instant(correction["decided_at"], "2026-09-01T00:00:00Z", "decided_at")
    assert read_cycle(scenario["cycle"]["id"])["correction_round"] == 0


def test_granting_an_appeal_revives_the_rejected_correction_and_rewinds_the_cycle(
    api, analyst_headers
):
    """A panel grant is the only way out of a rejected correction, and it hands the
    correction the panelist's identity before rewinding the rating.

    PRD §3.7: "The contested correction travels `REJECTED` → `ACCEPTED` — the only path out of that terminal state anywhere in the product — with its `decided_by_user_id` overwritten by the deciding panel member and its `decided_at` overwritten by the logical clock."

    PRD §3.7: "The cycle moves `APPEAL_OPEN` → `DATA_COLLECTION`, every dimension row goes to `STALE`, `review_opened_at`, `correction_deadline_at`, `appeal_deadline_at`, `weighted_sum_provisional`, `provisional_composite_score` and `provisional_grade` are cleared to null, `correction_round` is recomputed one higher, and the cycle's `version` counter advances by one."

    Design: Difficulty/transitive_cascade/granted_appeal_four_hop_filing_substitution_cascade
    """
    scenario = setup_panel_assigned_appeal()
    appeal = decide_appeal(
        scenario["appeal"]["id"], "GRANT", decision_note="restatement accepted"
    )

    assert appeal["status"] == "GRANTED"
    assert appeal["decided_by_user_id"] == PANELIST_USER_IDS[0]
    assert_instant(appeal["decided_at"], "2026-09-01T00:00:00Z", "appeal decided_at")

    correction = read_correction(
        scenario["correction"]["id"], scenario["analyst_headers"]
    )
    assert correction["status"] == "ACCEPTED"
    assert correction["decided_by_user_id"] == PANELIST_USER_IDS[0]

    cycle = read_cycle(scenario["cycle"]["id"])
    assert cycle["status"] == "DATA_COLLECTION"
    assert cycle["correction_round"] == 1
    assert cycle["review_opened_at"] is None
    assert cycle["correction_deadline_at"] is None
    assert cycle["appeal_deadline_at"] is None
    assert cycle["weighted_sum_provisional"] is None
    assert cycle["provisional_grade"] is None

    rows = read_dimension_scores(cycle["id"], scenario["analyst_headers"])
    assert len(rows) == 4
    assert all(row["status"] == "STALE" for row in rows)


def test_the_granted_appeal_supersedes_the_disputed_filing_with_a_correction_applied_row(
    api, analyst_headers
):
    """The disputed audited figure is not edited in place: the old filing is retired and
    a replacement filing carries the corrected reserve figure.

    PRD §3.7: "For a `FILING_FINANCIAL` target, the `VALIDATED` filing identified by the cycle's organization together with the request's `target_fiscal_year` and `target_source_kind` moves `VALIDATED` → `SUPERSEDED`, and a replacement filing is created carrying `origin` `CORRECTION_APPLIED`, `status` `VALIDATED`, and the field named by `target_field_name` overwritten with `proposed_value`."

    Design: Difficulty/transitive_cascade/granted_appeal_four_hop_filing_substitution_cascade
    """
    scenario = setup_panel_assigned_appeal()
    original_filing_id = scenario["filing_by_year"][2025]["id"]
    decide_appeal(scenario["appeal"]["id"], "GRANT")

    filings = read_organization_filings(
        scenario["organization"]["id"],
        headers=scenario["analyst_headers"],
        fiscal_year=2025,
    )
    superseded = [f for f in filings if f["id"] == original_filing_id]
    assert len(superseded) == 1
    assert superseded[0]["status"] == "SUPERSEDED"

    surviving = [f for f in filings if f["status"] == "VALIDATED"]
    assert len(surviving) == 1
    assert surviving[0]["origin"] == "CORRECTION_APPLIED"
    assert surviving[0]["net_assets_cents"] == 2000000
    assert surviving[0]["id"] != original_filing_id


def test_the_rescore_after_the_grant_reads_the_replacement_filing_and_not_the_superseded_one(
    api, analyst_headers
):
    """The corrected reserve figure costs the charity all eight reserve points, which is
    only visible because the superseded original is never read again.

    PRD §3.3: "The candidate set is every filing for that organization and that fiscal year whose `status` is `VALIDATED`; filings in `RECEIVED`, `REJECTED` or `SUPERSEDED` are never read, no matter how recent they are or how authoritative their `source_kind` looks."

    PRD §3.5: "The reserve ladder rewards larger values again: 8 points when `months_of_reserve` is at least 12, otherwise 5 at 6 or more, otherwise 2 at 3 or more, otherwise 0."

    Design: Difficulty/transitive_cascade/granted_appeal_four_hop_filing_substitution_cascade
    """
    scenario = setup_panel_assigned_appeal()
    decide_appeal(scenario["appeal"]["id"], "GRANT")

    cycle = score_cycle(scenario["cycle"]["id"], scenario["analyst_headers"])
    assert_number(cycle["months_of_reserve"], 2.40, 2, "months_of_reserve")

    financial = dimension_by_name(
        read_dimension_scores(cycle["id"], scenario["analyst_headers"]),
        "FINANCIAL_HEALTH",
    )
    assert financial["raw_points"] == 24
    assert_score(financial["normalized_score"], 60.00, "FINANCIAL_HEALTH normalized_score")

    assert_score(cycle["weighted_sum_provisional"], 79.63, "weighted_sum_provisional")
    assert_score(cycle["standards_penalty_points"], 1.50, "standards_penalty_points")
    assert_score(
        cycle["provisional_composite_score"], 78.13, "provisional_composite_score"
    )
    assert cycle["provisional_grade"] == "MEETS_STANDARDS"
