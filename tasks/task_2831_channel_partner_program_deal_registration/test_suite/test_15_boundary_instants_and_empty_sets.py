"""Probes placed one unit either side of a threshold: the millisecond that ends an exclusivity
window, and the empty set of verified evidence behind a claim."""

import pytest
from test_helpers import (
    ANALYST,
    ApiErrorId,
    draft_registration,
    make_partner_headers,
    read_account,
    read_allocation,
    read_claim,
    read_proof,
    read_registration,
    seed_gold_claim_with_unverified_proofs,
    seed_protected_account,
    set_clock,
    validate_error,
    validate_success,
)


class TestExclusivityEndInstantIsExclusive:
    def test_a_rival_submit_one_millisecond_before_the_end_instant_is_still_refused(self, api):
        """PRD §2.6: "One millisecond before `exclusivity_end_at` the protection is still live and
        a competing submission is rejected with `ERR_EXCLUSIVITY_CONFLICT`; at exactly
        `exclusivity_end_at` the protection is over, the expiry sweep of §3.3 flips the incumbent
        to `EXPIRED`, and the competing submission succeeds."

        Design: Difficulty/boundary_precision_check/exclusivity_window_end_instant_is_exclusive_on_submit
        """
        seed = seed_protected_account()
        incumbent_registration = seed["incumbent_registration"]
        assert incumbent_registration["exclusivity_start_at"] == "2026-04-01T00:00:00.000Z"
        assert incumbent_registration["exclusivity_end_at"] == "2026-05-01T00:00:00.000Z"
        assert incumbent_registration["protection_days"] == 30

        challenger_id = seed["challenger"]["id"]
        rival = draft_registration(
            challenger_id,
            seed["account"]["id"],
            product_line="ANALYTICS_ADDON",
            expected_amount_cents=400_000,
            expected_close_date="2026-09-30T00:00:00.000Z",
        )

        set_clock("2026-04-30T23:59:59.999Z")
        validate_error(
            api.submit_deal_registration(rival["id"], make_partner_headers(challenger_id)),
            ApiErrorId.ERR_EXCLUSIVITY_CONFLICT.value,
            409,
        )

        refused = read_registration(rival["id"])
        assert refused["status"] == "DRAFT"
        assert refused["submitted_at"] is None
        assert read_registration(incumbent_registration["id"])["status"] == "APPROVED"

    def test_at_exactly_the_end_instant_the_sweep_fires_and_the_rival_submit_succeeds(self, api):
        """PRD §3.3: "The sweep visits every registration on the same account-and-product-line pair
        whose `status` is `APPROVED` and whose `exclusivity_end_at` is at or before the current
        logical instant, moves each `APPROVED → EXPIRED`, sets its `closure_reason` to
        `WINDOW_ELAPSED`, sets its `registration_margin_uplift_pct` to 0.02, and advances its
        `version` by 1."
        PRD §3.3: "On success, `submitted_at` is set to the current logical instant and the
        registration's `version` advances by 1."

        Design: Difficulty/boundary_precision_check/exclusivity_window_end_instant_is_exclusive_on_submit
        """
        seed = seed_protected_account()
        challenger_id = seed["challenger"]["id"]
        rival = draft_registration(
            challenger_id,
            seed["account"]["id"],
            product_line="ANALYTICS_ADDON",
            expected_amount_cents=400_000,
            expected_close_date="2026-09-30T00:00:00.000Z",
        )

        set_clock("2026-04-30T23:59:59.999Z")
        api.submit_deal_registration(rival["id"], make_partner_headers(challenger_id))

        set_clock("2026-05-01T00:00:00.000Z")
        submitted = validate_success(
            api.submit_deal_registration(rival["id"], make_partner_headers(challenger_id))
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_at"] == "2026-05-01T00:00:00.000Z"
        assert submitted["revision_round"] == 0

        swept = read_registration(seed["incumbent_registration"]["id"])
        assert swept["status"] == "EXPIRED"
        assert swept["closure_reason"] == "WINDOW_ELAPSED"
        assert swept["registration_margin_uplift_pct"] == pytest.approx(0.02, abs=1e-9)

    def test_the_sweep_second_hop_returns_the_account_to_the_open_channel(self, api):
        """PRD §3.3: "This sweep is the only producer of a registration in `EXPIRED` and the only
        path an account has back to `OPEN_CHANNEL`; because it reads nothing but the logical clock,
        it is fully deterministic."

        Design: Difficulty/boundary_precision_check/exclusivity_window_end_instant_is_exclusive_on_submit
        """
        seed = seed_protected_account()
        account_id = seed["account"]["id"]
        challenger_id = seed["challenger"]["id"]
        assert seed["account"]["coverage_state"] == "CHANNEL_PROTECTED"

        rival = draft_registration(
            challenger_id,
            account_id,
            product_line="ANALYTICS_ADDON",
            expected_amount_cents=400_000,
            expected_close_date="2026-09-30T00:00:00.000Z",
        )

        set_clock("2026-05-01T00:00:00.000Z")
        validate_success(
            api.submit_deal_registration(rival["id"], make_partner_headers(challenger_id))
        )

        account = read_account(account_id)
        assert account["coverage_state"] == "OPEN_CHANNEL"
        assert account["protected_until"] is None
        assert account["protected_partner_id"] is None
        assert account["protected_product_line"] is None


class TestZeroVerifiedProofsBlocksValidation:
    def test_two_attached_but_unverified_documents_are_still_an_empty_input_set(self, api):
        """PRD §3.7: "It requires the period to be `OPEN` and requires at least one of the claim's
        documents to have `verified` true, or `ERR_NO_VERIFIED_PROOF`."
        PRD §3.7: "A new document is stored with its `claim_id` set to the claim named in the path
        — the document's only foreign key, and the field a proof read reports its parentage through
        — with `verified` false, `verified_at` null, `verified_by_user_id` null and
        `matched_line_cents` null, and the parent claim's `version` advances by 1."

        Design: Difficulty/boundary_precision_check/zero_verified_proofs_blocks_claim_validation
        """
        seed = seed_gold_claim_with_unverified_proofs()
        claim_id = seed["claim"]["id"]
        assert seed["tiny_proof"]["verified"] is False
        assert seed["unverified_proof"]["verified"] is False

        validate_error(
            api.validate_mdf_claim(claim_id, {"decision": "VALIDATE"}, ANALYST),
            ApiErrorId.ERR_NO_VERIFIED_PROOF.value,
            409,
        )

        refused = read_claim(claim_id)
        assert refused["validation_state"] == "SUBMITTED"
        assert refused["matched_total_cents"] is None
        assert refused["approved_cents"] is None

        allocation = read_allocation(seed["allocation"]["id"])
        assert allocation["committed_cents"] == 20000
        assert allocation["available_cents"] == 253000

    def test_verifying_a_single_cent_document_makes_the_same_call_succeed(self, api):
        """PRD §3.7: "Verification sets `verified` to true, `verified_at` to the current logical
        instant and `verified_by_user_id` to the acting analyst's opaque identifier, and advances
        the document's `version` by 1; the parent period must still be `OPEN`."
        PRD §3.7: "Unverified documents contribute nothing and keep `matched_line_cents` null."

        Design: Difficulty/boundary_precision_check/zero_verified_proofs_blocks_claim_validation
        """
        seed = seed_gold_claim_with_unverified_proofs()
        claim_id = seed["claim"]["id"]

        validate_error(
            api.validate_mdf_claim(claim_id, {"decision": "VALIDATE"}, ANALYST),
            ApiErrorId.ERR_NO_VERIFIED_PROOF.value,
            409,
        )

        verified = validate_success(
            api.verify_proof(claim_id, seed["tiny_proof"]["id"], ANALYST)
        )
        assert verified["verified"] is True
        assert verified["verified_at"] == "2026-02-10T00:00:00.000Z"

        claim = validate_success(
            api.validate_mdf_claim(claim_id, {"decision": "VALIDATE"}, ANALYST)
        )
        assert claim["validation_state"] == "VALIDATED"
        # round_half_up(1 * 0.50) is the smallest non-zero match the rule can produce.
        assert read_proof(seed["tiny_proof"]["id"])["matched_line_cents"] == 1
        assert claim["matched_total_cents"] == 1
        assert claim["approved_cents"] == 1

        untouched = read_proof(seed["unverified_proof"]["id"])
        assert untouched["verified"] is False
        assert untouched["matched_line_cents"] is None

        allocation = read_allocation(seed["allocation"]["id"])
        assert allocation["committed_cents"] == 1
        assert allocation["available_cents"] == 272999
