"""Every cascade a write fires is already readable in the next request."""
from test_helpers import (
    CLOCK_CORRECTION_DEADLINE,
    assert_instant,
    assert_score,
    read_publication_records,
    score_cycle,
    setup_scored_cycle,
    validate_paginated,
    validate_success,
    walk_cycle_to_published,
)

# The figures the scoring response must already have stored, not merely computed
# for the body it returns.
MIRRORED_SCORE_FIELDS = [
    "status",
    "program_expense_ratio",
    "fundraising_efficiency",
    "months_of_reserve",
    "data_completeness_pct",
    "failed_standard_count",
    "weighted_sum_provisional",
    "provisional_composite_score",
    "provisional_grade",
    "weighted_sum_final",
    "final_composite_score",
    "grade",
    "standards_penalty_points",
    "version",
]


def test_every_cascade_is_readable_the_instant_its_own_response_returns(
    api, analyst_headers, public_headers
):
    """The scoring response and the read one call later agree field for field, and the
    publication ledger row, the organization roll-up and the computed trend are all
    correct to an unrelated public reader on the very first read after publication.

    PRD §3.5: "Scoring closes by writing everything at once: the four dimension rows are created on a first score, travelling `PENDING` → `COMPUTED`, or rewritten on a re-score; `program_expense_ratio`, `fundraising_efficiency` and `months_of_reserve` are stored; `failed_standard_count` is refreshed from the governance profile; `data_completeness_pct` is stored; both composite variants are evaluated, writing `weighted_sum_provisional`, `provisional_composite_score` and `provisional_grade` from the provisional variant and `weighted_sum_final`, `final_composite_score` and `grade` from the final one, with `standards_penalty_points` recording the **final** variant's penalty; and the cycle's `version` counter advances by one."

    PRD §3.9: "Hop one computes the final score family — `weighted_sum_final`, `standards_penalty_points`, `final_composite_score` and `grade` under the final variant of the composite calculation — stamps `published_at` from the logical clock, records `publishing_reviewer_user_id` from the acting `X-User-ID`, moves the cycle to `PUBLISHED` and advances its `version` counter by one."

    PRD §3.9: "Hop two, caused by the cycle reaching `PUBLISHED`, appends one row to the immutable publication ledger. It carries the `rating_cycle_id`, the `organization_id` denormalised for trend queries, and a `sequence_number` equal to the count of that organization's pre-existing publication records plus one, so numbering is 1-based and gap-free per organization."

    PRD §3.9: "It copies `published_score` from the cycle's `final_composite_score`, `published_grade` from its `grade`, `weighted_sum_final` and `standards_penalty_points` from the cycle's like-named fields, `methodology_version_label` from the `version_label` of the methodology version pinned on the cycle, and `published_at` from the cycle."

    PRD §3.9: "When `sequence_number` is 1, `previous_published_score` and `score_delta` are both null and `change_direction` is `FIRST_PUBLICATION`."

    PRD §3.9: "It then recomputes the organization's four publication roll-ups from the new row — `latest_published_score` and `latest_published_grade` from the row's `published_score` and `published_grade`, `published_cycle_count` from its `sequence_number`, and `trend_direction` as `NOT_APPLICABLE` on a first publication and otherwise `IMPROVED`, `DECLINED` or `UNCHANGED` by the sign of `score_delta`"

    PRD §3.9: "The ledger is the public face of the product and is readable by every role including `PublicUser`, either as a filtered list by `organization_id` or `rating_cycle_id` ordered by `sequence_number` ascending, or one row at a time."

    Design: Corner/consistency_model/every_cascade_is_readable_the_instant_its_own_response_returns
    """
    scenario = setup_scored_cycle(score=False)
    organization = scenario["organization"]
    cycle = scenario["cycle"]
    profile = scenario["governance_profile"]

    scored = score_cycle(cycle["id"], analyst_headers)
    mirrored = validate_success(api.get_rating_cycle(cycle["id"], analyst_headers))
    for field in MIRRORED_SCORE_FIELDS:
        assert mirrored[field] == scored[field], f"{field} was not stored as reported"

    assert scored["status"] == "SCORED"
    assert_score(
        scored["provisional_composite_score"], 83.13, "provisional_composite_score"
    )
    assert_score(scored["program_expense_ratio"], 0.7500, "program_expense_ratio")
    assert_score(scored["data_completeness_pct"], 100.00, "data_completeness_pct")
    assert scored["failed_standard_count"] == 1

    dimension_rows, dimension_meta = validate_paginated(
        api.list_dimension_scores(cycle["id"], analyst_headers)
    )
    assert dimension_meta["total_count"] == 4
    assert [row["status"] for row in dimension_rows] == ["COMPUTED"] * 4

    standard_rows, standard_meta = validate_paginated(
        api.list_standard_evaluations(profile["id"], analyst_headers)
    )
    assert standard_meta["total_count"] == 8
    assert all(row["id"] for row in standard_rows)

    published = walk_cycle_to_published(cycle["id"], analyst_headers=analyst_headers)
    assert published["status"] == "PUBLISHED"
    assert_score(published["final_composite_score"], 83.13, "final_composite_score")
    assert published["grade"] == "MEETS_STANDARDS"
    assert_instant(published["published_at"], CLOCK_CORRECTION_DEADLINE, "published_at")

    rolled_up = validate_success(
        api.get_organization(organization["id"], public_headers)
    )
    assert_score(rolled_up["latest_published_score"], 83.13, "latest_published_score")
    assert rolled_up["latest_published_grade"] == "MEETS_STANDARDS"
    assert rolled_up["published_cycle_count"] == 1
    assert rolled_up["trend_direction"] == "NOT_APPLICABLE"

    records = read_publication_records(
        public_headers, organization_id=organization["id"]
    )
    assert len(records) == 1
    assert_score(records[0]["published_score"], 83.13, "published_score")
    assert records[0]["sequence_number"] == 1
    assert records[0]["change_direction"] == "FIRST_PUBLICATION"
    assert records[0]["previous_published_score"] is None
    assert records[0]["score_delta"] is None
    assert_instant(records[0]["published_at"], CLOCK_CORRECTION_DEADLINE, "published_at")

    trend = validate_success(
        api.get_rating_trend(organization["id"], public_headers)
    )
    assert trend["latest_published_score"] == rolled_up["latest_published_score"]
    assert trend["published_cycle_count"] == rolled_up["published_cycle_count"]
    assert trend["latest_published_score"] == records[0]["published_score"]
    assert trend["trend_direction"] == "NOT_APPLICABLE"
