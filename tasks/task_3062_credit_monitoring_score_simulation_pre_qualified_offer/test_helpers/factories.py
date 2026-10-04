"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS

DEFAULTS = {
    "CONSUMER_NAME": "Maya Chen",
    "CONSUMER_EMAIL": "maya@example.com",
    "STATE_CODE": "CA",
    "BUREAU_PIN": "4821",
    "DTI_PCT": TEST_DEFAULTS["DTI_PCT"],
    "CREDIT_LIMIT_TOTAL_CENTS": TEST_DEFAULTS["CREDIT_LIMIT_TOTAL_CENTS"],
    "SCORE": TEST_DEFAULTS["SCORE"],
    "LENDER_NAME": "Northstar Bank",
    "PROGRAM_NAME": "Northstar Personal Loan",
    "PROGRAM_CODE": "NS-LOAN-01",
    "PRODUCT_NAME": "Personal Loan",
}


def create_consumer_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["CONSUMER_NAME"],
        "email": DEFAULTS["CONSUMER_EMAIL"],
        "state_code": DEFAULTS["STATE_CODE"],
        "bureau_pin": DEFAULTS["BUREAU_PIN"],
        "dti_pct": DEFAULTS["DTI_PCT"],
    }
    payload.update(overrides)
    return payload


def create_bureau_snapshot_payload(expected_consumer_version, **overrides) -> dict:
    payload = {
        "score": DEFAULTS["SCORE"],
        "added_account_count": 1,
        "total_revolving_balance_cents": 300_000,
        "credit_limit_total_cents": DEFAULTS["CREDIT_LIMIT_TOTAL_CENTS"],
        "factor_codes": ["high_utilization"],
        "channel": "EMAIL",
        "expected_consumer_version": expected_consumer_version,
    }
    payload.update(overrides)
    return payload


def create_score_tier_payload(**overrides) -> dict:
    payload = {
        "tier_code": "GOOD",
        "min_score": 670,
        "max_score": 739,
        "factor_catalog": ["high_utilization", "length_of_credit_history"],
    }
    payload.update(overrides)
    return payload


def create_catalog_item_payload(**overrides) -> dict:
    payload = {
        "product_kind": "LOAN",
        "product_name": DEFAULTS["PRODUCT_NAME"],
        "min_score": 560,
        "max_score": 720,
        "max_dti_pct": 60.0,
    }
    payload.update(overrides)
    return payload


def create_lender_payload(**overrides) -> dict:
    payload = {
        "lender_name": DEFAULTS["LENDER_NAME"],
        "states_served": ["CA", "NY", "TX"],
    }
    payload.update(overrides)
    return payload


def create_lender_program_payload(lender_id, product_catalog_item_id, **overrides) -> dict:
    payload = {
        "lender_id": lender_id,
        "product_catalog_item_id": product_catalog_item_id,
        "program_name": DEFAULTS["PROGRAM_NAME"],
        "program_code": DEFAULTS["PROGRAM_CODE"],
        "min_modeled_score": 560,
        "max_dti_pct": 45.0,
        "max_eligible_utilization_pct": 55.0,
        "annual_fee_cents": 0,
        "intro_apr_bps": 1299,
        "go_live_at": "2026-08-01T00:00:00Z",
        "expiry_at": "2027-08-01T00:00:00Z",
        "revenue_share_bps": TEST_DEFAULTS["REVENUE_SHARE_BPS"],
        "clawback_rate_bps": TEST_DEFAULTS["CLAWBACK_RATE_BPS"],
        "clawback_days": TEST_DEFAULTS["CLAWBACK_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_targeting_criterion_payload(**overrides) -> dict:
    payload = {
        "criterion_field": "UTILIZATION_PCT",
        "operator": "LTE",
        "criterion_value": "50",
        "is_hard_requirement": True,
    }
    payload.update(overrides)
    return payload


def create_simulation_payload(expected_consumer_version, actions=None, **overrides) -> dict:
    payload = {
        "actions": actions or [{"action_code": "PAY_DOWN_REVOLVING", "amount_cents": 72_000}],
        "expected_consumer_version": expected_consumer_version,
    }
    payload.update(overrides)
    return payload


def create_consent_payload(expected_consumer_version, **overrides) -> dict:
    payload = {
        "consent_method": "ELECTRONIC",
        "consent_scope": "SHARE_PII_WITH_LENDER",
        "expected_consumer_version": expected_consumer_version,
    }
    payload.update(overrides)
    return payload


def create_referral_payload(offer_id, **overrides) -> dict:
    payload = {
        "external_referral_ref": "NS-L-9001",
        "channel": "WEB",
        "offer_id": offer_id,
    }
    payload.update(overrides)
    return payload


def create_referral_attempt_payload(decision_id, **overrides) -> dict:
    payload = {"decision_id": decision_id, "channel": "MARKETPLACE"}
    payload.update(overrides)
    return payload


def create_dispute_referral_payload(consumer_id, snapshot_id, **overrides) -> dict:
    payload = {
        "consumer_id": consumer_id,
        "snapshot_id": snapshot_id,
        "inaccuracy_type": "ACCOUNT_INFO",
        "narrative": "An account that was closed in 2023 still reports an open balance on this file.",
    }
    payload.update(overrides)
    return payload


def create_content_quality_facet_payload(**overrides) -> dict:
    payload = {"topic": "factor_explanations", "score_bps": 9000}
    payload.update(overrides)
    return payload