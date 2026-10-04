"""Payload factories — one per creatable resource, input fields only.

Computed and system fields are never included. Emails and full names are
minted with a per-process counter so a test can register several applicants
without tripping the email-uniqueness rule. All default dates are pinned to
the canonical logical-clock timeline (clock default 2026-09-01T00:00:00Z;
canonical declaration DR-4821 declared 2026-10-01T00:00:00Z).
"""
import itertools

from .constants import (
    CANONICAL_COUNTY_BOTH,
    CANONICAL_COUNTY_EIDL_ONLY,
    CANONICAL_DECLARED_DATE,
)

_nonce = itertools.count(1)


def _next(tag: str) -> str:
    return f"{tag}-{next(_nonce)}"


DEFAULTS = {
    "DECLARATION_NUMBER": "DR-4821",
    "DISASTER_TYPE": "HURRICANE",
    "INCIDENT_START_DATE": CANONICAL_DECLARED_DATE,
    "INCIDENT_END_DATE": "2026-10-15T00:00:00Z",
    "COUNTY_FIPS": CANONICAL_COUNTY_BOTH,
    "LOAN_PURPOSE": "PHYSICAL_DAMAGE",
    "REQUESTED_AMOUNT_CENTS": 20000000,
    "APPLICANT_TYPE": "HOMEOWNER",
    "ANNUAL_INCOME_CENTS": 12000000,
    "MONTHLY_DEBT_CENTS": 100000,
    "CREDIT_SCORE": 700,
    "ASSESSED_LOSS_CENTS": 25000000,
    "INSURANCE_PROCEEDS_CENTS": 5000000,
    "COLLATERAL_DESCRIPTION": "primary residence",
    "GRANT_PROGRAM_NAME": "FEMA-OTG",
    "MILESTONE_DESCRIPTION": "roof replaced",
    "MODIFICATION_REASON": "contractor cost overrun",
    "SETTLEMENT_RECEIVED_DATE": "2026-12-15T00:00:00Z",
}


def create_declaration_payload(**overrides) -> dict:
    """Disaster declaration create body; canonical two-county geography."""
    defaults = {
        "declaration_number": DEFAULTS["DECLARATION_NUMBER"],
        "disaster_type": DEFAULTS["DISASTER_TYPE"],
        "incident_start_date": DEFAULTS["INCIDENT_START_DATE"],
        "incident_end_date": DEFAULTS["INCIDENT_END_DATE"],
        "declared_date": CANONICAL_DECLARED_DATE,
        "counties": [
            {"county_fips": CANONICAL_COUNTY_BOTH,
             "eligible_purposes": ["PHYSICAL_DAMAGE", "ECONOMIC_INJURY"]},
            {"county_fips": CANONICAL_COUNTY_EIDL_ONLY,
             "eligible_purposes": ["ECONOMIC_INJURY"]},
        ],
    }
    defaults.update(overrides)
    return defaults


def create_applicant_payload(**overrides) -> dict:
    """Applicant self-registration body; email is unique per call."""
    tag = _next("applicant")
    defaults = {
        "full_name": f"Test Applicant {tag}",
        "email": f"{tag}@example.com",
        "applicant_type": DEFAULTS["APPLICANT_TYPE"],
        "annual_income_cents": DEFAULTS["ANNUAL_INCOME_CENTS"],
        "monthly_debt_cents": DEFAULTS["MONTHLY_DEBT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(declaration_id, **overrides) -> dict:
    """DRAFT application create body; applicant_id comes from X-User-ID."""
    defaults = {
        "declaration_id": declaration_id,
        "county_fips": DEFAULTS["COUNTY_FIPS"],
        "loan_purpose": DEFAULTS["LOAN_PURPOSE"],
        "requested_amount_cents": DEFAULTS["REQUESTED_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def credit_review_payload(**overrides) -> dict:
    """Credit review body; verdict fields are server-computed, never sent."""
    defaults = {
        "credit_score": DEFAULTS["CREDIT_SCORE"],
        "verified_monthly_debt_cents": DEFAULTS["MONTHLY_DEBT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


_UNSET = object()


def create_verification_payload(method="INSPECTION",
                                valuation_basis="REPLACEMENT_COST",
                                depreciation_pct=_UNSET) -> dict:
    """Damage-verification open body.

    depreciation_pct semantics: _UNSET (default) applies the PRD pairing —
    included at 0.20 for ACTUAL_CASH_VALUE, omitted for REPLACEMENT_COST.
    Pass an explicit number to override, or None to force omission (for the
    missing-field shape-error tests).
    """
    payload = {"method": method, "valuation_basis": valuation_basis}
    if depreciation_pct is _UNSET:
        if valuation_basis == "ACTUAL_CASH_VALUE":
            payload["depreciation_pct"] = 0.20
    elif depreciation_pct is not None:
        payload["depreciation_pct"] = depreciation_pct
    return payload


def complete_verification_payload(**overrides) -> dict:
    """Damage-verification completion body (loss figures)."""
    defaults = {
        "assessed_loss_cents": DEFAULTS["ASSESSED_LOSS_CENTS"],
        "insurance_proceeds_cents": DEFAULTS["INSURANCE_PROCEEDS_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def application_decision_payload(decision="APPROVED",
                                 collateral_description=None,
                                 collateral_value_cents=None) -> dict:
    """Application decision body; collateral fields included only when given."""
    payload = {"decision": decision}
    if collateral_description is not None:
        payload["collateral_description"] = collateral_description
    if collateral_value_cents is not None:
        payload["collateral_value_cents"] = collateral_value_cents
    return payload


def grant_award_payload(**overrides) -> dict:
    """Grant award report body."""
    defaults = {
        "program_name": DEFAULTS["GRANT_PROGRAM_NAME"],
        "award_amount_cents": 1000000,
        "purpose_category": "PHYSICAL_DAMAGE",
    }
    defaults.update(overrides)
    return defaults


def milestone_payload(**overrides) -> dict:
    """Repair milestone report body."""
    defaults = {
        "description": DEFAULTS["MILESTONE_DESCRIPTION"],
        "claimed_cost_cents": 2500000,
    }
    defaults.update(overrides)
    return defaults


def milestone_decision_payload(decision="VERIFIED", verified_cost_cents=None) -> dict:
    """Milestone decision body; verified_cost_cents included only when given."""
    payload = {"decision": decision}
    if verified_cost_cents is not None:
        payload["verified_cost_cents"] = verified_cost_cents
    return payload


def modification_request_payload(requested_amount_cents,
                                 expected_loan_version,
                                 reason=None) -> dict:
    """Modification create body; expected_loan_version is the OCC field."""
    return {
        "requested_amount_cents": requested_amount_cents,
        "reason": reason or DEFAULTS["MODIFICATION_REASON"],
        "expected_loan_version": expected_loan_version,
    }


def modification_decision_payload(decision="APPROVED") -> dict:
    return {"decision": decision}


def settlement_payload(**overrides) -> dict:
    """Insurance settlement report body."""
    defaults = {
        "settlement_amount_cents": 12000000,
        "received_date": DEFAULTS["SETTLEMENT_RECEIVED_DATE"],
    }
    defaults.update(overrides)
    return defaults


def apply_settlement_payload(expected_loan_version) -> dict:
    """Settlement apply body; expected_loan_version is the OCC field."""
    return {"expected_loan_version": expected_loan_version}


def servicing_action_payload(action_type="DEFERMENT",
                             start_date="2027-01-01T00:00:00Z",
                             end_date="2027-03-01T00:00:00Z") -> dict:
    """Servicing accommodation request body (half-open window)."""
    return {
        "action_type": action_type,
        "start_date": start_date,
        "end_date": end_date,
    }


def servicing_action_decision_payload(decision="APPROVED") -> dict:
    return {"decision": decision}


def payment_payload(amount_cents) -> dict:
    """Loan payment body."""
    return {"amount_cents": amount_cents}


def receivable_payment_payload(amount_cents) -> dict:
    """Excess-funds receivable payment body."""
    return {"amount_cents": amount_cents}
