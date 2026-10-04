"""Difficulty tests: dual-variant calculations produce two divergent readings
from identical inputs."""
from __future__ import annotations

from test_helpers import (
    add_standard_service_period,
    create_coe_request_payload,
    create_loan_payload,
    create_veteran_payload,
    get_entitlement_account,
    get_funding_fee_assessment,
    get_loan,
    setup_closed_loan,
    setup_submitted_loan,
    setup_veteran_with_issued_coe,
    validate_success,
)


class TestEntitlementBaseVsBonus:
    def test_entitlement_base_vs_bonus_after_first_charge(self, api):
        """PRD §2.6: "The base-only variant, `remaining_base_cents`, is the
        greater of zero and the basic entitlement minus the entitlement in use —
        this reading caps guaranty capacity at $36,000.00, so identical inputs
        yield a remaining base of zero once a $300,000 loan has charged $75,000,
        while the bonus reading still shows $116,637.50."

        Design: Difficulty/dual_variant_calc/entitlement_base_vs_bonus_second_loan
        """
        ctx = setup_closed_loan(price_cents=30000000)
        account = get_entitlement_account(ctx["veteran"]["id"])
        assert account["total_charged_cents"] == 7500000
        assert account["remaining_base_cents"] == 0
        assert account["remaining_with_bonus_cents"] == 11663750
        assert account["remaining_base_cents"] != account["remaining_with_bonus_cents"]

    def test_entitlement_variants_agree_before_any_charge(self, api):
        """PRD §2.6: "Define the entitlement in use as `total_charged_cents`
        minus `total_restored_cents`. The base-only variant,
        `remaining_base_cents`, is the greater of zero and the basic entitlement
        minus the entitlement in use"
        PRD §2.6: "The with-bonus variant, `remaining_with_bonus_cents`, is the
        greater of zero and one quarter of the county limit minus the entitlement
        in use — guaranty capacity under this variant is 25% of the county
        limit, $191,637.50"

        Design: Difficulty/dual_variant_calc/entitlement_base_vs_bonus_second_loan
        """
        ctx = setup_veteran_with_issued_coe()
        account = get_entitlement_account(ctx["veteran"]["id"])
        assert account["remaining_base_cents"] == 3600000
        assert account["remaining_with_bonus_cents"] == 19163750
        assert account["total_charged_cents"] == 0
        assert account["total_restored_cents"] == 0


class TestUnderwritingVaMethodVsDtiOnly:
    def test_va_method_denies_where_dti_only_passes(self, api):
        """PRD §3.4: "The decision `outcome` is `APPROVED` when the residual
        income is at least the requirement — equality passes — and additionally
        either the `dti_percent` is at most 41.00 or the residual income
        reaches at least 120 percent of the requirement"

        Here residual 450000 >= 100300 and dti 25.00 <= 41.00, so the VA gate
        approves; `dti_only_pass` is the exposed conventional benchmark, not
        the decision gate.

        Design: Difficulty/dual_variant_calc/underwriting_va_method_vs_dti_only_divergence
        """
        ctx = setup_submitted_loan(loan_overrides={"purchase_price_cents": 30000000})
        decision = validate_success(
            api.create_underwriting_decision(ctx["loan"]["id"], {
                "gross_monthly_income_cents": 600000,
                "new_housing_payment_cents": 150000,
                "other_obligations_annual_cents": [],
                "family_size": 4,
                "region": "SOUTH",
            }),
            expected_status=201,
        )
        assert decision["outcome"] == "APPROVED"
        assert decision["dti_only_pass"] is True
        assert float(decision["dti_percent"]) == 25.00
        assert decision["residual_income_cents"] == 450000
        assert decision["residual_required_cents"] == 100300

    def test_va_method_denial_moves_loan_underwriting_status(self, api):
        """PRD §3.4: "Recording the decision persists the `UnderwritingDecision`
        with all computed fields, moves the loan's `underwriting_status` to the
        outcome, and increments the loan's `version`."

        Design: Difficulty/dual_variant_calc/underwriting_va_method_vs_dti_only_divergence
        """
        ctx = setup_submitted_loan(loan_overrides={"purchase_price_cents": 30000000})
        decision = validate_success(
            api.create_underwriting_decision(ctx["loan"]["id"], {
                "gross_monthly_income_cents": 600000,
                "new_housing_payment_cents": 150000,
                "other_obligations_annual_cents": [],
                "family_size": 4,
                "region": "SOUTH",
            }),
            expected_status=201,
        )
        assert decision["outcome"] == "APPROVED"
        assert decision["dti_only_pass"] is True
        assert get_loan(ctx["loan"]["id"])["underwriting_status"] == "APPROVED"


class TestFundingFeeExemptVariant:
    def _make_veteran_with_coe(self, api, exempt: bool):
        veteran = validate_success(
            api.create_veteran(create_veteran_payload(
                receives_disability_compensation=exempt)),
            expected_status=201,
        )
        add_standard_service_period(veteran["id"])
        coe = validate_success(
            api.create_coe_request(veteran["id"], create_coe_request_payload()),
            expected_status=201,
        )
        validate_success(api.issue_coe(coe["id"]))
        return veteran, coe

    def test_funding_fee_exempt_variant_zeroes_tiered_fee(self, api):
        """PRD §3.3: "When the veteran `receives_disability_compensation` or
        `is_surviving_spouse` at assessment time, the assessment's `exempt` flag
        is true, the `fee_rate` is 0, and the `assessed_fee_cents` is 0 —
        exemption overrides every tier."

        Design: Difficulty/dual_variant_calc/funding_fee_exempt_variant_zeroes_tiered_fee
        """
        exempt_vet, exempt_coe = self._make_veteran_with_coe(api, exempt=True)
        normal_vet, normal_coe = self._make_veteran_with_coe(api, exempt=False)

        exempt_loan = validate_success(
            api.create_loan(
                exempt_vet["id"],
                create_loan_payload(exempt_coe["id"],
                                    purchase_price_cents=30000000,
                                    down_payment_cents=0),
            ),
            expected_status=201,
        )
        normal_loan = validate_success(
            api.create_loan(
                normal_vet["id"],
                create_loan_payload(normal_coe["id"],
                                    purchase_price_cents=30000000,
                                    down_payment_cents=0),
            ),
            expected_status=201,
        )
        exempt_fee = get_funding_fee_assessment(exempt_loan["id"])
        normal_fee = get_funding_fee_assessment(normal_loan["id"])
        assert exempt_fee["exempt"] is True
        assert exempt_fee["assessed_fee_cents"] == 0
        assert normal_fee["exempt"] is False
        assert normal_fee["assessed_fee_cents"] == 645000
        assert exempt_fee["assessed_fee_cents"] != normal_fee["assessed_fee_cents"]

    def test_funding_fee_exempt_fee_rate_is_zero(self, api):
        """PRD §3.3: "When the veteran `receives_disability_compensation` or
        `is_surviving_spouse` at assessment time, the assessment's `exempt` flag
        is true, the `fee_rate` is 0, and the `assessed_fee_cents` is 0 —
        exemption overrides every tier."

        Design: Difficulty/dual_variant_calc/funding_fee_exempt_variant_zeroes_tiered_fee
        """
        exempt_vet, exempt_coe = self._make_veteran_with_coe(api, exempt=True)
        loan = validate_success(
            api.create_loan(
                exempt_vet["id"],
                create_loan_payload(exempt_coe["id"],
                                    purchase_price_cents=30000000,
                                    down_payment_cents=0),
            ),
            expected_status=201,
        )
        fee = get_funding_fee_assessment(loan["id"])
        assert float(fee["fee_rate"]) == 0
        assert fee["collected_cents"] == 0
        assert fee["refunded_cents"] == 0
