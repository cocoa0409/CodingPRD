"""Four-hop cascades from two different triggering transitions: a registration approval that
ends in conflict probation, and a claim claw-back that ends in marketing probation."""

import pytest
from test_helpers import (
    ANALYST,
    DIRECTOR,
    assert_mdf_fund_conservation,
    find_conflict_cases,
    read_account,
    read_allocation,
    read_partner,
    read_proof,
    read_registration,
    seed_cascade_a_two_account_conflict,
    seed_cascade_b_validated_claim,
    validate_success,
)


class TestCascadeAFromRegistrationApproval:
    def test_approval_protects_the_account_and_holds_every_competing_registration(self, api):
        """PRD §3.4: "Hop one: because the registration became `APPROVED`, the account's
        `coverage_state` is set to `CHANNEL_PROTECTED`, its `protected_until` to the new
        registration's `exclusivity_end_at`, its `protected_partner_id` to the registration's
        `partner_id` and its `protected_product_line` to the registration's `product_line`, with
        the account's `version` advanced by 1."
        PRD §3.4: "`exclusivity_start_at` is the current logical instant — the same instant as
        `approved_at` — and `exclusivity_end_at` is that instant plus `protection_days` days, each
        day an exact twenty-four hours."

        Design: Difficulty/transitive_cascade/cascade_a_registration_approval_to_partner_probation_depth_four
        """
        seed = seed_cascade_a_two_account_conflict()
        account_two_id = seed["account_two"]["id"]
        assert seed["account_two"]["coverage_state"] == "OPEN_CHANNEL"

        approved = validate_success(
            api.decide_deal_registration(
                seed["approver_registration_two"]["id"], {"decision": "APPROVE"}, DIRECTOR
            )
        )

        assert approved["status"] == "APPROVED"
        assert approved["approved_at"] == "2026-04-01T00:00:00.000Z"
        assert approved["protection_days"] == 30
        assert approved["exclusivity_start_at"] == "2026-04-01T00:00:00.000Z"
        assert approved["exclusivity_end_at"] == "2026-05-01T00:00:00.000Z"
        assert approved["registration_margin_uplift_pct"] == pytest.approx(0.06, abs=1e-9)

        account_two = read_account(account_two_id)
        assert account_two["coverage_state"] == "CHANNEL_PROTECTED"
        assert account_two["protected_until"] == "2026-05-01T00:00:00.000Z"
        assert account_two["protected_partner_id"] == seed["approver"]["id"]
        assert account_two["protected_product_line"] == "ANALYTICS_ADDON"

        held = read_registration(seed["rival_registration_two"]["id"])
        assert held["status"] == "CONFLICT_HELD"
        assert held["closure_reason"] == "ACCOUNT_PROTECTED_BY_OTHER_PARTNER"

    def test_the_held_registration_raises_a_case_that_pushes_its_partner_onto_probation(self, api):
        """PRD §3.4: "Hop four: because each of those cases was created in `OPEN`, the held
        registration's partner has `open_conflict_count` recomputed, and when the recomputed count
        reaches 2 while that partner's `tier_status` is `COMPLIANT`, the partner moves to
        `PROBATION` with `standing_reason` `OPEN_CONFLICT_THRESHOLD` and `portal_entitlement_level`
        recomputed — one ladder step down, so a `GOLD` partner drops to `STANDARD` while a
        `REGISTERED` partner stays at `BASIC`."
        PRD §3.1: "Demotions accumulate, and the resulting rung is the starting rung stepped down
        by the number of demotions, never falling below the first rung."

        Design: Difficulty/transitive_cascade/cascade_a_registration_approval_to_partner_probation_depth_four
        """
        seed = seed_cascade_a_two_account_conflict()
        rival_id = seed["rival"]["id"]
        assert seed["rival"]["open_conflict_count"] == 1
        assert seed["rival"]["tier_status"] == "COMPLIANT"

        validate_success(
            api.decide_deal_registration(
                seed["approver_registration_two"]["id"], {"decision": "APPROVE"}, DIRECTOR
            )
        )

        cases = find_conflict_cases(
            subject_registration_id=seed["rival_registration_two"]["id"]
        )
        assert len(cases) == 1
        case = cases[0]
        assert case["status"] == "OPEN"
        assert case["conflict_type"] == "PARTNER_VS_PARTNER"
        assert case["account_id"] == seed["account_two"]["id"]
        assert case["counter_registration_id"] == seed["approver_registration_two"]["id"]
        assert case["detected_at"] == "2026-04-01T00:00:00.000Z"
        assert case["escalation_level"] == 0

        rival = read_partner(rival_id)
        assert rival["open_conflict_count"] == 2
        assert rival["tier_status"] == "PROBATION"
        assert rival["standing_reason"] == "OPEN_CONFLICT_THRESHOLD"
        assert rival["portal_entitlement_level"] == "BASIC"
        assert rival["tier"] == "REGISTERED"

    def test_the_cascade_leaves_the_approving_partner_and_the_earlier_account_alone(self, api):
        """PRD §3.4: "Hop two: because the account is now protected for that
        account-and-product-line pair, every **other** registration on the same pair whose
        `status` is `SUBMITTED`, `UNDER_REVIEW` or `CHANGES_REQUESTED` moves to `CONFLICT_HELD`
        with `closure_reason` `ACCOUNT_PROTECTED_BY_OTHER_PARTNER` and its `version` advanced
        by 1."
        PRD §3.1: "A partner's `tier`, by contrast, is never written by this amendment or by any
        other operation except an approving performance-review decision, and `tier_status` is only
        ever written by the standing rules described later in this document."

        Design: Difficulty/transitive_cascade/cascade_a_registration_approval_to_partner_probation_depth_four
        """
        seed = seed_cascade_a_two_account_conflict()
        assert seed["rival_registration_one"]["status"] == "CONFLICT_HELD"

        validate_success(
            api.decide_deal_registration(
                seed["approver_registration_two"]["id"], {"decision": "APPROVE"}, DIRECTOR
            )
        )

        approver = read_partner(seed["approver"]["id"])
        assert approver["tier_status"] == "COMPLIANT"
        assert approver["open_conflict_count"] == 0

        first_held = read_registration(seed["rival_registration_one"]["id"])
        assert first_held["status"] == "CONFLICT_HELD"

        account_one = read_account(seed["account_one"]["id"])
        assert account_one["protected_partner_id"] == seed["approver"]["id"]
        assert account_one["coverage_state"] == "CHANNEL_PROTECTED"


class TestCascadeBFromClaimClawBack:
    def test_the_claw_back_returns_the_previous_approved_cents_to_the_pool(self, api):
        """PRD §3.7: "Hop two: because the claim left `VALIDATED`, `committed_cents` decreases by
        the claim's **previous** `approved_cents` — the amount that was still committed after
        validation, not the original request — and `available_cents` is recomputed, so a
        file-validate-reject round trip restores `available_cents` to its pre-claim value with zero
        drift."

        Design: Difficulty/transitive_cascade/cascade_b_claim_clawback_to_marketing_probation_depth_four
        """
        seed = seed_cascade_b_validated_claim()
        allocation_id = seed["allocation"]["id"]
        assert seed["allocation"]["allocated_cents"] == 273000
        assert seed["allocation"]["committed_cents"] == 20000
        assert seed["allocation"]["available_cents"] == 253000
        assert seed["claim"]["approved_cents"] == 20000

        claim = validate_success(
            api.validate_mdf_claim(
                seed["claim"]["id"],
                {"decision": "REJECT", "rejection_reason": "post-audit disqualification"},
                ANALYST,
            )
        )

        assert claim["validation_state"] == "REJECTED"
        assert claim["approved_cents"] == 0
        assert claim["rejection_reason"] == "post-audit disqualification"
        assert claim["settlement_state"] == "UNPAID"

        allocation = read_allocation(allocation_id)
        assert allocation["committed_cents"] == 0
        assert allocation["available_cents"] == 273000
        assert allocation["paid_cents"] == 0
        assert allocation["expired_cents"] == 0
        assert_mdf_fund_conservation(allocation)

    def test_the_claw_back_withdraws_the_verified_spend_and_trips_the_marketing_floor(self, api):
        """PRD §3.7: "Hop three: because the claim is no longer `VALIDATED`, the partner's
        `marketing_qualified_spend_cents` drops by the sum of `spend_amount_cents` over this
        claim's verified documents and `marketing_attainment_pct` is recomputed."
        PRD §3.7: "Hop four: when that recomputed attainment has fallen below 0.75 while the
        partner's `tier_status` is `COMPLIANT`, the partner moves to `PROBATION` with
        `standing_reason` `MARKETING_ATTAINMENT_SHORTFALL` and `portal_entitlement_level` is
        recomputed."

        Design: Difficulty/transitive_cascade/cascade_b_claim_clawback_to_marketing_probation_depth_four
        """
        seed = seed_cascade_b_validated_claim()
        partner_id = seed["partner"]["id"]
        assert seed["partner"]["marketing_attainment_pct"] == pytest.approx(1.0, abs=1e-9)
        assert seed["partner"]["tier_status"] == "COMPLIANT"
        assert seed["partner"]["portal_entitlement_level"] == "PREMIUM"

        validate_success(
            api.validate_mdf_claim(
                seed["claim"]["id"],
                {"decision": "REJECT", "rejection_reason": "post-audit disqualification"},
                ANALYST,
            )
        )

        partner = read_partner(partner_id)
        assert partner["marketing_qualified_spend_cents"] == 0
        assert partner["marketing_attainment_pct"] == pytest.approx(0.0, abs=1e-9)
        assert partner["tier_status"] == "PROBATION"
        assert partner["standing_reason"] == "MARKETING_ATTAINMENT_SHORTFALL"

    def test_the_claw_back_demotes_the_portal_rung_without_rewriting_tier_or_the_proof(self, api):
        """PRD §3.1: "Otherwise the service counts demotions: one demotion if `tier_status` is
        `PROBATION`, and one further demotion if `cert_credit_total` has fallen below the
        certification floor for the partner's tier."
        PRD §3.1: "Verified evidence hanging off a claim that is merely `SUBMITTED`, still
        `PROOF_REQUESTED`, or already `REJECTED` contributes nothing, so the very same document can
        enter and leave the numerator as its claim is validated and later clawed back."

        Design: Difficulty/transitive_cascade/cascade_b_claim_clawback_to_marketing_probation_depth_four
        """
        seed = seed_cascade_b_validated_claim()
        partner_id = seed["partner"]["id"]
        assert seed["partner"]["cert_credit_total"] == 12

        validate_success(
            api.validate_mdf_claim(
                seed["claim"]["id"],
                {"decision": "REJECT", "rejection_reason": "post-audit disqualification"},
                ANALYST,
            )
        )

        partner = read_partner(partner_id)
        # GOLD starts at the third rung; one PROBATION demotion drops it to STANDARD, and the
        # credit floor of 6 for GOLD is still cleared so there is no second demotion.
        assert partner["portal_entitlement_level"] == "STANDARD"
        assert partner["tier"] == "GOLD"
        assert partner["cert_credit_total"] == 12

        proof = read_proof(seed["proof"]["id"])
        assert proof["verified"] is True
        assert proof["verified_by_user_id"] == ANALYST["X-User-ID"]
