"""Payload factories — one per entity, declared input fields only."""
from .constants import (
    MINIMUM_CHARGE_CENTS_DEFAULT,
    SETTLEMENT_TERMS_DAYS_DEFAULT,
    DISPUTE_GRACE_DAYS_DEFAULT,
    RENEWAL_NOTICE_DAYS_DEFAULT,
    PURCHASE_RIGHT_RATE_DEFAULT,
    TEST_DEFAULTS,
)


def create_partner_payload(**overrides) -> dict:
    payload = {
        "retailer_name": "Test Retailer",
        "loyalty_program_code": "TEST_REWARDS",
    }
    payload.update(overrides)
    return payload


def create_agreement_payload(partner_id, **overrides) -> dict:
    payload = {
        "partner_id": partner_id,
        "revenue_share_rate": TEST_DEFAULTS["REVENUE_SHARE_RATE"],
        "promo_subsidy_rate": TEST_DEFAULTS["PROMO_SUBSIDY_RATE"],
        "promo_term_months": TEST_DEFAULTS["PROMO_TERM_MONTHS"],
        "minimum_charge_cents": MINIMUM_CHARGE_CENTS_DEFAULT,
        "settlement_terms_days": SETTLEMENT_TERMS_DAYS_DEFAULT,
        "dispute_grace_days": DISPUTE_GRACE_DAYS_DEFAULT,
        "renewal_notice_days": RENEWAL_NOTICE_DAYS_DEFAULT,
        "purchase_right_rate": PURCHASE_RIGHT_RATE_DEFAULT,
    }
    payload.update(overrides)
    return payload


def create_credit_program_payload(partner_id, agreement_id, **overrides) -> dict:
    payload = {
        "partner_id": partner_id,
        "agreement_id": agreement_id,
        "cycle_day": 15,
    }
    payload.update(overrides)
    return payload


def create_application_payload(program_id, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "source_channel": "DIGITAL",
        "requested_credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_transaction_payload(account_id, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "merchant_name": "Test Merchant",
        "amount_cents": TEST_DEFAULTS["PURCHASE_AMOUNT_CENTS"],
        "transaction_channel": "IN_STORE",
    }
    payload.update(overrides)
    return payload


def create_promo_transaction_payload(account_id, amount_cents, promo_term_months,
                                     **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "merchant_name": "Test Promo Merchant",
        "amount_cents": amount_cents,
        "transaction_channel": "IN_STORE",
        "promo_requested": True,
        "promo_term_months": promo_term_months,
    }
    payload.update(overrides)
    return payload


def create_balance_payload(principal_balance_cents, balance_bucket="PRINCIPAL") -> dict:
    return {
        "principal_balance_cents": principal_balance_cents,
        "balance_bucket": balance_bucket,
    }


def create_settlement_batch_payload(agreement_id, period_start, period_end, **overrides) -> dict:
    payload = {
        "agreement_id": agreement_id,
        "period_start": period_start,
        "period_end": period_end,
        "settlement_method": "AS_CHARGED",
        "reconciliation_method": "PROJECTED",
    }
    payload.update(overrides)
    return payload


def create_dispute_payload(transaction_id, account_id, dispute_reason="FRAUD") -> dict:
    return {
        "transaction_id": transaction_id,
        "account_id": account_id,
        "dispute_reason": dispute_reason,
    }


def create_benefit_posting_payload(account_id, transaction_id, points_amount,
                                   posting_reason="PURCHASE_EARN", **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "transaction_id": transaction_id,
        "posting_reason": posting_reason,
        "points_amount": points_amount,
        "posts_to_retailer_loyalty": True,
    }
    payload.update(overrides)
    return payload


def create_transfer_payload(program_id, buyer_role="RETAILER", **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "buyer_role": buyer_role,
    }
    payload.update(overrides)
    return payload