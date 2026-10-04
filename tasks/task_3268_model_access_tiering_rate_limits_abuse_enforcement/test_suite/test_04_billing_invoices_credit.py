"""Invoicing, per-line rounding, batch discounts, and prepaid credit tests."""
from test_helpers import (
    ADMIN,
    BILLING,
    ApiErrorId,
    create_and_activate_organization,
    create_invoice_payload,
    create_model_version_payload,
    create_settled_payment,
    make_organization_admin_headers,
    set_clock,
    setup_org_with_model,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestBatchDiscountVariants:
    def _setup_batch_invoice(self, api):
        set_clock()
        org = create_and_activate_organization(legal_name="Batch Discount Co")
        mv = validate_success(
            api.create_model_version(create_model_version_payload(), ADMIN),
            expected_status=201,
        )
        resp = api.create_invoice(
            create_invoice_payload(
                org["id"],
                lines=[
                    {
                        "model_version_id": mv["id"],
                        "kind": "INPUT_TOKENS",
                        "quantity": 2000000,
                        "rate_per_mtok_cents": 300,
                        "batch": True,
                    },
                    {
                        "model_version_id": mv["id"],
                        "kind": "OUTPUT_TOKENS",
                        "quantity": 1000000,
                        "rate_per_mtok_cents": 1500,
                        "batch": True,
                    },
                ],
            ),
            BILLING,
        )
        return org, mv, validate_success(resp, expected_status=201)

    def test_draft_invoice_totals_unset(self, api):
        """PRD §3.5: "While the invoice remains `DRAFT`, its totals are unset: `subtotal_cents`, `batch_discount_cents`, and `total_cents` all read zero, and each line's `amount_cents` is null."
        PRD §3.5: "While the invoice is still in draft the same arithmetic may be recomputed on demand as a provisional estimate, but that value is never persisted and is not sticky: adding lines before finalization changes what the finalized discount will be."

        Design: Difficulty/dual_variant_calc/batch_discount_provisional_vs_finalized
        """
        org, mv, invoice = self._setup_batch_invoice(api)
        assert invoice["status"] == "DRAFT"
        assert invoice["batch_discount_cents"] == 0, (
            f"provisional discount must never be persisted on a DRAFT invoice, got {invoice['batch_discount_cents']}"
        )
        assert invoice["subtotal_cents"] == 0
        assert invoice["total_cents"] == 0

    def test_finalize_locks_discount_and_totals(self, api):
        """PRD §3.5: "The batch discount is then computed over exactly the lines flagged `batch`: their already-rounded amounts are summed, half of that sum is taken — the batch discount is fifty percent — and the result is rounded half-up once, at the invoice level only, yielding `batch_discount_cents`."
        PRD §3.5: "The invoice's `total_cents` is the subtotal minus the discount, floored at zero."

        Design: Difficulty/dual_variant_calc/batch_discount_provisional_vs_finalized
        """
        org, mv, invoice = self._setup_batch_invoice(api)
        finalized = validate_success(api.finalize_invoice(invoice["id"], BILLING))
        assert finalized["status"] == "FINALIZED"
        assert finalized["subtotal_cents"] == 2100, (
            f"600 + 1500 per-line rounded must sum to 2100, got {finalized['subtotal_cents']}"
        )
        assert finalized["batch_discount_cents"] == 1050, (
            f"round_half_up(2100 * 0.5) == 1050, got {finalized['batch_discount_cents']}"
        )
        assert finalized["total_cents"] == 1050


class TestPerLineRoundingOrder:
    def _setup_rounding_invoice(self, api):
        set_clock()
        org = create_and_activate_organization(legal_name="Rounding Order LLC")
        mv = validate_success(
            api.create_model_version(
                create_model_version_payload(
                    model_slug="claude-haiku",
                    version_tag="4-5",
                    pricing={
                        "input_per_mtok_cents": 1,
                        "output_per_mtok_cents": 1,
                        "cached_per_mtok_cents": 0,
                    },
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        resp = api.create_invoice(
            create_invoice_payload(
                org["id"],
                lines=[
                    {
                        "model_version_id": mv["id"],
                        "kind": "INPUT_TOKENS",
                        "quantity": 1500000,
                        "rate_per_mtok_cents": 1,
                    },
                    {
                        "model_version_id": mv["id"],
                        "kind": "INPUT_TOKENS",
                        "quantity": 1500000,
                        "rate_per_mtok_cents": 1,
                    },
                ],
            ),
            BILLING,
        )
        return org, mv, validate_success(resp, expected_status=201)

    def test_per_line_amounts_rounded_half_up_individually(self, api):
        """PRD §2.9: "First, invoice line amounts are rounded individually, half-up, before any summation: each line's `amount_cents` is its `quantity` multiplied by its `rate_per_mtok_cents`, divided by one million, rounded half-up to a whole cent — and only then are the rounded line amounts summed into the invoice's `subtotal_cents`."

        Design: Difficulty/combinatorial_formula/invoice_pricing_per_line_rounding_order
        """
        org, mv, invoice = self._setup_rounding_invoice(api)
        validate_success(api.finalize_invoice(invoice["id"], BILLING))
        lines, meta = validate_paginated(
            api.list_invoice_lines(BILLING, params={"invoice_id": invoice["id"]})
        )
        assert meta["total_count"] == 2
        for line in lines:
            assert line["amount_cents"] == 2, (
                f"round_half_up(1.5) must be 2 per line, got {line['amount_cents']}"
            )

    def test_subtotal_sums_rounded_lines(self, api):
        """PRD §2.9: "The alternative order (summing quantities and rounding once) yields different cents and is forbidden."
        PRD §3.5: "the rounded line amounts are then summed into the invoice's `subtotal_cents`"

        Design: Difficulty/combinatorial_formula/invoice_pricing_per_line_rounding_order
        """
        org, mv, invoice = self._setup_rounding_invoice(api)
        finalized = validate_success(api.finalize_invoice(invoice["id"], BILLING))
        assert finalized["subtotal_cents"] == 4, (
            f"per-line rounding gives 2 + 2 = 4 (sum-then-round would give 3), got {finalized['subtotal_cents']}"
        )
        assert finalized["batch_discount_cents"] == 0
        assert finalized["total_cents"] == 4


class TestCreditBalanceInvariant:
    def test_finalize_debits_credit_balance_exactly(self, api):
        """PRD §3.5: "Finally, the organization's prepaid credit is applied: `credit_balance_cents` is debited by the smaller of the invoice total and the available balance, and any remainder becomes payable."
        PRD §3.1: "If the payment is a `PREPAID_TOPUP`, its amount is also added to `credit_balance_cents`; if it is a `REFUND`, its (negative) amount is applied to `credit_balance_cents` as well, floored at zero — the prepaid balance may never go negative."

        Design: Difficulty/compensating_invariant/credit_balance_topup_then_invoice_debit
        """
        set_clock()
        org = create_and_activate_organization(legal_name="Credit Invariant Co")
        mv = validate_success(
            api.create_model_version(create_model_version_payload(), ADMIN),
            expected_status=201,
        )
        invoice = validate_success(
            api.create_invoice(
                create_invoice_payload(
                    org["id"],
                    lines=[
                        {
                            "model_version_id": mv["id"],
                            "kind": "INPUT_TOKENS",
                            "quantity": 3333334,
                            "rate_per_mtok_cents": 300,
                        }
                    ],
                ),
                BILLING,
            ),
            expected_status=201,
        )
        before = validate_success(api.get_organization(org["id"], BILLING))
        assert before["credit_balance_cents"] == 1000000

        finalized = validate_success(api.finalize_invoice(invoice["id"], BILLING))
        assert finalized["total_cents"] == 1000, (
            f"round_half_up(3333334 * 300 / 1000000) == 1000, got {finalized['total_cents']}"
        )

        after = validate_success(api.get_organization(org["id"], BILLING))
        assert after["credit_balance_cents"] == 999000, (
            f"balance must be debited by exactly the invoice total, got {after['credit_balance_cents']}"
        )


class TestInsufficientCreditGuard:
    def test_finalize_debit_capped_at_balance(self, api):
        """PRD §3.5: "Because the debit is capped at the balance, underflow cannot occur; any implementation path that would drive `credit_balance_cents` negative is rejected with `ERR_INSUFFICIENT_CREDIT` (HTTP 422)."

        Design: Corner/validations/insufficient_credit_guarded_on_finalize
        """
        set_clock()
        org = create_and_activate_organization(legal_name="Cap Debit Co")
        mv = validate_success(
            api.create_model_version(create_model_version_payload(), ADMIN),
            expected_status=201,
        )
        invoice = validate_success(
            api.create_invoice(
                create_invoice_payload(
                    org["id"],
                    lines=[
                        {
                            "model_version_id": mv["id"],
                            "kind": "INPUT_TOKENS",
                            "quantity": 10000,
                            "rate_per_mtok_cents": 300,
                        }
                    ],
                ),
                BILLING,
            ),
            expected_status=201,
        )
        finalized = validate_success(api.finalize_invoice(invoice["id"], BILLING))
        assert finalized["total_cents"] == 3
        org_data = validate_success(api.get_organization(org["id"], BILLING))
        assert org_data["credit_balance_cents"] == 999997
        assert org_data["credit_balance_cents"] >= 0


class TestInvoicePeriodOverlap:
    def _setup_first_invoice(self, api):
        set_clock()
        org = create_and_activate_organization(legal_name="Overlap Test Co")
        invoice = validate_success(
            api.create_invoice(
                create_invoice_payload(
                    org["id"],
                    period_start="2026-09-01T00:00:00Z",
                    period_end="2026-09-15T00:00:00Z",
                ),
                BILLING,
            ),
            expected_status=201,
        )
        return org, invoice

    def test_adjacent_period_permitted(self, api):
        """PRD §3.5: "A `BillingContact` or `PlatformAdmin` opens an invoice in `DRAFT` status for an `organization_id` over a half-open period from `period_start` inclusive to `period_end` exclusive, with `period_end` strictly after `period_start`. Periods for one organization may not overlap: the new interval is tested, closed-open, against every existing invoice for that organization, and a collision is rejected with `ERR_PERIOD_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/invoice_period_closed_open_overlap
        """
        org, invoice = self._setup_first_invoice(api)
        resp = api.create_invoice(
            create_invoice_payload(
                org["id"],
                period_start="2026-09-15T00:00:00Z",
                period_end="2026-09-30T00:00:00Z",
            ),
            BILLING,
        )
        validate_success(resp, expected_status=201)

    def test_interior_overlap_rejected(self, api):
        """PRD §3.5: "Periods for one organization may not overlap: the new interval is tested, closed-open, against every existing invoice for that organization, and a collision is rejected with `ERR_PERIOD_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/invoice_period_closed_open_overlap
        """
        org, invoice = self._setup_first_invoice(api)
        resp = api.create_invoice(
            create_invoice_payload(
                org["id"],
                period_start="2026-09-14T23:59:59Z",
                period_end="2026-09-16T00:00:00Z",
            ),
            BILLING,
        )
        validate_error(resp, ApiErrorId.ERR_PERIOD_OVERLAP)


class TestInvoiceRBAC:
    def test_organization_admin_cannot_finalize_invoice(self, api):
        """PRD §4: "POST | `/invoices/{id}/finalize` | Compute amounts, discount, totals; debit credit; terminal | BillingContact"
        PRD §2.1: "A well-authenticated request whose role is not authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/organization_admin_cannot_finalize_invoice
        """
        set_clock()
        org = validate_success(
            api.create_organization({"legal_name": "RBAC Invoice Co"}, ADMIN),
            expected_status=201,
        )
        invoice = validate_success(
            api.create_invoice(create_invoice_payload(org["id"]), BILLING),
            expected_status=201,
        )
        resp = api.finalize_invoice(
            invoice["id"], make_organization_admin_headers(org["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
