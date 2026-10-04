"""Invoice take-or-pay credit: provisional (DRAFT read) vs final (ISSUED) variant.

PRD §3.6: the provisional preview excludes fueling events on the last in-period
day; the issued final variant includes all lines.
"""
import pytest

from test_helpers import (
    validate_success, get_success_data, api_client,
    create_fueling_event, create_invoice_with_lines, setup_billing_scenario,
    BILLING,
)


def _setup_invoice_with_last_day_line():
    """DELIVERED_LIQUID contract (base 2.00/kg, committed 100 kg); two 40 kg
    events, one mid-period (2026-10-15) and one on the last in-period day
    (2026-10-31; period_end 2026-11-01); DRAFT invoice with both as lines."""
    site, contract, station = setup_billing_scenario(
        site_code="S-DV1", supply_mode="DELIVERED_LIQUID",
        base_price_per_kg=2.0, committed_monthly_kg=100)
    fe_mid = create_fueling_event(
        station["id"], contract["id"], forklift_id="FL-1",
        occurred_at="2026-10-15T10:00:00Z", kg_dispensed=40)
    fe_last = create_fueling_event(
        station["id"], contract["id"], forklift_id="FL-2",
        occurred_at="2026-10-31T10:00:00Z", kg_dispensed=40)
    invoice, _lines = create_invoice_with_lines(
        site["id"], contract["id"], [fe_mid["id"], fe_last["id"]],
        period_start="2026-10-01", period_end="2026-11-01")
    return invoice


def test_provisional_credit_excludes_last_in_period_day(api):
    """PRD §3.6: "the shortfall is the contract's `committed_monthly_kg` minus
    the invoice's `total_kg`, floored at zero, except that lines whose fueling
    event occurred on the calendar day immediately preceding `period_end` —
    the last in-period day — are excluded from both `total_kg` and
    `subtotal_cents` for this preview, so the provisional figure shows a larger
    shortfall (and larger credit) whenever last-day lines exist."

    Design: Difficulty/dual_variant_calc/invoice_take_or_pay_provisional_excludes_last_day
    """
    invoice = _setup_invoice_with_last_day_line()
    resp = api.get_invoice(invoice["id"], BILLING)
    data = validate_success(resp)
    # Provisional basis excludes the 40 kg last-day line: shortfall 60 kg
    # x 2.00 USD/kg x 0.25 = 30.00 USD = 3000 cents.
    assert data["credit_cents"] == 3000, (
        f"provisional credit must price the 60 kg shortfall, got {data['credit_cents']}")
    assert data["subtotal_cents"] == 17280, "subtotal is the sum of rounded line amounts"
    assert data["total_kg"] == 80
    # The preview excludes the last-day line from the subtotal feeding the
    # total: provisional subtotal 8640 - credit 3000 = 5640 cents.
    assert data["total_cents"] == 5640, (
        f"provisional total = provisional subtotal 8640 - credit 3000, "
        f"got {data['total_cents']}")


def test_issue_freezes_final_credit_including_last_day(api):
    """PRD §3.6: "Issuing the invoice freezes the **final** variant: all lines
    count (no last-day exclusion), and on top of the final take-or-pay credit
    the system adds the availability component — the `credit_cents` from the
    site's monthly availability calculation for the calendar month containing
    `period_start`, added only when a service agreement exists for the site —
    then caps the combined credit at the invoice's `subtotal_cents` and
    recomputes `total_cents` as the subtotal minus the combined credit, floored
    at zero. From issuance on, `credit_cents` and `total_cents` are frozen on
    the invoice."

    Design: Difficulty/dual_variant_calc/invoice_take_or_pay_provisional_excludes_last_day
    """
    invoice = _setup_invoice_with_last_day_line()
    provisional_credit = invoice["credit_cents"]
    resp = api.issue_invoice(invoice["id"], BILLING)
    data = validate_success(resp)
    assert data["status"] == "ISSUED"
    # Final basis: total_kg 80, shortfall 20 kg x 2.00 x 0.25 = 5.00 USD;
    # no service agreement exists, so the availability component is absent.
    assert data["credit_cents"] == 1000, (
        f"final credit must include the last-day line, got {data['credit_cents']}")
    assert data["total_cents"] == 16280, "final total = 17280 - 1000"
    assert provisional_credit != data["credit_cents"], (
        "provisional and final variants must diverge when last-day lines exist")
    # Frozen: a later read returns the same finalized figures.
    reread = validate_success(api.get_invoice(invoice["id"], BILLING))
    assert reread["credit_cents"] == 1000 and reread["total_cents"] == 16280
