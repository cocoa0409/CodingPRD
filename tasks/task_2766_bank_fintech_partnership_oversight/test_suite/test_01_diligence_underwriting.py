"""Diligence underwriting: the composite blend, its two complaint-history
variants, the INFO_REQUESTED loop and the two ordered pass floors."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_diligence_review_payload,
    create_partner_payload,
    file_complaint,
    open_cycle,
    pass_diligence,
    read_partner,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import CO, PO


def _seed_email_complaints(partner_id, received_ats):
    for received_at in received_ats:
        file_complaint(
            partner_id,
            channel="EMAIL",
            category="FEES",
            severity="LOW",
            received_at=received_at,
            narrative="unexpected monthly fee",
        )


class TestComplaintHistoryVariants:
    def test_renewal_review_substitutes_the_live_complaint_rate_for_the_submitted_score(self):
        """For a `RENEWAL` review, the submitted `complaint_history_score` is still stored on
        the row but is **not used**: `effective_complaint_history_score` becomes 100 less one
        point for every 5 basis points of the partner's persisted `complaint_rate_bps`, with
        the basis-point quotient taken as a whole number by discarding any fraction, and the
        result floored at 0 so it never goes negative.

        Design: Difficulty/dual_variant_calc/renewal_variant_reunderwrites_composite_from_live_complaint_rate
        """
        open_cycle()
        partner = validate_success(
            api_client.create_partner(
                create_partner_payload(
                    legal_name="Aurora Wallet Inc",
                    business_model="DEPOSIT_WALLET",
                    funding_stage="SERIES_A",
                    months_runway=24,
                    disclosed_complaints_per_10k=12.50,
                    end_user_account_count=160,
                ),
                PO,
            ),
            expected_status=201,
        )
        pass_diligence(
            partner,
            business_model_score=91,
            funding_score=87,
            compliance_capability_score=89,
            complaint_history_score=100,
        )
        _seed_email_complaints(
            partner["id"],
            ["2026-07-10T00:00:00Z", "2026-07-11T00:00:00Z", "2026-07-12T00:00:00Z"],
        )
        partner = read_partner(partner["id"])
        assert partner["complaint_rate_bps"] == 188, (
            f"three complaints over 160 accounts is 187.5 bps rounded half up to 188, got "
            f"{partner['complaint_rate_bps']}"
        )

        renewal = validate_success(
            api_client.create_diligence_review(
                create_diligence_review_payload(
                    partner["id"],
                    partner["version"],
                    review_type="RENEWAL",
                    business_model_score=91,
                    funding_score=87,
                    compliance_capability_score=89,
                    complaint_history_score=100,
                ),
                PO,
            ),
            expected_status=201,
        )
        submitted = validate_success(
            api_client.submit_diligence_review(
                renewal["id"], {"submission_note": "annual renewal"}, PO
            )
        )

        assert submitted["complaint_history_score"] == 100, "the submitted score is still stored"
        assert submitted["effective_complaint_history_score"] == 63, (
            f"100 - floor(188/5) is 63, got {submitted['effective_complaint_history_score']}"
        )
        assert submitted["composite_score"] == 83.7, (
            f"expected 83.7 from the substituted history score, got {submitted['composite_score']}"
        )
        assert submitted["tier"] == "TIER_2", submitted["tier"]
        assert submitted["status"] == "SUBMITTED", submitted["status"]

    def test_initial_review_takes_the_submitted_complaint_history_score_verbatim(self):
        """For an `INITIAL` review, `effective_complaint_history_score` is the analyst's
        submitted `complaint_history_score` verbatim — the partner's self-disclosed history
        taken at face value.

        Design: Difficulty/dual_variant_calc/renewal_variant_reunderwrites_composite_from_live_complaint_rate
        """
        open_cycle()
        partner = validate_success(
            api_client.create_partner(
                create_partner_payload(
                    legal_name="Aurora Wallet Inc",
                    business_model="DEPOSIT_WALLET",
                    funding_stage="SERIES_A",
                    months_runway=24,
                    disclosed_complaints_per_10k=12.50,
                    end_user_account_count=160,
                ),
                PO,
            ),
            expected_status=201,
        )
        review, partner = pass_diligence(
            partner,
            business_model_score=91,
            funding_score=87,
            compliance_capability_score=89,
            complaint_history_score=100,
        )

        assert review["effective_complaint_history_score"] == 100, (
            "an INITIAL review consumes the submitted score unchanged"
        )
        assert review["composite_score"] == 91.1, (
            f"expected 91.1 from 91/87/89/100, got {review['composite_score']}"
        )
        assert review["tier"] == "TIER_1", review["tier"]
        assert partner["latest_composite_score"] == 91.1, partner["latest_composite_score"]
        assert partner["capability_tier"] == "TIER_1", partner["capability_tier"]
        assert partner["status"] == "DILIGENCE_PASSED", partner["status"]


class TestInfoRequestedLoop:
    def _setup_renewal_in_draft(self):
        open_cycle()
        partner = validate_success(
            api_client.create_partner(
                create_partner_payload(
                    legal_name="Coriolis Wallet Inc",
                    business_model="DEPOSIT_WALLET",
                    funding_stage="SERIES_A",
                    months_runway=20,
                    disclosed_complaints_per_10k=15.00,
                    end_user_account_count=160,
                ),
                PO,
            ),
            expected_status=201,
        )
        initial, partner = pass_diligence(
            partner,
            business_model_score=82,
            funding_score=80,
            compliance_capability_score=84,
            complaint_history_score=88,
        )
        _seed_email_complaints(
            partner["id"],
            ["2026-07-10T00:00:00Z", "2026-07-11T00:00:00Z", "2026-07-12T00:00:00Z"],
        )
        partner = read_partner(partner["id"])
        renewal = validate_success(
            api_client.create_diligence_review(
                create_diligence_review_payload(
                    partner["id"],
                    partner["version"],
                    review_type="RENEWAL",
                    business_model_score=82,
                    funding_score=80,
                    compliance_capability_score=84,
                    complaint_history_score=88,
                ),
                PO,
            ),
            expected_status=201,
        )
        return partner, initial, renewal

    def test_info_requested_round_trip_recomputes_the_composite_afresh(self):
        """From `INFO_REQUESTED` the officer resubmits, moving the file
        `INFO_REQUESTED → SUBMITTED` again; that resubmission requires the partner to be in
        `IN_DILIGENCE`, increments `revision_round` by 1 rather than setting it, clears
        `requested_info_items` back to an empty array, records the new `submitted_by_user_id`,
        and recomputes `effective_complaint_history_score`, `composite_score` and `tier` afresh.

        Design: Difficulty/non_linear_state_machine/diligence_info_requested_cycle_revisits_submitted_with_a_different_composite
        """
        partner, initial, renewal = self._setup_renewal_in_draft()

        round_1 = validate_success(
            api_client.submit_diligence_review(
                renewal["id"], {"submission_note": "renewal round 1"}, PO
            )
        )
        assert round_1["effective_complaint_history_score"] == 63, (
            f"188 bps gives 63, got {round_1['effective_complaint_history_score']}"
        )
        assert round_1["composite_score"] == 78.4, round_1["composite_score"]
        assert round_1["tier"] == "TIER_2", round_1["tier"]
        assert round_1["revision_round"] == 1, round_1["revision_round"]

        returned = validate_success(
            api_client.decide_diligence_review(
                renewal["id"],
                {
                    "outcome": "INFO_REQUESTED",
                    "requested_info_items": ["AUDITED_FINANCIALS", "COMPLAINT_LOG"],
                    "decision_note": "need more",
                },
                CO,
            )
        )
        assert returned["status"] == "INFO_REQUESTED", returned["status"]

        _seed_email_complaints(
            partner["id"],
            [
                "2026-07-13T00:00:00Z",
                "2026-07-14T00:00:00Z",
                "2026-07-15T00:00:00Z",
                "2026-07-16T00:00:00Z",
                "2026-07-17T00:00:00Z",
            ],
        )
        assert read_partner(partner["id"])["complaint_rate_bps"] == 500, (
            "eight complaints over 160 accounts is exactly 500 bps"
        )

        round_2 = validate_success(
            api_client.submit_diligence_review(
                renewal["id"], {"submission_note": "renewal round 2"}, PO
            )
        )
        assert round_2["effective_complaint_history_score"] == 0, (
            f"100 - floor(500/5) floors at 0, got {round_2['effective_complaint_history_score']}"
        )
        assert round_2["composite_score"] == 65.8, round_2["composite_score"]
        assert round_2["tier"] == "TIER_3", round_2["tier"]
        assert round_2["revision_round"] == 2, (
            f"revision_round increments rather than resets, got {round_2['revision_round']}"
        )
        assert round_2["requested_info_items"] == [], round_2["requested_info_items"]

    def test_passing_the_second_round_copies_the_lower_tier_onto_the_partner(self):
        """A successful pass advances the partner `IN_DILIGENCE → DILIGENCE_PASSED`, copies the
        file's `tier` onto the partner's `capability_tier` and the file's `composite_score` onto
        the partner's `latest_composite_score`, and increments the partner's `version` by 1.

        Design: Difficulty/non_linear_state_machine/diligence_info_requested_cycle_revisits_submitted_with_a_different_composite
        """
        partner, initial, renewal = self._setup_renewal_in_draft()
        assert initial["composite_score"] == 83.4, initial["composite_score"]

        validate_success(api_client.submit_diligence_review(renewal["id"], {}, PO))
        validate_success(
            api_client.decide_diligence_review(
                renewal["id"],
                {"outcome": "INFO_REQUESTED", "requested_info_items": ["COMPLAINT_LOG"]},
                CO,
            )
        )
        _seed_email_complaints(
            partner["id"],
            [
                "2026-07-13T00:00:00Z",
                "2026-07-14T00:00:00Z",
                "2026-07-15T00:00:00Z",
                "2026-07-16T00:00:00Z",
                "2026-07-17T00:00:00Z",
            ],
        )
        validate_success(api_client.submit_diligence_review(renewal["id"], {}, PO))
        passed = validate_success(
            api_client.decide_diligence_review(
                renewal["id"], {"outcome": "PASSED", "decision_note": "accepted at lower tier"}, CO
            )
        )

        assert passed["status"] == "PASSED", passed["status"]
        refreshed = read_partner(partner["id"])
        assert refreshed["capability_tier"] == "TIER_3", refreshed["capability_tier"]
        assert refreshed["latest_composite_score"] == 65.8, refreshed["latest_composite_score"]
        assert refreshed["status"] == "DILIGENCE_PASSED", refreshed["status"]
        assert refreshed["total_complaint_count"] == 8, refreshed["total_complaint_count"]


def _partner_with_submitted_review(legal_name, scores):
    partner = validate_success(
        api_client.create_partner(
            create_partner_payload(
                legal_name=legal_name,
                business_model="LENDING",
                funding_stage="SEED",
                months_runway=9,
                disclosed_complaints_per_10k=40.00,
                end_user_account_count=0,
            ),
            PO,
        ),
        expected_status=201,
    )
    review = validate_success(
        api_client.create_diligence_review(
            create_diligence_review_payload(
                partner["id"], partner["version"], review_type="INITIAL", **scores
            ),
            PO,
        ),
        expected_status=201,
    )
    review = validate_success(api_client.submit_diligence_review(review["id"], {}, PO))
    return partner, review


class TestOrderedPassFloors:
    def test_capability_floor_is_reported_when_both_diligence_floors_fail(self):
        """First, `compliance_capability_score` must be at least 60; below that the decision is
        refused with `ERR_COMPLIANCE_CAPABILITY_FLOOR` and the composite floor is never
        consulted.

        Design: Difficulty/priority_pair_validation_conflict/compliance_capability_floor_outranks_composite_floor_on_diligence_pass
        """
        open_cycle()
        partner, review = _partner_with_submitted_review(
            "Tallow Credit LLC",
            {
                "business_model_score": 60,
                "funding_score": 60,
                "compliance_capability_score": 59,
                "complaint_history_score": 35,
            },
        )
        assert review["composite_score"] == 54.7, review["composite_score"]
        assert review["tier"] == "UNRATED", review["tier"]

        response = api_client.decide_diligence_review(
            review["id"], {"outcome": "PASSED", "decision_note": "attempt A"}, CO
        )
        error = validate_error(response, ApiErrorId.ERR_COMPLIANCE_CAPABILITY_FLOOR)
        assert error["error_id"] != ApiErrorId.ERR_DILIGENCE_SCORE_BELOW_FLOOR, (
            "the composite floor must never be consulted once the capability floor has failed"
        )

        unchanged = validate_success(api_client.get_diligence_review(review["id"], PO))
        assert unchanged["status"] == "SUBMITTED", unchanged["status"]
        refreshed = read_partner(partner["id"])
        assert refreshed["status"] == "IN_DILIGENCE", refreshed["status"]
        assert refreshed["capability_tier"] == "UNRATED", refreshed["capability_tier"]
        assert refreshed["latest_composite_score"] == 0.0, (
            "only a PASSED or FAILED outcome copies the file's composite onto the partner, so a "
            "refused decision leaves the partner's score untouched at its initial 0.0, got "
            f"{refreshed['latest_composite_score']}"
        )

    def test_composite_floor_is_reported_when_only_the_composite_fails(self):
        """Second, `composite_score` must be at least 55.0, else
        `ERR_DILIGENCE_SCORE_BELOW_FLOOR`.

        Design: Difficulty/priority_pair_validation_conflict/compliance_capability_floor_outranks_composite_floor_on_diligence_pass
        """
        open_cycle()
        partner, review = _partner_with_submitted_review(
            "Rushmere Credit LLC",
            {
                "business_model_score": 60,
                "funding_score": 59,
                "compliance_capability_score": 60,
                "complaint_history_score": 35,
            },
        )
        assert review["composite_score"] == 54.8, review["composite_score"]
        assert review["tier"] == "UNRATED", review["tier"]

        response = api_client.decide_diligence_review(
            review["id"], {"outcome": "PASSED", "decision_note": "attempt B"}, CO
        )
        validate_error(response, ApiErrorId.ERR_DILIGENCE_SCORE_BELOW_FLOOR)

        unchanged = validate_success(api_client.get_diligence_review(review["id"], PO))
        assert unchanged["status"] == "SUBMITTED", unchanged["status"]
        assert read_partner(partner["id"])["status"] == "IN_DILIGENCE"


def _threshold_partner_with_submitted_review(legal_name, scores):
    partner = validate_success(
        api_client.create_partner(
            create_partner_payload(
                legal_name=legal_name,
                business_model="PAYMENT_FACILITATION",
                funding_stage="SERIES_A",
                months_runway=14,
                disclosed_complaints_per_10k=20.00,
                end_user_account_count=0,
            ),
            PO,
        ),
        expected_status=201,
    )
    review = validate_success(
        api_client.create_diligence_review(
            create_diligence_review_payload(
                partner["id"], partner["version"], review_type="INITIAL", **scores
            ),
            PO,
        ),
        expected_status=201,
    )
    review = validate_success(api_client.submit_diligence_review(review["id"], {}, PO))
    return partner, review


class TestCompositeFloorBoundary:
    def test_composite_exactly_at_the_inclusive_pass_floor_is_accepted(self):
        """The `tier` follows from the composite with inclusive floors: a composite of 85.0 or
        above is `TIER_1`, 70.0 or above is `TIER_2`, 55.0 or above is `TIER_3`, and anything
        lower leaves the tier at `UNRATED`.

        Design: Difficulty/boundary_precision_check/composite_score_rounds_half_up_at_the_inclusive_pass_floor
        """
        open_cycle()
        partner, review = _threshold_partner_with_submitted_review(
            "Threshold Pay A Inc",
            {
                "business_model_score": 60,
                "funding_score": 60,
                "compliance_capability_score": 60,
                "complaint_history_score": 35,
            },
        )
        assert review["composite_score"] == 55.0, (
            f"12.00 + 15.00 + 21.00 + 7.00 is exactly 55.00, got {review['composite_score']}"
        )
        assert review["tier"] == "TIER_3", review["tier"]

        decided = validate_success(
            api_client.decide_diligence_review(
                review["id"], {"outcome": "PASSED", "decision_note": "exactly at floor"}, CO
            )
        )
        assert decided["status"] == "PASSED", "the pass floor is inclusive at exact equality"
        refreshed = read_partner(partner["id"])
        assert refreshed["status"] == "DILIGENCE_PASSED", refreshed["status"]
        assert refreshed["capability_tier"] == "TIER_3", refreshed["capability_tier"]
        assert refreshed["latest_composite_score"] == 55.0, refreshed["latest_composite_score"]

    def test_composite_rounds_half_up_and_still_falls_below_the_pass_floor(self):
        """Those four already-rounded contributions are added together, and only that sum is
        rounded — half up, to one decimal place — to give `composite_score`.

        Design: Difficulty/boundary_precision_check/composite_score_rounds_half_up_at_the_inclusive_pass_floor
        """
        open_cycle()
        partner, review = _threshold_partner_with_submitted_review(
            "Threshold Pay B Inc",
            {
                "business_model_score": 60,
                "funding_score": 58,
                "compliance_capability_score": 61,
                "complaint_history_score": 33,
            },
        )
        assert review["composite_score"] == 54.5, (
            f"12.00 + 14.50 + 21.35 + 6.60 is 54.45, half up to 54.5, got "
            f"{review['composite_score']}"
        )
        assert review["tier"] == "UNRATED", review["tier"]

        response = api_client.decide_diligence_review(
            review["id"], {"outcome": "PASSED", "decision_note": "one tick under"}, CO
        )
        validate_error(response, ApiErrorId.ERR_DILIGENCE_SCORE_BELOW_FLOOR)

        unchanged = validate_success(api_client.get_diligence_review(review["id"], PO))
        assert unchanged["status"] == "SUBMITTED", unchanged["status"]
        refreshed = read_partner(partner["id"])
        assert refreshed["status"] == "IN_DILIGENCE", refreshed["status"]
        assert refreshed["capability_tier"] == "UNRATED", refreshed["capability_tier"]
        assert refreshed["latest_composite_score"] == 0.0, (
            "the refused pass copies nothing onto the partner, so its score stays at 0.0, got "
            f"{refreshed['latest_composite_score']}"
        )
