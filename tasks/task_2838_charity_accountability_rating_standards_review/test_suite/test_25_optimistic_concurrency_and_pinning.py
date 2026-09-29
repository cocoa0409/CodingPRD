"""Optimistic concurrency on the two versioned writes, and the methodology pin."""
from test_helpers import (
    ANALYST_USER_ID,
    adopt_successor_methodology,
    assert_instant,
    assert_score,
    create_filing_record_payload,
    create_organization,
    create_rating_cycle_payload,
    dimension_by_name,
    dimension_overrides_payload,
    organization_version,
    override_dimensions,
    read_cycle,
    read_publication_records,
    score_cycle,
    setup_scored_cycle,
    validate_error,
    validate_paginated,
    validate_success,
    walk_cycle_to_published,
)

# The public filing Harbor Relief lodges first: 3,000,000 + 600,000 + 400,000
# whole cents of expense, so the §2.8 check-29 expense identity holds.
FILING_FIRST = {
    "total_expense_cents": 4000000,
    "program_expense_cents": 3000000,
    "fundraising_expense_cents": 600000,
    "admin_expense_cents": 400000,
    "contributions_cents": 3500000,
    "total_revenue_cents": 4200000,
    "net_assets_cents": 2400000,
    "total_liabilities_cents": 400000,
}

# The same fiscal year and the same source kind, re-split across the three
# expense components — a body that is legal on every field except the version.
FILING_SECOND = dict(
    FILING_FIRST,
    program_expense_cents=1000000,
    fundraising_expense_cents=2000000,
    admin_expense_cents=1000000,
)

# Two filings for the busier sibling charity, whose only job is to drive that
# organization's own version counter past Harbor Relief's.
FILING_SIBLING_FY2025 = {
    "total_expense_cents": 1000000,
    "program_expense_cents": 800000,
    "fundraising_expense_cents": 100000,
    "admin_expense_cents": 100000,
    "contributions_cents": 900000,
    "total_revenue_cents": 1100000,
    "net_assets_cents": 600000,
    "total_liabilities_cents": 100000,
}
FILING_SIBLING_FY2024 = {
    "total_expense_cents": 900000,
    "program_expense_cents": 700000,
    "fundraising_expense_cents": 100000,
    "admin_expense_cents": 100000,
    "contributions_cents": 800000,
    "total_revenue_cents": 950000,
    "net_assets_cents": 500000,
    "total_liabilities_cents": 100000,
}


def test_a_filing_submission_is_serialised_by_the_version_the_submitter_actually_read(
    api, analyst_headers
):
    """A version harvested from a busier sibling charity is exactly as stale as one
    left over from before the last accepted filing, because the guard is an equality
    test against this parent's counter rather than a not-older-than test.

    PRD §2.7: "`POST /filing-records` requires a non-optional `expected_organization_version` field in its request body, carrying the client's last observed `version` of the `Organization` named by `organization_id`. If that value does not equal the organization's current `version`, the submission is rejected with `ERR_STALE_VERSION` (HTTP 412) and no filing row is written."

    PRD §2.8: "**Stale parent version.** The supplied `expected_organization_version` or `expected_rating_cycle_version` equals the parent's current `version`, else `ERR_STALE_VERSION` (412). This applies to exactly two endpoints: `POST /filing-records` and `POST /rating-cycles/{rating_cycle_id}/dimension-overrides`."

    PRD §3.3: "`validated_at`, `rejection_code` and `superseded_at` all start null, and the submission advances the parent organization's `version` counter by one."

    PRD §3.3: "`status` starts at `RECEIVED`. `source_precedence` is 1 for an `AUDITED_STATEMENT`, 2 for a `PUBLIC_FILING` and 3 for an `ORG_SUBMISSION`."

    PRD §2.4: "`version`, an integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row, whether the mutation came from a client request or from a cascade fired by an operation on another resource."

    Design: Corner/cross_cutting_complexity_layers/occ_rule_filing_create_stale_organization
    """
    organization = create_organization()
    first_read = organization_version(organization["id"], analyst_headers)
    assert first_read == 1

    first_filing = validate_success(
        api.create_filing_record(
            create_filing_record_payload(
                organization["id"],
                first_read,
                fiscal_year=2025,
                source_kind="PUBLIC_FILING",
                **FILING_FIRST,
            ),
            analyst_headers,
        ),
        201,
    )
    assert first_filing["status"] == "RECEIVED"
    assert organization_version(organization["id"], analyst_headers) == 2

    validate_error(
        api.create_filing_record(
            create_filing_record_payload(
                organization["id"],
                first_read,
                fiscal_year=2025,
                source_kind="PUBLIC_FILING",
                **FILING_SECOND,
            ),
            analyst_headers,
        ),
        "ERR_STALE_VERSION",
        412,
    )
    after_reject = organization_version(organization["id"], analyst_headers)
    assert after_reject == 2

    sibling = create_organization(
        legal_name="Beacon Youth Alliance",
        ein="222222222",
        fiscal_year_end_month=6,
        contact_email="rep@beacon.org",
    )
    assert sibling["version"] == 1
    validate_success(
        api.create_filing_record(
            create_filing_record_payload(
                sibling["id"], 1, fiscal_year=2025, source_kind="PUBLIC_FILING",
                **FILING_SIBLING_FY2025,
            ),
            analyst_headers,
        ),
        201,
    )
    assert organization_version(sibling["id"], analyst_headers) == 2
    validate_success(
        api.create_filing_record(
            create_filing_record_payload(
                sibling["id"], 2, fiscal_year=2024, source_kind="PUBLIC_FILING",
                **FILING_SIBLING_FY2024,
            ),
            analyst_headers,
        ),
        201,
    )
    sibling_version = organization_version(sibling["id"], analyst_headers)
    assert sibling_version == 3
    assert organization_version(organization["id"], analyst_headers) == 2

    validate_error(
        api.create_filing_record(
            create_filing_record_payload(
                organization["id"],
                sibling_version,
                fiscal_year=2025,
                source_kind="PUBLIC_FILING",
                **FILING_SECOND,
            ),
            analyst_headers,
        ),
        "ERR_STALE_VERSION",
        412,
    )
    assert organization_version(organization["id"], analyst_headers) == 2

    second_filing = validate_success(
        api.create_filing_record(
            create_filing_record_payload(
                organization["id"],
                after_reject,
                fiscal_year=2025,
                source_kind="PUBLIC_FILING",
                **FILING_SECOND,
            ),
            analyst_headers,
        ),
        201,
    )
    assert second_filing["id"] != first_filing["id"]
    assert organization_version(organization["id"], analyst_headers) == 3
    assert organization_version(sibling["id"], analyst_headers) == 3

    rows, meta = validate_paginated(
        api.list_organization_filing_records(
            organization["id"], analyst_headers, params={"fiscal_year": 2025}
        )
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first_filing["id"], second_filing["id"]}
    assert [row["status"] for row in rows] == ["RECEIVED", "RECEIVED"]
    assert all(row["source_precedence"] == 2 for row in rows)


def test_an_override_chain_is_serialised_against_the_row_it_recomputes(
    api, analyst_headers
):
    """The override's parent is the very cycle whose score it rewrites, so the version
    moves under the analyst's feet on every attempt and a double submit cannot silently
    re-apply the same downgrade.

    PRD §2.7: "If that value does not equal the cycle's current `version`, the override is rejected with `ERR_STALE_VERSION` (HTTP 412) and no dimension row is touched."

    PRD §2.7: "This endpoint drives a `SCORED` to `SCORED` self-loop, so no state precondition can catch a later override that supersedes an earlier one"

    PRD §3.6: "a row already `OVERRIDDEN` moves `OVERRIDDEN` → `OVERRIDDEN`, overwriting both the earlier `raw_points` and the earlier `override_reason` and `overridden_by_user_id`"

    PRD §3.6: "The cycle itself travels `SCORED` → `SCORED` and recomputes both composite variants and both grades."

    PRD §2.4: "`version`, an integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row, whether the mutation came from a client request or from a cascade fired by an operation on another resource."

    Design: Corner/cross_cutting_complexity_layers/occ_rule_dimension_override_stale_cycle
    """
    scenario = setup_scored_cycle()
    cycle = scenario["cycle"]
    accountability = dimension_by_name(scenario["dimension_scores"], "ACCOUNTABILITY")
    read_version = cycle["version"]
    assert_score(cycle["weighted_sum_final"], 84.63, "weighted_sum_final")

    downgraded = override_dimensions(
        cycle["id"],
        [{"dimension_score_id": accountability["id"], "raw_points": 20}],
        read_version,
        override_reason="conflict of interest policy was reviewed late, documented downgrade",
    )
    assert_score(downgraded["weighted_sum_final"], 83.58, "weighted_sum_final")
    assert_score(downgraded["final_composite_score"], 82.08, "final_composite_score")
    assert downgraded["grade"] == "MEETS_STANDARDS"
    assert downgraded["version"] == read_version + 1

    validate_error(
        api.create_dimension_overrides(
            cycle["id"],
            dimension_overrides_payload(
                [{"dimension_score_id": accountability["id"], "raw_points": 20}],
                read_version,
                override_reason="replaying the same override with the version I read before it",
            ),
            analyst_headers,
        ),
        "ERR_STALE_VERSION",
        412,
    )

    unmoved = read_cycle(cycle["id"], analyst_headers)
    assert unmoved["version"] == downgraded["version"]
    assert_score(unmoved["weighted_sum_final"], 83.58, "weighted_sum_final")
    assert_score(unmoved["final_composite_score"], 82.08, "final_composite_score")

    corrected = override_dimensions(
        cycle["id"],
        [{"dimension_score_id": accountability["id"], "raw_points": 21}],
        unmoved["version"],
        override_reason="corrected downgrade after re-reading the cycle",
    )
    assert_score(corrected["weighted_sum_final"], 84.63, "weighted_sum_final")
    assert_score(corrected["final_composite_score"], 83.13, "final_composite_score")
    assert corrected["version"] == downgraded["version"] + 1

    rows, meta = validate_paginated(
        api.list_dimension_scores(
            cycle["id"], analyst_headers, params={"dimension": "ACCOUNTABILITY"}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["raw_points"] == 21
    assert rows[0]["status"] == "OVERRIDDEN"
    assert_score(rows[0]["normalized_score"], 87.50, "ACCOUNTABILITY normalized_score")
    assert rows[0]["override_reason"] == "corrected downgrade after re-reading the cycle"
    assert rows[0]["overridden_by_user_id"] == ANALYST_USER_ID


def test_a_pinned_methodology_keeps_scoring_its_cycle_after_it_has_been_retired(
    api, admin_headers, analyst_headers, public_headers
):
    """M1 is retired between the pin and the score, so every weight this cycle is ever
    judged by is read from a version that is no longer adopted — while a brand new cycle
    may not choose that same version at all.

    PRD §3.2: "In the same hop, the methodology version that was `ADOPTED` — the one named by `supersedes_version_id` — moves `ADOPTED` → `RETIRED`, its `retired_at` takes the logical clock and its `effective_until` is closed at the new version's `effective_from`."

    PRD §3.2: "Retirement is not destructive to work in flight: a rating cycle already pinned to the retiring version keeps its pin and publishes normally, because its `methodology_pin_locked` flag was set when the cycle was created."

    PRD §3.2: "Organizations with no publication at all are skipped entirely and never receive a grant."

    PRD §3.5: "The pinned `methodology_version_id` is written once at creation and is **never** rewritten afterwards, not even when that version is later retired — this is the whole point of the pin, and it is why a mid-cycle methodology revision cannot re-grade work in flight."

    PRD §3.6: "**Step one** chooses the weight vector. The four declared weights come from the cycle's pinned methodology version: `weight_financial_health`, `weight_accountability`, `weight_transparency` and `weight_impact`."

    PRD §3.5: "The pinned methodology must ordinarily be `ADOPTED`, or the creation is `ERR_METHODOLOGY_NOT_ADOPTED`"

    PRD §3.9: "`methodology_version_label` from the `version_label` of the methodology version pinned on the cycle"

    Design: Corner/cross_cutting_complexity_layers/a_pinned_methodology_keeps_scoring_its_cycle_after_it_is_retired
    """
    scenario = setup_scored_cycle(score=False)
    organization = scenario["organization"]
    cycle = scenario["cycle"]
    m1 = scenario["methodology"]
    assert organization["published_cycle_count"] == 0

    successor = adopt_successor_methodology(
        m1["id"],
        effective_from="2026-10-01T00:00:00Z",
        version_label="M2",
        weight_financial_health=0.325,
        weight_accountability=0.25,
        weight_transparency=0.2,
        weight_impact=0.225,
        revision_note="Impact weight raised after public consultation",
    )
    assert successor["status"] == "ADOPTED"
    assert successor["supersedes_version_id"] == m1["id"]

    retired = validate_success(api.get_methodology_version(m1["id"], admin_headers))
    assert retired["status"] == "RETIRED"
    assert_instant(retired["retired_at"], "2026-09-01T00:00:00Z", "retired_at")
    assert_instant(
        retired["effective_until"], "2026-10-01T00:00:00Z", "effective_until"
    )

    _grants, grant_meta = validate_paginated(
        api.list_transition_grants(
            admin_headers, params={"organization_id": organization["id"]}
        )
    )
    assert grant_meta["total_count"] == 0

    pinned = read_cycle(cycle["id"], analyst_headers)
    assert pinned["methodology_version_id"] == m1["id"]
    assert pinned["methodology_pin_locked"] is True

    scored = score_cycle(cycle["id"], analyst_headers)
    assert_score(scored["weighted_sum_provisional"], 84.63, "weighted_sum_provisional")
    assert_score(
        scored["provisional_composite_score"], 83.13, "provisional_composite_score"
    )
    assert scored["provisional_grade"] == "MEETS_STANDARDS"

    validate_error(
        api.create_rating_cycle(
            create_rating_cycle_payload(
                organization["id"],
                m1["id"],
                fiscal_year=2024,
                period_start="2024-01-01T00:00:00Z",
                period_end="2025-01-01T00:00:00Z",
            ),
            analyst_headers,
        ),
        "ERR_METHODOLOGY_NOT_ADOPTED",
        409,
    )

    published = walk_cycle_to_published(cycle["id"], analyst_headers=analyst_headers)
    assert published["status"] == "PUBLISHED"
    assert_score(published["weighted_sum_final"], 84.63, "weighted_sum_final")
    assert_score(published["final_composite_score"], 83.13, "final_composite_score")
    assert published["grade"] == "MEETS_STANDARDS"
    assert published["methodology_version_id"] == m1["id"]
    assert published["methodology_pin_locked"] is True

    records = read_publication_records(public_headers, rating_cycle_id=cycle["id"])
    assert len(records) == 1
    assert records[0]["methodology_version_label"] == "M1"
    assert_score(records[0]["published_score"], 83.13, "published_score")
    assert records[0]["published_grade"] == "MEETS_STANDARDS"
