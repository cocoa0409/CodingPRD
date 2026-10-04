"""Payload factories — one per entity, input fields only."""
from .types import Unset

_UNSET = Unset.UNSET


def _apply(payload: dict, overrides: dict) -> dict:
    """Apply overrides; an explicit ``Unset`` value removes the field so
    omission-as-required-field cases can be expressed without mutating
    the caller's dict."""
    for key, value in overrides.items():
        if value is _UNSET:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ─── Industry categories ──────────────────────────────

def create_industry_category_payload(**overrides) -> dict:
    payload = {
        "industry_code": "MCC-5812",
        "industry_name": "Dining",
        "risk_tier": "MEDIUM",
        "base_discount_rate_bps": 250,
        "high_risk_flag": False,
    }
    return _apply(payload, overrides)


# ─── Merchants ────────────────────────────────────────

def create_merchant_payload(industry_category_id: str, **overrides) -> dict:
    payload = {
        "industry_category_id": industry_category_id,
        "merchant_name": "Test Merchant",
        "region_code": "US-NE",
        "acquisition_channel": "DIRECT",
    }
    return _apply(payload, overrides)


def accept_merchant_payload(expected_merchant_version, **overrides) -> dict:
    payload = {"expected_merchant_version": expected_merchant_version}
    return _apply(payload, overrides)


# ─── Declined attempts ────────────────────────────────

def create_declined_attempt_payload(**overrides) -> dict:
    payload = {
        "card_product": "PLATINUM",
        "attempted_amount_cents": 100000,
        "decline_reason": "MERCHANT_NOT_ACCEPTED",
        "occurred_at": "2026-08-10T00:00:00.000Z",
    }
    return _apply(payload, overrides)


# ─── Acceptance gap rollup ────────────────────────────

def rollup_acceptance_gap_payload(region_code: str, industry_category_id: str,
                                  window_start: str, window_end: str,
                                  window_days: int = 30, **overrides) -> dict:
    payload = {
        "region_code": region_code,
        "industry_category_id": industry_category_id,
        "window_start": window_start,
        "window_end": window_end,
        "window_days": window_days,
    }
    return _apply(payload, overrides)


def stamp_sweep_index_payload(sweep_index, rolled_at="2026-09-01T00:00:00.000Z",
                              **overrides) -> dict:
    payload = {"sweep_index": sweep_index, "rolled_at": rolled_at}
    return _apply(payload, overrides)


# ─── Offers ───────────────────────────────────────────

def create_offer_payload(merchant_id: str, **overrides) -> dict:
    payload = {
        "merchant_id": merchant_id,
        "audience_segment": "HIGH_SPEND",
        "min_segment_spend_cents": 10000,
        "reward_bps": 1000,
    }
    return _apply(payload, overrides)


def offer_consent_payload(**overrides) -> dict:
    """Consent body. Both keys are optional on the contract, so defaults
    leave them off entirely."""
    payload = {}
    return _apply(payload, overrides)


# ─── Offer redemption pools ───────────────────────────

def create_redemption_pool_payload(**overrides) -> dict:
    payload = {"funder": "MERCHANT", "initial_funded_cents": 500000}
    return _apply(payload, overrides)


# ─── Card members ─────────────────────────────────────

def create_cardmember_payload(**overrides) -> dict:
    payload = {"member_name": "Test Member", "card_product": "PLATINUM"}
    return _apply(payload, overrides)


def set_monthly_spend_payload(trailing_lowest_month_spend_cents: int,
                              **overrides) -> dict:
    payload = {"trailing_lowest_month_spend_cents": trailing_lowest_month_spend_cents}
    return _apply(payload, overrides)


# ─── Annual fee statements ────────────────────────────

def create_annual_fee_statement_payload(cardmember_id: str, **overrides) -> dict:
    payload = {
        "cardmember_id": cardmember_id,
        "statement_year": 2026,
        "principal_fee_cents": 1000000,
        "authorised_user_count": 2,
        "per_user_fee_cents": 50000,
    }
    return _apply(payload, overrides)


# ─── Settlements ──────────────────────────────────────

def create_settlement_payload(**overrides) -> dict:
    payload = {
        "settlement_cycle": 1,
        "gross_volume_cents": 500000,
        "refund_volume_cents": 0,
    }
    return _apply(payload, overrides)


# ─── Disputes ─────────────────────────────────────────

def create_dispute_payload(cardmember_id: str, original_merchant_id: str,
                           final_merchant_id: str, amount_cents: int = 100000,
                           **overrides) -> dict:
    payload = {
        "cardmember_id": cardmember_id,
        "original_merchant_id": original_merchant_id,
        "final_merchant_id": final_merchant_id,
        "amount_cents": amount_cents,
    }
    return _apply(payload, overrides)


def resolve_dispute_payload(outcome: str, **overrides) -> dict:
    payload = {"outcome": outcome}
    return _apply(payload, overrides)


# ─── Complaints ───────────────────────────────────────

def create_complaint_payload(merchant_id: str, cardmember_id: str,
                             **overrides) -> dict:
    payload = {
        "merchant_id": merchant_id,
        "cardmember_id": cardmember_id,
        "complaint_type": "MERCHANT_NOT_ACCEPTED",
    }
    return _apply(payload, overrides)