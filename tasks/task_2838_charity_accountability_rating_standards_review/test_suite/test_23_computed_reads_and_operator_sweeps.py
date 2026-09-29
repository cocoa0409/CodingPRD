"""The two computed reads, the publication boundary, the remaining reverse lookups
and the operator sweep that expires transition grace."""
from test_helpers import (
    FILING_FY2025,
    PUBLIC_USER_ID,
    REVIEWER_USER_ID,
    assert_instant,
    assert_ratio,
    assert_score,
    create_rating_cycle_payload,
    file_complaint,
    make_panelist_headers,
    publish_payload,
    read_cycle,
    read_organization,
    read_score_breakdown,
    run_transition_sweep,
    set_clock,
    setup_cycle_in_org_review,
    setup_published_cycle,
    setup_scored_cycle,
    setup_transition_grant,
    standard_by_code,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_the_two_computed_reads_agree_with_the_stored_rating_they_summarise(
    api, public_headers
):
    """Neither projection owns any state: the breakdown reconstructs the pinned
    intermediates behind both variants and the trend reports the organization
    roll-up newest-first, and every figure in both reconciles with the stored rows.

    PRD §3.6: "The score-breakdown read exists so that this order can be inspected rather than reverse-engineered. It answers with the cycle's `rating_cycle_id` and the `methodology_version_label` of its pinned version, the three financial figures `program_expense_ratio`, `fundraising_efficiency` and `months_of_reserve`, the `data_completeness_pct`, `failed_standard_count` and `accountability_penalty_points`, then the provisional intermediates `provisional_band`, `provisional_penalty`, `weighted_sum_provisional`, `provisional_composite_score` and `provisional_grade`, and finally the final-variant intermediates `final_included_dimensions` — the list of dimensions the final variant kept — `final_band`, `final_penalty`, `weighted_sum_final`, `final_composite_score` and `grade`."

    PRD §3.9: "Alongside it, an organization's rating trend is a computed read returning the roll-up figures — `organization_id`, `latest_published_score`, `latest_published_grade`, `published_cycle_count`, `trend_direction` — together with a paginated `points` array of that organization's published history ordered newest-first, which is the display order a donor-facing trend chart wants and the reverse of the ledger's own ascending order."

    PRD §3.6: "**Step three** derives a band from that **pre-penalty** weighted sum: band A when the weighted sum is at least 90, band B at 75 or more, band C at 60 or more, band D below that."

    Design: Corner/endpoints/the_two_computed_reads_agree_with_the_stored_rating_they_summarise
    """
    scenario = setup_published_cycle()
    cycle = scenario["cycle"]
    breakdown = read_score_breakdown(cycle["id"], scenario["org_rep_headers"])

    assert breakdown["rating_cycle_id"] == cycle["id"]
    assert breakdown["methodology_version_label"] == "M1"
    assert_ratio(breakdown["program_expense_ratio"], 0.7500, "program_expense_ratio")
    assert_ratio(breakdown["fundraising_efficiency"], 0.1867, "fundraising_efficiency")
    assert_score(breakdown["months_of_reserve"], 7.20, "months_of_reserve")
    assert_score(breakdown["data_completeness_pct"], 100.00, "data_completeness_pct")
    assert breakdown["failed_standard_count"] == 1
    assert breakdown["accountability_penalty_points"] == 0

    assert_score(breakdown["weighted_sum_final"], 84.63, "weighted_sum_final")
    assert breakdown["final_band"] == "B"
    assert_score(breakdown["final_penalty"], 1.50, "final_penalty")
    assert_score(breakdown["final_composite_score"], 83.13, "final_composite_score")
    assert breakdown["grade"] == "MEETS_STANDARDS"
    assert_score(breakdown["weighted_sum_provisional"], 84.63, "weighted_sum_provisional")
    assert_score(
        breakdown["provisional_composite_score"], 83.13, "provisional_composite_score"
    )
    assert breakdown["provisional_band"] == "B"
    assert breakdown["provisional_grade"] == "MEETS_STANDARDS"
    assert breakdown["final_included_dimensions"] == [
        "FINANCIAL_HEALTH",
        "ACCOUNTABILITY",
        "TRANSPARENCY",
        "IMPACT",
    ]

    trend = validate_success(
        api.get_rating_trend(scenario["organization"]["id"], public_headers)
    )
    assert trend["organization_id"] == scenario["organization"]["id"]
    assert_score(trend["latest_published_score"], 83.13, "latest_published_score")
    assert trend["latest_published_grade"] == "MEETS_STANDARDS"
    assert trend["published_cycle_count"] == 1
    assert trend["trend_direction"] == "NOT_APPLICABLE"
    assert len(trend["points"]) == 1
    point = trend["points"][0]
    assert point["sequence_number"] == 1
    assert_score(point["published_score"], 83.13, "published_score")
    assert point["previous_published_score"] is None
    assert point["score_delta"] is None
    assert point["change_direction"] == "FIRST_PUBLICATION"

    public_view = read_cycle(cycle["id"], public_headers)
    assert_score(
        public_view["final_composite_score"],
        breakdown["final_composite_score"],
        "cycle final_composite_score",
    )
    assert public_view["grade"] == breakdown["grade"]


def test_publication_is_permitted_only_from_the_correction_deadline_onwards(
    api, reviewer_headers, analyst_headers, public_headers
):
    """Two byte-identical publish calls one second apart around
    `correction_deadline_at`: the earlier one is refused with nothing written, the
    later one runs the whole three-hop cascade.

    PRD §2.5: "The **correction window** is armed when an analyst opens organization review on a scored cycle: `correction_deadline_at` becomes the clock at that moment plus 21 days. A correction may be filed while the clock is at or before `correction_deadline_at` — the deadline instant itself is still open for filing. Publication, conversely, is permitted while the clock is at or after `correction_deadline_at`. The two windows therefore touch: at exactly `correction_deadline_at`, both filing a correction and publishing the cycle are legal."

    PRD §2.8: "32. **Publishability.** A cycle is published only when the logical clock is at or after `correction_deadline_at`, no correction of the cycle is `SUBMITTED` or `UNDER_ANALYST_REVIEW`, and no appeal of the cycle is `FILED` or `PANEL_ASSIGNED`. Otherwise `ERR_CYCLE_NOT_PUBLISHABLE` (409), on `POST /rating-cycles/{rating_cycle_id}/publish`."

    PRD §3.9: "The logical clock must have reached `correction_deadline_at`, inclusively — a publication attempted at exactly that instant is admissible, which is the deliberate mirror image of the appeal window's strictly-before rule."

    PRD §3.9: "It then recomputes the organization's four publication roll-ups from the new row — `latest_published_score` and `latest_published_grade` from the row's `published_score` and `published_grade`, `published_cycle_count` from its `sequence_number`, and `trend_direction` as `NOT_APPLICABLE` on a first publication and otherwise `IMPROVED`, `DECLINED` or `UNCHANGED` by the sign of `score_delta` — and advances the organization's `version` counter by one."

    Design: Corner/endpoints/publication_is_permitted_only_from_the_correction_deadline_onwards
    """
    scenario = setup_cycle_in_org_review()
    cycle = scenario["cycle"]
    assert_instant(
        cycle["correction_deadline_at"], "2026-09-22T00:00:00Z", "correction_deadline_at"
    )

    set_clock("2026-09-21T23:59:59Z")
    validate_error(
        api.publish_rating_cycle(
            cycle["id"], publish_payload("one second early"), reviewer_headers
        ),
        "ERR_CYCLE_NOT_PUBLISHABLE",
        409,
    )

    refused = read_cycle(cycle["id"], analyst_headers)
    assert refused["status"] == "ORG_REVIEW"
    assert refused["published_at"] is None
    assert refused["publishing_reviewer_user_id"] is None
    _empty, empty_meta = validate_paginated(
        api.list_publication_records(public_headers, params={"rating_cycle_id": cycle["id"]})
    )
    assert empty_meta["total_count"] == 0

    set_clock("2026-09-22T00:00:00Z")
    published = validate_success(
        api.publish_rating_cycle(
            cycle["id"],
            publish_payload("window elapsed, cleared for release"),
            reviewer_headers,
        )
    )
    assert published["status"] == "PUBLISHED"
    assert_instant(published["published_at"], "2026-09-22T00:00:00Z", "published_at")
    assert published["publishing_reviewer_user_id"] == REVIEWER_USER_ID

    records, records_meta = validate_paginated(
        api.list_publication_records(public_headers, params={"rating_cycle_id": cycle["id"]})
    )
    assert records_meta["total_count"] == 1
    record = records[0]
    assert record["sequence_number"] == 1
    assert_score(record["published_score"], 83.13, "published_score")
    assert record["change_direction"] == "FIRST_PUBLICATION"
    assert record["score_delta"] is None
    assert record["notified_recipient_kinds"] == ["RATED_ORGANIZATION"]

    organization = read_organization(scenario["organization"]["id"], public_headers)
    assert_score(organization["latest_published_score"], 83.13, "latest_published_score")
    assert organization["published_cycle_count"] == 1
    assert organization["trend_direction"] == "NOT_APPLICABLE"

    validate_error(
        api.publish_rating_cycle(
            cycle["id"], publish_payload("a second release"), reviewer_headers
        ),
        "ERR_CYCLE_NOT_PUBLISHABLE",
        409,
    )


def test_the_remaining_reverse_lookups_and_single_row_reads_answer_and_narrow(
    api, analyst_headers, reviewer_headers, public_headers
):
    """Each declared filter is paired with one that must match nothing, so a handler
    that ignores its query string is caught by the zero-row half, and the ledger a
    donor may write to is still one a donor may not enumerate.

    PRD §2.9: "Reverse reads accept the filters their §4 rows declare and no others: organizations by `org_type` and `trend_direction`; an organization's filings by `fiscal_year`, `source_kind` and `status`; methodology versions by `status` and by `supersedes_version_id`, which is the reverse lookup for the self-referential supersession chain; a version's comments by `status` and `commenter_kind`; transition grants by `organization_id`, `methodology_version_id` and `status`; governance profiles by `rating_cycle_id` and `evaluation_status`; standard evaluations by `standard_code` and `result`; rating cycles by `organization_id`, `methodology_version_id`, `status` and `fiscal_year`; dimension scores by `dimension` and `status`; corrections by `rating_cycle_id` and `status`; appeals by `rating_cycle_id`, `correction_request_id` and `status`; complaints by `organization_id`, `penalized_rating_cycle_id`, `status` and `category`; and publication records by `organization_id` and `rating_cycle_id`."

    PRD §3.4: "It first computes `independence_ratio` as `independent_board_member_count` divided by `board_member_count`, rounded half up to four decimal places, defined as 0.0000 when `board_member_count` is zero."

    PRD §3.4: "`CEO_COMP_REVIEW` — observed is `ceo_compensation_reviewed`, required is "true", and the standard is met when the board documented a comparability review of chief-executive compensation. Inapplicable when `org_type` is `RELIGIOUS_CONGREGATION`."

    PRD §3.8: "The complaint lands with `status` `INTAKE`, its `complainant_user_id` taken from the caller's `X-User-ID`, `credibility_score`, `credibility_variant`, `severity_tier` and `investigation_due_at` all null, `penalty_points_applied` at 0 and `penalized_rating_cycle_id` null."

    PRD §4: "| `GET` | `/complaints` | Reverse lookup of complaints by organization or by the rating cycle a substantiated complaint penalised. | `MethodologyAdmin`, `RatingAnalyst`, `PublishingReviewer`, `AppealPanelist`, `OrganizationRep` |"

    Design: Corner/endpoints/the_remaining_reverse_lookups_and_single_row_reads_answer_and_narrow
    """
    scenario = setup_scored_cycle(filings=[(2025, FILING_FY2025)], score=False)
    organization = scenario["organization"]
    cycle = scenario["cycle"]
    profile = scenario["governance_profile"]

    adopted, adopted_meta = validate_paginated(
        api.list_methodology_versions(public_headers, params={"status": "ADOPTED"})
    )
    assert adopted_meta["total_count"] == 1
    assert adopted[0]["id"] == scenario["methodology"]["id"]
    assert adopted[0]["version_label"] == "M1"
    drafts, drafts_meta = validate_paginated(
        api.list_methodology_versions(public_headers, params={"status": "DRAFT"})
    )
    assert drafts == []
    assert drafts_meta["total_count"] == 0

    by_org, by_org_meta = validate_paginated(
        api.list_rating_cycles(public_headers, params={"organization_id": organization["id"]})
    )
    assert by_org_meta["total_count"] == 1
    assert by_org[0]["id"] == cycle["id"]
    assert by_org[0]["status"] == "DATA_COLLECTION"
    _wrong_year, wrong_year_meta = validate_paginated(
        api.list_rating_cycles(analyst_headers, params={"fiscal_year": 2024})
    )
    assert wrong_year_meta["total_count"] == 0
    _scored, scored_meta = validate_paginated(
        api.list_rating_cycles(analyst_headers, params={"status": "SCORED"})
    )
    assert scored_meta["total_count"] == 0

    profile_read = validate_success(
        api.get_governance_profile(profile["id"], reviewer_headers)
    )
    assert_ratio(profile_read["independence_ratio"], 0.5714, "independence_ratio")
    assert profile_read["standards_met_count"] == 7
    assert profile_read["standards_not_met_count"] == 1
    assert profile_read["evaluation_status"] == "EVALUATED"

    failed_rows, failed_meta = validate_paginated(
        api.list_standard_evaluations(
            profile["id"], reviewer_headers, params={"result": "NOT_MET"}
        )
    )
    assert failed_meta["total_count"] == 1
    failed = standard_by_code(failed_rows, "CEO_COMP_REVIEW")
    single_row = validate_success(
        api.get_standard_evaluation(failed["id"], make_panelist_headers("panel-a"))
    )
    assert single_row["standard_code"] == "CEO_COMP_REVIEW"
    assert single_row["result"] == "NOT_MET"
    assert single_row["observed_value"] == "false"
    assert single_row["required_value"] == "true"

    complaint = file_complaint(
        organization["id"],
        headers=public_headers,
        complainant_kind="DONOR",
        category="TRANSPARENCY",
        narrative="The annual report never appeared on the website",
        corroborating_document_count=2,
    )
    assert complaint["status"] == "INTAKE"
    assert complaint["credibility_score"] is None
    assert complaint["penalty_points_applied"] == 0
    assert complaint["complainant_user_id"] == PUBLIC_USER_ID

    intake_rows, intake_meta = validate_paginated(
        api.list_complaints(
            analyst_headers,
            params={"organization_id": organization["id"], "status": "INTAKE"},
        )
    )
    assert intake_meta["total_count"] == 1
    assert intake_rows[0]["id"] == complaint["id"]
    _misuse, misuse_meta = validate_paginated(
        api.list_complaints(analyst_headers, params={"category": "MISUSE_OF_FUNDS"})
    )
    assert misuse_meta["total_count"] == 0

    complaint_read = validate_success(
        api.get_complaint(complaint["id"], make_panelist_headers("panel-a"))
    )
    assert complaint_read["complainant_kind"] == "DONOR"
    assert complaint_read["category"] == "TRANSPARENCY"
    assert complaint_read["corroborating_document_count"] == 2
    assert complaint_read["severity_tier"] is None

    validate_error(
        api.list_complaints(public_headers), "ERR_ROLE_NOT_PERMITTED", 403
    )


def test_the_transition_sweep_expires_grace_strictly_after_the_deadline(
    api, admin_headers, analyst_headers
):
    """The sweep's condition is strictly `grace_until` before the clock while the
    admission check is inclusive, so the deadline instant itself is still grace: the
    sweep expires nothing at it and a cycle opened at it is still licensed.

    PRD §3.2: "Grace also expires on its own: an operator-run sweep, available to a `MethodologyAdmin`, moves every `ACTIVE` grant whose `grace_until` lies strictly before the logical clock to `EXPIRED`, advances each such grant's `version` counter by one, and answers with an `expired_grant_count` and the matching list of `expired_grant_ids`."

    PRD §3.2: "When a `RatingAnalyst` opens a new cycle pinned to a `RETIRED` methodology version while passing `use_transition_grant` as true, the organization's `ACTIVE` grant whose `superseded_version_label` matches the pinned version's `version_label` moves `ACTIVE` → `CONSUMED` and its `version` counter advances by one. Where no such live grant exists, or its `grace_until` has already elapsed, the cycle creation is refused with `ERR_TRANSITION_GRACE_UNAVAILABLE`."

    PRD §2.8: "13. **Transition grace.** When a new rating cycle pins a `MethodologyVersion` whose status is `RETIRED`, `use_transition_grant` must be true **and** the organization must hold a `TransitionGrant` whose `superseded_version_label` equals that version's `version_label`, whose `status` is `ACTIVE`, and whose `grace_until` is at or after the logical clock. Otherwise `ERR_TRANSITION_GRACE_UNAVAILABLE` (409), on `POST /rating-cycles`."

    PRD §3.3: "`transition_grace_until` mirrors the `grace_until` of the organization's `ACTIVE` transition grant and is null when there is none."

    Design: Corner/endpoints/the_transition_sweep_expires_grace_strictly_after_the_deadline
    """
    scenario = setup_transition_grant()
    organization = scenario["organization"]
    methodology = scenario["methodology"]

    active, active_meta = validate_paginated(
        api.list_transition_grants(
            admin_headers,
            params={"organization_id": organization["id"], "status": "ACTIVE"},
        )
    )
    assert active_meta["total_count"] == 1
    grant = active[0]
    assert_instant(grant["grace_until"], "2026-12-21T00:00:00Z", "grace_until")
    assert grant["superseded_version_label"] == "M1"
    assert methodology["status"] == "RETIRED"

    early = run_transition_sweep()
    assert early["expired_grant_count"] == 0

    set_clock("2026-12-21T00:00:00Z")
    at_deadline = run_transition_sweep()
    assert at_deadline["expired_grant_count"] == 0

    licensed = validate_success(
        api.create_rating_cycle(
            create_rating_cycle_payload(
                organization["id"],
                methodology["id"],
                fiscal_year=2024,
                period_start="2024-01-01T00:00:00Z",
                period_end="2025-01-01T00:00:00Z",
                use_transition_grant=True,
            ),
            analyst_headers,
        ),
        201,
    )
    assert licensed["methodology_version_id"] == methodology["id"]

    consumed = validate_success(api.get_transition_grant(grant["id"], admin_headers))
    assert consumed["status"] == "CONSUMED"
    assert consumed["version"] == 2

    set_clock("2026-12-21T00:00:01Z")
    past = run_transition_sweep()
    assert past["expired_grant_count"] == 0
    assert past["expired_grant_ids"] == []

    unchanged = validate_success(api.get_transition_grant(grant["id"], admin_headers))
    assert unchanged["status"] == "CONSUMED"
    assert unchanged["version"] == 2
    assert read_organization(organization["id"], admin_headers)["transition_grace_until"] is None

    validate_error(
        api.create_rating_cycle(
            create_rating_cycle_payload(
                organization["id"],
                methodology["id"],
                fiscal_year=2023,
                period_start="2023-01-01T00:00:00Z",
                period_end="2024-01-01T00:00:00Z",
                use_transition_grant=True,
            ),
            analyst_headers,
        ),
        "ERR_TRANSITION_GRACE_UNAVAILABLE",
        409,
    )

    again = run_transition_sweep()
    assert again["expired_grant_count"] == 0
