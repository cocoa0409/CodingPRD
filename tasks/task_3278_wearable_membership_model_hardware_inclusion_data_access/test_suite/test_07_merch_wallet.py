"""Merch commerce: pricing rules, wallet ledger conservation, version increments."""
from test_helpers import (
    ApiErrorId,
    create_member_with_term,
    get_success_data,
    make_member_headers,
    make_support_headers,
    pause_term,
    record_payment,
    resume_term,
    setup_funded_wallet,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestMerchPricing:
    def test_merch_pricing_tier_bundle_cap_interaction(self, api, anonymous_headers):
        """PRD: "The member discount applies when the member's current term — one
        in ACTIVE or PAUSED status — has hardware_tier BAND_PRO; then
        member_discount_cents is ten percent of the subtotal, rounded half-up to
        whole cents".
        PRD: "The bundle discount looks only at APPAREL lines: when the total
        apparel quantity is at least three, bundle_discount_cents is five percent
        of the apparel subtotal — the sum of quantity times unit price over the
        apparel lines — rounded half-up to whole cents, and otherwise it is zero.
        The combined discount is then capped: discount_cents is the smaller of the
        sum of the two discount components and thirty percent of the subtotal
        rounded half-up to whole cents. Finally total_cents is the subtotal minus
        the capped discount."

        Design: Difficulty/combinatorial_formula/merch_pricing_tier_bundle_cap_interaction
        """
        member, term = setup_funded_wallet(
            term_overrides={"hardware_tier": "BAND_PRO"}
        )
        order = validate_success(
            api.place_merch_order(
                member["id"],
                {
                    "lines": [
                        {"sku": "A1", "category": "APPAREL", "unit_price_cents": 10000, "qty": 3},
                        {"sku": "B1", "category": "BAND_ACCESSORY", "unit_price_cents": 10000, "qty": 1},
                    ]
                },
                make_member_headers(member["id"]),
            ),
            expected_status=201,
        )
        assert order["subtotal_cents"] == 40000
        assert order["member_discount_cents"] == 4000
        assert order["bundle_discount_cents"] == 1500
        assert order["discount_cents"] == 5500
        assert order["total_cents"] == 34500

    def test_merch_pricing_debits_wallet_by_total(self, api, anonymous_headers):
        """PRD: "placing a merch order debits the order's total_cents".

        Design: Difficulty/combinatorial_formula/merch_pricing_tier_bundle_cap_interaction
        """
        member, term = setup_funded_wallet(
            term_overrides={"hardware_tier": "BAND_PRO"}
        )
        validate_success(
            api.place_merch_order(
                member["id"],
                {
                    "lines": [
                        {"sku": "A1", "category": "APPAREL", "unit_price_cents": 10000, "qty": 3},
                        {"sku": "B1", "category": "BAND_ACCESSORY", "unit_price_cents": 10000, "qty": 1},
                    ]
                },
                make_member_headers(member["id"]),
            ),
            expected_status=201,
        )
        member_after = validate_success(
            api.get_member(member["id"], make_member_headers(member["id"]))
        )
        assert member_after["wallet_credit_cents"] == 90000 - 34500

    def test_merch_pricing_components_rounded_then_summed_then_capped(self, api, anonymous_headers):
        """PRD: "For merch pricing the rounding order is pinned: each discount
        component is rounded to cents individually, the components are then
        summed, and only then is the percentage cap applied."

        Design: Corner/calculations/merch_pricing_cap_binds
        """
        member, term = setup_funded_wallet(
            term_overrides={"hardware_tier": "BAND_PRO"}
        )
        order = validate_success(
            api.place_merch_order(
                member["id"],
                {
                    "lines": [
                        {"sku": "AP", "category": "APPAREL", "unit_price_cents": 3000, "qty": 3},
                    ]
                },
                make_member_headers(member["id"]),
            ),
            expected_status=201,
        )
        assert order["subtotal_cents"] == 9000
        assert order["member_discount_cents"] == 900
        assert order["bundle_discount_cents"] == 450
        # cap = 2700; min(1350, 2700) = 1350 (component sum below cap)
        assert order["discount_cents"] == 1350
        assert order["total_cents"] == 7650

    def test_merch_pricing_wallet_reflects_capped_discount(self, api, anonymous_headers):
        """PRD: "placing a merch order debits the order's total_cents".
        PRD: "The wallet is funded in exactly one way — the proration credit
        issued when a member resumes early from an open pause".

        Design: Corner/calculations/merch_pricing_cap_binds
        """
        member, term = setup_funded_wallet(
            term_overrides={"hardware_tier": "BAND_PRO"}
        )
        validate_success(
            api.place_merch_order(
                member["id"],
                {
                    "lines": [
                        {"sku": "AP", "category": "APPAREL", "unit_price_cents": 3000, "qty": 3},
                    ]
                },
                make_member_headers(member["id"]),
            ),
            expected_status=201,
        )
        member_after = validate_success(
            api.get_member(member["id"], make_member_headers(member["id"]))
        )
        assert member_after["wallet_credit_cents"] == 90000 - 7650

    def test_member_discount_gated_on_term_status(self, api, anonymous_headers):
        """PRD: "The member discount applies when the member's current term — one
        in ACTIVE or PAUSED status — has hardware_tier BAND_PRO; then
        member_discount_cents is ten percent of the subtotal, rounded half-up to
        whole cents, and otherwise (including when the member has no such term at
        all) it is zero."

        Design: Corner/calculations/member_discount_gated_on_term_status
        """
        member, term = setup_funded_wallet(
            term_overrides={"hardware_tier": "BAND_PRO"}
        )
        # Cancel the only term: the member now has no term in ACTIVE or PAUSED.
        validate_success(api.cancel_term(term["id"], make_member_headers(member["id"])))
        order = validate_success(
            api.place_merch_order(
                member["id"],
                {
                    "lines": [
                        {"sku": "AP", "category": "APPAREL", "unit_price_cents": 3000, "qty": 3},
                    ]
                },
                make_member_headers(member["id"]),
            ),
            expected_status=201,
        )
        assert order["subtotal_cents"] == 9000
        assert order["member_discount_cents"] == 0
        assert order["bundle_discount_cents"] == 450
        assert order["discount_cents"] == 450
        assert order["total_cents"] == 8550

    def test_member_discount_zero_when_no_qualifying_term_wallet_effect(self, api, anonymous_headers):
        """PRD: "The member discount applies when the member's current term — one
        in ACTIVE or PAUSED status — has hardware_tier BAND_PRO; then
        member_discount_cents is ten percent of the subtotal, rounded half-up to
        whole cents, and otherwise (including when the member has no such term at
        all) it is zero."

        Design: Corner/calculations/member_discount_gated_on_term_status
        """
        member, term = setup_funded_wallet(
            term_overrides={"hardware_tier": "BAND_PRO"}
        )
        validate_success(api.cancel_term(term["id"], make_member_headers(member["id"])))
        validate_success(
            api.place_merch_order(
                member["id"],
                {
                    "lines": [
                        {"sku": "AP", "category": "APPAREL", "unit_price_cents": 3000, "qty": 3},
                    ]
                },
                make_member_headers(member["id"]),
            ),
            expected_status=201,
        )
        member_after = validate_success(
            api.get_member(member["id"], make_member_headers(member["id"]))
        )
        assert member_after["wallet_credit_cents"] == 90000 - 8550


class TestWalletLedgerConservation:
    def test_wallet_conserved_across_merch_order_and_cancel(self, api, anonymous_headers):
        """PRD: "The wallet invariant is that a placement debit followed by that
        order's cancellation credit leaves the balance unchanged."

        Design: Difficulty/compensating_invariant/wallet_conserved_across_merch_order_and_cancel
        """
        member, term = setup_funded_wallet()  # BAND_STD, wallet 90000
        headers = make_member_headers(member["id"])
        order = validate_success(
            api.place_merch_order(
                member["id"],
                {
                    "lines": [
                        {"sku": "S1", "category": "BAND_ACCESSORY", "unit_price_cents": 12345, "qty": 2},
                    ]
                },
                headers,
            ),
            expected_status=201,
        )
        assert order["subtotal_cents"] == 24690
        assert order["member_discount_cents"] == 0
        assert order["bundle_discount_cents"] == 0
        assert order["total_cents"] == 24690
        after_place = validate_success(api.get_member(member["id"], headers))
        assert after_place["wallet_credit_cents"] == 65310
        cancelled = validate_success(api.cancel_merch_order(order["id"], headers))
        assert cancelled["order_status"] == "CANCELLED"
        after_cancel = validate_success(api.get_member(member["id"], headers))
        assert after_cancel["wallet_credit_cents"] == 90000

    def test_cancel_credits_exactly_order_total(self, api, anonymous_headers):
        """PRD: "cancelling a paid order credits exactly that same total_cents
        back".

        Design: Difficulty/compensating_invariant/wallet_conserved_across_merch_order_and_cancel
        """
        member, term = setup_funded_wallet()
        headers = make_member_headers(member["id"])
        order = validate_success(
            api.place_merch_order(
                member["id"],
                {
                    "lines": [
                        {"sku": "S1", "category": "BAND_ACCESSORY", "unit_price_cents": 12345, "qty": 2},
                    ]
                },
                headers,
            ),
            expected_status=201,
        )
        after_place = validate_success(api.get_member(member["id"], headers))
        validate_success(api.cancel_merch_order(order["id"], headers))
        after_cancel = validate_success(api.get_member(member["id"], headers))
        assert (
            after_cancel["wallet_credit_cents"]
            == after_place["wallet_credit_cents"] + order["total_cents"]
        )


class TestWalletGuards:
    def test_insufficient_wallet_rejected(self, api, anonymous_headers):
        """PRD: "The wallet may never go negative, so an order whose total_cents
        exceeds the member's current wallet_credit_cents is refused with
        ERR_INSUFFICIENT_WALLET_CREDIT."

        Design: Corner/validations/insufficient_wallet_rejected
        """
        member, term = create_member_with_term()  # wallet stays 0
        resp = api.place_merch_order(
            member["id"],
            {
                "lines": [
                    {"sku": "B1", "category": "BAND_ACCESSORY", "unit_price_cents": 1000, "qty": 1},
                ]
            },
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_WALLET_CREDIT, expected_status=422)

    def test_insufficient_wallet_creates_no_order(self, api, anonymous_headers):
        """PRD: "placement requires wallet_credit_cents to cover the order's
        total_cents, failing which the placement is refused with
        ERR_INSUFFICIENT_WALLET_CREDIT and nothing is created."

        Design: Corner/validations/insufficient_wallet_rejected
        """
        member, term = create_member_with_term()
        headers = make_member_headers(member["id"])
        api.place_merch_order(
            member["id"],
            {
                "lines": [
                    {"sku": "B1", "category": "BAND_ACCESSORY", "unit_price_cents": 1000, "qty": 1},
                ]
            },
            headers,
        )
        member_after = validate_success(api.get_member(member["id"], headers))
        assert member_after["wallet_credit_cents"] == 0
        orders, _ = validate_paginated(api.list_member_merch_orders(member["id"], headers))
        assert orders == []


class TestVersionIncrements:
    def test_version_increments_on_mutation(self, api, anonymous_headers):
        """PRD: "version is an integer that increments by one on every mutation of
        the resource and is the basis of the optimistic concurrency checks
        described in §2.7."
        PRD: "A successful placement decrements wallet_credit_cents by total_cents
        and increments the member's version by one."
        PRD: "The member's version increments with the credit."

        Design: Corner/cross_cutting/version_increments_on_mutation
        """
        member, term = setup_funded_wallet()  # registration v1; resume credit -> v2
        headers = make_member_headers(member["id"])
        before = validate_success(api.get_member(member["id"], headers))
        assert before["version"] == 2
        order = validate_success(
            api.place_merch_order(
                member["id"],
                {
                    "lines": [
                        {"sku": "B1", "category": "BAND_ACCESSORY", "unit_price_cents": 100, "qty": 1},
                    ]
                },
                headers,
            ),
            expected_status=201,
        )
        validate_success(api.cancel_merch_order(order["id"], headers))
        final = validate_success(api.get_member(member["id"], headers))
        assert final["version"] == 4

    def test_wallet_credit_mutation_visible_on_read(self, api, anonymous_headers):
        """PRD: "version is an integer that increments by one on every mutation of
        the resource".
        PRD: "The wallet is funded in exactly one way — the proration credit
        issued when a member resumes early from an open pause".

        Design: Corner/cross_cutting/version_increments_on_mutation
        """
        member, term = setup_funded_wallet()
        after = validate_success(
            api.get_member(member["id"], make_member_headers(member["id"]))
        )
        assert after["wallet_credit_cents"] == 90000
        assert after["version"] == 2


class TestSuspendedMemberCancel:
    def test_cascading_merch_cancel_after_suspend_still_allowed(self, api, anonymous_headers):
        """PRD: "Cancellation is the compensating action: the owning member or
        Support cancels an order in PAID status, moving it to the terminal
        CANCELLED state, and the member's wallet is credited exactly the order's
        total_cents".
        PRD: "While a member is SUSPENDED, five kinds of action are blocked and
        refused with ERR_MEMBER_SUSPENDED: starting a new term, upgrading
        hardware, placing a merch order, enrolling in a research study, and
        granting consent scopes."

        Design: Corner/cross_cutting/cascading_merch_cancel_after_suspend_still_allowed
        """
        member, term = setup_funded_wallet()
        headers = make_member_headers(member["id"])
        order = validate_success(
            api.place_merch_order(
                member["id"],
                {
                    "lines": [
                        {"sku": "B1", "category": "BAND_ACCESSORY", "unit_price_cents": 100, "qty": 1},
                    ]
                },
                headers,
            ),
            expected_status=201,
        )
        record_payment(term["id"], "FAILED")
        member_after = validate_success(api.get_member(member["id"], headers))
        assert member_after["member_status"] == "SUSPENDED"
        cancelled = validate_success(api.cancel_merch_order(order["id"], headers))
        assert cancelled["order_status"] == "CANCELLED"

    def test_merch_cancel_while_suspended_refunds_wallet(self, api, anonymous_headers):
        """PRD: "Cancellation is the compensating action: the owning member or
        Support cancels an order in PAID status, moving it to the terminal
        CANCELLED state, and the member's wallet is credited exactly the order's
        total_cents — placement debit plus cancellation credit leaves the wallet
        unchanged, per the invariant of §2.7."

        Design: Corner/cross_cutting/cascading_merch_cancel_after_suspend_still_allowed
        """
        member, term = setup_funded_wallet()
        headers = make_member_headers(member["id"])
        order = validate_success(
            api.place_merch_order(
                member["id"],
                {
                    "lines": [
                        {"sku": "B1", "category": "BAND_ACCESSORY", "unit_price_cents": 100, "qty": 1},
                    ]
                },
                headers,
            ),
            expected_status=201,
        )
        record_payment(term["id"], "FAILED")
        validate_success(api.cancel_merch_order(order["id"], headers))
        member_after = validate_success(api.get_member(member["id"], headers))
        assert member_after["wallet_credit_cents"] == 90000
