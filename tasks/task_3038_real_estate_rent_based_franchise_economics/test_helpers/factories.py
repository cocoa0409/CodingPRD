"""Payload factories — one per entity, client-supplied fields only."""
from .constants import TERMS

_seq = {"n": 0}


def _next(tag: str) -> str:
    _seq["n"] += 1
    return f"{tag}-{_seq['n']}"


def create_site_payload(**overrides) -> dict:
    payload = {
        "site_code": _next("SITE"),
        "address": "100 Test Blvd",
        "acquisition_type": "FEE_SIMPLE",
    }
    payload.update(overrides)
    return payload


def create_operator_payload(**overrides) -> dict:
    payload = {
        "legal_name": _next("Operator LLC"),
        "fy_net_worth_cents": TERMS["STRONG_NET_WORTH_CENTS"],
        "fy_operating_income_cents": TERMS["STRONG_OPERATING_INCOME_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_capacity_review_payload(operator_id, **overrides) -> dict:
    payload = {"operator_id": operator_id, "review_period": "2026"}
    payload.update(overrides)
    return payload


def create_store_payload(site_id, operator_id, expected_operator_version, **overrides) -> dict:
    payload = {
        "store_code": _next("STORE"),
        "site_id": site_id,
        "operator_id": operator_id,
        "expected_operator_version": expected_operator_version,
    }
    payload.update(overrides)
    return payload


def create_agreement_payload(store_id, operator_id, **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "operator_id": operator_id,
        "initial_fee_cents": TERMS["INITIAL_FEE_CENTS"],
        "royalty_rate": TERMS["ROYALTY_RATE"],
        "ad_fund_rate": TERMS["AD_FUND_RATE"],
        "occupancy_allocation_pct": TERMS["OCCUPANCY_ALLOCATION_PCT"],
        "term_years": TERMS["TERM_YEARS"],
        "term_start_date": TERMS["TERM_START_DATE"],
    }
    payload.update(overrides)
    return payload


def create_sublease_payload(store_id, operator_id, **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "operator_id": operator_id,
        "base_rent_cents": TERMS["BASE_RENT_CENTS"],
        "pct_rent_rate": TERMS["PCT_RENT_RATE"],
        "escalation_rate": TERMS["ESCALATION_RATE"],
        "escalation_month": TERMS["ESCALATION_MONTH"],
        "escalation_day": TERMS["ESCALATION_DAY"],
        "start_date": TERMS["SUBLEASE_START_DATE"],
        "end_date": TERMS["SUBLEASE_END_DATE"],
    }
    payload.update(overrides)
    return payload


def create_sales_report_payload(store_id, period_month="2026-09", gross_sales_cents=1_000_000, **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "period_month": period_month,
        "gross_sales_cents": gross_sales_cents,
    }
    payload.update(overrides)
    return payload


def create_rent_charge_payload(store_id, expected_sublease_version, **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "billing_period": "2026",
        "period_start": "2026-04-01",
        "period_end": "2027-03-31",
        "expected_sublease_version": expected_sublease_version,
    }
    payload.update(overrides)
    return payload


def create_reinvestment_obligation_payload(store_id, agreement_id, **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "agreement_id": agreement_id,
        "required_budget_cents": 2_000_000,
        "deadline_date": "2027-12-31",
    }
    payload.update(overrides)
    return payload


def create_advertising_fund_payload(**overrides) -> dict:
    payload = {
        "name": _next("Fund"),
        "fund_type": "NATIONAL",
        "admin_fee_rate": 0.0,
    }
    payload.update(overrides)
    return payload


def create_coop_assessment_payload(fund_id, store_id, **overrides) -> dict:
    payload = {
        "fund_id": fund_id,
        "store_id": store_id,
        "amount_cents": 50_000,
    }
    payload.update(overrides)
    return payload


def declare_default_payload(**overrides) -> dict:
    payload = {"reason": "RENT_NONPAYMENT", "cure_fee_cents": 15_000}
    payload.update(overrides)
    return payload


def disburse_payload(**overrides) -> dict:
    payload = {"amount_cents": 1_000, "purpose": "test disbursement"}
    payload.update(overrides)
    return payload
