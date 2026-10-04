"""Loan servicing: amortization, the payment waterfall, late fees, delinquency,
default, charge-off, payoff, and servicing event records."""
from test_helpers import (
    ApiErrorId,
    advance_loan_periods,
    get_success_data,
    setup_funded_loan,
    setup_securitized_loan,
    validate_error,
    validate_paginated,
    validate_success,
)


def _events(api, loan_id, auditor_headers):
    resp = api.list_servicing_events(loan_id, auditor_headers)
    data, _meta = validate_paginated(resp)
    return data


class TestAmortization:

    def test_monthly_payment_computed_at_funding_and_frozen(
        self, api, servicing_agent_headers
    ):
        """PRD 3.10: "A funded loan begins in `FUNDED` with its amortization computed once and frozen: the monthly rate is the loan's `apr` divided by twelve and by one hundred (the APR is stored as a percentage number, so 9.5 means nine and a half percent), and the `monthly_payment_cents` is the standard amortizing payment over the thirty-six-month term - the principal times the monthly rate, divided by one minus the quantity one plus the monthly rate raised to the negative term - rounded half up to whole cents."
        PRD 3.10: "The `scheduled_interest_cents` due for each period is the outstanding principal at the start of that period times the monthly rate, rounded half up to whole cents."

        Design: Corner/calculations/amortization_monthly_payment_computed_at_funding_and_frozen
        """
        bundle = setup_funded_loan()
        loan = bundle["loan"]
        # 5000000 * 0.01 / (1 - 1.01^-36) = 166071.856... -> round_half_up 166072
        assert loan["monthly_payment_cents"] == 166072
        # round_half_up(5000000 * 0.01) == 50000
        assert loan["scheduled_interest_cents"] == 50000
        assert loan["term_months"] == 36
        assert loan["apr"] == 12.0

        # Servicing advances never recompute the frozen payment.
        loan = advance_loan_periods(loan["id"], 1)
        assert loan["monthly_payment_cents"] == 166072

    def test_amortization_terms_copied_from_credit_box(
        self, api, servicing_agent_headers
    ):
        """PRD 3.9: "`principal_cents` copies the approved principal, `apr` copies the allocating credit box's rate, and `term_months` is fixed at thirty-six."

        Design: Corner/calculations/amortization_monthly_payment_computed_at_funding_and_frozen
        """
        bundle = setup_funded_loan(box_overrides={"annual_percentage_rate": 6.0})
        loan = bundle["loan"]
        assert loan["apr"] == 6.0
        assert loan["term_months"] == 36
        # 5000000 * 0.005 / (1 - 1.005^-36) = 152109.79... -> round half up 152110
        assert loan["monthly_payment_cents"] == 152110


class TestLateFees:

    def test_late_fee_capped_at_1500_per_period_and_accumulates(
        self, api, servicing_agent_headers, auditor_headers
    ):
        """PRD 3.10: "Each late fee is the lesser of five percent of `monthly_payment_cents` - rounded half up to whole cents - and 1500 cents; one fee is assessed per missed period and fees accumulate across periods with no aggregate cap beyond that per-period cap."
        PRD 3.10: "Against a `CURRENT` loan it sets `days_delinquent` to thirty, assesses the first late fee, and moves the loan to `DELINQUENT`."

        Design: Corner/calculations/late_fee_capped_at_1500_constant
        """
        bundle = setup_funded_loan()
        loan_id = bundle["loan"]["id"]

        loan = advance_loan_periods(loan_id, 1)
        # 0.05 * 166072 = 8303.6 exceeds the 1500 cap -> fee 1500.
        assert loan["late_fee_accrued_cents"] == 1500
        assert loan["days_delinquent"] == 30
        assert loan["status"] == "DELINQUENT"

        loan = advance_loan_periods(loan_id, 1)
        assert loan["late_fee_accrued_cents"] == 3000
        assert loan["days_delinquent"] == 60

        fee_events = [
            e for e in _events(api, loan_id, auditor_headers)
            if e["event_type"] == "LATE_FEE_ASSESSED"
        ]
        assert len(fee_events) == 2
        assert all(e["amount_cents"] == 1500 for e in fee_events)

    def test_late_fee_uncapped_when_five_percent_below_cap(
        self, api, servicing_agent_headers
    ):
        """PRD 3.10: "Each late fee is the lesser of five percent of `monthly_payment_cents` - rounded half up to whole cents - and 1500 cents"

        Design: Corner/calculations/late_fee_capped_at_1500_constant
        """
        # Principal 500000 at APR 12: payment = 500000*0.01/(1-1.01^-36) = 16607.15 -> 16607.
        # 5% of 16607 = 830.35 -> round half up 830, below the 1500 cap.
        bundle = setup_funded_loan(
            requested_amount_cents=500000,
            applicant_overrides={"monthly_debt_payments_cents": 100000},
        )
        loan = advance_loan_periods(bundle["loan"]["id"], 1)
        assert loan["monthly_payment_cents"] == 16607
        assert loan["late_fee_accrued_cents"] == 830


class TestPaymentWaterfall:

    def test_exact_fee_plus_interest_payment_cures_without_touching_principal(
        self, api, servicing_agent_headers, auditor_headers
    ):
        """PRD 3.10: "Every payment flows through a strict waterfall: accrued late fees first, then the current period's scheduled interest, then outstanding principal, each bucket drained in whole integer cents before the next is touched, and the per-payment split is never re-rounded after the fact."
        PRD 3.10: "A delinquent loan returns to `CURRENT` only when the posted payment covers the accrued late fees in full and the scheduled interest in full for every elapsed unpaid period - the complete catch-up amount - at which point `days_delinquent` and `late_fee_accrued_cents` reset to zero and a `PAYMENT_APPLIED` event is recorded"

        Design: Difficulty/combinatorial_formula/payment_waterfall_bucket_order_and_no_post_split_rounding
        """
        bundle = setup_funded_loan()
        loan = advance_loan_periods(bundle["loan"]["id"], 1)
        assert loan["status"] == "DELINQUENT"
        assert loan["late_fee_accrued_cents"] == 1500
        assert loan["scheduled_interest_cents"] == 50000

        resp = api.post_payment(
            loan["id"],
            {"amount_cents": 51500, "expected_loan_version": loan["version"]},
            servicing_agent_headers,
        )
        loan = validate_success(resp, expected_status=200)
        assert loan["late_fee_accrued_cents"] == 0
        assert loan["scheduled_interest_cents"] == 0
        assert loan["outstanding_principal_cents"] == 5000000
        assert loan["status"] == "CURRENT"
        assert loan["days_delinquent"] == 0

        payment_events = [
            e for e in _events(api, loan["id"], auditor_headers)
            if e["event_type"] == "PAYMENT_APPLIED"
        ]
        assert len(payment_events) == 1
        assert payment_events[0]["amount_cents"] == 51500

    def test_one_cent_short_of_full_catch_up_leaves_loan_delinquent(
        self, api, servicing_agent_headers
    ):
        """PRD 3.10: "A delinquent loan returns to `CURRENT` only when the posted payment covers the accrued late fees in full and the scheduled interest in full for every elapsed unpaid period - the complete catch-up amount"

        Design: Difficulty/combinatorial_formula/payment_waterfall_bucket_order_and_no_post_split_rounding
        """
        bundle = setup_funded_loan()
        loan = advance_loan_periods(bundle["loan"]["id"], 1)

        resp = api.post_payment(
            loan["id"],
            {"amount_cents": 51499, "expected_loan_version": loan["version"]},
            servicing_agent_headers,
        )
        loan = validate_success(resp, expected_status=200)
        # Fees drained in full, interest one cent short: no return to CURRENT.
        assert loan["late_fee_accrued_cents"] == 0
        assert loan["scheduled_interest_cents"] == 1
        assert loan["status"] == "DELINQUENT"


class TestDelinquencyLifecycle:

    def test_chargeoff_from_delinquent_is_invalid_state(
        self, api, collections_agent_headers, auditor_headers
    ):
        """PRD 3.10: "Charge-off is a `CollectionsAgent` action against a `DEFAULTED` loan"
        PRD 3.10: "advancing in any state the transition does not govern fails with `ERR_LOAN_INVALID_STATE` (HTTP 409)."
        PRD 5: "`ERR_LOAN_INVALID_STATE` | 409"

        Design: Corner/state_machines/loan_chargeoff_from_delinquent_is_invalid_state
        """
        bundle = setup_funded_loan()
        loan = advance_loan_periods(bundle["loan"]["id"], 2)
        assert loan["status"] == "DELINQUENT"
        assert loan["days_delinquent"] == 60

        resp = api.charge_off_loan(loan["id"], collections_agent_headers)
        validate_error(resp, ApiErrorId.ERR_LOAN_INVALID_STATE)

        loan = get_success_data(api.get_loan(loan["id"], collections_agent_headers))
        assert loan["status"] == "DELINQUENT"
        assert loan["days_delinquent"] == 60
        charge_off_events = [
            e for e in _events(api, loan["id"], auditor_headers)
            if e["event_type"] == "CHARGE_OFF_REPORTED"
        ]
        assert charge_off_events == []


class TestChargeOffInvariant:

    def test_pool_allocated_principal_conserved_across_chargeoff(
        self, api, partner_admin_headers, collections_agent_headers, auditor_headers
    ):
        """PRD 3.10: "Charging off records a `CHARGE_OFF_REPORTED` event whose `amount_cents` is the outstanding principal plus accrued late fees, moves the loan to `CHARGED_OFF`, and - when the loan's `allocation_channel` is `SECURITIZATION` - subtracts the loan's `principal_cents` from its pool's `allocated_principal_cents`."

        Design: Difficulty/compensating_invariant/pool_allocated_principal_conserved_across_chargeoff
        """
        bundle = setup_securitized_loan(pool_overrides={"pool_label": "TR-INV"})
        loan = bundle["loan"]
        pool = bundle["pool"]

        pool = get_success_data(api.get_securitization_pool(pool["id"], partner_admin_headers))
        assert pool["allocated_principal_cents"] == 5000000

        # 90 -> 4th advance reaches exactly 120 and the loan defaults.
        loan = advance_loan_periods(loan["id"], 4)
        assert loan["status"] == "DEFAULTED"
        assert loan["days_delinquent"] == 120
        expected_charge_amount = (
            loan["outstanding_principal_cents"] + loan["late_fee_accrued_cents"]
        )

        resp = api.charge_off_loan(loan["id"], collections_agent_headers)
        loan = validate_success(resp, expected_status=200)
        assert loan["status"] == "CHARGED_OFF"
        assert loan["days_delinquent"] == 120

        pool = get_success_data(api.get_securitization_pool(pool["id"], partner_admin_headers))
        assert pool["allocated_principal_cents"] == 0
        assert pool["status"] == "OPEN"
        assert pool["target_principal_cents"] == 100000000

        charge_off_events = [
            e for e in _events(api, loan["id"], auditor_headers)
            if e["event_type"] == "CHARGE_OFF_REPORTED"
        ]
        assert len(charge_off_events) == 1
        assert charge_off_events[0]["amount_cents"] == expected_charge_amount

    def test_charge_off_releases_pool_capacity_for_reuse(
        self, api, partner_admin_headers, collections_agent_headers
    ):
        """PRD 3.10: "Charging off records a `CHARGE_OFF_REPORTED` event whose `amount_cents` is the outstanding principal plus accrued late fees, moves the loan to `CHARGED_OFF`, and - when the loan's `allocation_channel` is `SECURITIZATION` - subtracts the loan's `principal_cents` from its pool's `allocated_principal_cents`."

        Design: Difficulty/compensating_invariant/pool_allocated_principal_conserved_across_chargeoff
        """
        bundle = setup_securitized_loan(pool_overrides={"pool_label": "TR-INV-2"})
        loan = advance_loan_periods(bundle["loan"]["id"], 4)
        validate_success(api.charge_off_loan(loan["id"], collections_agent_headers))

        pool = get_success_data(
            api.get_securitization_pool(bundle["pool"]["id"], partner_admin_headers)
        )
        assert pool["allocated_principal_cents"] == 0
        # The pool itself is untouched: still OPEN at its original target.
        assert pool["status"] == "OPEN"
        assert pool["target_principal_cents"] == 100000000


class TestPayoffInvariant:

    def test_partner_funded_balance_conserved_across_payoff(
        self, api, partner_admin_headers, servicing_agent_headers, auditor_headers
    ):
        """PRD 3.10: "An overpayment beyond all three buckets reduces `outstanding_principal_cents` ahead of schedule, and when the outstanding principal reaches exactly zero the loan moves from `CURRENT` to `PAID_OFF` and a `PAYOFF_RECORDED` event carries the final payment's amount."
        PRD 3.10: "every payment application also triggers recomputation of the holder partner's `funded_balance_cents`."

        Design: Difficulty/compensating_invariant/partner_funded_balance_conserved_across_payoff
        """
        bundle = setup_funded_loan()
        loan = bundle["loan"]
        partner_id = bundle["partner"]["id"]

        partner = get_success_data(api.get_partner(partner_id, partner_admin_headers))
        assert partner["funded_balance_cents"] == 5000000
        originated_before = partner["originated_this_month_count"]

        resp = api.post_payment(
            loan["id"],
            {"amount_cents": 5050000, "expected_loan_version": loan["version"]},
            servicing_agent_headers,
        )
        loan = validate_success(resp, expected_status=200)
        assert loan["status"] == "PAID_OFF"
        assert loan["outstanding_principal_cents"] == 0

        partner = get_success_data(api.get_partner(partner_id, partner_admin_headers))
        assert partner["funded_balance_cents"] == 0
        # Payoff is not an origination: the monthly counter is unchanged.
        assert partner["originated_this_month_count"] == originated_before

        payoff_events = [
            e for e in _events(api, loan["id"], auditor_headers)
            if e["event_type"] == "PAYOFF_RECORDED"
        ]
        assert len(payoff_events) == 1

    def test_payoff_records_final_payment_amount_on_event(
        self, api, partner_admin_headers, servicing_agent_headers, auditor_headers
    ):
        """PRD 3.10: "when the outstanding principal reaches exactly zero the loan moves from `CURRENT` to `PAID_OFF` and a `PAYOFF_RECORDED` event carries the final payment's amount."

        Design: Difficulty/compensating_invariant/partner_funded_balance_conserved_across_payoff
        """
        bundle = setup_funded_loan()
        loan = bundle["loan"]

        resp = api.post_payment(
            loan["id"],
            {"amount_cents": 5050000, "expected_loan_version": loan["version"]},
            servicing_agent_headers,
        )
        loan = validate_success(resp, expected_status=200)
        assert loan["status"] == "PAID_OFF"

        payoff_events = [
            e for e in _events(api, loan["id"], auditor_headers)
            if e["event_type"] == "PAYOFF_RECORDED"
        ]
        assert len(payoff_events) == 1
        assert payoff_events[0]["amount_cents"] == 5050000

        partner = get_success_data(
            api.get_partner(bundle["partner"]["id"], partner_admin_headers)
        )
        assert partner["funded_balance_cents"] == 0


class TestPaymentValidation:

    def test_payment_of_zero_returns_payment_invalid(
        self, api, servicing_agent_headers
    ):
        """PRD 3.10: "A payment is valid only when the amount is positive and the loan is in `CURRENT` or `DELINQUENT`; otherwise it is rejected with `ERR_PAYMENT_INVALID` (HTTP 422)."

        Design: Corner/validations/payment_of_zero_returns_payment_invalid
        """
        bundle = setup_funded_loan()
        loan = bundle["loan"]

        resp = api.post_payment(
            loan["id"],
            {"amount_cents": 0, "expected_loan_version": loan["version"]},
            servicing_agent_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_INVALID)

        loan = get_success_data(api.get_loan(loan["id"], servicing_agent_headers))
        assert loan["version"] == bundle["loan"]["version"]
        assert loan["outstanding_principal_cents"] == 5000000


class TestServicingEvents:

    def test_servicing_events_are_immutable_and_chronological(
        self, api, auditor_headers
    ):
        """PRD 2.4: "`ServicingEvent` and `AllocationDecision` are immutable records: they carry only `id` and `created_at`, and both `updated_at` and `version` are absent entirely - they are written once at decision or event time and never mutated thereafter."
        PRD 3.10: "A loan's servicing events are listed in chronological order by `occurred_at` ascending."
        PRD 3.10: "Each advance records a `LATE_FEE_ASSESSED` event followed by a `DELINQUENCY_ADVANCED` event."

        Design: Corner/entities/servicing_event_has_no_version_field_and_no_update_endpoint
        """
        bundle = setup_funded_loan()
        loan = advance_loan_periods(bundle["loan"]["id"], 1)

        events = _events(api, loan["id"], auditor_headers)
        assert len(events) >= 2
        for event in events:
            assert event.get("id")
            assert event.get("created_at")
            assert "version" not in event, "immutable record carries no version"
            assert "updated_at" not in event, "immutable record carries no updated_at"
            assert event.get("event_type")
            assert event.get("occurred_at")
            assert event.get("resulting_loan_status")

        occurred = [e["occurred_at"] for e in events]
        assert occurred == sorted(occurred), "events must be chronological by occurred_at"

        types = [e["event_type"] for e in events]
        fee_idx = types.index("LATE_FEE_ASSESSED")
        adv_idx = types.index("DELINQUENCY_ADVANCED", fee_idx)
        assert fee_idx < adv_idx, "LATE_FEE_ASSESSED precedes DELINQUENCY_ADVANCED"
