"""Distinct validation categories on the invoice endpoints (PRD §3.6, §2.10):
billability rejections fire on line-item adds while the OCC version matches.

Note: the sibling assertion of this design instance — issuing a zero-line
invoice under a TERMINATED contract returning ERR_CONTRACT_NOT_ACTIVE — is not
uniquely derivable from the PRD (no error id is named for the
"at least one line item" issuance requirement, so its precedence against the
contract-active check is undecidable from PRD text alone) and is not emitted.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    create_fueling_event, create_invoice_with_lines, create_draft_invoice,
    setup_billing_scenario, MANAGER, BILLING,
)


def _setup_paid_invoice_and_fresh_draft(api):
    """Contract c1 (PIPELINE, base 2.50, committed 10): fe_in billed on inv1
    (issued then paid); inv2 voided; c1 terminated; inv3 a fresh DRAFT for the
    same period. Returns (site, c1, fe_in, fe_out, inv3)."""
    site, contract, station = setup_billing_scenario(
        site_code="S-PP2", supply_mode="PIPELINE",
        base_price_per_kg=2.5, committed_monthly_kg=10,
        station_overrides={"station_code": "ST-P2",
                           "construction_start": "2026-10-01",
                           "construction_end": "2026-11-01"})
    fe_in = create_fueling_event(
        station["id"], contract["id"], forklift_id="FL-X",
        occurred_at="2026-10-10T08:00:00Z", kg_dispensed=20)
    fe_out = create_fueling_event(
        station["id"], contract["id"], forklift_id="FL-Y",
        occurred_at="2026-12-15T08:00:00Z", kg_dispensed=5)
    inv1, _lines = create_invoice_with_lines(
        site["id"], contract["id"], [fe_in["id"]])
    validate_success(api.issue_invoice(inv1["id"], BILLING))
    validate_success(api.pay_invoice(inv1["id"], BILLING))
    inv2 = create_draft_invoice(site["id"], contract["id"])
    validate_success(api.void_invoice(inv2["id"], BILLING))
    validate_success(api.terminate_supply_contract(site["id"], contract["id"], MANAGER))
    inv3 = create_draft_invoice(site["id"], contract["id"])
    return site, contract, fe_in, fe_out, inv3


def test_out_of_period_event_rejected_despite_matching_occ_version(api):
    """PRD §3.6: "the event must fall within the invoice's `[period_start,
    period_end)` window, be billed under the same `supply_contract_id` as the
    invoice, and not already appear on another line item of any non-`VOID`
    invoice — otherwise `ERR_EVENT_NOT_BILLABLE` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/fiscal_error_beats_referential_error_on_schedule
    """
    _site, _c, _fe_in, fe_out, inv3 = _setup_paid_invoice_and_fresh_draft(api)
    resp = api.add_line_item(
        inv3["id"], {"fueling_event_id": fe_out["id"],
                     "expected_invoice_version": inv3["version"]}, BILLING)
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_BILLABLE)
    after = get_success_data(api.get_invoice(inv3["id"], BILLING))
    assert after["status"] == "DRAFT", "a rejected line add leaves the invoice untouched"
    assert after["total_kg"] == 0


def test_event_billed_on_paid_invoice_rejected_on_second_invoice(api):
    """PRD §3.6: "the event must fall within the invoice's `[period_start,
    period_end)` window, be billed under the same `supply_contract_id` as the
    invoice, and not already appear on another line item of any non-`VOID`
    invoice — otherwise `ERR_EVENT_NOT_BILLABLE` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/fiscal_error_beats_referential_error_on_schedule
    """
    _site, _c, fe_in, _fe_out, inv3 = _setup_paid_invoice_and_fresh_draft(api)
    resp = api.add_line_item(
        inv3["id"], {"fueling_event_id": fe_in["id"],
                     "expected_invoice_version": inv3["version"]}, BILLING)
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_BILLABLE)
    after = get_success_data(api.get_invoice(inv3["id"], BILLING))
    assert after["status"] == "DRAFT"
