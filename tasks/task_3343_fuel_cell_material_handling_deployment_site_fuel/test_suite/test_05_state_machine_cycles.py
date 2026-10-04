"""Non-linear state-machine cycles: invoice dispute/resolve loop (PRD §3.6)
and assessment reject/revise/resubmit loop (PRD §3.1).
"""
import pytest

from test_helpers import (
    validate_success, get_success_data,
    create_site, create_assessment_payload, create_fueling_event,
    create_invoice_with_lines, setup_billing_scenario,
    MANAGER, SAFETY, BILLING,
)


def _setup_issued_invoice(api):
    """ON_SITE_GENERATION contract (base 3.00/kg, committed 10 kg); one 20 kg
    event; invoice with that line, issued."""
    site, contract, station = setup_billing_scenario(
        site_code="S-CYC", supply_mode="ON_SITE_GENERATION",
        base_price_per_kg=3.0, committed_monthly_kg=10)
    fe = create_fueling_event(
        station["id"], contract["id"], forklift_id="FL-C1",
        occurred_at="2026-10-10T09:00:00Z", kg_dispensed=20)
    invoice, _lines = create_invoice_with_lines(
        site["id"], contract["id"], [fe["id"]])
    return site, validate_success(api.issue_invoice(invoice["id"], BILLING))


class TestInvoiceDisputeResolveCycle:
    def test_dispute_then_resolve_reenters_issued(self, api):
        """PRD §3.6: "an `ISSUED` invoice may be paid (moving to `PAID`,
        terminal) by a `BillingOperator`, or disputed by the customer-side
        `SiteManager`, moving it to `DISPUTED`; a `BillingOperator` resolves a
        dispute, returning `DISPUTED` to `ISSUED`."

        Design: Difficulty/non_linear_state_machine/invoice_issue_dispute_resolve_cycle
        """
        _site, invoice = _setup_issued_invoice(api)
        disputed = validate_success(api.dispute_invoice(invoice["id"], MANAGER))
        assert disputed["status"] == "DISPUTED"
        resolved = validate_success(api.resolve_invoice(invoice["id"], BILLING))
        assert resolved["status"] == "ISSUED", "the cycle re-enters a live state"

    def test_resolved_invoice_is_payable_with_frozen_total(self, api):
        """PRD §3.6: "an `ISSUED` invoice may be paid (moving to `PAID`,
        terminal) by a `BillingOperator`, or disputed by the customer-side
        `SiteManager`, moving it to `DISPUTED`; a `BillingOperator` resolves a
        dispute, returning `DISPUTED` to `ISSUED`."
        PRD §3.6: "From issuance on, `credit_cents` and `total_cents` are
        frozen on the invoice."

        Design: Difficulty/non_linear_state_machine/invoice_issue_dispute_resolve_cycle
        """
        _site, invoice = _setup_issued_invoice(api)
        validate_success(api.dispute_invoice(invoice["id"], MANAGER))
        validate_success(api.resolve_invoice(invoice["id"], BILLING))
        paid = validate_success(api.pay_invoice(invoice["id"], BILLING))
        assert paid["status"] == "PAID"
        # 20 kg straddles the 10 kg committed boundary: 10 kg at base 3.00
        # plus 10 kg at base x 0.92 (second-tier discount) = 2.76, so
        # 30.00 + 27.60 = 57.60 USD = 5760 cents; no markup for
        # ON_SITE_GENERATION, no shortfall (20 kg billed >= 10 kg committed),
        # and no service agreement, so the credit stays 0.
        assert paid["total_cents"] == 5760
        assert paid["credit_cents"] == 0


class TestAssessmentReviseLoop:
    def _begin(self, api):
        site = create_site(code="S-REV")
        ass = get_success_data(api.create_assessment(
            site["id"], create_assessment_payload(
                forklift_count=4, duty_cycle_hours_per_day=8.0, peak_shift_hours=8),
            MANAGER))
        validate_success(api.submit_assessment(site["id"], ass["id"], MANAGER))
        validate_success(api.reject_assessment(site["id"], ass["id"], SAFETY))
        return site, ass

    def test_reject_revise_update_resubmit(self, api):
        """PRD §3.1: "A rejected assessment is not dead — the manager may
        revise it, returning `REJECTED` to `DRAFT` for another pass."
        PRD §3.1: "While in `DRAFT` or `REJECTED`, the manager may update its
        duty-cycle inputs, which recomputes `daily_kg_estimate` and increments
        the assessment's `version`."

        Design: Difficulty/non_linear_state_machine/assessment_reject_revise_resubmit_loop
        """
        site, ass = self._begin(api)
        revised = validate_success(api.revise_assessment(site["id"], ass["id"], MANAGER))
        assert revised["status"] == "DRAFT"
        updated = validate_success(api.update_assessment(
            ass["id"], {"forklift_count": 6}, MANAGER))
        assert updated["forklift_count"] == 6
        resubmitted = validate_success(
            api.submit_assessment(site["id"], ass["id"], MANAGER))
        assert resubmitted["status"] == "SUBMITTED"

    def test_resubmitted_assessment_reaches_approved_with_recomputed_estimate(self, api):
        """PRD §3.1: "A rejected assessment is not dead — the manager may
        revise it, returning `REJECTED` to `DRAFT` for another pass."
        PRD §3.1: "the system computes `daily_kg_estimate`: multiply the
        forklift count by the duty-cycle hours and by a consumption factor of
        0.9 kg per engine-on hour, then apply a peak-shift multiplier of 1.0
        when the peak window is 8 hours or shorter and 1.15 when it is longer,
        and round the result half-up to 2 decimal places."

        Design: Difficulty/non_linear_state_machine/assessment_reject_revise_resubmit_loop
        """
        site, ass = self._begin(api)
        validate_success(api.revise_assessment(site["id"], ass["id"], MANAGER))
        validate_success(api.update_assessment(ass["id"], {"forklift_count": 6}, MANAGER))
        validate_success(api.submit_assessment(site["id"], ass["id"], MANAGER))
        approved = validate_success(api.approve_assessment(site["id"], ass["id"], SAFETY))
        assert approved["status"] == "APPROVED"
        assert approved["forklift_count"] == 6
        # 6 x 8.0 x 0.9 x 1.0 (peak 8 <= 8) = 43.2
        assert approved["daily_kg_estimate"] == pytest.approx(43.2)
