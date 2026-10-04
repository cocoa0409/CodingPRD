"""Corner coverage — optimistic concurrency guards (PRD §2.9) and invoice
derived-field reconciliation across line add and void (PRD §3.6).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    create_site, create_approved_assessment, create_conversion_plan_payload,
    create_fueling_event, create_draft_invoice, create_invoice_with_lines,
    setup_billing_scenario, add_line,
    MANAGER, SAFETY, BILLING,
)


def test_occ_stale_invoice_line_add(api):
    """PRD §2.9: "Adding a line item to an invoice requires the request to
    carry `expected_invoice_version` holding the invoice `version` the client
    last observed. If the invoice's current `version` has advanced — for
    example because another writer issued or voided the invoice and froze its
    totals — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_invoice_line_add
    """
    site, contract, station = setup_billing_scenario(
        site_code="S-OC1", supply_mode="PIPELINE",
        base_price_per_kg=2.5, committed_monthly_kg=10)
    fe1 = create_fueling_event(
        station["id"], contract["id"], forklift_id="FL-OA",
        occurred_at="2026-10-05T08:00:00Z", kg_dispensed=5)
    fe2 = create_fueling_event(
        station["id"], contract["id"], forklift_id="FL-OB",
        occurred_at="2026-10-06T08:00:00Z", kg_dispensed=5)
    fe3 = create_fueling_event(
        station["id"], contract["id"], forklift_id="FL-OC",
        occurred_at="2026-10-07T08:00:00Z", kg_dispensed=5)
    invoice, _lines = create_invoice_with_lines(
        site["id"], contract["id"], [fe1["id"]])
    observed_version = invoice["version"]
    # Another writer adds a line first; per PRD §3.6 each line add bumps the
    # invoice version while the invoice stays DRAFT, so every earlier
    # validation stage still passes and the client's captured version is now
    # stale when the OCC check runs.
    add_line(invoice["id"], fe2["id"], observed_version)
    resp = api.add_line_item(
        invoice["id"], {"fueling_event_id": fe3["id"],
                        "expected_invoice_version": observed_version}, BILLING)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_occ_stale_plan_schedule(api):
    """PRD §2.9: "Scheduling a conversion plan requires the request to carry
    `expected_plan_version` holding the plan `version` the client last
    observed. If the plan's current `version` differs — for example because
    another writer already scheduled it or reverted it to draft — the request
    is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_plan_schedule
    """
    site = create_site(code="S-OC2")
    create_approved_assessment(
        site["id"], forklift_count=2, duty_cycle_hours_per_day=4.0,
        peak_shift_hours=6)
    plan = get_success_data(api.create_conversion_plan(
        site["id"], create_conversion_plan_payload(
            name="Wave OCC", baseline_productivity_units_per_hour=40.0,
            expected_productivity_gain_pct=5), MANAGER))
    v0 = plan["version"]
    validate_success(api.schedule_plan(
        site["id"], plan["id"], {"expected_plan_version": v0}, MANAGER))
    validate_success(api.revert_plan(site["id"], plan["id"], MANAGER))
    # Schedule and revert each advanced the plan version past v0.
    resp = api.schedule_plan(
        site["id"], plan["id"], {"expected_plan_version": v0}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_derived_field_recompute_on_line_add_and_void(api):
    """PRD §3.6: "Adding the line then recomputes the invoice: `total_kg` is
    the sum of line `kg`, `subtotal_cents` is the sum of the already-rounded
    line amounts, and the credit and total refresh (below), all bumping the
    invoice's `version`."
    PRD §3.6: "a `DRAFT` invoice may instead be voided, moving it to `VOID`
    and releasing its line items from the prior-billed-kg accumulation of
    future lines"

    Design: Corner/cross_cutting_layers/derived_field_recompute_on_line_add_and_void
    """
    site, contract, station = setup_billing_scenario(
        site_code="S-DF1", supply_mode="PIPELINE",
        base_price_per_kg=2.5, committed_monthly_kg=10)
    fe = create_fueling_event(
        station["id"], contract["id"], forklift_id="FL-DA",
        occurred_at="2026-10-05T08:00:00Z", kg_dispensed=5)
    inv_a, lines_a = create_invoice_with_lines(
        site["id"], contract["id"], [fe["id"]])
    assert inv_a["total_kg"] == pytest.approx(5)
    assert inv_a["subtotal_cents"] == 1250  # 5 kg x 2.50 x 100
    validate_success(api.void_invoice(inv_a["id"], BILLING))
    # The VOID invoice's line is released: the same event bills again on a
    # fresh invoice at the base price (prior billed kg excludes VOID lines).
    inv_b = create_draft_invoice(site["id"], contract["id"])
    line_b = add_line(inv_b["id"], fe["id"], inv_b["version"])
    assert line_b["unit_price_per_kg"] == pytest.approx(2.5)
    assert line_b["line_amount_cents"] == 1250
