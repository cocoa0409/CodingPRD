"""Dual-variant and combinatorial calculation claims.

Each test asserts one externally observable outcome of a calculation whose
legs are pinned by the contract.
"""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    create_account,
    create_activated_account,
    create_commission_record,
    create_transaction_request,
    create_lease,
    submit_transaction_request,
    set_clock,
    setup_executed_lease_with_accrual,
    setup_pending_request,
    ae_headers,
    TEST_USERS,
)


class TestDualVariantCalculations:

    def test_accrual_credit_is_the_commission_total(self, api):
        """PRD §2.9: "applying the credit against a fee accrual transfers value
        within the ledger without ever changing the total", and PRD §3.4:
        "Applying the credits moves the accrual to CREDITED, sets its
        applied_credit_cents to the sum of the uncredited records'
        credit_amount_cents".
        PRD §2.9: "A per-record commission credit is the record's base_rent_cents
        multiplied by its commission_pct, rounded half-up to 2 decimal places,
        and floored at a minimum of 10,000 cents".

        Design: Difficulty/dual_variant_calc/standby_fee_credit_conversion_vs_fee_level_netting
        """
        account, lease, request, assignment, engagement, accrual = (
            setup_executed_lease_with_accrual(
                accrual_period="2026-Q2",
                base_fee_cents=2_000_000,
                extra_record={
                    "base_rent_cents": 40_000_000,
                    "commission_pct": 0.15,
                    "accrual_date": "2026-06-01T00:00:00Z",
                },
            )
        )
        applied = validate_success(
            api.apply_lease_execution(accrual["id"], TEST_USERS["transaction_manager_headers"]),
            200,
        )
        # 6,000,000.00 (posted) + 1,850,000.00 (lease execution) = 7,850,000.00
        assert applied["applied_credit_cents"] == pytest.approx(7_850_000.00, abs=0.01)
        assert applied["credit_application_state"] == "CREDITED"
        assert applied["base_fee_cents"] == 2_000_000
        # The applied credit is not clamped to the accrual's base fee.
        assert applied["applied_credit_cents"] != applied["base_fee_cents"]

    def test_annual_fee_deducts_only_the_third_party_credit(self, api,
                                                            account_executive_headers):
        """PRD §2.9: "The account's annual_net_fee_cents is the gross fee — the
        selected tier rate multiplied by portfolio_sqft — reduced by the total
        third-party credit; self-performed credits lift the applied-credit
        ceiling but are never subtracted from the fee".
        PRD §2.9: "the per-square-foot rate is 145 cents when portfolio_sqft is
        at most 250,000, 118 cents when it is at most 750,000, and 96 cents
        otherwise".

        Design: Difficulty/dual_variant_calc/standby_fee_credit_conversion_vs_fee_level_netting
        """
        account, lease, request, assignment, engagement, accrual = (
            setup_executed_lease_with_accrual(
                accrual_period="2026-Q2", base_fee_cents=2_000_000,
            )
        )
        current = get_success_data(
            api.get_account(account["id"], ae_headers(account))
        )
        # gross fee = 118 * 400,000 = 47,200,000; third-party credit = 1,850,000
        assert current["annual_net_fee_cents"] == pytest.approx(45_350_000.00, abs=0.01)


class TestSavingsVariants:

    def test_submit_records_provisional_savings_against_the_benchmark(self, api):
        """PRD §3.3: "The benchmark rate is 1,750 cents per square foot per year,
        and the benchmark annual figure is that rate multiplied by the request's
        lease leased_sqft."
        PRD §3.3: "Provisional savings are the prior rent minus the benchmark
        annual figure, floored at zero, multiplied by requested_term_months and
        divided by 12."

        Design: Difficulty/dual_variant_calc/savings_recorded_provisional_vs_final
        """
        account, lease, request, assignment = setup_pending_request()
        current = validate_success(
            api.get_transaction_request(request["id"], TEST_USERS["transaction_manager_headers"]),
            200,
        )
        # (74,000,000 - 1750 * 40,000) * 60 / 12 = 4,000,000 * 5 = 20,000,000
        assert current["savings_provisional_cents"] == 20_000_000
        assert current["request_state"] == "PENDING_APPROVAL"
        # No final figure is written before execution.
        assert not current.get("savings_final_cents")

    def test_provisional_leg_ignores_the_proposed_rent(self, api):
        """PRD §3.3: "Provisional savings uses a market benchmark rather than the
        negotiated rent."
        PRD §3.3: "Final savings uses the executed rent instead and drops the
        benchmark entirely: they are the prior rent minus
        proposed_rent_cents_per_year, multiplied by requested_term_months and
        divided by 12".

        Design: Difficulty/dual_variant_calc/savings_recorded_provisional_vs_final
        """
        account, lease, request, assignment = setup_pending_request()
        current = get_success_data(
            api.get_transaction_request(
                request["id"], TEST_USERS["transaction_manager_headers"]
            )
        )
        # The final leg would give (74,000,000 - 68,000,000) * 60 / 12 = 30,000,000.
        assert current["savings_provisional_cents"] == 20_000_000
        assert current["savings_provisional_cents"] != 30_000_000


class TestCombinatorialFormula:

    def test_tiered_fee_applies_third_party_credit_and_self_perform_floor(self, api,
                                                                         account_executive_headers):
        """PRD §2.9: "A per-record commission credit is the record's
        base_rent_cents multiplied by its commission_pct, rounded half-up to 2
        decimal places, and floored at a minimum of 10,000 cents".
        PRD §2.9: "The account's annual_net_fee_cents is the gross fee — the
        selected tier rate multiplied by portfolio_sqft — reduced by the total
        third-party credit; self-performed credits lift the applied-credit
        ceiling but are never subtracted from the fee."

        Design: Difficulty/combinatorial_formula/tiered_fee_with_nested_credit_clamp
        """
        account = create_activated_account(platform_tier="ENTERPRISE", portfolio_sqft=400_000)
        r1 = create_commission_record(
            account, commission_source="THIRD_PARTY",
            base_rent_cents=40_000_000, commission_pct=0.15,
            accrual_date="2026-06-01T00:00:00Z",
        )
        r2 = create_commission_record(
            account, commission_source="SELF_PERFORM",
            base_rent_cents=30_000_000, commission_pct=0.10,
            accrual_date="2026-07-01T00:00:00Z",
        )
        assert r1["credit_amount_cents"] == pytest.approx(6_000_000.00, abs=0.01)
        assert r2["credit_amount_cents"] == pytest.approx(3_000_000.00, abs=0.01)
        current = get_success_data(api.get_account(account["id"], ae_headers(account)))
        # 47,200,000 - 6,000,000 (third-party only) = 41,200,000
        assert current["annual_net_fee_cents"] == pytest.approx(41_200_000.00, abs=0.01)

    def test_self_perform_credit_is_not_deducted_from_the_fee(self, api,
                                                             account_executive_headers):
        """PRD §2.9: "self-performed credits lift the applied-credit ceiling but
        are never subtracted from the fee."

        Design: Difficulty/combinatorial_formula/tiered_fee_with_nested_credit_clamp
        """
        account = create_activated_account(platform_tier="ENTERPRISE", portfolio_sqft=400_000)
        create_commission_record(
            account, commission_source="THIRD_PARTY",
            base_rent_cents=40_000_000, commission_pct=0.15,
            accrual_date="2026-06-01T00:00:00Z",
        )
        create_commission_record(
            account, commission_source="SELF_PERFORM",
            base_rent_cents=30_000_000, commission_pct=0.10,
            accrual_date="2026-07-01T00:00:00Z",
        )
        current = get_success_data(api.get_account(account["id"], ae_headers(account)))
        # Deducting both credits would yield 38,200,000 — the contract forbids it.
        assert current["annual_net_fee_cents"] != pytest.approx(38_200_000.00, abs=0.01)
        assert current["annual_net_fee_cents"] == pytest.approx(41_200_000.00, abs=0.01)


class TestRoundingOrder:

    def test_per_record_credit_rounds_before_summing(self, api, account_executive_headers):
        """PRD §2.9: "A per-record commission credit is the record's
        base_rent_cents multiplied by its commission_pct, rounded half-up to 2
        decimal places, and floored at a minimum of 10,000 cents".
        PRD §2.6: "All monetary arithmetic that the system performs internally
        must be evaluated with decimal arithmetic rather than binary floating
        point, and every intermediate rounding step uses the round-half-up method
        to 2 decimal places."

        Design: Difficulty/combinatorial_formula/commission_rounding_order_per_record_then_sum
        """
        account = create_activated_account(platform_tier="ENTERPRISE", portfolio_sqft=400_000)
        r2 = create_commission_record(
            account, commission_source="THIRD_PARTY",
            base_rent_cents=333_333, commission_pct=0.185,
            accrual_date="2026-06-01T00:00:00Z",
        )
        r3 = create_commission_record(
            account, commission_source="THIRD_PARTY",
            base_rent_cents=190_001, commission_pct=0.185,
            accrual_date="2026-07-01T00:00:00Z",
        )
        assert r2["credit_amount_cents"] == pytest.approx(61_666.61, abs=0.01)
        assert r3["credit_amount_cents"] == pytest.approx(35_150.19, abs=0.01)

    def test_ledger_total_is_the_sum_of_rounded_records(self, api, account_executive_headers):
        """PRD §3.4: "The per-record contributions are ordered by accrual_date
        ascending and then by created_at ascending before the running sum is
        taken."
        PRD §2.9: "fee_ledger_credit_cents is the sum of credit_amount_cents over
        every commission record on the account".

        Design: Difficulty/combinatorial_formula/commission_rounding_order_per_record_then_sum
        """
        account = create_activated_account(platform_tier="ENTERPRISE", portfolio_sqft=400_000)
        create_commission_record(
            account, commission_source="THIRD_PARTY",
            base_rent_cents=333_333, commission_pct=0.185,
            accrual_date="2026-06-01T00:00:00Z",
        )
        create_commission_record(
            account, commission_source="THIRD_PARTY",
            base_rent_cents=190_001, commission_pct=0.185,
            accrual_date="2026-07-01T00:00:00Z",
        )
        current = get_success_data(api.get_account(account["id"], ae_headers(account)))
        # 61,666.61 + 35,150.19 = 96,816.80; rounding the raw sum first gives .79.
        assert current["fee_ledger_credit_cents"] == pytest.approx(96_816.80, abs=0.01)
        assert current["fee_ledger_credit_cents"] != pytest.approx(96_816.79, abs=0.01)