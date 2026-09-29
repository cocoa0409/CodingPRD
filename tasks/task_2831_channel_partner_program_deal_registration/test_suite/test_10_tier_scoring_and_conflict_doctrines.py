"""Dual-variant program arithmetic: the two scoring variants of a performance review and
the two conflict doctrines stored on a channel conflict case."""

import pytest
from test_helpers import (
    ANALYST,
    DIRECTOR,
    assert_performance_review,
    assert_score_precision,
    decide_review_payload,
    decide_registration_payload,
    find_conflict_cases,
    prepare_review,
    read_partner,
    read_registration,
    read_account,
    read_invoice,
    seed_dual_variant_scoring_partner,
    seed_sequential_rival_submissions,
    validate_success,
)


class TestPerformanceReviewScoringVariants:
    def test_preparation_writes_the_provisional_variant_over_active_certs_and_pending_orders(
        self, api
    ):
        """PRD §3.9: "The **provisional** variant, computed at preparation and producing
        `recommended_tier`, is forward-looking: its certification basis is the sum of
        `credit_weight` over every certification record still in `ACTIVE`, regardless of how
        soon it lapses, and its period revenue is the sum of `invoice_amount_cents` over the
        partner's orders whose `status` is `PENDING`, `INVOICED` or `CREDITED` and whose
        window instant falls inside the review period inclusively at both ends"
        PRD §3.9: "The score is 40 times the certification component plus 35 times the revenue
        component plus 25 times the marketing component, rounded half-up to two decimal places
        **once, at the end**"

        Design: Difficulty/dual_variant_calc/provisional_vs_final_tier_divergence_on_performance_review
        """
        seed = seed_dual_variant_scoring_partner()
        partner_id = seed["partner"]["id"]
        assert seed["partner"]["cert_credit_total"] == 12

        review = validate_success(
            api.create_performance_review(
                {
                    "partner_id": partner_id,
                    "period_start": "2026-01-01T00:00:00.000Z",
                    "period_end": "2026-01-31T23:59:59.999Z",
                    "findings_count": 0,
                },
                ANALYST,
            ),
            201,
        )
        assert_performance_review(review)

        assert review["provisional_cert_credit"] == 12
        assert review["provisional_revenue_cents"] == 12170000
        assert review["provisional_score"] == pytest.approx(73.52, abs=0.001)
        assert_score_precision(review["provisional_score"])
        assert review["recommended_tier"] == "GOLD"
        assert review["marketing_attainment_pct"] == pytest.approx(1.0, abs=0.0001)
        assert review["status"] == "PREPARED"
        assert review["remediation_due_at"] is None
        assert review["final_cert_credit"] is None
        assert review["final_revenue_cents"] is None
        assert review["final_score"] is None
        assert review["approved_tier"] is None

        short_cert = validate_success(api.get_certification(seed["cert_short"]["id"], ANALYST))
        assert short_cert["status"] == "ACTIVE", (
            "a certification whose expires_at is after the logical instant survives preparation"
        )

    def test_decision_writes_the_final_variant_and_is_the_only_writer_of_partner_tier(self, api):
        """PRD §3.9: "The **final** variant, computed at the decision and producing
        `approved_tier`, is coverage-tested: its certification basis counts only records in
        `ACTIVE` whose `expires_at` is at or after `period_end` plus 90 days, and its period
        revenue counts only orders whose `status` is `INVOICED` or `CREDITED` and whose
        `invoiced_at` falls inside the review period inclusively at both ends, with `PENDING`
        orders excluded entirely."
        PRD §3.9: "Approval writes `approved_tier` from the final variant's gate ladder and
        copies it onto the partner's `tier` — the one and only writer of that field in the
        whole service."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_tier_divergence_on_performance_review
        """
        seed = seed_dual_variant_scoring_partner()
        partner_id = seed["partner"]["id"]
        review = prepare_review(partner_id, findings_count=0)

        decided = validate_success(
            api.decide_performance_review(review["id"], decide_review_payload("APPROVE"), DIRECTOR)
        )

        assert decided["provisional_cert_credit"] == 12
        assert decided["provisional_score"] == pytest.approx(73.52, abs=0.001)
        assert decided["recommended_tier"] == "GOLD"
        assert decided["final_cert_credit"] == 8, (
            "the certification lapsing before period_end plus 90 days drops out of the final basis"
        )
        assert decided["final_revenue_cents"] == 8650000, (
            "the PENDING order is excluded entirely from the final revenue basis"
        )
        assert decided["final_score"] == pytest.approx(57.72, abs=0.001)
        assert_score_precision(decided["final_score"])
        assert decided["approved_tier"] == "SILVER"
        assert decided["status"] == "APPROVED"

        partner = read_partner(partner_id)
        assert partner["tier"] == "SILVER", (
            "the final variant, not the provisional recommendation, is copied onto Partner.tier"
        )
        assert partner["tier_status"] == "COMPLIANT"

    def test_pending_order_counts_in_the_provisional_basis_but_never_in_the_final_basis(self, api):
        """PRD §3.9: "Consequently `final_score` is at or below `provisional_score` whenever
        either dropped set is non-empty, and identical data can imply two different tiers."
        PRD §3.9: "its period revenue counts only orders whose `status` is `INVOICED` or
        `CREDITED` and whose `invoiced_at` falls inside the review period inclusively at both
        ends, with `PENDING` orders excluded entirely."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_tier_divergence_on_performance_review
        """
        seed = seed_dual_variant_scoring_partner()
        pending_order = read_invoice(seed["pending_order"]["id"])
        invoiced_order = read_invoice(seed["invoiced_order"]["id"])
        assert pending_order["status"] == "PENDING"
        assert invoiced_order["status"] == "INVOICED"

        review = prepare_review(seed["partner"]["id"], findings_count=0)
        assert review["provisional_revenue_cents"] == (
            invoiced_order["invoice_amount_cents"] + pending_order["invoice_amount_cents"]
        )

        decided = validate_success(
            api.decide_performance_review(review["id"], decide_review_payload("APPROVE"), DIRECTOR)
        )
        assert decided["final_revenue_cents"] == invoiced_order["invoice_amount_cents"]
        assert decided["final_score"] <= decided["provisional_score"]


class TestConflictRecommendationDoctrines:
    def test_partner_versus_partner_case_stores_both_doctrines_and_applies_registration_first(
        self, api
    ):
        """PRD §3.5: "Which of the two stored figures is authoritative is recorded in
        `applied_variant`, whose value is `REGISTRATION_FIRST` on a `PARTNER_VS_PARTNER` case
        and `COVERAGE_FIRST` on a `PARTNER_VS_DIRECT` case, and `recommended_resolution` is a
        copy of whichever of the two doctrine fields `applied_variant` names."
        PRD §3.5: "The claimant with the earliest claim instant wins; if two claim instants are
        identical the earlier tiebreaker instant wins; identifiers are never used to break a
        tie."

        Design: Difficulty/dual_variant_calc/conflict_recommendation_variant_divergence_on_partner_vs_partner_case
        """
        seed = seed_sequential_rival_submissions()
        validate_success(
            api.decide_deal_registration(
                seed["registration_b"]["id"], decide_registration_payload("APPROVE"), DIRECTOR
            )
        )

        cases = find_conflict_cases(subject_registration_id=seed["registration_a"]["id"])
        assert len(cases) == 1, f"expected exactly one case on the held claim, got {len(cases)}"
        case = cases[0]

        assert case["conflict_type"] == "PARTNER_VS_PARTNER"
        assert case["subject_registration_id"] == seed["registration_a"]["id"]
        assert case["counter_registration_id"] == seed["registration_b"]["id"]
        assert case["detected_at"] == "2026-02-02T00:00:00.000Z"
        assert case["recommended_resolution_registration_first"] == "GRANT_SUBJECT", (
            "the subject staked its claim a day earlier, so registration order favours it"
        )
        assert case["recommended_resolution_coverage_first"] == "GRANT_COUNTER", (
            "the counter partner holds the live protection, so coverage order favours it"
        )
        assert case["applied_variant"] == "REGISTRATION_FIRST"
        assert case["recommended_resolution"] == "GRANT_SUBJECT"
        assert case["status"] == "OPEN"
        assert case["escalation_level"] == 0

    def test_registration_first_doctrine_ranks_on_the_stored_submitted_at_instants(self, api):
        """PRD §3.5: "The subject registration always contributes a claimant labelled
        `GRANT_SUBJECT` whose claim instant is the subject's `submitted_at` and whose
        tiebreaker is the subject's `created_at`."
        PRD §3.4: "Hop two: because the account is now protected for that
        account-and-product-line pair, every **other** registration on the same pair whose
        `status` is `SUBMITTED`, `UNDER_REVIEW` or `CHANGES_REQUESTED` moves to `CONFLICT_HELD`
        with `closure_reason` `ACCOUNT_PROTECTED_BY_OTHER_PARTNER` and its `version` advanced
        by 1."

        Design: Difficulty/dual_variant_calc/conflict_recommendation_variant_divergence_on_partner_vs_partner_case
        """
        seed = seed_sequential_rival_submissions()
        assert seed["registration_a"]["submitted_at"] == "2026-02-01T00:00:00.000Z"
        assert seed["registration_b"]["submitted_at"] == "2026-02-02T00:00:00.000Z"

        validate_success(
            api.decide_deal_registration(
                seed["registration_b"]["id"], decide_registration_payload("APPROVE"), DIRECTOR
            )
        )

        held = read_registration(seed["registration_a"]["id"])
        assert held["status"] == "CONFLICT_HELD"
        assert held["closure_reason"] == "ACCOUNT_PROTECTED_BY_OTHER_PARTNER"
        assert held["submitted_at"] == "2026-02-01T00:00:00.000Z"

        account = read_account(seed["account"]["id"])
        assert account["coverage_state"] == "CHANNEL_PROTECTED"
        assert account["protected_partner_id"] == seed["partner_b"]["id"]

    def test_single_open_case_leaves_the_held_partner_compliant_below_the_probation_threshold(
        self, api
    ):
        """PRD §3.4: "Hop four: because each of those cases was created in `OPEN`, the held
        registration's partner has `open_conflict_count` recomputed, and when the recomputed
        count reaches 2 while that partner's `tier_status` is `COMPLIANT`, the partner moves to
        `PROBATION` with `standing_reason` `OPEN_CONFLICT_THRESHOLD` and
        `portal_entitlement_level` recomputed — one ladder step down, so a `GOLD` partner drops
        to `STANDARD` while a `REGISTERED` partner stays at `BASIC`."

        Design: Difficulty/dual_variant_calc/conflict_recommendation_variant_divergence_on_partner_vs_partner_case
        """
        seed = seed_sequential_rival_submissions()
        validate_success(
            api.decide_deal_registration(
                seed["registration_b"]["id"], decide_registration_payload("APPROVE"), DIRECTOR
            )
        )

        held_partner = read_partner(seed["partner_a"]["id"])
        assert held_partner["open_conflict_count"] == 1
        assert held_partner["tier_status"] == "COMPLIANT", (
            "one open case is below the threshold of two, so standing is untouched"
        )
