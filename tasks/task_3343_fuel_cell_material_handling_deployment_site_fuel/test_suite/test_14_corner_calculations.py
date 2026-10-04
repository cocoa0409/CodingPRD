"""Corner coverage — pricing, credit, and availability calculations
(PRD §2.8, §3.5, §3.6).
"""
import pytest

from test_helpers import (
    validate_success, create_site, create_approved_assessment,
    create_active_agreement, create_active_contract, report_downtime,
    create_commissioned_station, create_fueling_event,
    create_invoice_with_lines, setup_billing_scenario,
    MANAGER, BILLING,
)


def test_tier_discount_applies_to_full_line_past_boundary(api):
    """PRD §3.6: "If the prior billed quantity alone already reaches or exceeds
    the boundary, the whole line prices at the base price multiplied by the
    0.92 second-tier discount."
    PRD §3.6: "If this line straddles the boundary, the under-boundary portion
    prices at base and the over-boundary portion at the discounted base, and
    the line's unit price is the quantity-weighted blend of the two."

    Design: Corner/calculations/tier_discount_applies_to_full_line_past_boundary
    """
    site, contract, station = setup_billing_scenario(
        site_code="S-CL1", supply_mode="PIPELINE",
        base_price_per_kg=2.5, committed_monthly_kg=100)
    fe120 = create_fueling_event(
        station["id"], contract["id"], forklift_id="FL-C1",
        occurred_at="2026-10-05T08:00:00Z", kg_dispensed=120)
    fe10 = create_fueling_event(
        station["id"], contract["id"], forklift_id="FL-C2",
        occurred_at="2026-10-06T08:00:00Z", kg_dispensed=10)
    invoice, lines = create_invoice_with_lines(
        site["id"], contract["id"], [fe120["id"], fe10["id"]])
    line1, line2 = lines
    # Line 1 straddles: (100 x 2.50 + 20 x 2.30)/120 = 2.4667 -> 29600 cents.
    assert line1["unit_price_per_kg"] == pytest.approx(2.4667)
    assert line1["line_amount_cents"] == 29600
    # Line 2: prior 120 >= 100, so the whole line is at 2.50 x 0.92 = 2.30.
    assert line2["unit_price_per_kg"] == pytest.approx(2.30)
    assert line2["line_amount_cents"] == 2300
    assert invoice["subtotal_cents"] == 31900


def test_take_or_pay_no_shortfall_zero_credit(api):
    """PRD §3.6: "the shortfall is the contract's `committed_monthly_kg` minus
    the invoice's `total_kg`, floored at zero"
    PRD §3.6: "then caps the combined credit at the invoice's `subtotal_cents`
    and recomputes `total_cents` as the subtotal minus the combined credit,
    floored at zero."

    Design: Corner/calculations/take_or_pay_no_shortfall_zero_credit
    """
    site, contract, station = setup_billing_scenario(
        site_code="S-CL2", supply_mode="PIPELINE",
        base_price_per_kg=2.5, committed_monthly_kg=100)
    fe = create_fueling_event(
        station["id"], contract["id"], forklift_id="FL-C3",
        occurred_at="2026-10-05T08:00:00Z", kg_dispensed=150)
    invoice, lines = create_invoice_with_lines(
        site["id"], contract["id"], [fe["id"]])
    # 150 kg straddles: (100 x 2.50 + 50 x 2.30)/150 = 2.4333 ->
    # ROUND_HALF_UP(150 x 2.4333 x 100) = ROUND_HALF_UP(36499.5) = 36500.
    assert lines[0]["line_amount_cents"] == 36500
    issued = validate_success(api.issue_invoice(invoice["id"], BILLING))
    # Billed 150 kg against a 100 kg commitment: shortfall floors at zero.
    assert issued["credit_cents"] == 0
    assert issued["total_cents"] == issued["subtotal_cents"] == 36500


def test_availability_no_agreement_zero_credit(api):
    """PRD §3.5: "The governing agreement is the site's latest-created `ACTIVE`
    service agreement whose `coverage_start` falls on or before the last day of
    the month and whose `coverage_end` falls on or after the first day of the
    month; if none exists, `guarantee_pct` is null and the credit is zero."

    Design: Corner/calculations/availability_no_agreement_zero_credit
    """
    site = create_site(code="S-CL3")
    create_approved_assessment(
        site["id"], forklift_count=1, duty_cycle_hours_per_day=8.0,
        peak_shift_hours=8)
    report_downtime(site["id"], month="2026-10", forklift_id="FL-D1",
                    downtime_hours=200)
    report = validate_success(api.get_availability_report(site["id"], "2026-10", BILLING))
    # 100 x (1 - 200/730) = 72.6027... -> 72.6
    assert report["availability_pct"] == pytest.approx(72.6)
    assert report["credit_cents"] == 0
    assert report["guarantee_pct"] is None


def test_invoice_availability_component_added_at_issue(api):
    """PRD §3.6: "Issuing the invoice freezes the **final** variant: all lines
    count (no last-day exclusion), and on top of the final take-or-pay credit
    the system adds the availability component — the `credit_cents` from the
    site's monthly availability calculation for the calendar month containing
    `period_start`, added only when a service agreement exists for the site —
    then caps the combined credit at the invoice's `subtotal_cents` and
    recomputes `total_cents` as the subtotal minus the combined credit, floored
    at zero."

    Design: Corner/calculations/invoice_availability_component_added_at_issue
    """
    site = create_site(code="S-CL4")
    create_approved_assessment(
        site["id"], forklift_count=1, duty_cycle_hours_per_day=8.0,
        peak_shift_hours=8)
    create_active_agreement(
        site["id"], coverage_start="2026-10-01", coverage_end="2027-09-30",
        availability_guarantee_pct=90.0, monthly_fee_cents=2000000)
    # 146 / 730 -> availability 80.00 < 90.0 -> availability credit 200,000.
    report_downtime(site["id"], month="2026-10", forklift_id="FL-D2",
                    downtime_hours=146)
    contract = create_active_contract(
        site["id"], supply_mode="PIPELINE", base_price_per_kg=2.5,
        reliability_sla_pct=99.0, committed_monthly_kg=10)
    station = create_commissioned_station(site["id"], station_code="ST-C4")
    fe = create_fueling_event(
        station["id"], contract["id"], forklift_id="FL-C4",
        occurred_at="2026-10-05T08:00:00Z", kg_dispensed=20)
    invoice, lines = create_invoice_with_lines(
        site["id"], contract["id"], [fe["id"]])
    # 20 kg straddles the 10 kg boundary: (10 x 2.50 + 10 x 2.30)/20 = 2.40
    # -> line 4,800 cents; no take-or-pay shortfall (20 billed >= 10 committed).
    assert lines[0]["line_amount_cents"] == 4800
    assert invoice["credit_cents"] == 0, (
        "the provisional variant carries take-or-pay only, which is zero here")
    issued = validate_success(api.issue_invoice(invoice["id"], BILLING))
    # Final credit = 0 take-or-pay + 200,000 availability, capped at subtotal.
    assert issued["credit_cents"] == 4800
    assert issued["total_cents"] == 0
