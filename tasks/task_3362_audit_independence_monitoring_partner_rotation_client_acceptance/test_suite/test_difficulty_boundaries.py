"""Difficulty claims about values sitting exactly on a threshold."""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    fixtures,
    get_acceptance_data,
    get_client_data,
    get_engagement_data,
    get_review_data,
    get_service_data,
    validate_error,
)


class TestApprovalRiskBandBoundary:
    """The approval band is a strict upper bound at 70."""

    def test_combined_score_of_seventy_blocks_approval(self, api):
        """PRD §3.2: "An `APPROVE` decision on a submitted evaluation requires
        the clamped combined risk score to be below 70 and requires that no
        integrity assessment of `CRITICAL` severity remain unresolved".

        Design: Difficulty/boundary_precision_check/risk_score_seventy_blocks_approval_sixty_nine_allows
        """
        world = fixtures.scenario_risk_band_boundary(api)
        acceptance = get_acceptance_data(api, world["acceptance_a"]["id"])
        assert acceptance["combined_risk_score"] == pytest.approx(70.0)

        response = fixtures.decide_acceptance(api, world["acceptance_a"]["id"], "APPROVE", "band edge")
        validate_error(response, ApiErrorId.ERR_ACCEPTANCE_CONDITIONS_UNMET)

        engagement = get_engagement_data(api, world["engagement_a"]["id"])
        assert engagement["status"] == "ACCEPTANCE_PENDING"

    def test_combined_score_of_sixty_nine_is_approved(self, api):
        """PRD §3.2: "on success `decided_at` is stamped from the logical clock,
        the governing engagement becomes `ACTIVE` with the evaluation's
        `combined_risk_score` and `risk_tier` copied onto it, and the client
        becomes `ACTIVE`."

        Design: Difficulty/boundary_precision_check/risk_score_seventy_blocks_approval_sixty_nine_allows
        """
        world = fixtures.scenario_risk_band_boundary(api)
        acceptance = get_acceptance_data(api, world["acceptance_b"]["id"])
        assert acceptance["combined_risk_score"] == pytest.approx(69.0)

        fixtures.decide_acceptance_ok(api, world["acceptance_b"]["id"], "APPROVE", "band edge")

        decided = get_acceptance_data(api, world["acceptance_b"]["id"])
        engagement = get_engagement_data(api, world["engagement_b"]["id"])
        client = get_client_data(api, world["at_sixty_nine"]["id"])
        assert decided["status"] == "APPROVED"
        assert engagement["status"] == "ACTIVE"
        assert engagement["combined_risk_score"] == pytest.approx(69.0)
        assert client["status"] == "ACTIVE"


class TestFeeCapBoundary:
    """The cap comparison is inclusive at exactly the ceiling."""

    def test_pool_landing_exactly_on_the_cap_is_approved(self, api):
        """PRD §3.6: "the candidate's whole-dollar-rounded fee added to the
        client's current `naf_approved_fee_cents` must not exceed the client's
        `naf_annual_cap_cents`."

        Design: Difficulty/boundary_precision_check/naf_cap_exact_equality_allows_next_cent_rejected
        """
        world = fixtures.scenario_naf_cap_boundary(api)
        assert world["client"]["naf_approved_fee_cents"] == 200000

        fixtures.service_transition_ok(
            api, world["candidate"]["id"], "APPROVE", committee_resolution_ref="AC-2027-0003"
        )

        approved = get_service_data(api, world["candidate"]["id"])
        client = get_client_data(api, world["client"]["id"])
        assert approved["status"] == "APPROVED"
        assert approved["approved_fee_cents"] == 800000
        assert client["naf_approved_fee_cents"] == 1000000
        assert client["naf_approved_fee_cents"] == client["naf_annual_cap_cents"]

    def test_the_next_cent_over_the_cap_is_rejected_at_submission(self, api):
        """PRD §3.6: "Submission also runs the fee-cap test described below as
        a pre-check, so a service that plainly cannot be admitted under the
        client's annual ceiling is stopped before the committee spends time on
        it."

        Design: Difficulty/boundary_precision_check/naf_cap_exact_equality_allows_next_cent_rejected
        """
        world = fixtures.scenario_naf_cap_boundary(api)
        fixtures.service_transition_ok(
            api, world["candidate"]["id"], "APPROVE", committee_resolution_ref="AC-2027-0003"
        )

        over_the_line = fixtures.create_service(
            api, world["client"]["id"], service_category="OTHER", fee_cents=100
        )
        response = fixtures.service_transition(
            api, over_the_line["id"], "SUBMIT_FOR_APPROVAL"
        )
        validate_error(response, ApiErrorId.ERR_NAF_CAP_EXCEEDED)

        still_draft = get_service_data(api, over_the_line["id"])
        assert still_draft["status"] == "DRAFT"


class TestInspectionWindowBoundary:
    """The deficiency halving threshold is inclusive at five."""

    def test_four_deficiencies_keep_the_full_response_window(self, api):
        """PRD §3.8: "A regulatory inspection takes its base window from the
        inspection body: 30 days for `PCAOB`, 21 days for `SEC`, 45 days for
        `LOCAL_REGULATOR` and 15 days for `INTERNAL_QC`."

        Design: Difficulty/boundary_precision_check/review_response_window_halves_at_five_deficiencies
        """
        world = fixtures.scenario_inspection_windows(api)
        review = fixtures.create_review_ok(
            api, world["engagement"]["id"], world["first_reviewer"]["id"],
            review_type="REGULATORY_INSPECTION", inspection_body="PCAOB",
            received_on="2026-01-01T00:00:00Z", due_on="2026-03-01T00:00:00Z",
            deficiency_count=4,
        )
        stored = get_review_data(api, review["id"])
        assert_same_instant(stored["response_due_on"], "2026-01-31T00:00:00Z")

    def test_five_deficiencies_halve_the_response_window(self, api):
        """PRD §3.8: "That window is then halved when the review carries five
        or more deficiencies — the boundary is inclusive, so exactly 5
        deficiencies halves the window, and the halved figure is rounded
        half-up to a whole day".

        Design: Difficulty/boundary_precision_check/review_response_window_halves_at_five_deficiencies
        """
        world = fixtures.scenario_inspection_windows(api)
        review = fixtures.create_review_ok(
            api, world["engagement"]["id"], world["second_reviewer"]["id"],
            review_type="REGULATORY_INSPECTION", inspection_body="PCAOB",
            received_on="2026-01-01T00:00:00Z", due_on="2026-03-01T00:00:00Z",
            deficiency_count=5,
        )
        stored = get_review_data(api, review["id"])
        assert_same_instant(stored["response_due_on"], "2026-01-16T00:00:00Z")
