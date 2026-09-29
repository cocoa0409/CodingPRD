"""Endpoints whose whole job is to aggregate, to associate or to report."""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as W
from test_helpers import (
    make_executive_editor_headers,
    make_legal_counsel_headers,
    make_reporter_headers,
)


class TestStandardsSummaryAggregation:
    """``GET /standards-desk/newsrooms/{id}/standards-summary``."""

    def test_the_summary_totals_the_whole_desk_at_the_current_instant(
        self, api, public_editor_headers
    ):
        """Two trained journalists and one open complaint on each of two stories.

        PRD §3.1: "There is also a computed summary read of the newsroom's
        position at the current logical instant, returning `standards_posture`,
        `open_high_severity_count`, `training_compliance_index`, a
        `published_story_count` of the newsroom's stories that have reached
        publication, an `open_correction_request_count` aggregating the newsroom's
        unresolved complaints, and a `breached_correction_count` giving the number
        of those complaints whose response deadline has already passed as measured
        against the logical clock." PRD §3.8 fixes the cohort arithmetic: "add
        those already-rounded ratios together, divide by the number of journalists
        in the cohort, multiply by 100, and round half up to 2 decimal places
        again." PRD §2.9's pool starts empty because PRD §3.1 opens a newsroom
        with "`standards_posture` `OPEN`, `open_high_severity_count` 0".

        Design: Corner/endpoints/standards_summary_aggregates_open_corrections_across_the_whole_desk
        """
        newsroom = W.bootstrap_newsroom(api)
        exec_editor = W.bootstrap_executive_editor(api, newsroom["id"])
        exec_headers = make_executive_editor_headers(exec_editor["id"])
        reporter = W.add_journalist(
            api,
            newsroom["id"],
            "Rae Lindqvist",
            "rae@ledger.test",
            C.TITLE_REPORTER,
            exec_headers,
        )
        reporter_headers = make_reporter_headers(reporter["id"])

        get_success_data(
            api.create_training_record(
                F.training_record_payload(
                    exec_editor["id"], C.MODULE_SOURCING, "CS-2025-01"
                ),
                exec_headers,
            )
        )
        get_success_data(
            api.create_training_record(
                F.training_record_payload(
                    reporter["id"], C.MODULE_SOURCING, "CS-2025-02"
                ),
                reporter_headers,
            )
        )

        for headline, email, claim, category, reach in (
            (
                "Permits, part one",
                "reader1@example.test",
                "The date in the second paragraph is wrong.",
                C.CATEGORY_FACTUAL,
                800,
            ),
            (
                "Permits, part two",
                "reader2@example.test",
                "The quotation is truncated.",
                C.CATEGORY_QUOTE,
                900,
            ),
        ):
            story = get_success_data(
                api.create_story(
                    F.story_payload(newsroom["id"], reporter["id"], headline),
                    reporter_headers,
                )
            )
            get_success_data(
                api.create_correction_request(
                    F.correction_request_payload(
                        story["id"],
                        submitter_type=C.SUBMITTER_READER,
                        submitter_email=email,
                        claim_text=claim,
                        claimed_error_category=category,
                        reader_reported_reach=reach,
                        subject_named=False,
                    ),
                    public_editor_headers,
                )
            )

        summary = get_success_data(
            api.get_standards_summary(newsroom["id"], public_editor_headers)
        )

        A.assert_decimal_equals(summary["training_compliance_index"], 100.00)
        assert summary["open_correction_request_count"] == 2
        assert summary["published_story_count"] == 0
        assert summary["breached_correction_count"] == 0
        assert summary["standards_posture"] == C.POSTURE_OPEN
        assert summary["open_high_severity_count"] == 0


class TestReviewAssignmentAssociation:
    """``POST /standards-desk/review-assignments`` as an association record."""

    def test_a_booked_slot_names_both_ends_and_commits_its_minutes(self, api, desk):
        """The record links a round to a reviewer and moves the ledger.

        PRD §3.4: "A `LegalCounsel` or `StandardsEditor` books a slot against an
        open round by naming the `review_id`, the `reviewer_id` whose minutes it
        will occupy, an inclusive `starts_at` and an inclusive `ends_at` — both ISO
        8601 UTC instants — and the `expected_reviewer_version` token from §2.8.
        The booking is created in `status` `SCHEDULED`, and the server derives
        `duration_minutes` as the number of whole minutes between the two
        instants". PRD §3.4 then commits them: "On acceptance, `reserved_minutes`
        rises and `available_minutes` falls by the slot's duration, and the
        reviewer's `version` is incremented by one", and the record can be found
        again because bookings "can be read individually or listed with filters on
        `review_id`, `reviewer_id` and `status`".

        Design: Corner/endpoints/review_assignment_links_review_and_reviewer_and_moves_the_minute_ledger
        """
        reviewer = W.add_legal_reviewer(
            api, desk, full_name="Iris Vance", weekly_capacity_minutes=480
        )
        story = W.open_story(api, desk, "A story for the lawyers")
        review = W.submit_review(api, desk, story["id"], high_risk_declared=True)

        response = api.create_assignment(
            F.assignment_payload(
                review["id"],
                reviewer["id"],
                "2026-08-03T09:00:00Z",
                "2026-08-03T10:00:00Z",
                reviewer["version"],
            ),
            make_legal_counsel_headers(reviewer["id"]),
        )

        assignment = validate_success(response, 201)

        assert assignment["review_id"] == review["id"]
        assert assignment["reviewer_id"] == reviewer["id"]
        assert assignment["duration_minutes"] == 60
        assert assignment["status"] == C.ASSIGNMENT_SCHEDULED
        assert assignment["cancellation_reason"] is None

        committed = W.read_reviewer(api, desk, reviewer["id"])
        A.assert_minute_ledger(committed, 60, 420)

        A.assert_total_count(
            api.list_assignments(desk.sed_headers, {"review_id": review["id"]}), 1
        )
        A.assert_total_count(
            api.list_assignments(
                desk.sed_headers,
                {"reviewer_id": reviewer["id"], "status": C.ASSIGNMENT_SCHEDULED},
            ),
            1,
        )


class TestLogicalClockEndpoint:
    """``POST /standards-desk/_clock/set_current_utc`` and its bespoke body."""

    def test_the_clock_reports_its_new_reading_and_dates_what_follows(
        self, api, desk
    ):
        """An action endpoint that returns an instant rather than an entity.

        PRD §2.5: "An `ExecutiveEditor` may move the clock forward or backward
        through an administrative test-driving capability that accepts a single
        field, `to_iso8601`, carrying the target instant. The response body is the
        object `{ current_utc: string }` reporting the clock's new reading." PRD
        §3.6 dates the next filing from it: the deadline "a whole number of hours,
        is added to the logical clock's current reading to give
        `response_due_at`", the band being "`MINOR` when raw is 6 or more but below
        11" whose factor is "1.0 for `MINOR`", with the `READER` bump adding
        nothing.

        Design: Corner/endpoints/clock_endpoint_returns_the_instant_it_set
        """
        story = W.open_story(api, desk, "Filed after the clock moved")

        moved = W.set_clock(api, desk, "2026-08-05T12:00:00Z")

        A.assert_instant_equals(moved["current_utc"], "2026-08-05T12:00:00.000Z")

        request = W.file_correction(
            api,
            desk,
            story["id"],
            submitter_type=C.SUBMITTER_READER,
            submitter_email="reader@example.test",
            claim_text="The date in the second paragraph is wrong.",
            claimed_error_category=C.CATEGORY_FACTUAL,
            reader_reported_reach=800,
            subject_named=False,
        )

        assert request["provisional_severity_band"] == C.BAND_MINOR
        A.assert_instant_equals(
            request["response_due_at"], "2026-08-08T12:00:00.000Z"
        )


class TestStoryListingFilters:
    """``GET /standards-desk/stories`` with two filters at once."""

    def test_the_draft_and_high_tier_filters_compose(self, api, desk):
        """Three drafts, three tiers, one match.

        PRD §3.5: stories may be "listed with filters on `newsroom_id`,
        `lead_journalist_id`, `publication_status`, `standards_status` and
        `risk_tier`." PRD §3.2 bands each of them: `risk_tier` "is `HIGH` when
        `risk_index_estimate` is 40.00 or greater, `ELEVATED` when it is 20.00 or
        greater but below 40.00, and `STANDARD` otherwise", from an estimate that
        adds "three points for every potentially defamatory assertion counted in
        `defamation_claim_count` plus two points for every identifiable private
        individual counted in `privacy_subject_count`". PRD §2.3 supplies the
        window: "`total_count` is the size of the full filtered set before paging
        and `has_more` indicates whether records remain beyond the current
        window."

        Design: Corner/endpoints/story_list_filters_by_publication_status_and_risk_tier_together
        """
        standard = W.open_story(api, desk, "Low risk")
        elevated = W.open_story(
            api,
            desk,
            "Elevated risk",
            defamation_claim_count=4,
            privacy_subject_count=4,
        )
        high = W.open_story(
            api,
            desk,
            "High risk",
            defamation_claim_count=10,
            privacy_subject_count=5,
        )

        rows = A.assert_page(
            api.list_stories(
                desk.exec_headers,
                {
                    "newsroom_id": desk.newsroom_id,
                    "publication_status": C.PUB_DRAFT,
                    "risk_tier": C.TIER_HIGH,
                    "limit": 50,
                    "offset": 0,
                },
            ),
            total_count=1,
            has_more=False,
            row_count=1,
        )

        assert rows[0]["id"] == high["id"]
        A.assert_decimal_equals(rows[0]["risk_index_estimate"], 40.00)

        A.assert_risk_figures(
            W.read_story(api, desk, elevated["id"]),
            estimate=20.00,
            tier=C.TIER_ELEVATED,
        )
        A.assert_risk_figures(
            W.read_story(api, desk, standard["id"]), tier=C.TIER_STANDARD
        )
