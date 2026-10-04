"""Corner coverage — error catalogue spot check: ERR_INVALID_REQUEST on a
required-field omission (PRD §2.10, §3.6, §5).
"""
from test_helpers import (
    validate_error, get_success_data, ApiErrorId,
    create_site, create_supply_contract_payload,
    MANAGER, BILLING,
)


def test_invoice_missing_period_end_rejected(api):
    """PRD §2.10: "Sixth, request shape: required fields present, well-typed,
    enum values within their declared sets, date and datetime formats valid
    (`ERR_INVALID_REQUEST`, HTTP 400)."
    PRD §3.6: "A `BillingOperator` creates one in `DRAFT` for a site and
    contract, delimited by `period_start` (inclusive) and `period_end`
    (exclusive, strictly after the start)."

    Design: Corner/errors/error_invalid_request_covered
    """
    site = create_site(code="S-ER1")
    contract = get_success_data(api.create_supply_contract(
        site["id"], create_supply_contract_payload(
            supply_mode="PIPELINE", base_price_per_kg=2.5,
            reliability_sla_pct=99.0, committed_monthly_kg=10), MANAGER))
    resp = api.create_invoice(
        {"site_id": site["id"], "supply_contract_id": contract["id"],
         "period_start": "2026-10-01"}, BILLING)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
