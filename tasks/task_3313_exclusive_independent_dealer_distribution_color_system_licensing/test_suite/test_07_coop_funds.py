"""Co-op fund accrual, claim lifecycle, and ledger conservation."""
from test_helpers import (
    CD,
    RM,
    ApiErrorId,
    api_client,
    make_dealer_principal_headers,
    place_order,
    setup_coop_claim,
    setup_onboarded_dealer,
    validate_error,
    validate_success,
    walk_order_to_paid,
)


class TestCoopLedgerConservation:
    def test_approve_moves_amount_into_pending_conserving_total(self, api):
        """PRD section 3.5: "Payment books the co-op accrual:
        `coop_accrued_cents` is the order's `invoice_cents` multiplied by the
        dealer's `coop_accrual_rate`, rounded half-up to integer cents, and
        that amount is added to the dealer's `coop_balance_cents`."
        PRD section 3.5: "Approval moves the claim to `APPROVED` and adds
        `amount_cents` to the dealer's `coop_pending_cents`."

        Design: Difficulty/compensating_invariant/coop_ledger_conservation_through_claim_lifecycle
        """
        ctx = setup_onboarded_dealer(
            dealer_overrides={"branding_compliant": True}, pay_stock=True,
        )
        dealer_id = ctx["dealer"]["id"]
        # 40 units x 100 cents x 0.02 = 80 cents accrued.
        before = validate_success(api.get_dealer(dealer_id, RM))
        assert before["coop_balance_cents"] == 80
        assert before["coop_pending_cents"] == 0
        claim = setup_coop_claim(dealer_id, amount_cents=50)
        validate_success(api.approve_coop_claim(claim["id"], CD))
        after = validate_success(api.get_dealer(dealer_id, RM))
        assert after["coop_balance_cents"] == 80
        assert after["coop_pending_cents"] == 50

    def test_pay_drains_pending_and_balance_by_exact_amount(self, api):
        """PRD section 3.5: "Payment by a `ChannelDirector` moves an
        `APPROVED` claim to `PAID`, subtracting `amount_cents` from both
        `coop_pending_cents` and `coop_balance_cents`."

        Design: Difficulty/compensating_invariant/coop_ledger_conservation_through_claim_lifecycle
        """
        ctx = setup_onboarded_dealer(
            dealer_overrides={"branding_compliant": True}, pay_stock=True,
        )
        dealer_id = ctx["dealer"]["id"]
        claim = setup_coop_claim(dealer_id, amount_cents=50)
        validate_success(api.approve_coop_claim(claim["id"], CD))
        paid = validate_success(api.pay_coop_claim(claim["id"], CD))
        assert paid["status"] == "PAID"
        after = validate_success(api.get_dealer(dealer_id, RM))
        assert after["coop_balance_cents"] == 30
        assert after["coop_pending_cents"] == 0


class TestCoopAccrualRounding:
    def test_half_up_rounding_on_accrual(self, api):
        """PRD section 3.5: "Payment books the co-op accrual:
        `coop_accrued_cents` is the order's `invoice_cents` multiplied by the
        dealer's `coop_accrual_rate`, rounded half-up to integer cents, and
        that amount is added to the dealer's `coop_balance_cents`."
        PRD section 2.6: "Where a calculation produces a fractional cent, the
        result is rounded half-up to the nearest integer cent at the step the
        rule specifies".

        Design: Corner/calculations/coop_accrual_rounding_half_up
        """
        ctx = setup_onboarded_dealer(
            system_overrides={
                "code": "G26",
                "name": "Gen-26",
                "generation": 26,
                "annual_license_fee_cents": 1_000_000,
                "min_initial_inventory_units": 20,
            },
            line_overrides={"code": "S165", "name": "Specialty 165", "base_price_cents": 165},
            initial_stock_units=25,
        )
        dealer_id = ctx["dealer"]["id"]
        order = place_order(dealer_id, ctx["line"]["id"], units=25, purpose="RESTOCK")
        assert order["invoice_cents"] == 4125
        paid = walk_order_to_paid(order["id"], dealer_id)
        # round_half_up(4125 * 0.02) = round_half_up(82.5) = 83.
        assert paid["coop_accrued_cents"] == 83
        dealer = validate_success(api.get_dealer(dealer_id, RM))
        assert dealer["coop_balance_cents"] == 83

    def test_accrual_zero_rate_accords_zero(self, api):
        """PRD section 3.5: "`coop_accrued_cents` is the order's
        `invoice_cents` multiplied by the dealer's `coop_accrual_rate`,
        rounded half-up to integer cents, and that amount is added to the
        dealer's `coop_balance_cents`."

        Design: Corner/calculations/coop_accrual_rounding_half_up
        """
        ctx = setup_onboarded_dealer(dealer_overrides={"coop_accrual_rate": 0.0})
        dealer_id = ctx["dealer"]["id"]
        order = place_order(dealer_id, ctx["line"]["id"], units=10, purpose="RESTOCK")
        paid = walk_order_to_paid(order["id"], dealer_id)
        assert paid["coop_accrued_cents"] == 0


class TestClaimWindowBoundary:
    def test_claim_91_days_old_rejected(self, api):
        """PRD section 3.5: "The activity window is enforced at both
        submission and approval: the `activity_date` must not be in the
        future and must be no more than 90 days before the current logical
        time, with the comparison made at day precision; violations are
        rejected with `ERR_CLAIM_WINDOW_EXPIRED` (HTTP 422)."

        Design: Corner/validations/claim_window_90_days_boundary
        """
        ctx = setup_onboarded_dealer()
        dealer_id = ctx["dealer"]["id"]
        resp = api.create_coop_claim(
            {
                "dealer_id": dealer_id,
                "amount_cents": 10,
                "description": "Old flyer",
                "activity_date": "2026-06-02T00:00:00Z",
            },
            make_dealer_principal_headers(dealer_id),
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_WINDOW_EXPIRED)

    def test_claim_exactly_90_days_old_accepted(self, api):
        """PRD section 3.5: "The activity window is enforced at both
        submission and approval: the `activity_date` must not be in the
        future and must be no more than 90 days before the current logical
        time, with the comparison made at day precision".

        Design: Corner/validations/claim_window_90_days_boundary
        """
        ctx = setup_onboarded_dealer()
        dealer_id = ctx["dealer"]["id"]
        claim = setup_coop_claim(
            dealer_id, amount_cents=10, description="Edge flyer",
            activity_date="2026-06-03T00:00:00Z",
        )
        assert claim["status"] == "SUBMITTED"


class TestCoopApproveGates:
    def test_approve_rejected_without_branding_compliance(self, api):
        """PRD section 3.5: "Approval by a `ChannelDirector` requires three
        conditions: the dealer's `branding_compliant` flag is true; the
        dealer is `ACTIVE`; and the dealer's `coop_balance_cents` is at least
        the claim's `amount_cents` — pending reservations on other
        approved-but-unpaid claims do not reduce the approvable balance. A
        failure of the balance or branding conditions is rejected with
        `ERR_COOP_FUNDS_INSUFFICIENT` (HTTP 422)."

        Design: Corner/validations/coop_approve_without_branding_compliance_fails
        """
        ctx = setup_onboarded_dealer(
            dealer_overrides={"branding_compliant": False}, pay_stock=True,
        )
        dealer_id = ctx["dealer"]["id"]
        assert ctx["dealer"]["branding_compliant"] is False
        claim = setup_coop_claim(dealer_id, amount_cents=10)
        resp = api.approve_coop_claim(claim["id"], CD)
        validate_error(resp, ApiErrorId.ERR_COOP_FUNDS_INSUFFICIENT)

    def test_approve_rejected_when_claim_exceeds_balance(self, api):
        """PRD section 3.5: "Approval by a `ChannelDirector` requires three
        conditions: the dealer's `branding_compliant` flag is true; the
        dealer is `ACTIVE`; and the dealer's `coop_balance_cents` is at least
        the claim's `amount_cents` — pending reservations on other
        approved-but-unpaid claims do not reduce the approvable balance. A
        failure of the balance or branding conditions is rejected with
        `ERR_COOP_FUNDS_INSUFFICIENT` (HTTP 422)."

        Design: Corner/validations/coop_claim_over_balance_rejected_at_approve
        """
        ctx = setup_onboarded_dealer(pay_stock=True)
        dealer_id = ctx["dealer"]["id"]
        # Balance is 80 cents after the paid stock order.
        claim = setup_coop_claim(dealer_id, amount_cents=90, description="Too big")
        resp = api.approve_coop_claim(claim["id"], CD)
        validate_error(resp, ApiErrorId.ERR_COOP_FUNDS_INSUFFICIENT)

    def test_approve_accepts_claim_equal_to_balance(self, api):
        """PRD section 3.5: "Approval by a `ChannelDirector` requires three
        conditions: the dealer's `branding_compliant` flag is true; the
        dealer is `ACTIVE`; and the dealer's `coop_balance_cents` is at least
        the claim's `amount_cents`".

        Design: Corner/validations/coop_claim_over_balance_rejected_at_approve
        """
        ctx = setup_onboarded_dealer(
            dealer_overrides={"branding_compliant": True}, pay_stock=True,
        )
        dealer_id = ctx["dealer"]["id"]
        claim = setup_coop_claim(dealer_id, amount_cents=80, description="Exact")
        approved = validate_success(api.approve_coop_claim(claim["id"], CD))
        assert approved["status"] == "APPROVED"
