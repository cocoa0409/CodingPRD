"""Terminal-state lockdown, the methodology revision loop, and cascade scoping."""
from test_helpers import (
    FILING_FY2025,
    GOVERNANCE_CORRECTION,
    PANELIST_USER_IDS,
    adopt_methodology_payload,
    assert_instant,
    assert_ratio,
    assert_score,
    close_comment,
    create_draft_methodology,
    create_organization,
    decide_appeal,
    dimension_by_name,
    dimension_overrides_payload,
    dispose_public_comment,
    evaluate_governance_profile,
    file_public_comment,
    open_comment,
    publish_cycle,
    read_appeal,
    read_correction,
    read_cycle,
    read_dimension_scores,
    read_filing,
    read_governance_profile,
    read_publication_records,
    read_standard_evaluations,
    return_to_draft_payload,
    score_cycle,
    set_clock,
    setup_accepted_correction,
    setup_filed_appeal,
    setup_panel_assigned_appeal,
    setup_published_cycle,
    submit_filing,
    submit_validated_filing,
    validate_error,
    validate_filing,
    validate_paginated,
    validate_success,
    withdraw_payload,
)


def test_a_published_rating_refuses_withdrawal_rescoring_review_and_overrides(
    api, admin_headers, analyst_headers, public_headers
):
    """Nothing may edit the numbers a donor has already read, and the override refusal
    beats the optimistic-concurrency check even though the version supplied is current.

    PRD §3.9: "A cycle may be withdrawn from any of the six non-terminal statuses — `DATA_COLLECTION`, `SCORED`, `ORG_REVIEW`, `CORRECTION_REQUESTED`, `APPEAL_OPEN` and `APPEAL_RESOLVED` — and attempting it on a cycle already `PUBLISHED` or `WITHDRAWN` is `ERR_CYCLE_STATE_INVALID`."

    PRD §3.5: "Scoring is the analyst's principal act, and it may be run only from `DATA_COLLECTION`; any other status is `ERR_CYCLE_STATE_INVALID`."

    PRD §3.7: "Three conditions gate that move: the cycle must be in `SCORED`, or the request is `ERR_CYCLE_STATE_INVALID`; the acting `X-User-ID` must be the cycle's `assigned_analyst_user_id`, or the request is `ERR_NOT_ASSIGNED_ANALYST`; and no dimension row of the cycle may be `STALE`, or the request is again `ERR_CYCLE_STATE_INVALID` — an organization must never be shown figures the system already knows are out of date."

    PRD §3.6: "Attempting it on a cycle in any status other than `SCORED` is `ERR_CYCLE_STATE_INVALID`, and attempting it as an analyst other than the cycle's `assigned_analyst_user_id` is `ERR_NOT_ASSIGNED_ANALYST`."

    PRD §2.8: "Because the state precondition (8) precedes the stale-version check (9), an override aimed at a `WITHDRAWN` cycle reports `ERR_CYCLE_STATE_INVALID` even when the supplied `expected_rating_cycle_version` is also wrong."

    Design: Corner/state_machines/published_cycle_rejects_every_further_transition
    """
    scenario = setup_published_cycle()
    cycle = scenario["cycle"]
    version_before = cycle["version"]
    financial = dimension_by_name(
        read_dimension_scores(cycle["id"], analyst_headers), "FINANCIAL_HEALTH"
    )

    validate_error(
        api.withdraw_rating_cycle(
            cycle["id"],
            withdraw_payload(withdrawal_reason="Retracting a published rating"),
            admin_headers,
        ),
        "ERR_CYCLE_STATE_INVALID",
        409,
    )
    validate_error(
        api.score_rating_cycle(cycle["id"], analyst_headers),
        "ERR_CYCLE_STATE_INVALID",
        409,
    )
    validate_error(
        api.open_org_review(cycle["id"], analyst_headers),
        "ERR_CYCLE_STATE_INVALID",
        409,
    )
    validate_error(
        api.create_dimension_overrides(
            cycle["id"],
            dimension_overrides_payload(
                [{"dimension_score_id": financial["id"], "raw_points": 18}],
                version_before,
                override_reason="Editing a published rating",
            ),
            analyst_headers,
        ),
        "ERR_CYCLE_STATE_INVALID",
        409,
    )

    after = read_cycle(cycle["id"], analyst_headers)
    assert after["status"] == "PUBLISHED"
    assert_score(after["final_composite_score"], 83.13, "final_composite_score")
    assert after["grade"] == "MEETS_STANDARDS"
    assert_instant(after["published_at"], "2026-09-22T00:00:00Z", "published_at")
    assert after["withdrawal_reason"] is None
    assert after["version"] == version_before

    records = read_publication_records(public_headers, rating_cycle_id=cycle["id"])
    assert len(records) == 1
    assert records[0]["sequence_number"] == 1


def test_the_revision_loop_clears_the_dates_but_keeps_the_objection_alive(
    api, admin_headers
):
    """Looping a closed consultation back to draft re-dates the next window yet
    preserves the comment counts, so an unresolved objection still blocks adoption until
    it is genuinely disposed.

    PRD §3.1: "The transition stores the note and any supplied values, clears `comment_open_at`, `comment_deadline_at` and `comment_closed_at` back to null, and advances the version counter — but it deliberately **preserves** `comment_count` and `unresolved_comment_count`, so comments filed against the earlier draft still gate adoption."

    PRD §2.8: "**Comments disposed.** A methodology version is adopted only when its `unresolved_comment_count` is zero — every public comment has been disposed to `INCORPORATED` or `DECLINED` — else `ERR_UNRESOLVED_COMMENTS` (409), on `POST /methodology-versions/{methodology_version_id}/adopt`."

    PRD §3.1: "Disposal is a separate act by a `MethodologyAdmin`, who supplies a `disposition` of `INCORPORATED` or `DECLINED` and an optional `disposition_note`; the comment moves from `SUBMITTED` to the chosen disposition, its parent's `unresolved_comment_count` falls by one, and both the comment's and the parent version's `version` counters advance by one."

    Design: Corner/state_machines/methodology_revision_loop_preserves_comment_counts_and_regates_adoption
    """
    methodology = create_draft_methodology()
    open_comment(methodology["id"])
    comment = file_public_comment(
        methodology["id"], commenter_kind="DONOR", body="The impact weight is too low"
    )
    close_comment(methodology["id"])

    looped = validate_success(
        api.return_to_draft(
            methodology["id"],
            return_to_draft_payload(
                revision_note="Reweighting impact after the first consultation",
                weight_financial_health=0.325,
                weight_accountability=0.25,
                weight_transparency=0.2,
                weight_impact=0.225,
            ),
            admin_headers,
        )
    )

    assert looped["status"] == "DRAFT"
    assert looped["comment_open_at"] is None
    assert looped["comment_closed_at"] is None
    assert looped["comment_deadline_at"] is None
    assert looped["comment_count"] == 1
    assert looped["unresolved_comment_count"] == 1
    assert_ratio(looped["weight_financial_health"], 0.3250, "weight_financial_health")
    assert_ratio(looped["weight_accountability"], 0.2500, "weight_accountability")
    assert_ratio(looped["weight_transparency"], 0.2000, "weight_transparency")
    assert_ratio(looped["weight_impact"], 0.2250, "weight_impact")
    assert looped["revision_note"] == "Reweighting impact after the first consultation"

    reopened = open_comment(methodology["id"])
    assert_instant(
        reopened["comment_deadline_at"],
        "2026-08-31T00:00:00Z",
        "re-armed comment_deadline_at",
    )
    close_comment(methodology["id"])

    validate_error(
        api.adopt_methodology_version(
            methodology["id"],
            adopt_methodology_payload("2026-08-31T00:00:00Z"),
            admin_headers,
        ),
        "ERR_UNRESOLVED_COMMENTS",
        409,
    )

    dispose_public_comment(
        comment["id"],
        "INCORPORATED",
        disposition_note="Impact weight raised to 0.2250",
    )
    disposed_parent = validate_success(
        api.get_methodology_version(methodology["id"], admin_headers)
    )
    assert disposed_parent["comment_count"] == 1
    assert disposed_parent["unresolved_comment_count"] == 0

    adopted = validate_success(
        api.adopt_methodology_version(
            methodology["id"],
            adopt_methodology_payload("2026-08-31T00:00:00Z"),
            admin_headers,
        )
    )
    assert adopted["status"] == "ADOPTED"
    assert_instant(adopted["effective_from"], "2026-08-31T00:00:00Z", "effective_from")
    assert_instant(adopted["adopted_at"], "2026-08-01T00:00:00Z", "adopted_at")
    assert adopted["version"] == 9


def test_a_denied_appeal_resolves_the_cycle_and_publishes_the_identical_composite(
    api, analyst_headers, public_headers
):
    """The denial fork changes no score at all, and the cycle it resolves publishes from
    APPEAL_RESOLVED exactly as an unappealed cycle publishes from ORG_REVIEW.

    PRD §3.7: "Denying moves the appeal `PANEL_ASSIGNED` → `DENIED`, advances the cycle `APPEAL_OPEN` → `APPEAL_RESOLVED`, and changes no score whatsoever; the contested correction stays `REJECTED` and the rating becomes publishable."

    PRD §3.9: "A cycle can be published from `ORG_REVIEW` or from `APPEAL_RESOLVED`, and the two paths carry identical preconditions and identical side effects — a cycle that survived an appeal publishes exactly as a cycle that was never appealed does."

    Design: Corner/state_machines/appeal_denial_resolves_the_cycle_without_touching_the_scores
    """
    scenario = setup_panel_assigned_appeal()
    cycle_before = read_cycle(scenario["cycle"]["id"], analyst_headers)

    appeal = decide_appeal(
        scenario["appeal"]["id"],
        "DENY",
        panelist_user_id=PANELIST_USER_IDS[1],
        decision_note="The audited schedule supports the figure on file",
    )
    assert appeal["status"] == "DENIED"
    assert appeal["decided_by_user_id"] == PANELIST_USER_IDS[1]
    assert_instant(appeal["decided_at"], "2026-09-01T00:00:00Z", "decided_at")

    resolved = read_cycle(scenario["cycle"]["id"], analyst_headers)
    assert resolved["status"] == "APPEAL_RESOLVED"
    assert resolved["correction_round"] == 0
    rows = read_dimension_scores(resolved["id"], analyst_headers)
    assert len(rows) == 4
    assert all(row["status"] == "COMPUTED" for row in rows)
    assert_score(resolved["final_composite_score"], 83.13, "final_composite_score")
    assert_score(resolved["weighted_sum_final"], 84.63, "weighted_sum_final")
    assert_score(resolved["standards_penalty_points"], 1.50, "standards_penalty_points")
    assert resolved["grade"] == "MEETS_STANDARDS"
    assert_score(
        resolved["final_composite_score"],
        float(cycle_before["final_composite_score"]),
        "composite unchanged by the denial",
    )
    assert read_correction(scenario["correction"]["id"], analyst_headers)["status"] == "REJECTED"

    set_clock(resolved["correction_deadline_at"])
    published = publish_cycle(
        resolved["id"], publishing_reviewer_note="Appeal denied, released as scored"
    )
    assert published["status"] == "PUBLISHED"

    records = read_publication_records(public_headers, rating_cycle_id=resolved["id"])
    assert len(records) == 1
    assert_score(records[0]["published_score"], 83.13, "published_score")
    assert records[0]["published_grade"] == "MEETS_STANDARDS"
    assert records[0]["sequence_number"] == 1


def test_withdrawal_dismisses_the_open_appeal_and_leaves_the_rejected_correction_alone(
    api, admin_headers, analyst_headers
):
    """The withdraw cascade is scoped by child state rather than by child type, so the
    FILED appeal is closed while the already-REJECTED correction is not restamped.

    PRD §3.9: "All six paths behave identically: the `withdrawal_reason` is stored, every dimension row of the cycle in `COMPUTED` or `OVERRIDDEN` moves to `STALE`, every correction in `SUBMITTED` or `UNDER_ANALYST_REVIEW` moves to `REJECTED` and every appeal in `FILED` or `PANEL_ASSIGNED` moves to `DISMISSED` — each carrying `decision_note` `cycle withdrawn` and a null `decided_by_user_id` — and the cycle's `version` counter advances by one."

    PRD §3.9: "`WITHDRAWN` and `PUBLISHED` are both terminal; no operation moves a cycle out of either, and no publication record is ever produced for a withdrawn cycle."

    Design: Corner/state_machines/withdraw_dismisses_open_appeal_stales_scores_and_spares_terminal_children
    """
    scenario = setup_filed_appeal()
    correction_before = read_correction(scenario["correction"]["id"], analyst_headers)

    withdrawn = validate_success(
        api.withdraw_rating_cycle(
            scenario["cycle"]["id"],
            withdraw_payload(withdrawal_reason="Organization dissolved mid-review"),
            admin_headers,
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["withdrawal_reason"] == "Organization dissolved mid-review"

    appeal = read_appeal(scenario["appeal"]["id"], analyst_headers)
    assert appeal["status"] == "DISMISSED"
    assert appeal["decided_by_user_id"] is None

    stale_rows, stale_meta = validate_paginated(
        api.list_dimension_scores(
            scenario["cycle"]["id"], analyst_headers, params={"status": "STALE"}
        )
    )
    assert stale_meta["total_count"] == 4
    assert len(stale_rows) == 4

    correction_after = read_correction(scenario["correction"]["id"], analyst_headers)
    assert correction_after["status"] == "REJECTED"
    assert correction_after["version"] == correction_before["version"]
    assert_instant(
        correction_after["decided_at"], correction_before["decided_at"], "decided_at"
    )

    validate_error(
        api.withdraw_rating_cycle(
            scenario["cycle"]["id"],
            withdraw_payload(
                withdrawal_reason="Withdrawing an already withdrawn cycle"
            ),
            admin_headers,
        ),
        "ERR_CYCLE_STATE_INVALID",
        409,
    )
    assert read_cycle(scenario["cycle"]["id"], analyst_headers)["version"] == withdrawn["version"]


def test_a_restated_audited_statement_retires_only_the_earlier_audited_statement(
    api, analyst_headers
):
    """The supersede sweep is keyed on the full organization, fiscal-year and source-kind
    triple, so the same year's public filing keeps its VALIDATED status.

    PRD §3.3: "Any *other* filing sharing the same `organization_id`, the same `fiscal_year` and the same `source_kind` whose `status` is `VALIDATED` moves `VALIDATED` → `SUPERSEDED`, takes `superseded_at` from the logical clock, and has its own `version` counter advanced by one."

    PRD §3.3: "The invariant this enforces is absolute: at most one filing per organization, fiscal year and source-kind triple holds `VALIDATED` at any instant."

    Design: Corner/state_machines/second_validated_audited_filing_supersedes_only_its_own_triple
    """
    organization = create_organization()
    audited = submit_validated_filing(
        organization["id"], fiscal_year=2025, **FILING_FY2025
    )
    public_filing = submit_validated_filing(
        organization["id"],
        fiscal_year=2025,
        source_kind="PUBLIC_FILING",
        total_expense_cents=10000000,
        program_expense_cents=7900000,
        fundraising_expense_cents=1300000,
        admin_expense_cents=800000,
        contributions_cents=9000000,
        total_revenue_cents=11000000,
        net_assets_cents=6000000,
        total_liabilities_cents=2000000,
    )

    restated = submit_filing(
        organization["id"],
        fiscal_year=2025,
        source_kind="AUDITED_STATEMENT",
        total_expense_cents=10000000,
        program_expense_cents=8500000,
        fundraising_expense_cents=1000000,
        admin_expense_cents=500000,
        contributions_cents=9000000,
        total_revenue_cents=11000000,
        net_assets_cents=6000000,
        total_liabilities_cents=2000000,
        joint_cost_allocated_cents=500000,
    )
    accepted = validate_filing(restated["id"], "ACCEPT")

    assert accepted["status"] == "VALIDATED"
    assert_instant(accepted["validated_at"], "2026-08-01T00:00:00Z", "validated_at")

    displaced = read_filing(audited["id"], analyst_headers)
    assert displaced["status"] == "SUPERSEDED"
    assert_instant(displaced["superseded_at"], "2026-08-01T00:00:00Z", "superseded_at")
    assert displaced["version"] == audited["version"] + 1

    survivor = read_filing(public_filing["id"], analyst_headers)
    assert survivor["status"] == "VALIDATED"
    assert survivor["superseded_at"] is None

    validated_rows, validated_meta = validate_paginated(
        api.list_organization_filing_records(
            organization["id"],
            analyst_headers,
            params={"fiscal_year": 2025, "status": "VALIDATED"},
        )
    )
    assert validated_meta["total_count"] == 2
    assert sorted(row["source_kind"] for row in validated_rows) == [
        "AUDITED_STATEMENT",
        "PUBLIC_FILING",
    ]

    _superseded_rows, superseded_meta = validate_paginated(
        api.list_organization_filing_records(
            organization["id"],
            analyst_headers,
            params={"fiscal_year": 2025, "status": "SUPERSEDED"},
        )
    )
    assert superseded_meta["total_count"] == 1


def test_an_accepted_governance_correction_rewinds_the_profile_and_lifts_the_rating(
    api, analyst_headers
):
    """The governance branch of hop three supersedes no filing: it rewinds the profile to
    PENDING, deletes the eight standard rows, and the re-score lands on ACCREDITED.

    PRD §3.7: "For a `GOVERNANCE_DISCLOSURE` target, the cycle's governance profile has the field named by `target_field_name` overwritten with `proposed_value`, its `evaluation_status` returns `EVALUATED` → `PENDING`, and its eight standard evaluation rows are deleted."

    PRD §3.7: "Hop four, caused by hop three deleting the standard rows, resets the cycle's `failed_standard_count` and the profile's four `standards_*_count` fields to zero, so the next score recomputes the accountability arithmetic from scratch."

    PRD §3.5: "Its base is the smaller of 24 and the sum of 3 points for each `MET` standard on the cycle's governance profile plus 2 points for each `WAIVED` standard."

    PRD §3.5: "Its `max_points` is the smaller of 24 and 3 points multiplied by the number of gradeable standards, that is eight less `standards_not_applicable_count`."

    Design: Corner/state_machines/accepted_governance_correction_returns_profile_to_pending_and_rescoring_lifts_the_rating
    """
    scenario = setup_accepted_correction(correction_overrides=GOVERNANCE_CORRECTION)
    profile_id = scenario["governance_profile"]["id"]

    assert scenario["correction"]["status"] == "ACCEPTED"
    assert scenario["correction"]["decided_by_user_id"] == scenario["analyst_user_id"]

    profile = read_governance_profile(profile_id, analyst_headers)
    assert profile["evaluation_status"] == "PENDING"
    assert profile["evaluated_at"] is None
    assert profile["ceo_compensation_reviewed"] is True
    assert profile["standards_met_count"] == 0
    assert profile["standards_not_met_count"] == 0
    assert profile["standards_waived_count"] == 0
    assert profile["standards_not_applicable_count"] == 0
    assert read_standard_evaluations(profile_id, analyst_headers) == []

    cycle = scenario["cycle"]
    assert cycle["status"] == "DATA_COLLECTION"
    assert cycle["correction_round"] == 1
    assert cycle["failed_standard_count"] == 0
    assert cycle["review_opened_at"] is None
    assert cycle["correction_deadline_at"] is None
    stale = read_dimension_scores(cycle["id"], analyst_headers)
    assert len(stale) == 4
    assert all(row["status"] == "STALE" for row in stale)
    assert read_filing(scenario["filing_by_year"][2025]["id"], analyst_headers)["status"] == "VALIDATED"

    reevaluated = evaluate_governance_profile(profile_id, analyst_headers)
    assert reevaluated["standards_met_count"] == 8
    assert reevaluated["standards_not_met_count"] == 0
    assert read_cycle(cycle["id"], analyst_headers)["failed_standard_count"] == 0

    rescored = score_cycle(cycle["id"], analyst_headers)
    accountability = dimension_by_name(
        read_dimension_scores(cycle["id"], analyst_headers), "ACCOUNTABILITY"
    )
    assert accountability["raw_points"] == 24
    assert accountability["max_points"] == 24
    assert_score(accountability["normalized_score"], 100.00, "ACCOUNTABILITY normalized_score")
    assert_score(rescored["weighted_sum_final"], 87.75, "weighted_sum_final")
    assert_score(rescored["standards_penalty_points"], 0.00, "standards_penalty_points")
    assert_score(rescored["final_composite_score"], 87.75, "final_composite_score")
    assert rescored["grade"] == "ACCREDITED"
