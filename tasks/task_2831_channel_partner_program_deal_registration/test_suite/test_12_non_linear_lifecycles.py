"""Lifecycle shapes that are not a single line: the bounded revision cycle on a deal
registration, and the two independent state dimensions carried by one fund claim."""

from test_helpers import (
    ANALYST,
    DIRECTOR,
    ApiErrorId,
    assert_mdf_fund_conservation,
    make_partner_headers,
    read_account,
    read_allocation,
    read_claim,
    read_registration,
    run_revision_loop,
    seed_reseller_draft_registration,
    seed_validated_gold_claim,
    set_clock,
    validate_error,
    validate_success,
)


class TestRegistrationRevisionCycle:
    def test_every_resubmission_advances_the_round_and_rewrites_the_chronological_key(self, api):
        """PRD §3.3: "On success `revision_round` advances by 1, `submitted_at` is rewritten to
        the current logical instant, and the `version` advances by 1."
        PRD §3.3: "That rewriting has a consequence the partner should understand: `submitted_at`
        is the chronological key by which competing claims are ranked in §3.5, so every trip
        through the revision loop pushes the partner's claim later in the queue."

        Design: Difficulty/non_linear_state_machine/deal_registration_revision_cycle_caps_at_two_rounds
        """
        seed = seed_reseller_draft_registration()
        registration_id = seed["registration"]["id"]
        partner_id = seed["partner"]["id"]

        assert seed["registration"]["status"] == "DRAFT"
        assert seed["registration"]["revision_round"] == 0
        assert seed["registration"]["submitted_at"] is None

        run_revision_loop(registration_id, partner_id)
        first = read_registration(registration_id)
        assert first["status"] == "CHANGES_REQUESTED"
        assert first["revision_round"] == 0
        assert first["submitted_at"] == "2026-03-01T00:00:00.000Z"

        run_revision_loop(
            registration_id,
            partner_id,
            submit_at="2026-03-02T00:00:00.000Z",
            reviewer_note="confirm the forecast close date",
        )
        second = read_registration(registration_id)
        assert second["revision_round"] == 1
        assert second["submitted_at"] == "2026-03-02T00:00:00.000Z"

        run_revision_loop(
            registration_id,
            partner_id,
            submit_at="2026-03-03T00:00:00.000Z",
            reviewer_note="final clarification round",
        )
        third = read_registration(registration_id)
        assert third["revision_round"] == 2
        assert third["submitted_at"] == "2026-03-03T00:00:00.000Z"
        assert third["closure_reason"] == "final clarification round"

    def test_the_third_resubmission_is_refused_and_leaves_the_cycle_untouched(self, api):
        """PRD §3.3: "It additionally requires `revision_round` to be strictly below 2; the third
        resubmission attempt is `ERR_INVALID_STATE_TRANSITION`."

        Design: Difficulty/non_linear_state_machine/deal_registration_revision_cycle_caps_at_two_rounds
        """
        seed = seed_reseller_draft_registration()
        registration_id = seed["registration"]["id"]
        partner_id = seed["partner"]["id"]

        run_revision_loop(registration_id, partner_id)
        run_revision_loop(
            registration_id,
            partner_id,
            submit_at="2026-03-02T00:00:00.000Z",
            reviewer_note="confirm the forecast close date",
        )
        run_revision_loop(
            registration_id,
            partner_id,
            submit_at="2026-03-03T00:00:00.000Z",
            reviewer_note="final clarification round",
        )

        set_clock("2026-03-04T00:00:00.000Z")
        validate_error(
            api.submit_deal_registration(registration_id, make_partner_headers(partner_id)),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            409,
        )

        refused = read_registration(registration_id)
        assert refused["status"] == "CHANGES_REQUESTED"
        assert refused["revision_round"] == 2
        assert refused["submitted_at"] == "2026-03-03T00:00:00.000Z"
        assert refused["closure_reason"] == "final clarification round"

    def test_a_registration_that_never_reaches_a_decision_leaves_the_account_open(self, api):
        """PRD §3.3: "With `REQUEST_CHANGES` the analyst sends the deal back to the partner
        instead of escalating it to a decision, moving it `UNDER_REVIEW → CHANGES_REQUESTED`."

        Design: Difficulty/non_linear_state_machine/deal_registration_revision_cycle_caps_at_two_rounds
        """
        seed = seed_reseller_draft_registration()
        registration_id = seed["registration"]["id"]
        partner_id = seed["partner"]["id"]
        account_id = seed["account"]["id"]
        assert seed["account"]["coverage_state"] == "OPEN_CHANNEL"

        run_revision_loop(registration_id, partner_id)
        assert read_account(account_id)["coverage_state"] == "OPEN_CHANNEL"

        run_revision_loop(
            registration_id,
            partner_id,
            submit_at="2026-03-02T00:00:00.000Z",
            reviewer_note="confirm the forecast close date",
        )
        account = read_account(account_id)
        assert account["coverage_state"] == "OPEN_CHANNEL"
        assert account["protected_until"] is None
        assert account["protected_partner_id"] is None
        assert account["protected_product_line"] is None


class TestClaimSettlementDimensionIsIndependent:
    def test_approving_payment_advances_settlement_without_touching_validation_or_cents(self, api):
        """PRD §3.8: "`APPROVE_PAYMENT` moves the claim `UNPAID → APPROVED_FOR_PAYMENT`."
        PRD §3.8: "No cents move: the claim's `approved_cents` was already sitting in
        `committed_cents`."

        Design: Difficulty/non_linear_state_machine/mdf_claim_settlement_dimension_advances_independently_of_validation
        """
        seed = seed_validated_gold_claim()
        claim_id = seed["claim"]["id"]
        allocation_id = seed["allocation"]["id"]
        assert seed["claim"]["approved_cents"] == 10000

        claim = validate_success(
            api.settle_mdf_claim(claim_id, {"action": "APPROVE_PAYMENT"}, DIRECTOR)
        )
        assert claim["settlement_state"] == "APPROVED_FOR_PAYMENT"
        assert claim["validation_state"] == "VALIDATED"

        allocation = read_allocation(allocation_id)
        assert allocation["allocated_cents"] == 273000
        assert allocation["committed_cents"] == 10000
        assert allocation["paid_cents"] == 0
        assert allocation["available_cents"] == 263000
        assert_mdf_fund_conservation(allocation)

    def test_the_claw_back_is_refused_once_settlement_has_left_unpaid(self, api):
        """PRD §3.7: "The third path, `VALIDATED → REJECTED`, is a claw-back and is only permitted
        while `settlement_state` is still `UNPAID`; a claim already `APPROVED_FOR_PAYMENT` or
        `PAID` can no longer be clawed back, and attempting it is `ERR_INVALID_STATE_TRANSITION`."

        Design: Difficulty/non_linear_state_machine/mdf_claim_settlement_dimension_advances_independently_of_validation
        """
        seed = seed_validated_gold_claim()
        claim_id = seed["claim"]["id"]

        validate_success(api.settle_mdf_claim(claim_id, {"action": "APPROVE_PAYMENT"}, DIRECTOR))

        validate_error(
            api.validate_mdf_claim(
                claim_id, {"decision": "REJECT", "rejection_reason": "late audit finding"}, ANALYST
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            409,
        )

        refused = read_claim(claim_id)
        assert refused["validation_state"] == "VALIDATED"
        assert refused["approved_cents"] == 10000
        assert refused["rejection_reason"] is None
        assert refused["settlement_state"] == "APPROVED_FOR_PAYMENT"

    def test_paying_moves_cents_from_committed_to_paid_while_validation_stays_validated(self, api):
        """PRD §3.8: "`PAY` moves the claim `APPROVED_FOR_PAYMENT → PAID`."
        PRD §3.8: "The claim's `approved_cents` transfers from `committed_cents` into
        `paid_cents`, and `available_cents` is recomputed."

        Design: Difficulty/non_linear_state_machine/mdf_claim_settlement_dimension_advances_independently_of_validation
        """
        seed = seed_validated_gold_claim()
        claim_id = seed["claim"]["id"]
        allocation_id = seed["allocation"]["id"]

        validate_success(api.settle_mdf_claim(claim_id, {"action": "APPROVE_PAYMENT"}, DIRECTOR))
        claim = validate_success(api.settle_mdf_claim(claim_id, {"action": "PAY"}, DIRECTOR))

        assert claim["settlement_state"] == "PAID"
        assert claim["validation_state"] == "VALIDATED"
        assert claim["validated_by_user_id"] == ANALYST["X-User-ID"]
        assert claim["settled_by_user_id"] == DIRECTOR["X-User-ID"]

        allocation = read_allocation(allocation_id)
        assert allocation["committed_cents"] == 0
        assert allocation["paid_cents"] == 10000
        assert allocation["available_cents"] == 263000
        assert allocation["expired_cents"] == 0
        assert allocation["allocated_cents"] == 273000
        assert 273000 == 263000 + 0 + 10000 + 0
        assert_mdf_fund_conservation(allocation)
