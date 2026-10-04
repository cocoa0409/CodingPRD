"""Affiliate invoicing, PER_LINE cost sharing, and the dispute cycle
(PRD §3.8, §2.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_CHILD_SPECS,
    InvoiceStatus,
    TEST_USERS,
    api_client,
    assert_affiliate_invoice,
    assert_invoice_invariants,
    dispute_invoice_payload,
    issue_invoice,
    make_affiliate_coordinator_headers,
    open_invoice_dispute,
    pay_invoice,
    resolve_dispute_overruled,
    resolve_dispute_upheld,
    setup_issued_invoice,
    setup_reconciled_wave,
    validate_error,
    validate_success,
)

_ADMIN = TEST_USERS["platform_admin_headers"]


class TestInvoiceCostShare:
    def test_issued_invoice_pinned_to_per_line_variant(self, api):
        """PRD §3.8: "The state/local split follows the pinned `PER_LINE`
        variant, which is the variant recorded in `pricing_variant` on every
        issued invoice. For each billable item, the capped cost is the lesser
        of the item cost and the program's `max_state_share_per_book_cents`;
        the state line is that capped cost times the program's
        `funding_share_bp` divided by 10,000, rounded half up to a whole cent;
        and the local line is the item cost minus the state line."
        (Share 4925bp, cap 300c, three 224c items: state 3 x 110 = 330, local
        342; the AGGREGATE variant would give 331 / 341 on the same items.)

        Design: Difficulty/dual_variant_calc/invoice_cost_share_per_line_vs_aggregate
        """
        ctx = setup_reconciled_wave()
        invoice = issue_invoice(ctx["invoices"][0]["id"])
        assert_affiliate_invoice(invoice)
        assert invoice["status"] == InvoiceStatus.ISSUED.value
        assert invoice["pricing_variant"] == "PER_LINE"
        assert invoice["item_count"] == 3
        assert invoice["gross_cents"] == 672
        assert invoice["state_share_cents"] == 330
        assert invoice["local_share_cents"] == 342
        assert_invoice_invariants(invoice)

    def test_reconciled_draft_invoice_uses_per_line_rounding(self, api):
        """PRD §3.8: "Each reconciliation mints `AffiliateInvoice` records in
        `DRAFT`, one per affiliate per wave".
        PRD §3.8: "`state_share_cents` is the sum of the state lines and
        `local_share_cents` is the sum of the local lines — equivalently
        `gross_cents` minus `state_share_cents` — because the rounding order
        is pinned: round each line first, then sum."
        PRD §3.8: "A fresh invoice's `credit_memo_cents` is zero."

        Design: Difficulty/dual_variant_calc/invoice_cost_share_per_line_vs_aggregate
        """
        ctx = setup_reconciled_wave()
        invoice = ctx["invoices"][0]
        assert_affiliate_invoice(invoice)
        assert invoice["status"] == InvoiceStatus.DRAFT.value
        assert invoice["item_count"] == 3
        assert invoice["gross_cents"] == 672
        assert invoice["state_share_cents"] == 330, (
            "round_half_up(224 x 4925 / 10000) = 110 per line, summed to 330 — "
            "rounding once over the total would give 331"
        )
        assert invoice["local_share_cents"] == 342
        assert invoice["credit_memo_cents"] == 0
        assert_invoice_invariants(invoice)


class TestInvoiceRoundingOrder:
    def test_invoice_rounding_rounds_each_line_then_sums(self, api):
        """PRD §3.8: "`state_share_cents` is the sum of the state lines and
        `local_share_cents` is the sum of the local lines — equivalently
        `gross_cents` minus `state_share_cents` — because the rounding order
        is pinned: round each line first, then sum."
        (Share 4975bp over item costs 224/224/225: 111 + 111 + 112 = 334;
        rounding once over 673 would give 335.)

        Design: Difficulty/combinatorial_formula/invoice_rounding_order_round_then_sum
        """
        ctx = setup_reconciled_wave(
            program_overrides={
                "state_code": "TN2",
                "name": "TN Second Program",
                "funding_share_bp": 4975,
            },
            affiliate_overrides={
                "name": "Knox County Books",
                "postal_prefixes": ["379"],
                "contact_email": "coord@kcb.org",
            },
            quantities={"TODDLER": 5000},
            child_specs=[
                {
                    "full_name": "Di Evans", "family_name": "Evans",
                    "birth_date": "2026-04-11T00:00:00Z",
                    "mailing_address": {
                        "line1": "4 Ash St", "city": "Knoxville", "region": "TN",
                        "postal_code": "37901", "country": "US",
                    },
                },
                {
                    "full_name": "Ed Fox", "family_name": "Fox",
                    "birth_date": "2026-06-21T00:00:00Z",
                    "mailing_address": {
                        "line1": "5 Birch St", "city": "Knoxville", "region": "TN",
                        "postal_code": "37902", "country": "US",
                    },
                },
                {
                    "full_name": "Fi Grant", "family_name": "Grant",
                    "birth_date": "2025-06-10T00:00:00Z",
                    "mailing_address": {
                        "line1": "6 Cedar St", "city": "Knoxville", "region": "TN",
                        "postal_code": "37909", "country": "US",
                    },
                },
            ],
        )
        invoice = ctx["invoices"][0]
        assert invoice["item_count"] == 3
        assert invoice["gross_cents"] == 673  # 224 + 224 + 225
        assert invoice["state_share_cents"] == 334
        assert invoice["local_share_cents"] == 339
        assert_invoice_invariants(invoice)

    def test_invoice_line_costs_come_from_floor_division(self, api):
        """PRD §3.8: "take the item's selection, find its single confirmed
        print order, divide that order's `total_cents` by its `quantity` using
        integer floor division to get the effective order unit, and add the
        35-cent per-book handling charge."
        (INFANT order 6,000 x 185 + 25,000 = 1,135,000 -> floor/6000 = 189 ->
        224 per item; TODDLER order 5,000 x 185 + 25,000 = 950,000 ->
        floor/5000 = 190 -> 225 per item.)

        Design: Difficulty/combinatorial_formula/invoice_rounding_order_round_then_sum
        """
        ctx = setup_reconciled_wave(
            program_overrides={
                "state_code": "TN2",
                "name": "TN Second Program",
                "funding_share_bp": 4975,
            },
            affiliate_overrides={
                "name": "Knox County Books",
                "postal_prefixes": ["379"],
                "contact_email": "coord@kcb.org",
            },
            quantities={"TODDLER": 5000},
            child_specs=[
                {
                    "full_name": "Di Evans", "family_name": "Evans",
                    "birth_date": "2026-04-11T00:00:00Z",
                    "mailing_address": {
                        "line1": "4 Ash St", "city": "Knoxville", "region": "TN",
                        "postal_code": "37901", "country": "US",
                    },
                },
                {
                    "full_name": "Ed Fox", "family_name": "Fox",
                    "birth_date": "2026-06-21T00:00:00Z",
                    "mailing_address": {
                        "line1": "5 Birch St", "city": "Knoxville", "region": "TN",
                        "postal_code": "37902", "country": "US",
                    },
                },
                {
                    "full_name": "Fi Grant", "family_name": "Grant",
                    "birth_date": "2025-06-10T00:00:00Z",
                    "mailing_address": {
                        "line1": "6 Cedar St", "city": "Knoxville", "region": "TN",
                        "postal_code": "37909", "country": "US",
                    },
                },
            ],
        )
        infant_order = ctx["orders"]["INFANT"]
        toddler_order = ctx["orders"]["TODDLER"]
        assert infant_order["unit_cents"] == 185
        assert infant_order["total_cents"] == 6000 * 185 + 25000  # 1,135,000
        assert toddler_order["unit_cents"] == 185
        assert toddler_order["total_cents"] == 5000 * 185 + 25000  # 950,000
        invoice = ctx["invoices"][0]
        assert invoice["item_count"] == 3
        assert invoice["gross_cents"] == 224 + 224 + 225
        assert_invoice_invariants(invoice)


class TestPerItemBookCost:
    def test_per_item_cost_floor_division(self, api):
        """PRD §3.8: "divide that order's `total_cents` by its `quantity`
        using integer floor division to get the effective order unit, and add
        the 35-cent per-book handling charge. Then `gross_cents` is the sum of
        per-item costs over the invoice's billable items."
        (Order 7,000 x 185 + 25,000 = 1,320,000 -> floor/7000 = 188, not 189
        -> item cost 223.)

        Design: Corner/calculations/per_item_cost_floor_division
        """
        ctx = setup_reconciled_wave(
            quantities={"INFANT": 7000}, child_specs=DEFAULT_CHILD_SPECS[:1]
        )
        order = ctx["orders"]["INFANT"]
        assert order["unit_cents"] == 185
        assert order["total_cents"] == 7000 * 185 + 25000  # 1,320,000
        invoice = ctx["invoices"][0]
        assert invoice["item_count"] == 1
        assert invoice["gross_cents"] == 188 + 35  # 223
        # round_half_up(223 x 4925 / 10000) = round_half_up(109.8275) = 110
        assert invoice["state_share_cents"] == 110
        assert invoice["local_share_cents"] == 223 - 110
        assert_invoice_invariants(invoice)


class TestInvoiceLifecycle:
    def test_invoice_pay_from_draft_rejected(self, api):
        """PRD §3.8: "Payment is the coordinator's act on their own
        affiliate's invoice (else `ERR_FORBIDDEN`) and moves the invoice to
        `PAID` from either `ISSUED` or `ADJUSTED`."
        PRD §2.8: "**State preconditions** — the target resource's state
        permits the requested transition, else `ERR_INVALID_STATE`."

        Design: Corner/state_machines/invoice_pay_from_draft_rejected
        """
        ctx = setup_reconciled_wave()
        invoice = ctx["invoices"][0]
        resp = api.pay_invoice(
            invoice["id"],
            make_affiliate_coordinator_headers(ctx["affiliate"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_invoice(invoice["id"], _ADMIN))
        assert after["status"] == InvoiceStatus.DRAFT.value

    def test_invoice_dispute_overruled_returns_to_issued(self, api):
        """PRD §3.8: "An overruled resolution returns the invoice to `ISSUED`
        unchanged, ready to be paid or disputed again."

        Design: Corner/state_machines/invoice_dispute_overruled_returns_to_issued
        """
        ctx = setup_issued_invoice()
        invoice = ctx["invoice"]
        disputed = open_invoice_dispute(invoice["id"], ctx["affiliate"]["id"])
        assert disputed["status"] == InvoiceStatus.DISPUTED.value
        resolved = resolve_dispute_overruled(invoice["id"])
        assert resolved["status"] == InvoiceStatus.ISSUED.value
        assert resolved["gross_cents"] == 672
        assert resolved["state_share_cents"] == 330
        assert resolved["local_share_cents"] == 342
        assert resolved["credit_memo_cents"] == 0, (
            "the dispute cycle leaves zero financial drift"
        )
        assert_invoice_invariants(resolved)

    def test_dispute_credit_above_gross_rejected(self, api):
        """PRD §3.8: "An upheld resolution carries a `credit_amount_cents`
        that must be greater than zero and no more than the invoice's
        `gross_cents` — a missing, non-positive, or over-gross credit is
        `ERR_CREDIT_EXCEEDS_GROSS`".

        Design: Corner/validations/dispute_credit_above_gross_rejected
        """
        ctx = setup_issued_invoice()
        invoice = ctx["invoice"]
        open_invoice_dispute(invoice["id"], ctx["affiliate"]["id"])
        resp = api.dispute_invoice(
            invoice["id"],
            dispute_invoice_payload("RESOLVE_UPHELD", credit_amount_cents=673),
            _ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_EXCEEDS_GROSS)
        after = validate_success(api.get_invoice(invoice["id"], _ADMIN))
        assert after["status"] == InvoiceStatus.DISPUTED.value
        assert after["credit_memo_cents"] == 0


class TestDisputeCreditMemo:
    def test_dispute_credit_memo_conserves_invoice_gross(self, api):
        """PRD §3.8: "moves the invoice to `ADJUSTED`: `credit_memo_cents`
        records the credit, `local_share_cents` becomes `gross_cents` minus
        `state_share_cents` minus the credit, and the invariant that
        `gross_cents` equals `state_share_cents` plus `local_share_cents`
        plus `credit_memo_cents` holds thereafter. The state share is never
        credited; credits come out of the local share only."

        Design: Difficulty/compensating_invariant/dispute_credit_memo_conserves_invoice_gross
        """
        ctx = setup_issued_invoice()
        invoice = ctx["invoice"]
        disputed = open_invoice_dispute(invoice["id"], ctx["affiliate"]["id"])
        assert disputed["status"] == InvoiceStatus.DISPUTED.value
        adjusted = resolve_dispute_upheld(invoice["id"], 224)
        assert adjusted["status"] == InvoiceStatus.ADJUSTED.value
        assert adjusted["credit_memo_cents"] == 224
        assert adjusted["state_share_cents"] == 330, "the state share is never credited"
        assert adjusted["local_share_cents"] == 118  # 342 - 224
        assert adjusted["gross_cents"] == 672
        assert_invoice_invariants(adjusted)

    def test_adjusted_invoice_keeps_gross_and_remains_payable(self, api):
        """PRD §3.8: "Payment is the coordinator's act on their own
        affiliate's invoice (else `ERR_FORBIDDEN`) and moves the invoice to
        `PAID` from either `ISSUED` or `ADJUSTED`."
        PRD §3.8: "the invariant that `gross_cents` equals `state_share_cents`
        plus `local_share_cents` plus `credit_memo_cents` holds thereafter."

        Design: Difficulty/compensating_invariant/dispute_credit_memo_conserves_invoice_gross
        """
        ctx = setup_issued_invoice()
        invoice = ctx["invoice"]
        open_invoice_dispute(invoice["id"], ctx["affiliate"]["id"])
        adjusted = resolve_dispute_upheld(invoice["id"], 224)
        assert adjusted["gross_cents"] == invoice["gross_cents"], (
            "the dispute never touches gross"
        )
        assert adjusted["item_count"] == invoice["item_count"]
        paid = pay_invoice(invoice["id"], ctx["affiliate"]["id"])
        assert paid["status"] == InvoiceStatus.PAID.value
        assert_invoice_invariants(paid)
