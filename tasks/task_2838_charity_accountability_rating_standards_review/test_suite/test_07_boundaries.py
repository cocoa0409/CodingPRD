"""Two boundaries: an inclusive publication instant and an empty candidate pool."""
from test_helpers import (
    REVIEWER_USER_ID,
    assert_instant,
    assert_score,
    dimension_by_name,
    file_complaint,
    make_public_headers,
    publish_cycle,
    publish_payload,
    read_cycle,
    read_dimension_scores,
    read_organization,
    read_publication_records,
    resolve_complaint,
    set_clock,
    setup_cycle_in_org_review,
    setup_published_cycle,
    triage_complaint,
    validate_error,
)


def test_publication_one_second_before_the_correction_deadline_is_refused(
    api, reviewer_headers
):
    """The charity's 21-day window is not over at 23:59:59 on its last day, so the
    rating cannot be published one second early.

    PRD §3.9: "The logical clock must have reached `correction_deadline_at`, inclusively — a publication attempted at exactly that instant is admissible, which is the deliberate mirror image of the appeal window's strictly-before rule."

    Design: Difficulty/boundary_precision_check/publish_at_exact_correction_deadline_instant
    """
    scenario = setup_cycle_in_org_review()
    assert_instant(
        scenario["cycle"]["correction_deadline_at"],
        "2026-09-22T00:00:00Z",
        "correction_deadline_at",
    )
    set_clock("2026-09-21T23:59:59Z")

    response = api.publish_rating_cycle(
        scenario["cycle"]["id"],
        publish_payload(publishing_reviewer_note="one second early"),
        reviewer_headers,
    )
    validate_error(response, "ERR_CYCLE_NOT_PUBLISHABLE", 409)

    cycle = read_cycle(scenario["cycle"]["id"])
    assert cycle["status"] == "ORG_REVIEW"
    assert cycle["published_at"] is None


def test_publication_at_the_exact_deadline_instant_succeeds_and_stamps_that_instant(
    api, reviewer_headers
):
    """One second later the same call publishes, and the published instant is the
    deadline itself rather than anything derived from it.

    PRD §3.9: "Hop one computes the final score family — `weighted_sum_final`, `standards_penalty_points`, `final_composite_score` and `grade` under the final variant of the composite calculation — stamps `published_at` from the logical clock, records `publishing_reviewer_user_id` from the acting `X-User-ID`, moves the cycle to `PUBLISHED` and advances its `version` counter by one."

    Design: Difficulty/boundary_precision_check/publish_at_exact_correction_deadline_instant
    """
    scenario = setup_cycle_in_org_review()
    set_clock("2026-09-21T23:59:59Z")
    api.publish_rating_cycle(
        scenario["cycle"]["id"], publish_payload(), reviewer_headers
    )
    set_clock("2026-09-22T00:00:00Z")

    cycle = publish_cycle(
        scenario["cycle"]["id"], publishing_reviewer_note="window elapsed"
    )
    assert cycle["status"] == "PUBLISHED"
    assert_instant(cycle["published_at"], "2026-09-22T00:00:00Z", "published_at")
    assert_score(cycle["final_composite_score"], 83.13, "final_composite_score")
    assert cycle["grade"] == "MEETS_STANDARDS"
    assert cycle["publishing_reviewer_user_id"] == REVIEWER_USER_ID


def test_the_first_publication_writes_a_gap_free_ledger_row_that_notifies_only_the_charity(
    api, admin_headers
):
    """A charity's first published rating has nothing to compare against, so the ledger
    records no delta and the press is not told.

    PRD §3.9: "When `sequence_number` is 1, `previous_published_score` and `score_delta` are both null and `change_direction` is `FIRST_PUBLICATION`."

    PRD §3.9: "It populates `notified_recipient_kinds` as an ordered list that always begins with `RATED_ORGANIZATION` and appends `MEDIA` only when `change_direction` is not `FIRST_PUBLICATION` and the absolute value of `score_delta` is at least `10.00`."

    Design: Difficulty/boundary_precision_check/publish_at_exact_correction_deadline_instant
    """
    scenario = setup_published_cycle()
    records = read_publication_records(
        admin_headers, rating_cycle_id=scenario["cycle"]["id"]
    )

    assert len(records) == 1
    record = records[0]
    assert record["sequence_number"] == 1
    assert_score(record["published_score"], 83.13, "published_score")
    assert record["previous_published_score"] is None
    assert record["score_delta"] is None
    assert record["change_direction"] == "FIRST_PUBLICATION"
    assert record["notified_recipient_kinds"] == ["RATED_ORGANIZATION"]

    organization = read_organization(scenario["organization"]["id"])
    assert organization["published_cycle_count"] == 1
    assert_score(organization["latest_published_score"], 83.13, "latest_published_score")
    assert organization["trend_direction"] == "NOT_APPLICABLE"


def test_a_substantiated_complaint_with_no_open_cycle_to_punish_still_succeeds(
    api, analyst_headers
):
    """The charity's only rating is already published and therefore immune, so the
    finding is recorded against a null target instead of raising anything.

    PRD §3.8: "When that candidate set is empty the field stays null, hops two through four are simply skipped, and **no error is raised** — a substantiated complaint against a charity with no open cycle is recorded, counts toward future pattern scoring, and penalises nothing."

    PRD §3.8: "The base is the complainant's standing — `DONOR` 30 points, `BENEFICIARY` 25, `EMPLOYEE` 35, `ANONYMOUS` 10 — plus the category — `MISUSE_OF_FUNDS` 30, `GOVERNANCE` 25, `SOLICITATION_PRACTICE` 20, `TRANSPARENCY` 15, `OTHER` 5 — plus 8 points for each corroborating document, counting at most 3 of them, so documentary support contributes at most 24 points however many files arrive."

    Design: Difficulty/boundary_precision_check/empty_open_cycle_pool_leaves_penalty_target_null
    """
    scenario = setup_published_cycle()
    complaint = file_complaint(
        scenario["organization"]["id"],
        headers=make_public_headers("donor-1"),
        complainant_kind="DONOR",
        category="MISUSE_OF_FUNDS",
        narrative="no receipts were ever provided for the appeal I funded",
    )
    assert complaint["corroborating_document_count"] == 0

    triaged = triage_complaint(complaint["id"], "INVESTIGATE")
    assert_score(triaged["credibility_score"], 60.00, "intake credibility_score")

    resolved = resolve_complaint(
        complaint["id"],
        "SUBSTANTIATED",
        penalty_points=5,
        finding_note="the organization could not evidence the program spend",
    )
    assert resolved["status"] == "SUBSTANTIATED"
    assert_score(resolved["credibility_score"], 70.00, "investigated credibility_score")
    assert resolved["credibility_variant"] == "INVESTIGATED"
    assert resolved["severity_tier"] == "MEDIUM"
    assert resolved["penalty_points_applied"] == 5
    assert resolved["penalized_rating_cycle_id"] is None


def test_the_published_rating_and_its_accountability_row_are_left_untouched(
    api, analyst_headers, admin_headers
):
    """Five penalty points are recorded on the complaint and nowhere else: the
    published score, its accountability row and the ledger all stand.

    PRD §3.9: "One further consequence is silent but material: because the cycle is now `PUBLISHED` it leaves the complaint penalty-target candidate pool, so a substantiated complaint arriving afterwards selects a different open cycle, or none at all."

    PRD §3.3: "`substantiated_complaint_count` is the number of complaints against this organization whose `status` is `SUBSTANTIATED`, and starts at 0."

    Design: Difficulty/boundary_precision_check/empty_open_cycle_pool_leaves_penalty_target_null
    """
    scenario = setup_published_cycle()
    complaint = file_complaint(
        scenario["organization"]["id"], headers=make_public_headers("donor-1")
    )
    triage_complaint(complaint["id"], "INVESTIGATE")
    resolve_complaint(complaint["id"], "SUBSTANTIATED", penalty_points=5)

    cycle = read_cycle(scenario["cycle"]["id"])
    assert cycle["status"] == "PUBLISHED"
    assert cycle["accountability_penalty_points"] == 0
    assert_score(cycle["final_composite_score"], 83.13, "final_composite_score")
    assert cycle["grade"] == "MEETS_STANDARDS"

    accountability = dimension_by_name(
        read_dimension_scores(cycle["id"], analyst_headers), "ACCOUNTABILITY"
    )
    assert accountability["penalty_points"] == 0
    assert accountability["raw_points"] == 21
    assert_score(accountability["normalized_score"], 87.50, "ACCOUNTABILITY normalized_score")
    assert accountability["status"] == "COMPUTED"

    organization = read_organization(scenario["organization"]["id"])
    assert_score(organization["latest_published_score"], 83.13, "latest_published_score")
    assert organization["substantiated_complaint_count"] == 1
    records = read_publication_records(admin_headers, rating_cycle_id=cycle["id"])
    assert len(records) == 1
    assert_score(records[0]["published_score"], 83.13, "published_score")
