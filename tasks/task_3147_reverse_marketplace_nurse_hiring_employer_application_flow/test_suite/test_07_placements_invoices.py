"""Placements, guarantee termination, invoices, fees, and settlement."""
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import ApiErrorId
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.test_users import ADMIN, make_candidate_headers, make_employer_headers


class TestPlacementComputedFields:
    def test_placement_fields_copied_from_offer_and_application_at_acceptance(self, api):
        """PRD §3.7: "Its `application_id`, `requisition_id`, `nurse_id`, and `employer_id` are copied from the application; its `hourly_rate_cents` is copied from the accepted offer's `offered_hourly_rate_cents`; its `start_date` is copied from the offer's `start_date`. Its `annualized_salary_cents` is computed once, now, as the hourly rate in cents multiplied by 2080 — forty hours per week across fifty-two weeks — and stored on the placement, because the placement, not the terminal-locked offer, is the billable source of truth. Its `guarantee_ends_on` is the `start_date` plus the employer's `guarantee_days` days."

        Design: Corner/entities/placement_fields_copied_from_offer_and_application_at_acceptance
        """
        ctx = fx.setup_placement_accepted()
        placement = ctx["placement"]

        assert placement["annualized_salary_cents"] == 8500 * 2080
        assert placement["annualized_salary_cents"] == 17680000
        assert placement["guarantee_ends_on"] == "2026-12-14"
        assert placement["status"] == "PENDING_START"
        assert placement["hourly_rate_cents"] == 8500
        assert placement["start_date"] == "2026-10-15"
        assert placement["employer_id"] == ctx["employer"]["id"]
        assert placement["requisition_id"] == ctx["requisition"]["id"]
        assert placement["nurse_id"] == ctx["nurse"]["id"]
        assert placement["application_id"] == ctx["application"]["id"]


    def test_provisional_invoice_created_issued_at_acceptance(self, api):
        """PRD §3.7: "Fifth, an **Invoice** is created in `ISSUED` with `amount_credited_cents` at zero, its `invoice_kind` set to `PLACEMENT_FEE`, its `employer_id` and `placement_id` wired to the new placement."
        PRD §3.7: "Under `PER_PLACEMENT`, the fee is the `annualized_salary_cents` multiplied by the employer's `placement_fee_bps` and divided by 10000, rounded half-up to whole cents — rounding applied to that product only."

        Design: Difficulty/dual_variant_calc/placement_fee_provisional_vs_guarantee_refund
        """
        ctx = fx.setup_placement_accepted()
        employer = ctx["employer"]
        invoice = fx.get_placement_invoice(ctx["placement"], employer)

        # PROVISIONAL variant: round_half_up(17680000 * 2000 / 10000) == 3536000.
        assert invoice["status"] == "ISSUED"
        assert invoice["invoice_kind"] == "PLACEMENT_FEE"
        assert invoice["amount_due_cents"] == 3536000
        assert invoice["amount_credited_cents"] == 0
        assert invoice["placement_id"] == ctx["placement"]["id"]
        assert invoice["employer_id"] == employer["id"]


class TestPlacementFeeVariants:
    def test_provisional_fee_at_acceptance_then_guarantee_refund(self, api):
        """PRD §3.7: "Under `PER_PLACEMENT`, the fee is the `annualized_salary_cents` multiplied by the employer's `placement_fee_bps` and divided by 10000, rounded half-up to whole cents — rounding applied to that product only."
        PRD §3.8: "The refund in cents is the invoice's `amount_due_cents` multiplied by that numerator and divided by `guarantee_days`, rounded half-up exactly once at the final quotient. The refund is added to the invoice's `amount_credited_cents`. The invoice then transitions to `VOID` when the refund equals the full `amount_due_cents` — the shape a pre-start termination takes — and to `PARTIALLY_CREDITED` when the refund is positive but smaller."

        Design: Difficulty/dual_variant_calc/placement_fee_provisional_vs_guarantee_refund
        """
        ctx = fx.setup_placement_accepted()
        employer = ctx["employer"]
        placement = ctx["placement"]

        invoice = fx.get_placement_invoice(placement, employer)
        # PROVISIONAL: round_half_up(8500 * 2080 * 2000 / 10000) = 3,536,000.
        assert invoice["amount_due_cents"] == 3536000
        assert invoice["amount_credited_cents"] == 0
        assert invoice["status"] == "ISSUED"
        assert invoice["invoice_kind"] == "PLACEMENT_FEE"

        fx.set_clock("2026-10-30T00:00:00Z")
        terminated = validate_success(
            api_client.terminate_placement(
                placement["id"], make_employer_headers(employer["id"])
            )
        )
        assert terminated["status"] == "TERMINATED_IN_GUARANTEE"

        invoice = validate_success(
            api_client.get_invoice(invoice["id"], make_employer_headers(employer["id"]))
        )
        # GUARANTEE_REFUND at 15 days served of a 60-day guarantee:
        # round_half_up(3536000 * 45 / 60) = 2,652,000.
        assert invoice["amount_due_cents"] == 3536000
        assert invoice["amount_credited_cents"] == 2652000
        assert invoice["status"] == "PARTIALLY_CREDITED"

        employer_after = validate_success(
            api_client.get_employer(employer["id"], make_employer_headers(employer["id"]))
        )
        assert employer_after["credit_balance_cents"] == 2652000

    def test_subscription_flat_fee_invariant_to_rate(self, api):
        """PRD §3.7: "Under `SUBSCRIPTION`, the fee is a tiered flat amount: 2500000 cents on the `BASIC` tier, 2000000 cents on `PRO`, and 1500000 cents on `ENTERPRISE`."

        Design: Corner/calculations/subscription_tier_flat_fee_invariant_to_rate
        """
        # Same pipeline but under a SUBSCRIPTION/BASIC employer and a 9000-cent offer.
        fx.set_clock()
        nurse = fx.setup_active_nurse(email="nora@x.com")["nurse"]
        employer = fx.create_employer(
            legal_name="Sub Hospital", fee_model="SUBSCRIPTION",
            subscription_tier="BASIC", guarantee_days=90, placement_fee_bps=1500,
        )
        req = fx.create_requisition(
            employer, unit_name="ICU-1", offered_hourly_rate_cents=8800, openings_total=1,
        )
        app = fx.create_application(req, nurse, employer, proposed_hourly_rate_cents=9000)
        fx.review_application(app, nurse)
        iv = fx.schedule_interview(app, employer)
        fx.set_clock("2026-09-02T12:00:00Z")
        fx.complete_interview(iv, employer)
        scr = fx.open_screening(app, employer)
        fx.verify_screening_credentials(scr)
        fx.clear_screening_background(scr)
        doc = fx.upload_document(app, nurse, doc_type="SIGNED_CONTRACT")
        fx.approve_document(doc, employer)
        offer = fx.issue_offer(app, req, employer, offered_hourly_rate_cents=9000)

        placement = validate_success(
            api_client.accept_offer(offer["id"], make_candidate_headers(nurse["id"]))
        )
        # The salary is bps-derivable but the fee is the flat BASIC tier.
        assert placement["annualized_salary_cents"] == 9000 * 2080
        assert placement["annualized_salary_cents"] == 18720000

        invoice = fx.get_placement_invoice(placement, employer)
        assert invoice["invoice_kind"] == "PLACEMENT_FEE"
        assert invoice["amount_due_cents"] == 2500000


class TestGuaranteeRefundRounding:
    def test_refund_rounds_final_quotient_once(self, api):
        """PRD §3.8: "The refund in cents is the invoice's `amount_due_cents` multiplied by that numerator and divided by `guarantee_days`, rounded half-up exactly once at the final quotient."
        PRD §2.9: "Where a calculation produces a fractional cent — the per-placement fee computation and the guarantee refund computation — the result is rounded half-up, and rounding is applied exactly once, to the final product or quotient, never to an intermediate fraction."

        Design: Difficulty/combinatorial_formula/guarantee_refund_rounding_order_pinned
        """
        ctx = fx.setup_placement_terminated_in_guarantee()
        employer = ctx["employer"]
        invoice = fx.get_placement_invoice(ctx["placement"], employer)

        # Single rounding of the final quotient: round_half_up(3536000 * 45 / 60).
        assert invoice["amount_credited_cents"] == 2652000
        assert invoice["amount_due_cents"] == 3536000, (
            "the provisional bill is never rewritten; only the credit accumulates"
        )
        assert invoice["status"] == "PARTIALLY_CREDITED"

    def test_refund_leaves_amount_due_unchanged(self, api):
        """PRD §3.8: "The refund is added to the invoice's `amount_credited_cents`."

        Design: Difficulty/combinatorial_formula/guarantee_refund_rounding_order_pinned
        """
        ctx = fx.setup_placement_terminated_in_guarantee()
        employer = ctx["employer"]
        invoice = fx.get_placement_invoice(ctx["placement"], employer)

        assert invoice["amount_due_cents"] == 3536000
        assert invoice["amount_credited_cents"] == 2652000
        residual = invoice["amount_due_cents"] - invoice["amount_credited_cents"]
        assert residual == 884000


class TestInvoiceSettlement:
    def test_settle_applies_credit_before_cash(self, api):
        """PRD §3.8: "An employer may settle any invoice in `ISSUED` or `PARTIALLY_CREDITED`; settling draws down the employer's `credit_balance_cents` first, decreasing it by the lesser of the available credit and the invoice's outstanding balance — its `amount_due_cents` minus its `amount_credited_cents` — and moves the invoice to the terminal `SETTLED`."

        Design: Corner/endpoints/invoice_settle_applies_credit_before_cash
        """
        ctx = fx.setup_placement_terminated_in_guarantee()
        employer = ctx["employer"]
        invoice = fx.get_placement_invoice(ctx["placement"], employer)

        settled = validate_success(
            api_client.settle_invoice(invoice["id"], make_employer_headers(employer["id"]))
        )
        assert settled["status"] == "SETTLED"
        assert settled["amount_due_cents"] == 3536000
        # The outstanding residual is drawn from the credit on top of the refund.
        assert settled["amount_credited_cents"] == 3536000

        employer_after = validate_success(
            api_client.get_employer(employer["id"], make_employer_headers(employer["id"]))
        )
        # min(credit 2652000, residual 884000) drawn down: 2652000 - 884000.
        assert employer_after["credit_balance_cents"] == 1768000


class TestFeeCreditConservation:
    def test_fee_credit_conserved_through_provisional_and_refund(self, api):
        """PRD §3.8: "An employer may settle any invoice in `ISSUED` or `PARTIALLY_CREDITED`; settling draws down the employer's `credit_balance_cents` first, decreasing it by the lesser of the available credit and the invoice's outstanding balance — its `amount_due_cents` minus its `amount_credited_cents` — and moves the invoice to the terminal `SETTLED`."
        PRD §3.8: "The refund is added to the invoice's `amount_credited_cents`."

        Design: Difficulty/compensating_invariant/fee_credit_conserved_through_provisional_and_refund
        """
        ctx = fx.setup_placement_terminated_in_guarantee()
        employer = ctx["employer"]
        invoice = fx.get_placement_invoice(ctx["placement"], employer)

        # Conservation across the refund: due never mutates; credit moves cents.
        assert invoice["amount_due_cents"] == 3536000
        assert invoice["amount_credited_cents"] == 2652000
        employer_mid = validate_success(
            api_client.get_employer(employer["id"], make_employer_headers(employer["id"]))
        )
        assert employer_mid["credit_balance_cents"] == invoice["amount_credited_cents"]

        settled = validate_success(
            api_client.settle_invoice(invoice["id"], make_employer_headers(employer["id"]))
        )
        # The outstanding residual is drawn from the credit on top of the refund.
        residual = settled["amount_due_cents"] - settled["amount_credited_cents"]
        assert residual == 0
        employer_after = validate_success(
            api_client.get_employer(employer["id"], make_employer_headers(employer["id"]))
        )
        # Drawdown is the outstanding balance at settle time (884000).
        assert employer_after["credit_balance_cents"] == 2652000 - 884000
        # Zero drift: credited + settled residual == original amount due.
        assert settled["amount_credited_cents"] + residual == settled["amount_due_cents"]

    def test_settle_draws_only_the_residual(self, api):
        """PRD §3.8: "settling draws down the employer's `credit_balance_cents` first, decreasing it by the lesser of the available credit and the invoice's outstanding balance — its `amount_due_cents` minus its `amount_credited_cents` — and moves the invoice to the terminal `SETTLED`."

        Design: Difficulty/compensating_invariant/fee_credit_conserved_through_provisional_and_refund
        """
        ctx = fx.setup_placement_terminated_in_guarantee()
        employer = ctx["employer"]
        invoice = fx.get_placement_invoice(ctx["placement"], employer)

        before = validate_success(
            api_client.get_employer(employer["id"], make_employer_headers(employer["id"]))
        )
        residual = invoice["amount_due_cents"] - invoice["amount_credited_cents"]

        settled = validate_success(
            api_client.settle_invoice(invoice["id"], make_employer_headers(employer["id"]))
        )
        assert settled["status"] == "SETTLED"
        after = validate_success(
            api_client.get_employer(employer["id"], make_employer_headers(employer["id"]))
        )
        assert before["credit_balance_cents"] - after["credit_balance_cents"] == residual
        assert after["credit_balance_cents"] == 1768000


class TestPlacementBrowsing:
    def test_placements_filter_by_requisition_and_status(self, api):
        """PRD §3.8: "Placements are likewise browsable by `nurse_id`, `employer_id`, `requisition_id`, `application_id`, or `status`, and applications by `nurse_id`, `employer_id`, `requisition_id`, or `status`."

        Design: Corner/endpoints/placements_filter_by_requisition_and_status
        """
        ctx = fx.setup_placement_terminated_in_guarantee()
        employer = ctx["employer"]
        placement = ctx["placement"]

        rows, meta = validate_paginated(
            api_client.list_placements(
                make_employer_headers(employer["id"]),
                params={
                    "requisition_id": ctx["requisition"]["id"],
                    "status": "TERMINATED_IN_GUARANTEE",
                },
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == placement["id"]

        _, meta_active = validate_paginated(
            api_client.list_placements(
                make_employer_headers(employer["id"]),
                params={
                    "requisition_id": ctx["requisition"]["id"],
                    "status": "GUARANTEE_ACTIVE",
                },
            )
        )
        assert meta_active["total_count"] == 0

        rows_by_app, meta_by_app = validate_paginated(
            api_client.list_placements(
                make_employer_headers(employer["id"]),
                params={"application_id": ctx["application"]["id"]},
            )
        )
        assert meta_by_app["total_count"] == 1
        assert rows_by_app[0]["id"] == placement["id"]
