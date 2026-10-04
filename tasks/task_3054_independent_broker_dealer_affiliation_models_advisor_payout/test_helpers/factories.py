"""Payload factories — one per entity, declared input fields only."""

from .constants import TEST_DEFAULTS


DEFAULTS = {
    "BRANCH_CODE": TEST_DEFAULTS["BRANCH_CODE"],
    "BRANCH_NAME": TEST_DEFAULTS["BRANCH_NAME"],
    "TRANSMITTAL_ACCOUNT": TEST_DEFAULTS["TRANSMITTAL_ACCOUNT"],
    "OSJ_NAME": TEST_DEFAULTS["OSJ_NAME"],
    "AFFILIATION_MODEL": "IC",
    "EO_COVERAGE_LEVEL": "STANDARD",
    "INGESTED_BOOK_CENTS": 500_000_000,
    "BOOK_TRANSFERRED_CENTS": 400_000_000,
    "LOAN_PRINCIPAL_CENTS": 500_000,
    "LOAN_AMORTIZATION_BPS": 2000,
    "LOAN_FORGIVENESS_PCT": 90,
    "PERIOD_YEAR": 2026,
    "PERIOD_MONTH": 9,
    "PERIOD_INDEX": 1,
}


def create_branch_payload(**overrides) -> dict:
    payload = {
        "branch_code": DEFAULTS["BRANCH_CODE"],
        "name": DEFAULTS["BRANCH_NAME"],
        "transmittal_account": DEFAULTS["TRANSMITTAL_ACCOUNT"],
        "osj_name": DEFAULTS["OSJ_NAME"],
    }
    payload.update(overrides)
    return payload


def create_advisor_payload(advisor_code, crd_number, full_name, **overrides) -> dict:
    payload = {
        "advisor_code": advisor_code,
        "crd_number": crd_number,
        "full_name": full_name,
        "affiliation_model": DEFAULTS["AFFILIATION_MODEL"],
        "primary_branch_code": DEFAULTS["BRANCH_CODE"],
        "ingested_book_total_cents": DEFAULTS["INGESTED_BOOK_CENTS"],
        "book_transferred_cents": DEFAULTS["BOOK_TRANSFERRED_CENTS"],
        "protocol_eligible": True,
        "eo_coverage_level": DEFAULTS["EO_COVERAGE_LEVEL"],
    }
    payload.update(overrides)
    return payload


def create_supervisor_enrollment_payload(branch_code, advisor_code,
                                         effective_date="2026-09-01", **overrides) -> dict:
    payload = {
        "branch_code": branch_code,
        "advisor_code": advisor_code,
        "effective_date": effective_date,
    }
    payload.update(overrides)
    return payload


def create_advisor_link_payload(advisor_code, branch_code,
                                is_supervisor=False, assignment_type="PRIMARY",
                                **overrides) -> dict:
    payload = {
        "advisor_code": advisor_code,
        "branch_code": branch_code,
        "is_supervisor": is_supervisor,
        "assignment_type": assignment_type,
    }
    payload.update(overrides)
    return payload


def create_account_payload(advisor_code, account_number, account_type="BROKERAGE",
                           **overrides) -> dict:
    payload = {
        "advisor_code": advisor_code,
        "account_number": account_number,
        "account_type": account_type,
        "balance_cents": 10_000_000,
        "annual_fee_cents": 0,
        "held_away": False,
    }
    payload.update(overrides)
    return payload


def create_revenue_entry_payload(advisor_code, account_id, gross_commission_cents,
                                 production_date="2026-09-03",
                                 product_type="EQUITY", **overrides) -> dict:
    payload = {
        "advisor_code": advisor_code,
        "account_id": account_id,
        "product_type": product_type,
        "gross_commission_cents": gross_commission_cents,
        "production_date": production_date,
    }
    payload.update(overrides)
    return payload


def create_payout_period_payload(branch_code, year=None, month=None,
                                 period_index=None, **overrides) -> dict:
    payload = {
        "branch_code": branch_code,
        "year": year if year is not None else DEFAULTS["PERIOD_YEAR"],
        "month": month if month is not None else DEFAULTS["PERIOD_MONTH"],
        "period_index": period_index if period_index is not None
        else DEFAULTS["PERIOD_INDEX"],
    }
    payload.update(overrides)
    return payload


def create_payout_line_payload(payout_period_id, projected_annual_production_cents,
                               **overrides) -> dict:
    payload = {
        "payout_period_id": payout_period_id,
        "projected_annual_production_cents": projected_annual_production_cents,
    }
    payload.update(overrides)
    return payload


def create_payout_loan_payload(advisor_code, principal_cents=None,
                               amortization_rate_bps=None,
                               forgiveness_milestone_pct=None, **overrides) -> dict:
    payload = {
        "advisor_code": advisor_code,
        "principal_cents": principal_cents if principal_cents is not None
        else DEFAULTS["LOAN_PRINCIPAL_CENTS"],
        "amortization_rate_bps": amortization_rate_bps if amortization_rate_bps is not None
        else DEFAULTS["LOAN_AMORTIZATION_BPS"],
        "forgiveness_milestone_pct": forgiveness_milestone_pct
        if forgiveness_milestone_pct is not None else DEFAULTS["LOAN_FORGIVENESS_PCT"],
    }
    payload.update(overrides)
    return payload


def create_expense_pass_through_payload(advisor_code, payout_period_id, category,
                                        billing_model="FLAT_MONTHLY", **overrides) -> dict:
    payload = {
        "advisor_code": advisor_code,
        "payout_period_id": payout_period_id,
        "category": category,
        "billing_model": billing_model,
    }
    payload.update(overrides)
    return payload


def create_transition_payload(advisor_code, payout_period_id,
                              expected_advisor_version, **overrides) -> dict:
    payload = {
        "advisor_code": advisor_code,
        "payout_period_id": payout_period_id,
        "expected_advisor_version": expected_advisor_version,
    }
    payload.update(overrides)
    return payload


def create_retention_contest_payload(account_id, retention_rate_bps=500,
                                     **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "retention_rate_bps": retention_rate_bps,
    }
    payload.update(overrides)
    return payload