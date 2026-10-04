"""Compensating invariants: dispute/resolve preserves frozen invoice totals
(PRD §3.6); unstart fully restores pre-start event state and a later
start+complete yields exactly one COMPLETED event (PRD §3.4).
"""
import pytest

from test_helpers import (
    validate_success, validate_paginated,
    create_site, create_technician, create_approved_assessment,
    create_scheduled_plan, create_event, start_event, complete_event,
    create_fueling_event, create_invoice_with_lines, setup_billing_scenario,
    tech_headers, MANAGER, BILLING,
)


def _setup_issued_invoice(api):
    """Two 40 kg mid-period lines under DELIVERED_LIQUID (base 2.00, committed
    100): issued with subtotal 17280, credit 1000, total 16280."""
    site, contract, station = setup_billing_scenario(
        site_code="S-INV1", supply_mode="DELIVERED_LIQUID",
        base_price_per_kg=2.0, committed_monthly_kg=100)
    fe1 = create_fueling_event(
        station["id"], contract["id"], forklift_id="FL-V1",
        occurred_at="2026-10-15T10:00:00Z", kg_dispensed=40)
    fe2 = create_fueling_event(
        station["id"], contract["id"], forklift_id="FL-V2",
        occurred_at="2026-10-16T10:00:00Z", kg_dispensed=40)
    invoice, _lines = create_invoice_with_lines(
        site["id"], contract["id"], [fe1["id"], fe2["id"]])
    return site, validate_success(api.issue_invoice(invoice["id"], BILLING))


class TestDisputeResolvePreservesTotals:
    def test_frozen_totals_at_issue(self, api):
        """PRD §3.6: "From issuance on, `credit_cents` and `total_cents` are
        frozen on the invoice."

        Design: Difficulty/compensating_invariant/dispute_resolve_preserves_invoice_totals
        """
        _site, invoice = _setup_issued_invoice(api)
        assert invoice["status"] == "ISSUED"
        # Final credit: shortfall 20 kg x 2.00 x 0.25 = 1,000 cents.
        assert invoice["subtotal_cents"] == 17280
        assert invoice["credit_cents"] == 1000
        assert invoice["total_cents"] == 16280

    def test_dispute_resolve_round_trip_keeps_totals_identical(self, api):
        """PRD §3.6: "From issuance on, `credit_cents` and `total_cents` are
        frozen on the invoice."
        PRD §3.6: "an `ISSUED` invoice may be paid (moving to `PAID`, terminal)
        by a `BillingOperator`, or disputed by the customer-side `SiteManager`,
        moving it to `DISPUTED`; a `BillingOperator` resolves a dispute,
        returning `DISPUTED` to `ISSUED`."

        Design: Difficulty/compensating_invariant/dispute_resolve_preserves_invoice_totals
        """
        _site, invoice = _setup_issued_invoice(api)
        validate_success(api.dispute_invoice(invoice["id"], MANAGER))
        resolved = validate_success(api.resolve_invoice(invoice["id"], BILLING))
        assert resolved["status"] == "ISSUED"
        assert resolved["subtotal_cents"] == 17280
        assert resolved["credit_cents"] == 1000
        assert resolved["total_cents"] == 16280


def _setup_plan_with_one_event(api):
    site = create_site(code="S-INV2")
    tech = create_technician(name="Tech Inv", certification_level="ADVANCED")
    create_approved_assessment(
        site["id"], forklift_count=3, duty_cycle_hours_per_day=8.0,
        peak_shift_hours=8)
    plan = create_scheduled_plan(
        site["id"], name="Wave Inv", target_forklift_count=1,
        transition_mode="CUTOVER", start_date="2026-10-01",
        end_date="2026-10-15", baseline_productivity_units_per_hour=50.0,
        expected_productivity_gain_pct=10)
    ev = create_event(plan["id"], tech["id"], forklift_id="FL-IV",
                      scheduled_start="2026-10-05T08:00:00Z",
                      scheduled_end="2026-10-05T12:00:00Z")
    return plan, tech, ev


class TestEventUnstartPreservesProgress:
    def test_unstart_restores_scheduled_state_without_completion_stamp(self, api):
        """PRD §3.4: "If the technician becomes unavailable, an `IN_PROGRESS`
        event can be unstarted back to `SCHEDULED`."
        PRD §3.4: "Completing an event moves `IN_PROGRESS` to `COMPLETED` and
        stamps `completed_at`"

        Design: Difficulty/compensating_invariant/event_unstart_preserves_plan_progress
        """
        plan, tech, ev = _setup_plan_with_one_event(api)
        started = start_event(plan["id"], ev["id"], tech["id"])
        assert started["status"] == "IN_PROGRESS"
        unstarted = validate_success(
            api.unstart_event(plan["id"], ev["id"], tech_headers(tech["id"])))
        assert unstarted["status"] == "SCHEDULED"
        assert unstarted["completed_at"] is None, (
            "no completion ever happened, so no completed_at stamp may exist")

    def test_restart_and_complete_counts_exactly_one_completed_event(self, api):
        """PRD §3.4: "Completing an event moves `IN_PROGRESS` to `COMPLETED`
        and stamps `completed_at`; when that completion leaves every sibling
        event in a terminal status (`COMPLETED` or `CANCELLED`) with at least
        one sibling — itself possibly this one — `COMPLETED`, the parent plan
        bubbles up to `COMPLETED`."

        Design: Difficulty/compensating_invariant/event_unstart_preserves_plan_progress
        """
        plan, tech, ev = _setup_plan_with_one_event(api)
        start_event(plan["id"], ev["id"], tech["id"])
        validate_success(api.unstart_event(plan["id"], ev["id"], tech_headers(tech["id"])))
        start_event(plan["id"], ev["id"], tech["id"])
        completed = complete_event(plan["id"], ev["id"], tech["id"])
        assert completed["status"] == "COMPLETED"
        assert completed["completed_at"] is not None
        events, meta = validate_paginated(
            api.list_plan_events(plan["id"], MANAGER))
        completed_events = [e for e in events if e["status"] == "COMPLETED"]
        assert len(completed_events) == 1, (
            "the unstart attempt must not double-count conversion progress")
        plan_after = validate_success(api.get_conversion_plan(plan["id"], MANAGER))
        assert plan_after["status"] == "COMPLETED"
