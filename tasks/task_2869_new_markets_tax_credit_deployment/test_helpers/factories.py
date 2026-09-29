"""Payload factories -- one per write endpoint, carrying only input fields.

Every money amount is sent as a JSON integer number of cents, and every instant
is sent as a full ISO 8601 UTC timestamp, never a date-only string.  Fields the
server derives or stamps from the acting identity are deliberately absent.
"""
from typing import List, Optional

from .constants import TEST_DEFAULTS

_CERTIFICATION_NUMBER_PREFIX = "CDE-2869-"


def certification_number(suffix: int) -> str:
    """A distinct certification number; the value is unique across entities."""
    return f"{_CERTIFICATION_NUMBER_PREFIX}{suffix}"


# ---------------------------------------------------------------------------
# Community development entity
# ---------------------------------------------------------------------------


def create_cde_payload(**overrides) -> dict:
    payload = {
        "legal_name": TEST_DEFAULTS["CDE_LEGAL_NAME"],
        "certification_number": certification_number(101),
        "service_area_scope": TEST_DEFAULTS["CDE_SERVICE_AREA_SCOPE"],
    }
    payload.update(overrides)
    return payload


def decertify_cde_payload(**overrides) -> dict:
    payload = {"decertification_reason": "Sustained failure of certification standards"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Allocation award
# ---------------------------------------------------------------------------


def create_allocation_award_payload(cde_id: str, **overrides) -> dict:
    payload = {
        "cde_id": cde_id,
        "award_year": TEST_DEFAULTS["AWARD_YEAR"],
        "allocation_amount_cents": TEST_DEFAULTS["ALLOCATION_AMOUNT_CENTS"],
        "service_area_state_codes": list(TEST_DEFAULTS["SERVICE_AREA_STATE_CODES"]),
        "min_severe_distress_share_pct": TEST_DEFAULTS[
            "MIN_SEVERE_DISTRESS_SHARE_PCT"
        ],
        "substantially_all_method": TEST_DEFAULTS["SUBSTANTIALLY_ALL_METHOD"],
    }
    payload.update(overrides)
    return payload


def sign_allocation_agreement_payload(**overrides) -> dict:
    payload = {"signatory_name": TEST_DEFAULTS["SIGNATORY_NAME"]}
    payload.update(overrides)
    return payload


def agency_report_payload(report_year: int = None, **overrides) -> dict:
    payload = {
        "report_year": (
            report_year if report_year is not None else TEST_DEFAULTS["AWARD_YEAR"]
        )
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Census tract
# ---------------------------------------------------------------------------


def create_census_tract_payload(
    contiguous_lic_tract_id: Optional[str] = None, **overrides
) -> dict:
    payload = {
        "tract_code": TEST_DEFAULTS["TRACT_CODE"],
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "poverty_rate_pct": TEST_DEFAULTS["TRACT_POVERTY_RATE_PCT"],
        "mfi_ratio_pct": TEST_DEFAULTS["TRACT_MFI_RATIO_PCT"],
        "unemployment_ratio": TEST_DEFAULTS["TRACT_UNEMPLOYMENT_RATIO"],
        "contiguous_lic_tract_id": contiguous_lic_tract_id,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Project company and its eligibility test
# ---------------------------------------------------------------------------


def create_qalicb_payload(census_tract_id: str, **overrides) -> dict:
    payload = {
        "census_tract_id": census_tract_id,
        "legal_name": TEST_DEFAULTS["QALICB_LEGAL_NAME"],
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "naics_code": TEST_DEFAULTS["QALICB_NAICS_CODE"],
    }
    payload.update(overrides)
    return payload


def eligibility_test_payload(**overrides) -> dict:
    """A six-prong submission that passes every prong by default."""
    payload = {
        "gross_income_lic_pct": 72.00,
        "services_lic_pct": 65.00,
        "tangible_property_lic_pct": 88.00,
        "collectibles_pct": 0.00,
        "nonqualified_financial_property_pct": 1.00,
        "location_prong_passed": True,
    }
    payload.update(overrides)
    return payload


def failing_eligibility_test_payload(**overrides) -> dict:
    """A submission that fails the gross-income and collectibles prongs."""
    payload = eligibility_test_payload(
        gross_income_lic_pct=40.00,
        collectibles_pct=9.00,
    )
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Investment fund
# ---------------------------------------------------------------------------


def create_investment_fund_payload(**overrides) -> dict:
    payload = {
        "legal_name": TEST_DEFAULTS["FUND_LEGAL_NAME"],
        "equity_contribution_cents": TEST_DEFAULTS["FUND_EQUITY_CONTRIBUTION_CENTS"],
        "leverage_lender_name": TEST_DEFAULTS["FUND_LEVERAGE_LENDER_NAME"],
        "leverage_loan_principal_cents": TEST_DEFAULTS[
            "FUND_LEVERAGE_LOAN_PRINCIPAL_CENTS"
        ],
        "leverage_loan_rate_bps": TEST_DEFAULTS["FUND_LEVERAGE_LOAN_RATE_BPS"],
    }
    payload.update(overrides)
    return payload


def close_investment_fund_payload(**overrides) -> dict:
    payload = {
        "equity_received_cents": TEST_DEFAULTS["FUND_EQUITY_CONTRIBUTION_CENTS"],
        "leverage_received_cents": TEST_DEFAULTS[
            "FUND_LEVERAGE_LOAN_PRINCIPAL_CENTS"
        ],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Qualified equity investment
# ---------------------------------------------------------------------------


def create_qei_payload(
    allocation_award_id: str,
    investment_fund_id: str,
    expected_allocation_award_version: int,
    **overrides,
) -> dict:
    payload = {
        "allocation_award_id": allocation_award_id,
        "investment_fund_id": investment_fund_id,
        "qei_amount_cents": TEST_DEFAULTS["QEI_AMOUNT_CENTS"],
        "expected_allocation_award_version": expected_allocation_award_version,
    }
    payload.update(overrides)
    return payload


def void_qei_payload(**overrides) -> dict:
    payload = {"void_reason": "Closing conditions not satisfied"}
    payload.update(overrides)
    return payload


def annual_test_payload(compliance_year: int, **overrides) -> dict:
    payload = {"compliance_year": compliance_year}
    payload.update(overrides)
    return payload


def cure_payload(qalicb_id: str, principal_cents: int, **overrides) -> dict:
    payload = {"qalicb_id": qalicb_id, "principal_cents": principal_cents}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Sub-allocation
# ---------------------------------------------------------------------------


def create_qlici_payload(qei_id: str, qalicb_id: str, **overrides) -> dict:
    payload = {
        "qei_id": qei_id,
        "qalicb_id": qalicb_id,
        "loan_class": TEST_DEFAULTS["QLICI_LOAN_CLASS"],
        "principal_cents": TEST_DEFAULTS["QLICI_PRINCIPAL_CENTS"],
    }
    payload.update(overrides)
    return payload


def principal_repayment_payload(amount_cents: int, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def reinvestment_payload(target_qlici_id: str, amount_cents: int, **overrides) -> dict:
    payload = {"target_qlici_id": target_qlici_id, "amount_cents": amount_cents}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Community benefits agreement
# ---------------------------------------------------------------------------


def create_cba_payload(qalicb_id: str, allocation_award_id: str, **overrides) -> dict:
    payload = {
        "qalicb_id": qalicb_id,
        "allocation_award_id": allocation_award_id,
        "target_fte_count": TEST_DEFAULTS["CBA_TARGET_FTE_COUNT"],
        "wage_floor_cents_per_hour": TEST_DEFAULTS["CBA_WAGE_FLOOR_CENTS_PER_HOUR"],
        "local_hire_pct_target": TEST_DEFAULTS["CBA_LOCAL_HIRE_PCT_TARGET"],
        "measurement_basis": TEST_DEFAULTS["CBA_MEASUREMENT_BASIS"],
    }
    payload.update(overrides)
    return payload


def job_report_payload(
    period_start_at: str,
    period_end_at: str,
    headcount: int = 10,
    qualifying_headcount: int = 9,
    total_hours: int = 20000,
    qualifying_hours: int = 18000,
    local_hires: int = 6,
    avg_hourly_wage_cents: int = 2100,
    **overrides,
) -> dict:
    payload = {
        "period_start_at": period_start_at,
        "period_end_at": period_end_at,
        "headcount": headcount,
        "qualifying_headcount": qualifying_headcount,
        "total_hours": total_hours,
        "qualifying_hours": qualifying_hours,
        "local_hires": local_hires,
        "avg_hourly_wage_cents": avg_hourly_wage_cents,
    }
    payload.update(overrides)
    return payload


def annual_certification_payload(
    certification_year: int, window_start_at: str, window_end_at: str, **overrides
) -> dict:
    payload = {
        "certification_year": certification_year,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Unwind
# ---------------------------------------------------------------------------


def open_unwind_payload(call_holder_user_id: str, **overrides) -> dict:
    payload = {"call_holder_user_id": call_holder_user_id}
    payload.update(overrides)
    return payload


def exercise_option_payload(option_type: str, **overrides) -> dict:
    payload = {"option_type": option_type}
    payload.update(overrides)
    return payload


def settlement_payload(**overrides) -> dict:
    payload = {"settlement_reference": "SETTLE-2869-0001"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Tract profiles used repeatedly across scenarios
# ---------------------------------------------------------------------------


def severe_tract_payload(**overrides) -> dict:
    """A tract that is low-income, meets three severe criteria and scores 100.00."""
    return create_census_tract_payload(
        poverty_rate_pct=32.00,
        mfi_ratio_pct=55.00,
        unemployment_ratio=1.80,
        **overrides,
    )


def moderate_tract_payload(**overrides) -> dict:
    """A low-income tract that meets no severe criterion."""
    return create_census_tract_payload(
        poverty_rate_pct=22.00,
        mfi_ratio_pct=78.00,
        unemployment_ratio=1.10,
        **overrides,
    )


def ineligible_tract_payload(**overrides) -> dict:
    """A tract that is neither low-income nor contiguity-qualifying."""
    return create_census_tract_payload(
        poverty_rate_pct=12.00,
        mfi_ratio_pct=95.00,
        unemployment_ratio=0.80,
        **overrides,
    )


def state_codes(*codes: str) -> List[str]:
    return list(codes)
