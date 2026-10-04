"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "BUSINESS_NAME": "Test Corp",
    "COUNTRY_CODE": "US",
    "LEGAL_NAME_SUFFIX": "LLC",
    "DAILY_BUDGET_CENTS": 1000,
    "START_DATE": "2026-09-01",
    "END_DATE": "2026-12-31",
    "FINAL_URL": "https://example.com/lp",
    "CATEGORY": "GENERAL",
    "QUALITY_ECTR": 5,
    "QUALITY_RELEVANCE": 5,
    "QUALITY_LP": 5,
    "MATCH_TYPE": "EXACT",
    "MAX_CPC_CENTS": 200,
    "PAYMENT_METHOD": "CARD",
    "DOCUMENT_TYPE": "BUSINESS_LICENSE",
}


def create_account_payload(**overrides) -> dict:
    defaults = {
        "business_name": DEFAULTS["BUSINESS_NAME"],
        "country_code": DEFAULTS["COUNTRY_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_identity_verification_payload(expected_account_version, **overrides) -> dict:
    defaults = {
        "legal_business_name": DEFAULTS["BUSINESS_NAME"] + " " + DEFAULTS["LEGAL_NAME_SUFFIX"],
        "registration_number": "RN-1000",
        "document_type": DEFAULTS["DOCUMENT_TYPE"],
        "disclosure_consent": True,
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def decide_verification_payload(outcome="APPROVED", **overrides) -> dict:
    defaults = {"outcome": outcome}
    if outcome == "REJECTED":
        defaults["rejection_reason"] = "document invalid"
    defaults.update(overrides)
    return defaults


def create_appeal_payload(**overrides) -> dict:
    defaults = {"argument_text": "Please review the suspension."}
    defaults.update(overrides)
    return defaults


def suspend_account_payload(**overrides) -> dict:
    defaults = {"reason_code": "POLICY_VIOLATION"}
    defaults.update(overrides)
    return defaults


def create_billing_profile_payload(**overrides) -> dict:
    defaults = {"payment_method_type": DEFAULTS["PAYMENT_METHOD"]}
    defaults.update(overrides)
    return defaults


def create_campaign_payload(account_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "name": "Campaign",
        "daily_budget_cents": DEFAULTS["DAILY_BUDGET_CENTS"],
        "start_date": DEFAULTS["START_DATE"],
        "end_date": DEFAULTS["END_DATE"],
    }
    defaults.update(overrides)
    return defaults


def update_campaign_payload(expected_campaign_version, **overrides) -> dict:
    defaults = {"expected_campaign_version": expected_campaign_version}
    defaults.update(overrides)
    return defaults


def create_ad_group_payload(**overrides) -> dict:
    defaults = {"name": "AdGroup"}
    defaults.update(overrides)
    return defaults


def create_ad_payload(**overrides) -> dict:
    defaults = {
        "headline": "Great Offer",
        "final_url": DEFAULTS["FINAL_URL"],
        "category": DEFAULTS["CATEGORY"],
        "quality_ectr_score": DEFAULTS["QUALITY_ECTR"],
        "quality_relevance_score": DEFAULTS["QUALITY_RELEVANCE"],
        "quality_lp_score": DEFAULTS["QUALITY_LP"],
    }
    defaults.update(overrides)
    return defaults


def create_keyword_payload(text, **overrides) -> dict:
    defaults = {
        "text": text,
        "match_type": DEFAULTS["MATCH_TYPE"],
        "max_cpc_cents": DEFAULTS["MAX_CPC_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def run_auction_payload(query_text, **overrides) -> dict:
    defaults = {"query_text": query_text, "clicked": True}
    defaults.update(overrides)
    return defaults


def pay_invoice_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def close_month_payload(month, **overrides) -> dict:
    defaults = {"month": month}
    defaults.update(overrides)
    return defaults
