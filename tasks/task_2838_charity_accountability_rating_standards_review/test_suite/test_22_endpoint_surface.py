"""The read surface, the smallest action endpoint, the bulk write and a two-key link."""
from test_helpers import (
    NON_EXISTENT_UUID,
    adopt_methodology_payload,
    assert_instant,
    assert_score,
    create_appeal_payload,
    create_draft_methodology,
    dimension_by_name,
    dimension_overrides_payload,
    dispose_public_comment,
    file_public_comment,
    make_organization_rep_headers,
    open_comment,
    close_comment,
    override_dimensions,
    read_correction,
    read_cycle,
    read_filing,
    setup_bare_organization,
    setup_rejected_correction,
    setup_scored_cycle,
    submit_filing,
    validate_error,
    validate_paginated,
    validate_success,
)

# The eight mandatory figures of the canonical audited statement, so the two
# filings this file writes differ in nothing but `source_kind` and the one
# optional joint-cost figure.
MANDATORY_FIGURES = {
    "total_expense_cents": 10000000,
    "program_expense_cents": 8000000,
    "fundraising_expense_cents": 1200000,
    "admin_expense_cents": 800000,
    "contributions_cents": 9000000,
    "total_revenue_cents": 11000000,
    "net_assets_cents": 6000000,
    "total_liabilities_cents": 2000000,
}


def test_a_written_filing_reads_back_identically_through_every_declared_route(
    api, analyst_headers, public_headers
):
    """Two filings that share an organization and a fiscal year and differ only in
    source kind, read back by id, through the parent's reverse read and through
    each declared filter, with the omitted optional figure defaulted rather than
    guessed at.

    PRD §3.3: "Three more are optional and default to 0 when omitted: `grants_paid_cents`, the grants this charity paid onward to other organizations; `membership_services_cents`, member-services spend; and `joint_cost_allocated_cents`, the joint costs allocated out of fundraising appeals and into program services."

    PRD §3.3: "`status` starts at `RECEIVED`. `source_precedence` is 1 for an `AUDITED_STATEMENT`, 2 for a `PUBLIC_FILING` and 3 for an `ORG_SUBMISSION`. `origin` records how the row arrived: `ORG_PORTAL` when the submitter was an `OrganizationRep`, `ANALYST_ENTRY` when it was a `RatingAnalyst`, and `CORRECTION_APPLIED` for the replacement rows the correction and appeal machinery synthesizes."

    PRD §2.3: "Where a different order is specified — the publication ledger by `sequence_number` ascending, an organization's filings by `fiscal_year` descending then `source_precedence` ascending then `created_at` ascending, an organization's rating trend newest-first, a profile's standard evaluations by `standard_code` ascending, a cycle's dimension rows in the fixed order `FINANCIAL_HEALTH`, `ACCOUNTABILITY`, `TRANSPARENCY`, `IMPACT` — that ordering is applied before the window is cut, so paging through a filtered read is positionally stable."

    PRD §2.9: "Reverse reads accept the filters their §4 rows declare and no others: organizations by `org_type` and `trend_direction`; an organization's filings by `fiscal_year`, `source_kind` and `status`; methodology versions by `status` and by `supersedes_version_id`, which is the reverse lookup for the self-referential supersession chain; a version's comments by `status` and `commenter_kind`; transition grants by `organization_id`, `methodology_version_id` and `status`; governance profiles by `rating_cycle_id` and `evaluation_status`; standard evaluations by `standard_code` and `result`; rating cycles by `organization_id`, `methodology_version_id`, `status` and `fiscal_year`; dimension scores by `dimension` and `status`; corrections by `rating_cycle_id` and `status`; appeals by `rating_cycle_id`, `correction_request_id` and `status`; complaints by `organization_id`, `penalized_rating_cycle_id`, `status` and `category`; and publication records by `organization_id` and `rating_cycle_id`."

    PRD §2.3: "For list responses the `meta` object carries all four pagination fields: `limit` and `offset` echo the effective values actually applied, `total_count` is the number of rows matching the filters before the window is applied, and `has_more` is true when rows remain beyond the current window."

    Design: Corner/endpoints/written_rows_read_back_identically_through_every_declared_route
    """
    scenario = setup_bare_organization()
    organization = scenario["organization"]
    org_rep_headers = scenario["org_rep_headers"]

    public_filing = submit_filing(
        organization["id"],
        fiscal_year=2025,
        source_kind="PUBLIC_FILING",
        headers=org_rep_headers,
        **MANDATORY_FIGURES,
    )
    assert public_filing["status"] == "RECEIVED"
    assert public_filing["joint_cost_allocated_cents"] == 0
    assert public_filing["grants_paid_cents"] == 0
    assert public_filing["membership_services_cents"] == 0
    assert public_filing["source_precedence"] == 2
    assert public_filing["origin"] == "ORG_PORTAL"

    audited_filing = submit_filing(
        organization["id"],
        fiscal_year=2025,
        source_kind="AUDITED_STATEMENT",
        headers=org_rep_headers,
        joint_cost_allocated_cents=500000,
        **MANDATORY_FIGURES,
    )
    assert audited_filing["source_precedence"] == 1

    by_id = read_filing(audited_filing["id"], analyst_headers)
    assert by_id["joint_cost_allocated_cents"] == 500000
    assert by_id["status"] == "RECEIVED"
    assert by_id["version"] == 1
    for field in ("fiscal_year", "source_kind", "origin", "source_precedence", *MANDATORY_FIGURES):
        assert by_id[field] == audited_filing[field], f"{field} did not round-trip"

    all_rows, all_meta = validate_paginated(
        api.list_organization_filing_records(organization["id"], analyst_headers)
    )
    assert all_meta["total_count"] == 2
    assert all_meta["has_more"] is False
    assert [row["id"] for row in all_rows] == [audited_filing["id"], public_filing["id"]]

    only_public, public_meta = validate_paginated(
        api.list_organization_filing_records(
            organization["id"], analyst_headers, params={"source_kind": "PUBLIC_FILING"}
        )
    )
    assert public_meta["total_count"] == 1
    assert only_public[0]["id"] == public_filing["id"]

    empty_year, empty_meta = validate_paginated(
        api.list_organization_filing_records(
            organization["id"], analyst_headers, params={"fiscal_year": 2024}
        )
    )
    assert empty_year == []
    assert empty_meta["total_count"] == 0
    assert empty_meta["has_more"] is False

    charities, charity_meta = validate_paginated(
        api.list_organizations(public_headers, params={"org_type": "PUBLIC_CHARITY"})
    )
    assert charity_meta["total_count"] == 1
    assert charities[0]["id"] == organization["id"]

    foundations, foundation_meta = validate_paginated(
        api.list_organizations(public_headers, params={"org_type": "PRIVATE_FOUNDATION"})
    )
    assert foundations == []
    assert foundation_meta["total_count"] == 0


def test_disposing_each_comment_walks_the_unresolved_ledger_down_to_the_adoption_gate(
    api, admin_headers, public_headers
):
    """One comment incorporated and one declined, the unresolved ledger falling two
    to one to zero while the tally stays at two, and the adoption the ledger had
    been blocking finally admitted.

    PRD §3.1: "A new comment lands with `status` `SUBMITTED` and a null `disposition_note`, and it advances its parent version's `comment_count` and `unresolved_comment_count` by one each and that version's `version` counter by one."

    PRD §3.1: "Disposal is a separate act by a `MethodologyAdmin`, who supplies a `disposition` of `INCORPORATED` or `DECLINED` and an optional `disposition_note`; the comment moves from `SUBMITTED` to the chosen disposition, its parent's `unresolved_comment_count` falls by one, and both the comment's and the parent version's `version` counters advance by one."

    PRD §2.8: "24. **Comments disposed.** A methodology version is adopted only when its `unresolved_comment_count` is zero — every public comment has been disposed to `INCORPORATED` or `DECLINED` — else `ERR_UNRESOLVED_COMMENTS` (409), on `POST /methodology-versions/{methodology_version_id}/adopt`."

    Design: Corner/endpoints/disposing_each_comment_walks_the_unresolved_ledger_down_to_the_adoption_gate
    """
    methodology = create_draft_methodology()
    open_comment(methodology["id"])
    donor_comment = file_public_comment(
        methodology["id"],
        headers=public_headers,
        commenter_kind="DONOR",
        body="Publish the sensitivity analysis behind the weights",
    )
    org_comment = file_public_comment(
        methodology["id"],
        headers=make_organization_rep_headers("org-rep-1"),
        commenter_kind="RATED_ORGANIZATION",
        body="Small charities cannot supply a third-party evaluation",
    )
    assert donor_comment["status"] == "SUBMITTED"
    assert donor_comment["disposition_note"] is None

    before = validate_success(api.get_methodology_version(methodology["id"], admin_headers))
    assert before["comment_count"] == 2
    assert before["unresolved_comment_count"] == 2
    # One create, one open-comment and two comments, each advancing the counter.
    assert before["version"] == 4

    incorporated = dispose_public_comment(
        donor_comment["id"],
        "INCORPORATED",
        disposition_note="the sensitivity table will accompany the methodology",
    )
    assert incorporated["status"] == "INCORPORATED"
    assert incorporated["version"] == 2

    middle = validate_success(api.get_methodology_version(methodology["id"], admin_headers))
    assert middle["unresolved_comment_count"] == 1
    assert middle["comment_count"] == 2

    declined = dispose_public_comment(
        org_comment["id"],
        "DECLINED",
        disposition_note="the standard already exempts organizations below the revenue floor",
    )
    assert declined["status"] == "DECLINED"

    after = validate_success(api.get_methodology_version(methodology["id"], admin_headers))
    assert after["unresolved_comment_count"] == 0
    assert after["comment_count"] == 2
    assert after["version"] == before["version"] + 2

    close_comment(methodology["id"])
    adopted = validate_success(
        api.adopt_methodology_version(
            methodology["id"],
            adopt_methodology_payload("2026-10-01T00:00:00Z"),
            admin_headers,
        )
    )
    assert adopted["status"] == "ADOPTED"
    assert_instant(adopted["adopted_at"], "2026-08-01T00:00:00Z", "adopted_at")

    incorporated_rows, incorporated_meta = validate_paginated(
        api.list_methodology_public_comments(
            methodology["id"], public_headers, params={"status": "INCORPORATED"}
        )
    )
    assert incorporated_meta["total_count"] == 1
    assert incorporated_rows[0]["id"] == donor_comment["id"]

    still_open, still_open_meta = validate_paginated(
        api.list_methodology_public_comments(
            methodology["id"], public_headers, params={"status": "SUBMITTED"}
        )
    )
    assert still_open == []
    assert still_open_meta["total_count"] == 0


def _dimension_row(api, cycle_id, headers, dimension):
    rows, meta = validate_paginated(
        api.list_dimension_scores(cycle_id, headers, params={"dimension": dimension})
    )
    assert meta["total_count"] == 1, f"expected one {dimension} row"
    return rows[0]


def test_a_bulk_override_with_one_bad_entry_writes_nothing_at_all(api, analyst_headers):
    """A two-entry batch whose first entry is perfectly valid is rejected as a unit,
    once for a row that belongs to no cycle and once for points above the row's own
    maximum, and only the third batch reaches the dimension rows.

    PRD §3.6: "Every `dimension_score_id` must resolve to a dimension row belonging to **this** cycle — a row that does not exist, or that belongs to a different cycle, is `ERR_DIMENSION_SCORE_NOT_FOUND` — and every `raw_points` must be an integer between 0 and that row's own `max_points` inclusive, or the request is `ERR_INVALID_REQUEST`. The operation is all-or-nothing: if any entry in the array is invalid, nothing at all is written."

    PRD §3.6: "On success each named dimension row takes its supplied `raw_points`, recomputes `normalized_score` and `weighted_contribution`, stores the shared `override_reason` and the acting `X-User-ID` as `overridden_by_user_id`, and advances its own `version` counter by one. A row previously `COMPUTED` moves `COMPUTED` → `OVERRIDDEN`"

    PRD §3.6: "The cycle itself travels `SCORED` → `SCORED` and recomputes both composite variants and both grades."

    PRD §3.6: "**Step two** forms the weighted sum: each included dimension's `normalized_score` is multiplied by that dimension's weight, each such product is rounded half up to two decimal places, the rounded products are summed, and the sum is rounded half up to two decimal places again."

    Design: Corner/endpoints/a_bulk_override_with_one_bad_entry_writes_nothing_at_all
    """
    scenario = setup_scored_cycle()
    cycle = scenario["cycle"]
    accountability = _dimension_row(api, cycle["id"], analyst_headers, "ACCOUNTABILITY")
    transparency = _dimension_row(api, cycle["id"], analyst_headers, "TRANSPARENCY")
    assert accountability["raw_points"] == 21
    assert accountability["max_points"] == 24
    assert transparency["max_points"] == 20
    cycle_version = cycle["version"]

    validate_error(
        api.create_dimension_overrides(
            cycle["id"],
            dimension_overrides_payload(
                [
                    {"dimension_score_id": accountability["id"], "raw_points": 20},
                    {"dimension_score_id": NON_EXISTENT_UUID, "raw_points": 10},
                ],
                cycle_version,
                override_reason="conflict of interest policy is stale but the audit committee compensates",
            ),
            analyst_headers,
        ),
        "ERR_DIMENSION_SCORE_NOT_FOUND",
        404,
    )
    validate_error(
        api.create_dimension_overrides(
            cycle["id"],
            dimension_overrides_payload(
                [
                    {"dimension_score_id": accountability["id"], "raw_points": 20},
                    {"dimension_score_id": transparency["id"], "raw_points": 21},
                ],
                cycle_version,
                override_reason="transparency deserves more than the maximum",
            ),
            analyst_headers,
        ),
        "ERR_INVALID_REQUEST",
        400,
    )

    untouched = _dimension_row(api, cycle["id"], analyst_headers, "ACCOUNTABILITY")
    assert untouched["raw_points"] == 21
    assert untouched["status"] == "COMPUTED"
    assert untouched["overridden_by_user_id"] is None
    assert read_cycle(cycle["id"], analyst_headers)["version"] == cycle_version

    overridden_cycle = override_dimensions(
        cycle["id"],
        [
            {"dimension_score_id": accountability["id"], "raw_points": 20},
            {"dimension_score_id": transparency["id"], "raw_points": 18},
        ],
        cycle_version,
        override_reason="documented analyst judgement on both dimensions",
    )
    assert_score(overridden_cycle["weighted_sum_final"], 81.58, "weighted_sum_final")
    assert_score(overridden_cycle["final_composite_score"], 80.08, "final_composite_score")
    assert overridden_cycle["grade"] == "MEETS_STANDARDS"
    assert overridden_cycle["status"] == "SCORED"
    assert overridden_cycle["version"] == cycle_version + 1

    rows, _meta = validate_paginated(api.list_dimension_scores(cycle["id"], analyst_headers))
    written_accountability = dimension_by_name(rows, "ACCOUNTABILITY")
    written_transparency = dimension_by_name(rows, "TRANSPARENCY")
    assert written_accountability["status"] == "OVERRIDDEN"
    assert written_accountability["raw_points"] == 20
    assert_score(written_accountability["normalized_score"], 83.33, "ACCOUNTABILITY normalized_score")
    assert written_accountability["overridden_by_user_id"] == scenario["analyst_user_id"]
    assert (
        written_accountability["override_reason"]
        == "documented analyst judgement on both dimensions"
    )
    assert written_transparency["status"] == "OVERRIDDEN"
    assert written_transparency["raw_points"] == 18
    assert_score(written_transparency["normalized_score"], 90.00, "TRANSPARENCY normalized_score")

    _overridden_rows, overridden_meta = validate_paginated(
        api.list_dimension_scores(cycle["id"], analyst_headers, params={"status": "OVERRIDDEN"})
    )
    assert overridden_meta["total_count"] == 2
    _computed_rows, computed_meta = validate_paginated(
        api.list_dimension_scores(cycle["id"], analyst_headers, params={"status": "COMPUTED"})
    )
    assert computed_meta["total_count"] == 2


def test_an_appeal_links_a_cycle_to_a_correction_and_both_ends_must_exist(
    api, admin_headers, analyst_headers
):
    """Each of the two body foreign keys is reported under its own not-found code, and
    the accepted appeal is then discoverable from the cycle and from the correction
    it contests without either end having moved.

    PRD §2.8: "7. **Body foreign keys.** Every foreign key supplied in the request body resolves to a stored row, yielding `ERR_ORGANIZATION_NOT_FOUND`, `ERR_METHODOLOGY_VERSION_NOT_FOUND`, `ERR_RATING_CYCLE_NOT_FOUND`, `ERR_CORRECTION_REQUEST_NOT_FOUND` or `ERR_DIMENSION_SCORE_NOT_FOUND` — the code belonging to the entity whose identifier failed to resolve — each HTTP 404."

    PRD §2.9: "No resource in this service is nested for the purpose of writing. Every write targets a root-level collection, and relationships travel in request bodies: a filing names its `organization_id`, a rating cycle names its `organization_id` and its `methodology_version_id`, a governance profile names its `rating_cycle_id`, a public comment names its `methodology_version_id`, a correction names its `rating_cycle_id`, an appeal names both its `rating_cycle_id` and the `correction_request_id` it contests, and a complaint names its `organization_id`."

    PRD §3.7: "The appeal lands with `status` `FILED`, `filed_by_org_user_id` from the caller's `X-User-ID`, `filed_at` from the logical clock, `deadline_at` as a retained copy of the cycle's `appeal_deadline_at` for audit purposes, an empty `panel_member_user_ids`, and null `decided_by_user_id`, `decided_at` and `decision_note`. Filing drives the cycle `ORG_REVIEW` → `APPEAL_OPEN` and advances the cycle's `version` counter by one."

    Design: Corner/endpoints/an_appeal_links_a_cycle_to_a_correction_and_both_ends_must_exist
    """
    scenario = setup_rejected_correction()
    cycle = scenario["cycle"]
    correction = scenario["correction"]
    org_rep_headers = scenario["org_rep_headers"]
    grounds = "the rejection ignored the restated audit schedule"

    validate_error(
        api.create_appeal(
            create_appeal_payload(NON_EXISTENT_UUID, correction["id"], grounds=grounds),
            org_rep_headers,
        ),
        "ERR_RATING_CYCLE_NOT_FOUND",
        404,
    )
    validate_error(
        api.create_appeal(
            create_appeal_payload(cycle["id"], NON_EXISTENT_UUID, grounds=grounds),
            org_rep_headers,
        ),
        "ERR_CORRECTION_REQUEST_NOT_FOUND",
        404,
    )

    appeal = validate_success(
        api.create_appeal(
            create_appeal_payload(cycle["id"], correction["id"], grounds=grounds),
            org_rep_headers,
        ),
        201,
    )
    assert appeal["rating_cycle_id"] == cycle["id"]
    assert appeal["correction_request_id"] == correction["id"]
    assert appeal["status"] == "FILED"
    assert appeal["panel_member_user_ids"] == []
    assert_instant(appeal["filed_at"], "2026-09-01T00:00:00Z", "filed_at")

    by_correction, correction_meta = validate_paginated(
        api.list_appeals(admin_headers, params={"correction_request_id": correction["id"]})
    )
    assert correction_meta["total_count"] == 1
    assert by_correction[0]["id"] == appeal["id"]

    by_cycle, cycle_meta = validate_paginated(
        api.list_appeals(admin_headers, params={"rating_cycle_id": cycle["id"]})
    )
    assert cycle_meta["total_count"] == 1
    assert by_cycle[0]["id"] == appeal["id"]

    assert read_correction(correction["id"], admin_headers)["status"] == "REJECTED"
    after = read_cycle(cycle["id"], analyst_headers)
    assert after["status"] == "APPEAL_OPEN"
    assert after["version"] == cycle["version"] + 1
