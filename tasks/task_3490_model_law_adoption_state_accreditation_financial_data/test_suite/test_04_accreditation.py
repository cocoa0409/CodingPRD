"""Accreditation reviews: desk vs onsite scoring, rotation/overlap/gap gates,
the fail-and-reinstate standing cycle, and version bookkeeping."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_score1_equals,
    assert_state,
    factories,
    fixtures,
    make_review_team_lead_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

STAFF = TEST_USERS["association_staff_headers"]

FIRST_PERIOD = ("2026-01-01T00:00:00Z", "2026-06-30T00:00:00Z")


class TestAccreditation:
    def test_desk_vs_onsite_divergence(self, api):
        """PRD §3.3: "its `desk_score` is computed immediately: one hundred times `self_assessment_compliant` divided by `self_assessment_total`, rounded half-up to one decimal place."
        PRD §3.3: "The desk score plays no part in the outcome; a state can look compliant on paper and fail on site — a desk picture of 18 out of 20 scores 90.0, while an on-site result of 12 out of 20 scores 60.0 and proposes `FAIL`."

        Design: Difficulty/dual_variant_calc/accreditation_desk_vs_onsite_divergence
        """
        state = fixtures.create_state(api, code="CA")
        review = fixtures.create_review(
            api, state["id"],
            period_start=FIRST_PERIOD[0], period_end=FIRST_PERIOD[1],
            team_lead_id="lead-1",
            self_assessment_compliant=18, self_assessment_total=20,
        )
        assert_score1_equals(review["desk_score"], 90.0, "desk_score")
        assert review["status"] == "SCHEDULED"
        issued = fixtures.issue_findings(
            api, review["id"], 12, 20, team_lead_id="lead-1"
        )
        assert_score1_equals(issued["onsite_score"], 60.0, "onsite_score")
        assert issued["proposed_outcome"] == "FAIL", (
            "the onsite variant alone decides the outcome, even with desk 90.0"
        )
        assert issued["status"] == "FINDINGS_ISSUED"

    def test_state_fail_reinstate_cycle(self, api):
        """PRD §3.3: "When it is `FAIL`, the review closes as `FINAL_FAIL` and the state's `consecutive_fail_count` increases by one: a count that becomes 1 moves the state from `ACCREDITED` to `PROBATION`; a count that becomes 2 moves a state on `PROBATION` to `SUSPENDED`; and a state already `SUSPENDED` stays `SUSPENDED` while its count keeps climbing."
        PRD §3.3: "When it is `PASS`, the review closes as `FINAL_PASS` and the state's standing is restored: `accreditation_status` becomes `ACCREDITED` and `consecutive_fail_count` resets to 0, whether the state entered the review `ACCREDITED`, on `PROBATION`, or `SUSPENDED` — the last is the reinstatement loop."

        Design: Difficulty/non_linear_state_machine/state_accreditation_fail_reinstate_cycle
        """
        state = fixtures.create_state(api, code="CA")
        fixtures.run_review(
            api, state["id"], FIRST_PERIOD[0], FIRST_PERIOD[1],
            team_lead_id="lead-1", findings_compliant=10, findings_total=20,
        )
        state = fixtures.read_state(api, state["id"])
        assert state["accreditation_status"] == "PROBATION"
        assert state["consecutive_fail_count"] == 1
        fixtures.run_review(
            api, state["id"], "2026-12-27T00:00:00Z", "2027-06-30T00:00:00Z",
            team_lead_id="lead-2", findings_compliant=5, findings_total=20,
        )
        state = fixtures.read_state(api, state["id"])
        assert state["accreditation_status"] == "SUSPENDED"
        assert state["consecutive_fail_count"] == 2
        fixtures.run_review(
            api, state["id"], "2027-12-27T00:00:00Z", "2028-06-30T00:00:00Z",
            team_lead_id="lead-1", findings_compliant=20, findings_total=20,
        )
        state = fixtures.read_state(api, state["id"])
        assert state["accreditation_status"] == "ACCREDITED", (
            "the reinstatement loop closes on FINAL_PASS"
        )
        assert state["consecutive_fail_count"] == 0

    def test_rotation_beats_temporal_overlap(self, api):
        """PRD §3.3: "Beyond shape, three checks apply in this order: first, reviewer rotation — the proposed `team_lead_id` must differ from the `team_lead_id` of the same state's most recent `FINAL_PASS` or `FINAL_FAIL` review, otherwise `ERR_REVIEWER_ROTATION_REQUIRED` (422); second, the new period must not intersect any existing review period of the same state, where closed intervals that merely touch still count as overlapping (`ERR_REVIEW_WINDOW_OVERLAP`, 409); third, the gap between the new `period_start` and the most recent prior `period_end` of that state must be at least 180 days (`ERR_REVIEW_GAP_TOO_SHORT`, 422)."

        Design: Difficulty/priority_pair_validation_conflict/review_create_rotation_beats_temporal_overlap
        """
        state = fixtures.create_state(api, code="CA")
        fixtures.run_review(
            api, state["id"], FIRST_PERIOD[0], FIRST_PERIOD[1],
            team_lead_id="lead-1", findings_compliant=20, findings_total=20,
        )
        # Same lead as the most recent FINAL review AND an overlapping period;
        # rotation is checked first.
        resp = api.create_review(
            factories.review_payload(
                state["id"],
                period_start="2026-03-01T00:00:00Z",
                period_end="2026-09-01T00:00:00Z",
                team_lead_id="lead-1",
            ),
            STAFF,
        )
        validate_error(resp, ApiErrorId.ERR_REVIEWER_ROTATION_REQUIRED)

    def test_review_period_closed_interval_min_gap(self, api):
        """PRD §3.3: "second, the new period must not intersect any existing review period of the same state, where closed intervals that merely touch still count as overlapping (`ERR_REVIEW_WINDOW_OVERLAP`, 409); third, the gap between the new `period_start` and the most recent prior `period_end` of that state must be at least 180 days (`ERR_REVIEW_GAP_TOO_SHORT`, 422)."
        PRD §3.3: "with a `period_start` and `period_end` forming a closed interval — both boundary days are inside the period"

        Design: Difficulty/resource_temporal_overlap/review_period_closed_interval_min_gap
        """
        state = fixtures.create_state(api, code="CA")
        fixtures.run_review(
            api, state["id"], FIRST_PERIOD[0], FIRST_PERIOD[1],
            team_lead_id="lead-1", findings_compliant=20, findings_total=20,
        )
        # Closed intervals: starting exactly on the prior period_end overlaps.
        resp = api.create_review(
            factories.review_payload(
                state["id"],
                period_start="2026-06-30T00:00:00Z",
                period_end="2026-12-31T00:00:00Z",
                team_lead_id="lead-2",
            ),
            STAFF,
        )
        validate_error(resp, ApiErrorId.ERR_REVIEW_WINDOW_OVERLAP)
        # 179 days after the prior period_end: under the 180-day gap.
        resp = api.create_review(
            factories.review_payload(
                state["id"],
                period_start="2026-12-26T00:00:00Z",
                period_end="2027-06-30T00:00:00Z",
                team_lead_id="lead-2",
            ),
            STAFF,
        )
        validate_error(resp, ApiErrorId.ERR_REVIEW_GAP_TOO_SHORT)
        # Exactly 180 days after the prior period_end: legal.
        review = fixtures.create_review(
            api, state["id"],
            period_start="2026-12-27T00:00:00Z",
            period_end="2027-06-30T00:00:00Z",
            team_lead_id="lead-2",
        )
        assert review["status"] == "SCHEDULED"

    def test_state_creation_defaults(self, api):
        """PRD §3.2: "A new state starts `ACCREDITED`, with `consecutive_fail_count` 0 and `core_act_coverage_pct` 100.0."
        PRD §3.2: "When no published core act exists the coverage reads 100.0"

        Design: Corner/entities/state_creation_defaults
        """
        resp = api.create_state(
            factories.state_payload(code="CA", name="California"), STAFF
        )
        data = validate_success(resp, 201)
        assert_state(data)
        assert data["accreditation_status"] == "ACCREDITED"
        assert data["consecutive_fail_count"] == 0
        assert_score1_equals(
            data["core_act_coverage_pct"], 100.0, "coverage with no core acts"
        )

    def test_state_create_system_fields_input_ignored(self, api):
        """PRD §2.4: "Every resource in this API — model acts, exposure drafts, ballots, states, adoptions, reviews, insurers, filings, RBC reports, producers, licenses, market conduct calls, responses, and valuation standards — carries four common properties: `id`, a server-minted UUID with no type prefix; `created_at` and `updated_at`, ISO 8601 UTC timestamps rendered with three fractional digits; and `version`, an integer that increments by exactly one on every mutation of the resource"

        Design: Corner/entities/state_create_system_fields_input_ignored
        """
        supplied_id = "00000000-0000-4000-8000-000000000000"
        resp = api.create_state(
            factories.state_payload(
                code="CA", name="California", id=supplied_id, version=99
            ),
            STAFF,
        )
        data = validate_success(resp, 201)
        assert_state(data)
        assert data["id"] != supplied_id, "the server mints its own id"
        assert data["version"] != 99, (
            "the server-managed version ignores the client-supplied value"
        )

    def test_review_state_errors(self, api):
        """PRD §3.3: "Finalization belongs to `AssociationStaff` and requires the review to be in `FINDINGS_ISSUED` (`ERR_REVIEW_NOT_FINDINGS_ISSUED`, 409)."
        PRD §3.3: "Issuing findings is the `ReviewTeamLead`'s exclusive act, and only while the review is `SCHEDULED` — otherwise `ERR_REVIEW_NOT_SCHEDULED` (409)"

        Design: Corner/state_machines/review_state_errors
        """
        state = fixtures.create_state(api, code="CA")
        review = fixtures.create_review(
            api, state["id"],
            period_start=FIRST_PERIOD[0], period_end=FIRST_PERIOD[1],
            team_lead_id="lead-1",
        )
        resp = api.finalize_review(review["id"], STAFF)
        validate_error(resp, ApiErrorId.ERR_REVIEW_NOT_FINDINGS_ISSUED)
        issued = fixtures.issue_findings(
            api, review["id"], 18, 20, team_lead_id="lead-1"
        )
        assert issued["status"] == "FINDINGS_ISSUED"
        resp = api.issue_findings(
            review["id"], factories.findings_payload(18, 20),
            make_review_team_lead_headers("lead-1"),
        )
        validate_error(resp, ApiErrorId.ERR_REVIEW_NOT_SCHEDULED)

    def test_accreditation_pass_threshold_inclusive(self, api):
        """PRD §3.3: "`proposed_outcome` is derived from it alone: `PASS` when the onsite score is at least 75.0, otherwise `FAIL`."
        PRD §3.3: "When it is `PASS`, the review closes as `FINAL_PASS` and the state's standing is restored: `accreditation_status` becomes `ACCREDITED` and `consecutive_fail_count` resets to 0"

        Design: Corner/calculations/accreditation_pass_threshold_inclusive
        """
        state = fixtures.create_state(api, code="CA")
        review = fixtures.create_review(
            api, state["id"],
            period_start=FIRST_PERIOD[0], period_end=FIRST_PERIOD[1],
            team_lead_id="lead-1",
        )
        issued = fixtures.issue_findings(
            api, review["id"], 15, 20, team_lead_id="lead-1"
        )
        assert_score1_equals(issued["onsite_score"], 75.0, "onsite_score")
        assert issued["proposed_outcome"] == "PASS", "75.0 meets the bar inclusively"
        final = fixtures.finalize_review(api, review["id"])
        assert final["status"] == "FINAL_PASS"
        state = fixtures.read_state(api, state["id"])
        assert state["accreditation_status"] == "ACCREDITED"
        assert state["consecutive_fail_count"] == 0

    def test_version_increments_on_mutation(self, api):
        """PRD §2.4: "`version`, an integer that increments by exactly one on every mutation of the resource"
        PRD §3.3: "Either way the review's `version` increments, and the state's `version` increments with every standing change."

        Design: Corner/cross_cutting_layers/version_increments_on_mutation
        """
        state = fixtures.create_state(api, code="CA")
        version_at_create = state["version"]
        fixtures.run_review(
            api, state["id"], FIRST_PERIOD[0], FIRST_PERIOD[1],
            team_lead_id="lead-1", findings_compliant=10, findings_total=20,
        )
        after_fail = fixtures.read_state(api, state["id"])
        assert after_fail["accreditation_status"] == "PROBATION"
        assert after_fail["version"] == version_at_create + 1, (
            "the finalize cascade is exactly one state mutation"
        )
        start, end = fixtures.next_review_period(FIRST_PERIOD[1])
        fixtures.run_review(
            api, state["id"], start, end,
            team_lead_id="lead-2", findings_compliant=18, findings_total=20,
        )
        after_pass = fixtures.read_state(api, state["id"])
        assert after_pass["accreditation_status"] == "ACCREDITED"
        assert after_pass["version"] == version_at_create + 2

    def test_rbac_review_findings_wrong_lead_forbidden(self, api):
        """PRD §3.3: "a header that fails to match the stored `team_lead_id` fails earlier with `ERR_FORBIDDEN`."
        PRD §2.1: "The server records it as `team_lead_id` on the `AccreditationReview` at scheduling time and compares the header against that stored value when findings are issued"

        Design: Corner/rbac/rbac_review_findings_wrong_lead_forbidden
        """
        state = fixtures.create_state(api, code="CA")
        review = fixtures.create_review(
            api, state["id"],
            period_start=FIRST_PERIOD[0], period_end=FIRST_PERIOD[1],
            team_lead_id="lead-1",
        )
        resp = api.issue_findings(
            review["id"], factories.findings_payload(10, 20),
            make_review_team_lead_headers("lead-2"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        reviews, _meta = validate_paginated(api.list_reviews(state["id"], STAFF))
        assert len(reviews) == 1
        assert reviews[0]["status"] == "SCHEDULED"
