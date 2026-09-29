"""The two independent tracks of a purchase request: approval, claim and settlement."""

from test_helpers import (
    ER1,
    ER2,
    PA,
    Q1_ADMIN_FEE_CENTS,
    Q1_GROSS_CENTS,
    Q1_NET_CENTS,
    ApiErrorId,
    assert_ledger_identity,
    assert_purchase_request,
    claim_purchase_request,
    create_claim_payload,
    create_curriculum_provider_payload,
    decide_purchase_request,
    file_purchase_request,
    make_provider_headers,
    read_account,
    read_purchase_request,
    setup_approved_provider,
    setup_approved_purchase_request,
    setup_pending_purchase_request,
    setup_purchase_environment,
    validate_error,
    validate_paginated,
    validate_success,
)

REQUEST_AMOUNT_CENTS = 150000
HOLD_BALANCE_CENTS = Q1_NET_CENTS - REQUEST_AMOUNT_CENTS


class TestClaimAdvancesWhileApprovalIsPending:
    """The money track moves on the provider's initiative, the approval track does not."""

    def test_a_claim_lands_while_review_is_pending_and_settlement_is_refused(self, api):
        """PRD §3.7: "The request's `settlement_status` must be `UNSETTLED`; its
        `approval_status` must be `PENDING_REVIEW` or `APPROVED`, and the approval dimension
        expressly does **not** need to have advanced yet — a provider may invoice while
        review is still pending, which is the whole point of two independent dimensions."

        PRD §3.7: "`approval_status` must be `APPROVED`, which is the cross-dimension guard
        that stops money leaving on an unapproved request and reports
        `ERR_INVALID_STATE_TRANSITION` when it is not met"

        Design: Difficulty/non_linear_state_machine/purchase_request_claim_advances_while_approval_still_pending
        """
        env = setup_purchase_environment(quarters=1, provider_codes=("TUTORING",))
        env = setup_pending_purchase_request(
            env, category_key="tutoring", amount_cents=REQUEST_AMOUNT_CENTS
        )
        assert env.purchase_request["approval_status"] == "PENDING_REVIEW", (
            f"the request starts unreviewed, got {env.purchase_request['approval_status']!r}"
        )
        assert env.purchase_request["settlement_status"] == "UNSETTLED", (
            f"and unsettled, got {env.purchase_request['settlement_status']!r}"
        )

        claimed = claim_purchase_request(
            env.purchase_request_id,
            env.provider_id,
            REQUEST_AMOUNT_CENTS,
            "INV-1001",
        )
        assert_purchase_request(claimed)
        assert claimed["settlement_status"] == "CLAIMED", (
            f"the money track advanced to CLAIMED, got {claimed['settlement_status']!r}"
        )
        assert claimed["approval_status"] == "PENDING_REVIEW", (
            "while the approval track stayed exactly where it was, got "
            f"{claimed['approval_status']!r}"
        )
        assert claimed["claimed_amount_cents"] == REQUEST_AMOUNT_CENTS, (
            f"the invoiced amount was recorded, got {claimed['claimed_amount_cents']}"
        )
        assert claimed["invoice_reference"] == "INV-1001", (
            f"along with the vendor's own reference, got {claimed['invoice_reference']!r}"
        )
        assert claimed["version"] == env.purchase_request["version"] + 1, (
            f"and the request's version rose by 1, got {claimed['version']}"
        )

        mid = read_account(env.account_id)
        assert mid["balance_cents"] == Q1_NET_CENTS, (
            f"a claim moves no money at all, got {mid['balance_cents']}"
        )
        assert mid["encumbered_cents"] == 0, (
            f"and places no hold, got {mid['encumbered_cents']}"
        )

        refused = api.settle_purchase_request(env.purchase_request_id, ER2)
        validate_error(refused, ApiErrorId.INVALID_STATE_TRANSITION.value, 409)

        after = read_purchase_request(env.purchase_request_id)
        assert after["settlement_status"] == "CLAIMED", (
            "the refused settlement left the money track at CLAIMED, got "
            f"{after['settlement_status']!r}"
        )
        assert after["paid_amount_cents"] is None, (
            f"and nothing was paid, got {after['paid_amount_cents']!r}"
        )
        assert after["settled_by_user_id"] is None, (
            f"nor was a settler recorded, got {after['settled_by_user_id']!r}"
        )
        assert read_account(env.account_id)["lifetime_spent_cents"] == 0, (
            "and the account has spent nothing"
        )

    def test_the_standing_claim_pays_out_once_the_approval_arrives(self, api):
        """PRD §3.7: "Settlement is performed by an `ExpenseReviewer` and advances the money
        track `CLAIMED → PAID`."

        PRD §3.7: "The account's `encumbered_cents` falls by the full `amount_cents` that
        was held, its `lifetime_spent_cents` rises by `claimed_amount_cents`, and its
        `balance_cents` rises by `amount_cents` less `claimed_amount_cents` — the unspent
        portion of the hold, which the response reports as `released_cents`."

        Design: Difficulty/non_linear_state_machine/purchase_request_claim_advances_while_approval_still_pending
        """
        env = setup_purchase_environment(quarters=1, provider_codes=("TUTORING",))
        env = setup_pending_purchase_request(
            env, category_key="tutoring", amount_cents=REQUEST_AMOUNT_CENTS
        )
        claimed = claim_purchase_request(
            env.purchase_request_id, env.provider_id, 120000, "INV-1002"
        )
        assert claimed["settlement_status"] == "CLAIMED", (
            "the vendor invoiced 120000 against a 150000 authorisation before any review, "
            f"got {claimed['settlement_status']!r}"
        )

        approved = decide_purchase_request(
            env.purchase_request_id, "APPROVED", headers=ER1
        )
        assert approved["approval_status"] == "APPROVED", (
            f"the approval track now advances on its own, got "
            f"{approved['approval_status']!r}"
        )
        assert approved["settlement_status"] == "CLAIMED", (
            "and the standing claim is untouched by it because the flow is PREAPPROVAL, "
            f"got {approved['settlement_status']!r}"
        )
        held = read_account(env.account_id)
        assert held["encumbered_cents"] == REQUEST_AMOUNT_CENTS, (
            f"the approval holds the full authorised amount, got "
            f"{held['encumbered_cents']}"
        )

        settlement = validate_success(
            api.settle_purchase_request(env.purchase_request_id, ER2)
        )
        assert settlement["settlement_status"] == "PAID", (
            f"with both dimensions aligned the money leaves, got "
            f"{settlement['settlement_status']!r}"
        )
        assert settlement["paid_amount_cents"] == 120000, (
            f"paying the claimed 120000, got {settlement['paid_amount_cents']}"
        )
        assert settlement["released_cents"] == REQUEST_AMOUNT_CENTS - 120000, (
            f"and returning the unspent 30000, got {settlement['released_cents']}"
        )
        assert settlement["account_encumbered_cents"] == 0, (
            f"the hold is gone, got {settlement['account_encumbered_cents']}"
        )

        account = read_account(env.account_id)
        assert account["encumbered_cents"] == 0, (
            f"nothing remains encumbered, got {account['encumbered_cents']}"
        )
        assert account["lifetime_spent_cents"] == 120000, (
            f"the spend counter carries the claimed amount, got "
            f"{account['lifetime_spent_cents']}"
        )
        assert account["balance_cents"] == Q1_NET_CENTS - 120000, (
            f"and the balance is the credit less the spend, got {account['balance_cents']}"
        )
        assert_ledger_identity(account)


class TestApprovalHold:
    """The hold is not a projection that catches up later."""

    def test_the_hold_is_readable_on_the_account_the_instant_the_decision_returns(
        self, api
    ):
        """PRD §3.7: "On success the reviewer's `X-User-ID` is stored as
        `approved_by_user_id`, and the hold is placed: `balance_cents` falls by
        `amount_cents` and `encumbered_cents` rises by the same `amount_cents`. Both the
        request's `version` and the account's `version` rise by 1."

        PRD §2.11: "An ESA account is a small ledger, and its fields are related by
        identities that must hold after every operation."

        Design: Corner/consistency_model/approval_hold_is_visible_in_the_response_and_on_reread
        """
        env = setup_purchase_environment(quarters=1, provider_codes=("TUTORING",))
        env = setup_pending_purchase_request(
            env, category_key="tutoring", amount_cents=REQUEST_AMOUNT_CENTS
        )
        before = read_account(env.account_id)
        assert before["balance_cents"] == Q1_NET_CENTS, (
            f"the account holds the quarter-1 credit, got {before['balance_cents']}"
        )
        assert before["encumbered_cents"] == 0, (
            f"with nothing committed, got {before['encumbered_cents']}"
        )

        decision = validate_success(
            api.decide_purchase_request(
                env.purchase_request_id, {"decision": "APPROVED"}, ER1
            )
        )
        assert_purchase_request(decision)
        assert decision["approval_status"] == "APPROVED", (
            f"the decision response carries the advanced request, got "
            f"{decision['approval_status']!r}"
        )
        assert decision["approved_by_user_id"] == ER1["X-User-ID"], (
            f"naming the reviewer who placed the hold, got "
            f"{decision['approved_by_user_id']!r}"
        )
        assert decision["version"] == env.purchase_request["version"] + 1, (
            f"and the request's version rose by 1, got {decision['version']}"
        )

        account = validate_success(api.get_account(env.account_id, env.guardian))
        assert account["balance_cents"] == HOLD_BALANCE_CENTS, (
            "the very next read already shows the balance at 79088, so no denormalised "
            f"figure lags behind the request row, got {account['balance_cents']}"
        )
        assert account["encumbered_cents"] == REQUEST_AMOUNT_CENTS, (
            f"and 150000 under encumbrance, got {account['encumbered_cents']}"
        )
        assert account["version"] == before["version"] + 1, (
            f"the account's own version rose by 1, got {account['version']}"
        )
        assert account["lifetime_spent_cents"] == 0, (
            f"a hold is not a spend, got {account['lifetime_spent_cents']}"
        )
        assert account["lifetime_disbursed_cents"] == Q1_GROSS_CENTS, (
            f"and no credit changed, got {account['lifetime_disbursed_cents']}"
        )
        assert account["lifetime_admin_fee_cents"] == Q1_ADMIN_FEE_CENTS, (
            f"nor did the fee, got {account['lifetime_admin_fee_cents']}"
        )
        assert_ledger_identity(account)


class TestClaimCeiling:
    """The authorised amount is the claim ceiling, and it is inclusive."""

    def test_one_cent_above_the_authorised_amount_is_refused_and_the_equal_claim_passes(
        self, api
    ):
        """PRD §3.7: "And `claimed_amount_cents` must be at least 1 and no greater than the
        request's `amount_cents`, else `ERR_CLAIM_AMOUNT_MISMATCH`."

        PRD §3.7: "On success both `claimed_amount_cents` and `invoice_reference` are
        recorded and the request's `version` rises by 1."

        Design: Corner/validations/claim_above_the_approved_amount_is_rejected_while_the_equal_claim_passes
        """
        env = setup_purchase_environment(quarters=1, provider_codes=("TUTORING",))
        env = setup_approved_purchase_request(
            env, category_key="tutoring", amount_cents=REQUEST_AMOUNT_CENTS
        )
        before = read_purchase_request(env.purchase_request_id)
        assert before["amount_cents"] == REQUEST_AMOUNT_CENTS, (
            f"the authorised maximum is 150000, got {before['amount_cents']}"
        )
        provider_headers = make_provider_headers(env.provider_id)

        refused = api.claim_purchase_request(
            env.purchase_request_id,
            create_claim_payload(REQUEST_AMOUNT_CENTS + 1, "INV-2001"),
            provider_headers,
        )
        validate_error(refused, ApiErrorId.CLAIM_AMOUNT_MISMATCH.value, 422)

        unchanged = read_purchase_request(env.purchase_request_id)
        assert unchanged["settlement_status"] == "UNSETTLED", (
            f"the refused claim left the money track alone, got "
            f"{unchanged['settlement_status']!r}"
        )
        assert unchanged["claimed_amount_cents"] is None, (
            f"recording no amount, got {unchanged['claimed_amount_cents']!r}"
        )
        assert unchanged["invoice_reference"] is None, (
            f"and no reference, got {unchanged['invoice_reference']!r}"
        )
        assert unchanged["version"] == before["version"], (
            f"nor bumping the version, got {unchanged['version']}"
        )

        accepted = validate_success(
            api.claim_purchase_request(
                env.purchase_request_id,
                create_claim_payload(REQUEST_AMOUNT_CENTS, "INV-2002"),
                provider_headers,
            )
        )
        assert accepted["settlement_status"] == "CLAIMED", (
            "the exactly-equal claim is inside the ceiling, so a strict comparison would "
            f"wrongly reject it, got {accepted['settlement_status']!r}"
        )
        assert accepted["claimed_amount_cents"] == REQUEST_AMOUNT_CENTS, (
            f"and it records the full 150000, got {accepted['claimed_amount_cents']}"
        )
        assert accepted["version"] == before["version"] + 1, (
            f"with a single version step for the single accepted write, got "
            f"{accepted['version']}"
        )


class TestClaimOwnership:
    """The claim route is scoped to the vendor named on the row, not to the role."""

    def test_a_different_approved_vendor_cannot_invoice_against_the_request(self, api):
        """PRD §2.1: "When `X-User-Role` is `Provider`, `X-User-ID` is the `id` of the
        acting `Provider`; a provider may act only on a purchase request whose `provider_id`
        equals `X-User-ID`, or file an appeal about itself, and a mismatch is rejected with
        `ERR_NOT_ASSIGNED_PROVIDER`."

        Design: Corner/errors/provider_cannot_claim_another_providers_purchase_request
        """
        env = setup_purchase_environment(quarters=1, provider_codes=("TUTORING",))
        env = setup_approved_purchase_request(
            env, category_key="tutoring", amount_cents=REQUEST_AMOUNT_CENTS
        )
        outsider = setup_approved_provider(
            payload_builder=create_curriculum_provider_payload,
            flags=[],
            codes=["TUTORING"],
        )
        assert outsider.provider["status"] == "APPROVED", (
            "the outsider is itself an admitted vendor, got "
            f"{outsider.provider['status']!r}"
        )
        assert outsider.provider_id != env.provider_id, (
            "but it is not the vendor named on the request"
        )

        refused = api.claim_purchase_request(
            env.purchase_request_id,
            create_claim_payload(REQUEST_AMOUNT_CENTS, "INV-3001"),
            make_provider_headers(outsider.provider_id),
        )
        validate_error(refused, ApiErrorId.NOT_ASSIGNED_PROVIDER.value, 403)

        untouched = read_purchase_request(env.purchase_request_id)
        assert untouched["settlement_status"] == "UNSETTLED", (
            f"the row is untouched, got {untouched['settlement_status']!r}"
        )
        assert untouched["invoice_reference"] is None, (
            f"and holds no foreign invoice reference, got "
            f"{untouched['invoice_reference']!r}"
        )

        accepted = validate_success(
            api.claim_purchase_request(
                env.purchase_request_id,
                create_claim_payload(REQUEST_AMOUNT_CENTS, "INV-3002"),
                make_provider_headers(env.provider_id),
            )
        )
        assert accepted["settlement_status"] == "CLAIMED", (
            "the vendor actually named on the request invoices without trouble, got "
            f"{accepted['settlement_status']!r}"
        )
        assert accepted["provider_id"] == env.provider_id, (
            f"and the row still names that vendor, got {accepted['provider_id']!r}"
        )


class TestSegregationOfDuties:
    """The paired steps are blocked per user, not per role."""

    def test_the_approver_cannot_settle_but_a_second_reviewer_can(self, api):
        """PRD §2.1: "The `ExpenseReviewer` whose `X-User-ID` was recorded as
        `approved_by_user_id` on a purchase request may not settle that request"

        PRD §3.7: "the acting `X-User-ID` must differ from `approved_by_user_id`, else
        `ERR_SEGREGATION_OF_DUTIES`"

        Design: Corner/rbac/approver_cannot_settle_the_request_they_approved
        """
        env = setup_purchase_environment(quarters=1, provider_codes=("TUTORING",))
        env = setup_approved_purchase_request(
            env, approver=ER1, category_key="tutoring", amount_cents=REQUEST_AMOUNT_CENTS
        )
        claimed = claim_purchase_request(
            env.purchase_request_id,
            env.provider_id,
            REQUEST_AMOUNT_CENTS,
            "INV-4001",
        )
        assert claimed["approved_by_user_id"] == ER1["X-User-ID"], (
            f"er-1 approved the request, got {claimed['approved_by_user_id']!r}"
        )

        refused = api.settle_purchase_request(env.purchase_request_id, ER1)
        validate_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)

        blocked = read_purchase_request(env.purchase_request_id)
        assert blocked["settlement_status"] == "CLAIMED", (
            f"no money left on the blocked attempt, got {blocked['settlement_status']!r}"
        )
        assert blocked["settled_by_user_id"] is None, (
            f"and no settler was recorded, got {blocked['settled_by_user_id']!r}"
        )
        assert read_account(env.account_id)["encumbered_cents"] == REQUEST_AMOUNT_CENTS, (
            "with the hold still standing"
        )

        settlement = validate_success(
            api.settle_purchase_request(env.purchase_request_id, ER2)
        )
        assert settlement["settlement_status"] == "PAID", (
            "a second reviewer in the identical role settles the same request, so the "
            f"block is per user id, got {settlement['settlement_status']!r}"
        )
        assert settlement["paid_amount_cents"] == REQUEST_AMOUNT_CENTS, (
            f"paying the claimed amount in full, got {settlement['paid_amount_cents']}"
        )
        assert settlement["released_cents"] == 0, (
            f"with nothing left over to release, got {settlement['released_cents']}"
        )

        settled = read_purchase_request(env.purchase_request_id)
        assert settled["settled_by_user_id"] == ER2["X-User-ID"], (
            f"the row names er-2 as the settler, got {settled['settled_by_user_id']!r}"
        )
        account = read_account(env.account_id)
        assert account["lifetime_spent_cents"] == REQUEST_AMOUNT_CENTS, (
            f"the spend is booked once, got {account['lifetime_spent_cents']}"
        )
        assert account["balance_cents"] == HOLD_BALANCE_CENTS, (
            f"and the balance stays at the held figure, got {account['balance_cents']}"
        )
        assert_ledger_identity(account)


class TestApprovalBalanceGate:
    """The balance guard belongs to the approval, not to the filing."""

    def test_the_second_approval_beyond_the_remaining_balance_is_refused(self, api):
        """PRD §3.7: "and `amount_cents` must not exceed the account's `balance_cents`, else
        `ERR_INSUFFICIENT_BALANCE`."

        PRD §2.8: "36. The account balance covers the hold — `ERR_INSUFFICIENT_BALANCE`, on
        an approval-track decision of `APPROVED`."

        Design: Corner/validations/approval_beyond_available_balance_returns_payment_required
        """
        env = setup_purchase_environment(quarters=1, provider_codes=("TUITION",))
        assert env.tuition["per_year_cap_cents"] == 500000, (
            f"the tuition ceiling is 500000, got {env.tuition['per_year_cap_cents']}"
        )
        env = setup_approved_purchase_request(
            env, category_key="tuition", amount_cents=REQUEST_AMOUNT_CENTS
        )
        first_hold = read_account(env.account_id)
        assert first_hold["balance_cents"] == HOLD_BALANCE_CENTS, (
            f"the first approval left 79088 spendable, got {first_hold['balance_cents']}"
        )
        assert first_hold["encumbered_cents"] == REQUEST_AMOUNT_CENTS, (
            f"with 150000 encumbered, got {first_hold['encumbered_cents']}"
        )

        second = file_purchase_request(
            env.account_id,
            env.student_id,
            env.provider_id,
            env.tuition["id"],
            amount_cents=REQUEST_AMOUNT_CENTS,
        )
        assert second["approval_status"] == "PENDING_REVIEW", (
            "the second filing is accepted because the aggregate 300000 is under the "
            f"500000 ceiling, got {second['approval_status']!r}"
        )

        refused = api.decide_purchase_request(
            second["id"], {"decision": "APPROVED"}, ER1
        )
        validate_error(refused, ApiErrorId.INSUFFICIENT_BALANCE.value, 402)

        still_pending = read_purchase_request(second["id"])
        assert still_pending["approval_status"] == "PENDING_REVIEW", (
            "only the hold failed, so the request stays reviewable, got "
            f"{still_pending['approval_status']!r}"
        )
        assert still_pending["approved_by_user_id"] is None, (
            f"and records no approver, got {still_pending['approved_by_user_id']!r}"
        )

        account = read_account(env.account_id)
        assert account["balance_cents"] == HOLD_BALANCE_CENTS, (
            f"the balance is untouched by the refusal, got {account['balance_cents']}"
        )
        assert account["encumbered_cents"] == REQUEST_AMOUNT_CENTS, (
            f"and only the first hold stands, got {account['encumbered_cents']}"
        )
        assert_ledger_identity(account)

        _, meta = validate_paginated(
            api.list_purchase_requests(PA, params={"account_id": env.account_id})
        )
        assert meta["total_count"] == 2, (
            f"both requests exist, one approved and one still pending, got "
            f"{meta['total_count']}"
        )
