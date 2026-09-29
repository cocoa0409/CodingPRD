"""Operations whose admissibility is decided by a *different* entity's state: a registration
submit gated on the account's coverage, and a claim create gated on the fund period's status."""

import pytest
from test_helpers import (
    ANALYST,
    ApiErrorId,
    assert_mdf_fund_conservation,
    close_allocation,
    create_account,
    create_claim,
    draft_registration,
    make_partner_headers,
    read_account,
    read_allocation,
    read_claim,
    read_partner,
    read_registration,
    seed_direct_locked_account,
    seed_gold_distributor_with_allocation,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSubmitDependsOnAccountCoverageState:
    def test_a_direct_locked_account_refuses_a_submit_with_no_live_window_anywhere(self, api):
        """PRD §2.8: "**Exclusivity conflict.** No other approved registration holds a live
        exclusivity window on the same account-and-product-line pair, and the account's
        `coverage_state` is not `DIRECT_LOCKED` — otherwise `ERR_EXCLUSIVITY_CONFLICT` (409). This
        guards two operations: registration submit and an approving registration decision."
        PRD §3.5: "The account moves to the terminal `DIRECT_LOCKED` — from `NAMED_DIRECT` or from
        `CHANNEL_PROTECTED`, whichever it was in — with `protected_until`, `protected_partner_id`
        and `protected_product_line` all cleared to null and its `version` advanced by 1."

        Design: Difficulty/cross_entity_state_dependency/registration_submit_depends_on_account_direct_locked_state
        """
        seed = seed_direct_locked_account()
        locked_account = seed["account"]
        assert locked_account["coverage_state"] == "DIRECT_LOCKED"
        assert locked_account["protected_until"] is None
        assert locked_account["protected_partner_id"] is None
        assert locked_account["protected_product_line"] is None

        rejected_incumbent = read_registration(seed["incumbent_registration"]["id"])
        assert rejected_incumbent["status"] == "REJECTED"
        assert rejected_incumbent["closure_reason"] == "RESOLVED_DIRECT"
        assert rejected_incumbent["registration_margin_uplift_pct"] == pytest.approx(0.0, abs=1e-9)

        challenger_id = seed["challenger"]["id"]
        blocked = draft_registration(
            challenger_id,
            locked_account["id"],
            product_line="ANALYTICS_ADDON",
            expected_amount_cents=400_000,
            expected_close_date="2026-09-30T00:00:00.000Z",
        )

        validate_error(
            api.submit_deal_registration(blocked["id"], make_partner_headers(challenger_id)),
            ApiErrorId.ERR_EXCLUSIVITY_CONFLICT.value,
            409,
        )
        refused = read_registration(blocked["id"])
        assert refused["status"] == "DRAFT"
        assert refused["submitted_at"] is None

    def test_the_same_submit_on_an_untouched_account_succeeds(self, api):
        """PRD §3.3: "The account must not be in `DIRECT_LOCKED`, and no **other** registration on
        the same account-and-product-line pair may be in `APPROVED` holding a live exclusivity
        window at the current logical instant — with one carve-out: an incumbent is ignored when it
        is precisely the registration this one supersedes and it belongs to the same partner."

        Design: Difficulty/cross_entity_state_dependency/registration_submit_depends_on_account_direct_locked_state
        """
        seed = seed_direct_locked_account()
        challenger_id = seed["challenger"]["id"]

        open_account = create_account(account_name="Lakeside Utilities", region_code="NA")
        blocked = draft_registration(
            challenger_id,
            seed["account"]["id"],
            product_line="ANALYTICS_ADDON",
            expected_amount_cents=400_000,
            expected_close_date="2026-09-30T00:00:00.000Z",
        )
        allowed = draft_registration(
            challenger_id,
            open_account["id"],
            product_line="ANALYTICS_ADDON",
            expected_amount_cents=400_000,
            expected_close_date="2026-09-30T00:00:00.000Z",
        )

        api.submit_deal_registration(blocked["id"], make_partner_headers(challenger_id))
        submitted = validate_success(
            api.submit_deal_registration(allowed["id"], make_partner_headers(challenger_id))
        )

        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_at"] == "2026-04-01T00:00:00.000Z"
        assert read_account(open_account["id"])["coverage_state"] == "OPEN_CHANNEL"

        challenger = read_partner(challenger_id)
        assert challenger["tier_status"] == "COMPLIANT"
        assert challenger["open_conflict_count"] == 0


class TestClaimCreateDependsOnAllocationStatus:
    def test_closing_the_period_rejects_the_in_flight_claim_and_burns_the_balance(self, api):
        """PRD §3.8: "Step one, first: every claim of this period whose `validation_state` is
        `SUBMITTED` or `PROOF_REQUESTED` moves to `validation_state` `REJECTED` with
        `approved_cents` set to 0 and `rejection_reason` set to `PERIOD_CLOSED`, and the period's
        `committed_cents` decreases by that claim's `requested_cents`."
        PRD §3.8: "Step three, third, operating on the balance the first two steps have produced:
        the period's `expired_cents` increases by its current `available_cents`, and
        `available_cents` is then set to 0."

        Design: Difficulty/cross_entity_state_dependency/mdf_claim_create_depends_on_allocation_closed_state
        """
        seed = seed_gold_distributor_with_allocation()
        allocation_id = seed["allocation"]["id"]
        partner_id = seed["partner"]["id"]

        claim = create_claim(
            allocation_id, partner_id, activity_type="DIGITAL_CAMPAIGN", requested_cents=30_000
        )
        assert read_allocation(allocation_id)["committed_cents"] == 30000
        assert read_allocation(allocation_id)["available_cents"] == 243000

        closed = close_allocation(allocation_id)
        assert closed["status"] == "CLOSED"

        swept = read_claim(claim["id"])
        assert swept["validation_state"] == "REJECTED"
        assert swept["approved_cents"] == 0
        assert swept["rejection_reason"] == "PERIOD_CLOSED"
        assert swept["settlement_state"] == "UNPAID"

        allocation = read_allocation(allocation_id)
        assert allocation["allocated_cents"] == 273000
        assert allocation["committed_cents"] == 0
        assert allocation["paid_cents"] == 0
        assert allocation["expired_cents"] == 273000
        assert allocation["available_cents"] == 0
        assert_mdf_fund_conservation(allocation)

    def test_the_closed_period_reports_the_structural_refusal_not_a_shortage(self, api):
        """PRD §2.8: "**Fund period open.** The `MdfAllocation` behind the operation has `status`
        of `OPEN` — otherwise `ERR_ALLOCATION_CLOSED` (409). This guards six operations: creating a
        claim, validating a claim, attaching a proof document, verifying a proof document, the
        `APPROVE_PAYMENT` and `PAY` settlement actions, and closing the period itself (a period
        already `CLOSED` cannot be closed again)."
        PRD §3.1: "Verified evidence hanging off a claim that is merely `SUBMITTED`, still
        `PROOF_REQUESTED`, or already `REJECTED` contributes nothing, so the very same document can
        enter and leave the numerator as its claim is validated and later clawed back."

        Design: Difficulty/cross_entity_state_dependency/mdf_claim_create_depends_on_allocation_closed_state
        """
        seed = seed_gold_distributor_with_allocation()
        allocation_id = seed["allocation"]["id"]
        partner_id = seed["partner"]["id"]

        create_claim(
            allocation_id, partner_id, activity_type="DIGITAL_CAMPAIGN", requested_cents=30_000
        )
        close_allocation(allocation_id)

        response = api.create_mdf_claim(
            {
                "allocation_id": allocation_id,
                "activity_type": "EVENT",
                "requested_cents": 10000,
            },
            make_partner_headers(partner_id),
        )
        validate_error(response, ApiErrorId.ERR_ALLOCATION_CLOSED.value, 409)
        assert (
            response.json()["data"]["error_id"]
            != ApiErrorId.ERR_MDF_ALLOCATION_INSUFFICIENT.value
        )

        rows, _ = validate_paginated(api.list_allocation_mdf_claims(allocation_id, ANALYST))
        assert len(rows) == 1

        assert read_partner(partner_id)["marketing_qualified_spend_cents"] == 0
