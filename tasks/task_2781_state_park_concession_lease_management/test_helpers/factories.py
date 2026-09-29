"""Request payload builders. Every builder accepts **overrides.

Monetary fields are emitted as Python ints (integer counts of cents, PRD §2.6)
and percentage fields as JSON numbers carrying at most two decimals.
"""
from typing import Any, Dict

from . import constants as C

_SEQ = {"n": 0}


def _next() -> int:
    _SEQ["n"] += 1
    return _SEQ["n"]


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    payload.update(overrides)
    return payload


# ─── clock ─────────────────────────────────────────────────────────────────

def clock_payload(current_utc: str = C.DEFAULT_CLOCK, **overrides: Any) -> Dict[str, Any]:
    return _merge({"current_utc": current_utc}, overrides)


# ─── park ──────────────────────────────────────────────────────────────────

def park_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "name": f"Cedar Hollow State Park {_next()}",
            "region_code": "NW",
            "annual_visitation": 480000,
            "comparable_lodging_rate_cents": 20000,
            "comparable_meal_rate_cents": 3000,
            "comparable_activity_rate_cents": 9000,
        },
        overrides,
    )


# ─── offeror ───────────────────────────────────────────────────────────────

def offeror_payload(**overrides: Any) -> Dict[str, Any]:
    n = _next()
    return _merge(
        {
            "legal_name": f"Cedar Hollow Hospitality LLC {n}",
            "contact_email": f"bids{n}@cedarhollow.example",
            "bond_capacity_cents": 50000000,
        },
        overrides,
    )


# ─── concession opportunity ────────────────────────────────────────────────

def opportunity_payload(park_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "park_id": park_id,
            "title": f"Cedar Hollow Lodge Concession {_next()}",
            "service_category": "LODGING",
            "required_capital_investment_cents": 30000000,
        },
        overrides,
    )


def market_analysis_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "comparable_gross_receipts_cents": 200000000,
            "market_capture_pct": 80.00,
            "analyst_note": "Regional lodging comparables reviewed.",
        },
        overrides,
    )


# ─── prospectus ────────────────────────────────────────────────────────────

def prospectus_payload(opportunity_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "opportunity_id": opportunity_id,
            "minimum_franchise_fee_pct": 4.00,
            "minimum_annual_guarantee_cents": 6000000,
            "term_years": 10,
            "submission_deadline": "2027-02-01T00:00:00Z",
            "weight_experience": 20,
            "weight_operating_plan": 25,
            "weight_capital_investment": 20,
            "weight_financial_capacity": 15,
            "weight_fee_offer": 20,
            "scoring_mode": "PER_CRITERION_ROUNDING",
            "min_technical_score": 70.00,
        },
        overrides,
    )


def award_payload(term_start: str = "2027-03-01", **overrides: Any) -> Dict[str, Any]:
    return _merge({"term_start": term_start}, overrides)


# ─── proposal ──────────────────────────────────────────────────────────────

def proposal_payload(prospectus_id: str, offeror_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "prospectus_id": prospectus_id,
            "offeror_id": offeror_id,
            "offered_franchise_fee_pct": 5.00,
            "proposed_capital_investment_cents": 30000000,
            "proposed_annual_guarantee_cents": 6000000,
            "experience_years": 12,
            "financial_capacity_ratio": 1.80,
        },
        overrides,
    )


def resubmit_proposal_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "offered_franchise_fee_pct": 5.50,
            "proposed_capital_investment_cents": 32000000,
            "proposed_annual_guarantee_cents": 6500000,
        },
        overrides,
    )


def evaluation_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "score_experience": 81,
            "score_operating_plan": 86,
            "score_capital_investment": 91,
            "score_financial_capacity": 76,
            "score_fee_offer": 71,
        },
        overrides,
    )


# ─── lease ─────────────────────────────────────────────────────────────────

def execute_lease_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "insurance_expires_on": "2028-06-30",
            "carrier_name": "Northline Mutual",
            "agency_maintenance_scope": "STRUCTURAL_ONLY",
        },
        overrides,
    )


def insurance_certificate_payload(
    insurance_expires_on: str = "2029-06-30", **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"insurance_expires_on": insurance_expires_on, "carrier_name": "Northline Mutual"},
        overrides,
    )


def close_out_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({}, overrides)


# ─── performance bond ──────────────────────────────────────────────────────

def post_bond_payload(penal_sum_cents: int = 3000000, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"penal_sum_cents": penal_sum_cents, "surety_name": "Granite Surety Co."},
        overrides,
    )


def reinstate_bond_payload(reinstatement_amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    return _merge({"reinstatement_amount_cents": reinstatement_amount_cents}, overrides)


# ─── capital improvement ───────────────────────────────────────────────────

def improvement_payload(lease_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "lease_id": lease_id,
            "description": f"Cabin roof replacement {_next()}",
            "funding_source": "CONCESSIONAIRE_CAPITAL",
            "proposed_cost_cents": 8000000,
            "useful_life_years": 20,
            "construction_window_start": "2027-04-01",
            "construction_window_end": "2027-06-01",
            "ownership_at_expiration": "AGENCY",
        },
        overrides,
    )


def approve_improvement_payload(approved_cost_cents: int = 8000000, **overrides: Any):
    return _merge({"approved_cost_cents": approved_cost_cents}, overrides)


def return_improvement_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"deficiency_note": "Scope and cost basis incomplete."}, overrides)


def resubmit_improvement_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "proposed_cost_cents": 8000000,
            "useful_life_years": 20,
            "construction_window_start": "2027-04-01",
            "construction_window_end": "2027-06-01",
        },
        overrides,
    )


def place_in_service_payload(
    actual_cost_cents: int = 8000000, in_service_date: str = "2027-06-01", **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"actual_cost_cents": actual_cost_cents, "in_service_date": in_service_date},
        overrides,
    )


# ─── operating plan ────────────────────────────────────────────────────────

def operating_plan_payload(
    lease_id: str, expected_lease_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "lease_id": lease_id,
            "expected_lease_version": expected_lease_version,
            "season_start": "2027-03-01",
            "season_end": "2027-12-31",
            "service_level": "FULL",
            "max_lodging_rate_cents": 22000,
            "max_meal_rate_cents": 3400,
            "max_activity_rate_cents": 10000,
        },
        overrides,
    )


def return_plan_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"deficiency_note": "Rate schedule requires narrative support."}, overrides)


def resubmit_plan_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "season_start": "2027-03-01",
            "season_end": "2027-12-31",
            "service_level": "FULL",
            "max_lodging_rate_cents": 22000,
            "max_meal_rate_cents": 3400,
            "max_activity_rate_cents": 10000,
        },
        overrides,
    )


# ─── gross receipts report ─────────────────────────────────────────────────

def report_payload(
    lease_id: str,
    period_start: str = "2027-04-01",
    period_end: str = "2027-07-01",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "lease_id": lease_id,
            "period_start": period_start,
            "period_end": period_end,
            "lodging_receipts_cents": 12000000,
            "food_beverage_receipts_cents": 3000000,
            "retail_receipts_cents": 2000000,
            "activity_receipts_cents": 1000000,
        },
        overrides,
    )


def accept_report_payload(remittance_received_cents: int, **overrides: Any) -> Dict[str, Any]:
    return _merge({"remittance_received_cents": remittance_received_cents}, overrides)


def reject_report_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"rejection_note": "Category receipts do not tie to the ledger."}, overrides)


def amend_report_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "lodging_receipts_cents": 12500000,
            "food_beverage_receipts_cents": 3000000,
            "retail_receipts_cents": 2000000,
            "activity_receipts_cents": 1000000,
        },
        overrides,
    )


# ─── fee reconciliation ────────────────────────────────────────────────────

def reconciliation_payload(
    lease_id: str,
    expected_lease_version: int,
    lease_year_start: str = "2027-03-01",
    lease_year_end: str = "2028-02-29",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "lease_id": lease_id,
            "expected_lease_version": expected_lease_version,
            "lease_year_start": lease_year_start,
            "lease_year_end": lease_year_end,
        },
        overrides,
    )


def settle_payload(payment_amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    return _merge({"payment_amount_cents": payment_amount_cents}, overrides)


# ─── audit engagement ──────────────────────────────────────────────────────

def audit_payload(
    lease_id: str,
    audit_period_start: str = "2027-04-01",
    audit_period_end: str = "2027-07-01",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "lease_id": lease_id,
            "audit_period_start": audit_period_start,
            "audit_period_end": audit_period_end,
            "scope_note": "Point-of-sale receipts reconciliation.",
        },
        overrides,
    )


def issue_findings_payload(adjusted_gross_receipts_cents: int, **overrides: Any):
    return _merge(
        {
            "adjusted_gross_receipts_cents": adjusted_gross_receipts_cents,
            "finding_note": "Unrecorded lodging folios identified.",
        },
        overrides,
    )


def contest_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"contest_basis": "Folio sample was not representative."}, overrides)


def withdraw_findings_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"withdrawal_basis": "Source ledger reconciled on review."}, overrides)


# ─── compliance action ─────────────────────────────────────────────────────

def compliance_action_payload(
    lease_id: str,
    action_type: str = "OPERATING_STANDARD",
    cure_deadline: str = "2027-12-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "lease_id": lease_id,
            "action_type": action_type,
            "deficiency_note": "Housekeeping standard not met on inspection.",
            "cure_deadline": cure_deadline,
        },
        overrides,
    )


def accept_cure_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"cure_note": "Corrective action verified on re-inspection."}, overrides)


def order_bond_draw_payload(draw_amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    return _merge({"draw_amount_cents": draw_amount_cents}, overrides)
