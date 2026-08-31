"""Payload factories — one per entity, client-supplied input fields only."""

from .constants import BASELINE


def group_payload(**overrides) -> dict:
    payload = {
        "name": BASELINE["GROUP_NAME"],
        "base_state_code": BASELINE["GROUP_BASE_STATE"],
        "everywhere_sales": BASELINE["EVERYWHERE_SALES"],
        "everywhere_property": BASELINE["EVERYWHERE_PROPERTY"],
        "everywhere_payroll": BASELINE["EVERYWHERE_PAYROLL"],
    }
    payload.update(overrides)
    return payload


def legal_entity_payload(**overrides) -> dict:
    payload = {
        "name": BASELINE["MEMBER_A_NAME"],
        "incorporation_state_code": "DE",
        "entity_type": "CORP",
        "is_unitary_member": True,
    }
    payload.update(overrides)
    return payload


def registration_payload(**overrides) -> dict:
    payload = {
        "state_code": BASELINE["STATE_CODE"],
        "factor_formula": "DOUBLE_WEIGHTED_SALES",
        "tax_rate": BASELINE["TAX_RATE"],
        "throwback_rule": "THROWBACK",
        "service_sourcing_rule": "MARKET_BASED",
    }
    payload.update(overrides)
    return payload


def activity_record_payload(legal_entity_id: str, **overrides) -> dict:
    payload = {
        "legal_entity_id": legal_entity_id,
        "tax_year": BASELINE["TAX_YEAR"],
    }
    payload.update(overrides)
    return payload


def election_payload(**overrides) -> dict:
    payload = {
        "election_basis": "COMBINED_UNITARY",
        "effective_tax_year": 2024,
        "binding_years": 3,
    }
    payload.update(overrides)
    return payload


def filing_payload(**overrides) -> dict:
    payload = {
        "tax_year": BASELINE["TAX_YEAR"],
        "filing_basis": "COMBINED_UNITARY",
        "federal_taxable_income": BASELINE["FEDERAL_TAXABLE_INCOME"],
    }
    payload.update(overrides)
    return payload


def modification_payload(**overrides) -> dict:
    payload = {
        "modification_code": "STATE_TAX_ADDBACK",
        "direction": "ADDITION",
        "raw_amount": 125042.00,
        "allocation_ratio": 0.008,
    }
    payload.update(overrides)
    return payload


def credit_claim_payload(expected_filing_version: int, **overrides) -> dict:
    payload = {
        "credit_code": "RD_CREDIT",
        "granted_amount": 30000.00,
        "priority_order": 1,
        "refundable": False,
        "expires_after_years": 5,
        "expected_filing_version": expected_filing_version,
    }
    payload.update(overrides)
    return payload


def payment_payload(expected_registration_version: int, **overrides) -> dict:
    payload = {
        "tax_year": BASELINE["TAX_YEAR"],
        "installment_number": 1,
        "amount": 8000.00,
        "paid_on_date": "2026-04-15T00:00:00Z",
        "expected_registration_version": expected_registration_version,
    }
    payload.update(overrides)
    return payload


def extension_payload(**overrides) -> dict:
    payload = {"estimated_tax_paid": BASELINE["REQUIRED_PREPAYMENT"]}
    payload.update(overrides)
    return payload


def notice_payload(**overrides) -> dict:
    payload = {
        "notice_type": "PROPOSED_ASSESSMENT",
        "state_notice_number": "CA-NOT-2027-77",
        "assessed_tax": 50000.00,
        "notice_date": "2027-05-01T00:00:00Z",
        "response_due_days": 45,
    }
    payload.update(overrides)
    return payload


def vda_agreement_payload(legal_entity_id: str, **overrides) -> dict:
    payload = {
        "legal_entity_id": legal_entity_id,
        "anchor_tax_year": 2024,
        "lookback_years": 3,
        "exposure_variant": "LOOKBACK_LIMITED",
        "estimated_exposure_tax": 210000.00,
    }
    payload.update(overrides)
    return payload


# The two reference activity rows of the multistate scenario used across the
# suite: one unprotected manufacturing member and one solicitation-protected
# services member.
def member_a_activity_payload(legal_entity_id: str, **overrides) -> dict:
    payload = {
        "legal_entity_id": legal_entity_id,
        "tax_year": BASELINE["TAX_YEAR"],
        "destination_sales": 1200000,
        "origin_sales": 300000,
        "purchaser_taxable_in_state": False,
        "property_average_value": 800000,
        "rented_property_annual_rent": 25000,
        "payroll_compensation": 500000,
        "employee_days_in_state": 40,
        "protected_solicitation_only": False,
    }
    payload.update(overrides)
    return payload


def member_b_activity_payload(legal_entity_id: str, **overrides) -> dict:
    payload = {
        "legal_entity_id": legal_entity_id,
        "tax_year": BASELINE["TAX_YEAR"],
        "destination_sales": 400000,
        "service_receipts": 250000,
        "cost_of_performance_state_code": "NV",
        "payroll_compensation": 100000,
        "employee_days_in_state": 5,
        "protected_solicitation_only": True,
    }
    payload.update(overrides)
    return payload


# The three reference modification lines whose per-line rounded sum is 676.57.
REFERENCE_MODIFICATIONS = [
    {"modification_code": "STATE_TAX_ADDBACK", "direction": "ADDITION",
     "raw_amount": 125042.00, "allocation_ratio": 0.008},
    {"modification_code": "MUNI_INTEREST_SUB", "direction": "SUBTRACTION",
     "raw_amount": 92379.00, "allocation_ratio": 0.008},
    {"modification_code": "DEPREC_ADJ", "direction": "ADDITION",
     "raw_amount": 51907.00, "allocation_ratio": 0.008},
]

# The two reference non-refundable credit claims.
REFERENCE_CREDITS = [
    {"credit_code": "RD_CREDIT", "granted_amount": 30000.00, "priority_order": 1,
     "refundable": False, "expires_after_years": 5},
    {"credit_code": "JOBS_CREDIT", "granted_amount": 40000.00, "priority_order": 2,
     "refundable": False, "expires_after_years": 3},
]
