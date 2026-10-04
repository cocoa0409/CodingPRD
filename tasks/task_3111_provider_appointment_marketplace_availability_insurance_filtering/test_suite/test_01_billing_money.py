"""Tests for the fee split, invoice aggregation, tier boundaries, and payout
reconciliation (PRD §3.6 and §3.7).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_payout_reconciliation,
    book_slot,
    create_patient,
    create_practice,
    get_invoice,
    list_charges_for_booking,
    list_charges_for_invoice,
    setup_bookable_practice,
    setup_invoiced_practice,
    slot_time,
    validate_error,
    validate_success,
)


class TestFeeSplitNestedRoundingOrder:
    def test_fee_split_components_rounded_independently_gross_9999(self, api):
        """PRD §3.6: "As a worked example, a gross of 9999 cents yields a
        marketplace fee of 1500 cents, processing of 320 cents, and a net to
        the practice of 8179 cents."

        Design: Difficulty/combinatorial_formula/fee_split_nested_rounding_order
        """
        ctx = setup_bookable_practice(copay_cents=9999, slot_windows=[slot_time(48)])
        patient = create_patient()
        booking = book_slot(ctx["slots"][0]["id"], patient["id"], ctx["type"]["id"])
        charges = list_charges_for_booking(booking["id"])
        assert len(charges) == 1, f"expected exactly one charge, got {len(charges)}"
        charge = charges[0]
        assert charge["marketplace_fee_cents"] == 1500, (
            f"fee must be 1500, got {charge['marketplace_fee_cents']}"
        )
        assert charge["processing_cents"] == 320, (
            f"processing must be 320, got {charge['processing_cents']}"
        )
        assert charge["net_to_practice_cents"] == 8179, (
            f"net must be 8179, got {charge['net_to_practice_cents']}"
        )

    def test_fee_split_net_is_subtraction_of_rounded_parts(self, api):
        """PRD §3.6: "Each component is rounded independently before the
        subtraction; the system never rounds once at the end."

        Design: Difficulty/combinatorial_formula/fee_split_nested_rounding_order
        """
        ctx = setup_bookable_practice(copay_cents=9999, slot_windows=[slot_time(48)])
        patient = create_patient()
        booking = book_slot(ctx["slots"][0]["id"], patient["id"], ctx["type"]["id"])
        charge = list_charges_for_booking(booking["id"])[0]
        # An implementation that subtracted the UNROUNDED parts and rounded only
        # the final net would return 8180, not 8179.
        assert (
            charge["net_to_practice_cents"]
            == charge["gross_cents"] - charge["marketplace_fee_cents"] - charge["processing_cents"]
        )
        assert charge["net_to_practice_cents"] == 8179
        assert charge["net_to_practice_cents"] != 8180, (
            "net 8180 indicates the unrounded parts were subtracted and only the final net rounded"
        )


class TestInvoiceTierEvaluationOrder:
    def test_invoice_aggregates_11_charges_of_copay_20000(self, api):
        """PRD §3.7: "`discount_tier` is 0.20 when `charge_count` is at least 21, 0.10 when it is at least 11, and 0.00 otherwise; and `discount_cents` is `fee_total_cents` multiplied by `discount_tier`, rounded half up, computed once after `fee_total_cents` is final."

        Design: Difficulty/combinatorial_formula/invoice_tier_evaluation_order
        """
        ctx = setup_invoiced_practice(num_bookings=11, copay_cents=20000)
        invoice = ctx["invoice"]
        assert invoice["charge_count"] == 11
        assert invoice["fee_total_cents"] == 33000, (
            f"fee_total must be 11 x round_half_up(20000*0.15)=3000 each = 33000, "
            f"got {invoice['fee_total_cents']}"
        )
        assert invoice["discount_tier"] == 0.10
        assert invoice["discount_cents"] == 3300
        assert invoice["amount_due_cents"] == 29700

    def test_discount_never_flows_back_into_per_charge_fees(self, api):
        """PRD §3.7: "`fee_total_cents` is the sum of the swept charges' individual `marketplace_fee_cents` values — the per-charge rounded values, never re-derived from gross and never re-adjusted per charge after the discount is known; `discount_tier` is 0.20 when `charge_count` is at least 21, 0.10 when it is at least 11, and 0.00 otherwise; and `discount_cents` is `fee_total_cents` multiplied by `discount_tier`, rounded half up, computed once after `fee_total_cents` is final."

        Design: Difficulty/combinatorial_formula/invoice_tier_evaluation_order
        """
        ctx = setup_invoiced_practice(num_bookings=11, copay_cents=20000)
        charges = list_charges_for_invoice(ctx["invoice"]["id"])
        assert len(charges) == 11
        for charge in charges:
            assert charge["marketplace_fee_cents"] == 3000, (
                f"per-charge fee must stay at 3000 after the tier discount, "
                f"got {charge['marketplace_fee_cents']}"
            )
            assert charge["status"] == "INVOICED"


class TestPayoutProvisionalVsFinalSettlement:
    def test_payout_variants_diverge_by_exactly_the_tier_discount(self, api):
        """PRD §3.7: "The two always reconcile: `payout_final_cents` equals `payout_provisional_cents` plus `discount_cents`. As a worked example, eleven charges with a gross of 10000 cents each produce a provisional payout of 89980 cents, a final payout of 91630 cents, and a delta of 1650 cents that equals the discount."

        Design: Difficulty/dual_variant_calc/payout_provisional_vs_final_settlement
        """
        ctx = setup_invoiced_practice(num_bookings=11, copay_cents=10000)
        invoice = get_invoice(ctx["invoice"]["id"])
        assert invoice["charge_count"] == 11
        assert invoice["fee_total_cents"] == 16500
        assert invoice["discount_tier"] == 0.10
        assert invoice["discount_cents"] == 1650
        assert invoice["amount_due_cents"] == 14850
        assert invoice["payout_provisional_cents"] == 89980
        assert invoice["payout_final_cents"] == 91630
        assert (
            invoice["payout_final_cents"] - invoice["payout_provisional_cents"]
            == invoice["discount_cents"]
        )

    def test_payout_provisional_is_sum_of_per_charge_net(self, api):
        """PRD §3.7: "`payout_provisional_cents` is the sum of the swept charges' `net_to_practice_cents` — the per-charge view that does not credit the tier discount back."

        Design: Difficulty/dual_variant_calc/payout_provisional_vs_final_settlement
        """
        ctx = setup_invoiced_practice(num_bookings=11, copay_cents=10000)
        charges = list_charges_for_invoice(ctx["invoice"]["id"])
        invoice = get_invoice(ctx["invoice"]["id"])
        expected_provisional = sum(c["net_to_practice_cents"] for c in charges)
        assert invoice["payout_provisional_cents"] == expected_provisional == 89980
        assert_payout_reconciliation(invoice)


class TestInvoiceTierBoundary10Vs11:
    def test_ten_charges_stay_below_tier_boundary(self, api):
        """PRD §3.7: "`discount_tier` is 0.20 when `charge_count` is at least 21, 0.10 when it is at least 11, and 0.00 otherwise; and `discount_cents` is `fee_total_cents` multiplied by `discount_tier`, rounded half up, computed once after `fee_total_cents` is final."

        Design: Corner/calculations/invoice_tier_boundary_10_vs_11_charges
        """
        ctx = setup_invoiced_practice(num_bookings=10, copay_cents=10000)
        invoice = ctx["invoice"]
        assert invoice["charge_count"] == 10
        assert invoice["discount_tier"] == 0
        assert invoice["discount_cents"] == 0
        assert invoice["amount_due_cents"] == 15000, (
            f"10 charges x 1500 fee = 15000 with no tier, got {invoice['amount_due_cents']}"
        )

    def test_eleven_charges_cross_into_tier_010(self, api):
        """PRD §3.7: "As a worked example, eleven charges each carrying a fee of 1500 cents produce a `fee_total_cents` of 16500, a tier of 0.10, a `discount_cents` of 1650, and an `amount_due_cents` of 14850."

        Design: Corner/calculations/invoice_tier_boundary_10_vs_11_charges
        """
        ctx = setup_invoiced_practice(num_bookings=11, copay_cents=10000)
        invoice = ctx["invoice"]
        assert invoice["charge_count"] == 11
        assert invoice["discount_tier"] == 0.10
        assert invoice["discount_cents"] == 1650
        assert invoice["amount_due_cents"] == 14850


class TestBillingModeSwitchGuard:
    def test_switch_blocked_while_billable_charges_exist(self, api):
        """PRD §3.1: "Switching `billing_mode` between `PER_BOOKING` and `SUBSCRIPTION` is an `OpsAdmin` action, but it is blocked while the practice has any charge still in `BILLABLE` status, rejected with `ERR_PENDING_CHARGES` — unswept per-booking revenue must first be invoiced before the practice's billing basis can change."

        Design: Corner/validations/billing_mode_switch_blocked_with_billable_charges
        """
        ctx = setup_bookable_practice(slot_windows=[slot_time(48)])
        patient = create_patient()
        book_slot(ctx["slots"][0]["id"], patient["id"], ctx["type"]["id"])
        resp = api_client.set_billing_mode(
            ctx["practice"]["id"], {"billing_mode": "SUBSCRIPTION"}, TEST_USERS["ops_admin_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_PENDING_CHARGES)

    def test_switch_succeeds_with_no_charges(self, api):
        """PRD §3.1: "Switching `billing_mode` between `PER_BOOKING` and `SUBSCRIPTION` is an `OpsAdmin` action, but it is blocked while the practice has any charge still in `BILLABLE` status, rejected with `ERR_PENDING_CHARGES` — unswept per-booking revenue must first be invoiced before the practice's billing basis can change."

        Design: Corner/validations/billing_mode_switch_blocked_with_billable_charges
        """
        practice = create_practice()
        resp = api_client.set_billing_mode(
            practice["id"], {"billing_mode": "SUBSCRIPTION"}, TEST_USERS["ops_admin_headers"]
        )
        data = validate_success(resp)
        assert data["billing_mode"] == "SUBSCRIPTION"
