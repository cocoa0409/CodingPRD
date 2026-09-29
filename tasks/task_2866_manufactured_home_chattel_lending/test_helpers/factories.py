"""Payload factories — one per write, carrying only caller-supplied fields.

Every monetary field is emitted as a JSON integer number of cents and every
rate as a JSON integer number of basis points; no monetary or rate field is
ever transmitted as a decimal fraction or as a string.  Every date field is a
full ISO 8601 UTC instant, never a bare calendar date.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


_hud_counter = itertools.count(1)
_policy_counter = itertools.count(1)
_agency_counter = itertools.count(1)


def unique_hud_label(prefix: str = "ALB") -> str:
    """A HUD certification label that no other unit in this test can carry."""
    return f"{prefix}{next(_hud_counter):07d}"


def unique_policy_number(prefix: str = "GM") -> str:
    return f"{prefix}-{next(_policy_counter):06d}"


def unique_agency_reference(prefix: str = "GA-TL-2026") -> str:
    return f"{prefix}-{next(_agency_counter):06d}"


def book_value_guide_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "guide_edition": TEST_DEFAULTS["GUIDE_EDITION"],
        "region_code": TEST_DEFAULTS["REGION_CODE"],
        "effective_date": TEST_DEFAULTS["GUIDE_EFFECTIVE_DATE"],
        "base_value_per_sqft_cents": TEST_DEFAULTS["BASE_VALUE_PER_SQFT_CENTS"],
        "single_wide_multiplier_bps": TEST_DEFAULTS["SINGLE_WIDE_MULTIPLIER_BPS"],
        "multi_wide_multiplier_bps": TEST_DEFAULTS["MULTI_WIDE_MULTIPLIER_BPS"],
        "annual_depreciation_bps": TEST_DEFAULTS["ANNUAL_DEPRECIATION_BPS"],
    }
    payload.update(overrides)
    return payload


def borrower_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "full_name": "Dana Whitfield",
        "credit_score": 705,
        "monthly_income_cents": 520000,
        "state_code": "GA",
    }
    payload.update(overrides)
    return payload


def community_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "name": "Pine Ridge MHC",
        "state_code": "GA",
        "lot_count": 180,
        "monthly_lot_rent_cents": 52000,
        "sales_commission_bps": 150,
    }
    payload.update(overrides)
    return payload


def community_unit_payload(community_id: str, **overrides) -> Dict[str, Any]:
    """A community placement: community_id, lot_number and placement_start_date."""
    payload = {
        "hud_label_number": unique_hud_label(),
        "manufacturer": "Clayton",
        "model_year": 2018,
        "width_class": "MULTI_WIDE",
        "square_feet": 1440,
        "condition_grade": "GOOD",
        "installation_type": "PIER_AND_ANCHOR",
        "wind_zone": 2,
        "placement_type": "COMMUNITY",
        "community_id": community_id,
        "lot_number": "A-14",
        "placement_start_date": "2026-08-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def private_land_unit_payload(land_owner_borrower_id: str, **overrides) -> Dict[str, Any]:
    """A private-land placement: land owner, parcel number and recording county."""
    payload = {
        "hud_label_number": unique_hud_label(),
        "manufacturer": "Clayton",
        "model_year": 2018,
        "width_class": "MULTI_WIDE",
        "square_feet": 1440,
        "condition_grade": "GOOD",
        "installation_type": "PERMANENT_FOUNDATION",
        "wind_zone": 2,
        "placement_type": "PRIVATE_LAND",
        "land_owner_borrower_id": land_owner_borrower_id,
        "land_parcel_apn": "071-14-002-118",
        "land_county": "Cobb",
        "land_value_cents": 4300000,
    }
    payload.update(overrides)
    return payload


def valuation_payload(
    unit_id: str,
    guide_id: str,
    expected_unit_version: int,
    variant: str = "ORIGINATION",
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "unit_id": unit_id,
        "guide_id": guide_id,
        "variant": variant,
        "expected_unit_version": expected_unit_version,
    }
    payload.update(overrides)
    return payload


def loan_payload(
    borrower_id: str,
    unit_id: str,
    origination_valuation_id: str,
    principal_cents: int = TEST_DEFAULTS["PRINCIPAL_CENTS"],
    requested_term_months: int = TEST_DEFAULTS["REQUESTED_TERM_MONTHS"],
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "borrower_id": borrower_id,
        "unit_id": unit_id,
        "origination_valuation_id": origination_valuation_id,
        "principal_cents": principal_cents,
        "requested_term_months": requested_term_months,
    }
    payload.update(overrides)
    return payload


def fund_payload(
    first_due_date: str = TEST_DEFAULTS["FIRST_DUE_DATE"], **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"first_due_date": first_due_date}
    payload.update(overrides)
    return payload


def title_lien_payload(loan_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "loan_id": loan_id,
        "filing_type": "TITLE_LIEN",
        "submitted_documents": ["TITLE_APPLICATION", "LIEN_ENTRY_FORM"],
    }
    payload.update(overrides)
    return payload


def deed_of_trust_payload(loan_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "loan_id": loan_id,
        "filing_type": "LAND_HOME_DEED_OF_TRUST",
        "submitted_documents": [
            "DEED_OF_TRUST",
            "AFFIXATION_AFFIDAVIT",
            "TITLE_SURRENDER_RECEIPT",
        ],
    }
    payload.update(overrides)
    return payload


def agency_response_payload(
    outcome: str = "RECORDED",
    agency_reference: Optional[str] = None,
    rejection_code: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    if outcome == "RECORDED":
        payload["agency_reference"] = agency_reference or unique_agency_reference()
    else:
        payload["rejection_code"] = rejection_code or "MISSING_DOCUMENT"
    return payload


def resubmit_payload(submitted_documents: List[str]) -> Dict[str, Any]:
    return {"submitted_documents": submitted_documents}


def insurance_policy_payload(
    loan_id: str,
    expected_loan_version: int,
    dwelling_coverage_cents: int = 5200000,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "loan_id": loan_id,
        "carrier_name": "Gulf Mutual",
        "policy_number": unique_policy_number(),
        "dwelling_coverage_cents": dwelling_coverage_cents,
        "wind_deductible_cents": 150000,
        "wind_endorsement": True,
        "effective_date": TEST_DEFAULTS["POLICY_EFFECTIVE_DATE"],
        "expiry_date": TEST_DEFAULTS["POLICY_EXPIRY_DATE"],
        "expected_loan_version": expected_loan_version,
    }
    payload.update(overrides)
    return payload


def force_place_payload(
    effective_date: str,
    expiry_date: str,
    carrier_name: str = "Lender Placed Casualty",
    policy_number: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "carrier_name": carrier_name,
        "policy_number": policy_number or unique_policy_number("LP"),
        "effective_date": effective_date,
        "expiry_date": expiry_date,
    }


def payment_payload(
    amount_cents: int, payment_kind: str = "SCHEDULED", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "amount_cents": amount_cents,
        "payment_kind": payment_kind,
    }
    payload.update(overrides)
    return payload


def lot_rent_report_payload(
    months_delinquent: int, lot_rent_state: str = "DELINQUENT"
) -> Dict[str, Any]:
    return {"months_delinquent": months_delinquent, "lot_rent_state": lot_rent_state}


def refurbishment_cost_payload(
    category: str, cost_cents: int, cost_class: str
) -> Dict[str, Any]:
    return {
        "category": category,
        "cost_cents": cost_cents,
        "cost_class": cost_class,
    }
