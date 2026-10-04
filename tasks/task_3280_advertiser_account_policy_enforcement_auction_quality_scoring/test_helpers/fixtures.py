"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so each test
starts against an empty database).

Ownership threading: the Advertiser role is entity-backed, so every
ownership-gated call uses make_advertiser_headers(account_id) with the real
account id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_account_payload,
    create_ad_group_payload,
    create_ad_payload,
    create_billing_profile_payload,
    create_campaign_payload,
    create_identity_verification_payload,
    decide_verification_payload,
    create_keyword_payload,
)
from .test_users import (
    TEST_USERS,
    make_advertiser_headers,
)


# ---------------------------------------------------------------------------
# Tier 0: clock + account primitives
# ---------------------------------------------------------------------------

def set_clock(iso8601: str):
    """Advance the logical clock."""
    resp = api_client.set_clock({"to_iso8601": iso8601}, TEST_USERS["platform_admin_headers"])
    return get_success_data(resp)


def create_account(business_name: str = "Test Corp", country_code: str = "US") -> dict:
    """Register a fresh advertiser account (PENDING_VERIFICATION)."""
    resp = api_client.create_advertiser_account(
        create_account_payload(business_name=business_name, country_code=country_code),
        TEST_USERS["anonymous_headers"],
    )
    return get_success_data(resp)


def submit_identity_verification(account: dict, **overrides) -> dict:
    """Submit an identity verification for the account (OCC-guarded on account version)."""
    headers = make_advertiser_headers(account["id"])
    payload = create_identity_verification_payload(account["version"], **overrides)
    resp = api_client.create_identity_verification(account["id"], payload, headers)
    return get_success_data(resp)


def approve_verification(verification_id: str) -> dict:
    resp = api_client.decide_identity_verification(
        verification_id, decide_verification_payload("APPROVED"), TEST_USERS["platform_admin_headers"]
    )
    return get_success_data(resp)


def reject_verification(verification_id: str, reason: str = "document invalid") -> dict:
    resp = api_client.decide_identity_verification(
        verification_id,
        decide_verification_payload("REJECTED", rejection_reason=reason),
        TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(resp)


def create_verified_account(
    business_name: str = "Verified Corp",
    with_billing_profile: bool = True,
    payment_method_type: str = "CARD",
) -> dict:
    """Create an account, submit + approve identity verification -> ACTIVE.

    Returns dict: {"account", "billing_profile"} (billing_profile may be None).
    The returned account dict is re-read after approval, so its status/version
    are current.
    """
    account = create_account(business_name)
    ver = submit_identity_verification(account)
    approve_verification(ver["id"])
    account = get_success_data(
        api_client.get_advertiser_account(account["id"], make_advertiser_headers(account["id"]))
    )
    profile = None
    if with_billing_profile:
        profile = create_billing_profile(account, payment_method_type=payment_method_type)
    return {"account": account, "billing_profile": profile}


def create_billing_profile(account: dict, payment_method_type: str = "CARD") -> dict:
    headers = make_advertiser_headers(account["id"])
    resp = api_client.create_billing_profile(
        account["id"], create_billing_profile_payload(payment_method_type=payment_method_type), headers
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: campaign state progression
# ---------------------------------------------------------------------------

def create_campaign(
    account: dict,
    name: str = "Campaign",
    daily_budget_cents: int = 1000,
    start_date: str = TEST_DEFAULTS["DEFAULT_DATE"],
    end_date: str = TEST_DEFAULTS["DEFAULT_END_DATE"],
) -> dict:
    headers = make_advertiser_headers(account["id"])
    resp = api_client.create_campaign(
        create_campaign_payload(
            account["id"],
            name=name,
            daily_budget_cents=daily_budget_cents,
            start_date=start_date,
            end_date=end_date,
        ),
        headers,
    )
    return get_success_data(resp)


def activate_campaign(campaign_id: str, account: dict) -> dict:
    resp = api_client.activate_campaign(campaign_id, make_advertiser_headers(account["id"]))
    return get_success_data(resp)


def create_and_activate_campaign(account: dict, **kwargs) -> dict:
    campaign = create_campaign(account, **kwargs)
    return activate_campaign(campaign["id"], account)


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy (campaign -> ad group -> ad -> keyword)
# ---------------------------------------------------------------------------

def create_ad_group(campaign: dict, account: dict, name: str = "AG") -> dict:
    headers = make_advertiser_headers(account["id"])
    resp = api_client.create_ad_group(campaign["id"], create_ad_group_payload(name=name), headers)
    return get_success_data(resp)


def create_ad(
    ad_group: dict,
    account: dict,
    headline: str,
    category: str = "GENERAL",
    restricted_category_certified: bool = False,
    quality_ectr_score: int = 5,
    quality_relevance_score: int = 5,
    quality_lp_score: int = 5,
    final_url: str = "https://example.com/lp",
) -> dict:
    headers = make_advertiser_headers(account["id"])
    payload = create_ad_payload(
        headline=headline,
        final_url=final_url,
        category=category,
        quality_ectr_score=quality_ectr_score,
        quality_relevance_score=quality_relevance_score,
        quality_lp_score=quality_lp_score,
    )
    if restricted_category_certified:
        payload["restricted_category_certified"] = True
    resp = api_client.create_ad(ad_group["id"], payload, headers)
    return get_success_data(resp)


def create_keyword(
    ad_group: dict,
    account: dict,
    text: str,
    match_type: str = "EXACT",
    max_cpc_cents: int = 200,
    is_negative: bool = False,
) -> dict:
    headers = make_advertiser_headers(account["id"])
    payload = {"text": text, "match_type": match_type}
    if is_negative:
        payload["is_negative"] = True
    else:
        payload["max_cpc_cents"] = max_cpc_cents
    resp = api_client.create_keyword(ad_group["id"], payload, headers)
    return get_success_data(resp)


def submit_ad_review(ad_id: str, account: dict) -> dict:
    resp = api_client.submit_ad_review(ad_id, make_advertiser_headers(account["id"]))
    return get_success_data(resp)


def create_eligible_general_ad(
    ad_group: dict,
    account: dict,
    headline: str,
    quality_ectr_score: int = 5,
    quality_relevance_score: int = 5,
    quality_lp_score: int = 5,
    final_url: str = "https://example.com/lp",
) -> dict:
    """GENERAL ad submitted for review -> auto-approved -> ELIGIBLE. Returns the ad (re-read)."""
    headers = make_advertiser_headers(account["id"])
    ad = create_ad(
        ad_group,
        account,
        headline=headline,
        category="GENERAL",
        quality_ectr_score=quality_ectr_score,
        quality_relevance_score=quality_relevance_score,
        quality_lp_score=quality_lp_score,
        final_url=final_url,
    )
    submit_ad_review(ad["id"], account)
    return get_success_data(api_client.get_ad(ad["id"], headers))


# ---------------------------------------------------------------------------
# Tier 3: full auction scenario (winner + runner-up pair, or solo ad)
# ---------------------------------------------------------------------------

def setup_auction_pair(
    keyword_text: str,
    winner_bid: int,
    runner_bid: int,
    daily_budget_cents: int = 100000,
    business_name: str = "Auction Corp",
    winner_quality: tuple = (10, 10, 10),
    runner_quality: tuple = (10, 10, 10),
    payment_method_type: str = "CARD",
    start_date: str = TEST_DEFAULTS["DEFAULT_DATE"],
    end_date: str = TEST_DEFAULTS["DEFAULT_END_DATE"],
) -> dict:
    """Verified ACTIVE account with billing profile, ACTIVE campaign, two ad groups
    each holding one ELIGIBLE GENERAL ad and one EXACT keyword on the same text.

    Winner bid > runner bid at equal quality guarantees the winner's ad_rank is
    higher. Returns dict of all pieces.
    """
    ctx = create_verified_account(business_name, payment_method_type=payment_method_type)
    account, profile = ctx["account"], ctx["billing_profile"]
    campaign = create_and_activate_campaign(
        account, name="CAMP", daily_budget_cents=daily_budget_cents,
        start_date=start_date, end_date=end_date,
    )
    gw = create_ad_group(campaign, account, name="GW")
    gr = create_ad_group(campaign, account, name="GR")
    ad_w = create_eligible_general_ad(
        gw, account, headline="W Ad", quality_ectr_score=winner_quality[0],
        quality_relevance_score=winner_quality[1], quality_lp_score=winner_quality[2],
        final_url="https://example.com/w",
    )
    ad_r = create_eligible_general_ad(
        gr, account, headline="R Ad", quality_ectr_score=runner_quality[0],
        quality_relevance_score=runner_quality[1], quality_lp_score=runner_quality[2],
        final_url="https://example.com/r",
    )
    create_keyword(gw, account, keyword_text, max_cpc_cents=winner_bid)
    create_keyword(gr, account, keyword_text, max_cpc_cents=runner_bid)
    return {
        "account": account,
        "billing_profile": profile,
        "campaign": campaign,
        "ad_group_w": gw,
        "ad_group_r": gr,
        "ad_w": ad_w,
        "ad_r": ad_r,
        "keyword_text": keyword_text,
    }


def setup_solo_auction_ad(
    keyword_text: str,
    bid: int,
    daily_budget_cents: int = 10000,
    business_name: str = "Solo Corp",
    quality: tuple = (8, 7, 6),
) -> dict:
    """Verified ACTIVE account with one ELIGIBLE GENERAL ad and one EXACT keyword."""
    ctx = create_verified_account(business_name)
    account, profile = ctx["account"], ctx["billing_profile"]
    campaign = create_and_activate_campaign(
        account, name="CAMP", daily_budget_cents=daily_budget_cents
    )
    ag = create_ad_group(campaign, account, name="AG")
    ad = create_eligible_general_ad(
        ag, account, headline="Solo Ad", quality_ectr_score=quality[0],
        quality_relevance_score=quality[1], quality_lp_score=quality[2],
    )
    create_keyword(ag, account, keyword_text, max_cpc_cents=bid)
    return {
        "account": account,
        "billing_profile": profile,
        "campaign": campaign,
        "ad_group": ag,
        "ad": ad,
        "keyword_text": keyword_text,
    }


# ---------------------------------------------------------------------------
# Tier 4: accumulation / fiscal helpers
# ---------------------------------------------------------------------------

def run_clicked_auction(query_text: str) -> dict:
    resp = api_client.run_auction(
        {"query_text": query_text, "clicked": True}, TEST_USERS["platform_admin_headers"]
    )
    return get_success_data(resp)


def run_n_clicked_auctions(query_text: str, n: int):
    for _ in range(n):
        run_clicked_auction(query_text)


def close_month(billing_profile: dict, month: str) -> dict:
    resp = api_client.close_month(
        billing_profile["id"], {"month": month}, TEST_USERS["billing_admin_headers"]
    )
    return get_success_data(resp)


def list_invoices(billing_profile: dict) -> list:
    resp = api_client.list_invoices(billing_profile["id"], TEST_USERS["billing_admin_headers"])
    return get_success_data(resp)


def list_daily_spend_records(campaign: dict, account: dict) -> list:
    resp = api_client.list_daily_spend_records(
        campaign["id"], make_advertiser_headers(account["id"])
    )
    return get_success_data(resp)


def refresh_account(account: dict) -> dict:
    return get_success_data(
        api_client.get_advertiser_account(account["id"], TEST_USERS["platform_admin_headers"])
    )


def refresh_campaign(campaign: dict, account: dict) -> dict:
    return get_success_data(
        api_client.get_campaign(campaign["id"], make_advertiser_headers(account["id"]))
    )


def refresh_billing_profile(billing_profile: dict) -> dict:
    return get_success_data(
        api_client.get_billing_profile(billing_profile["id"], TEST_USERS["billing_admin_headers"])
    )


# ---------------------------------------------------------------------------
# Tier 5: suspension / appeal lifecycle shortcuts
# ---------------------------------------------------------------------------

def suspend_account(account: dict, reason_code: str = "POLICY_VIOLATION") -> dict:
    resp = api_client.suspend_advertiser_account(
        account["id"], {"reason_code": reason_code}, TEST_USERS["platform_admin_headers"]
    )
    return get_success_data(resp)


def file_appeal(account: dict, argument_text: str = "appeal") -> dict:
    resp = api_client.create_appeal(
        account["id"], {"argument_text": argument_text}, make_advertiser_headers(account["id"])
    )
    return get_success_data(resp)


def decide_appeal(appeal_id: str, outcome: str, reviewer_note: str = None) -> dict:
    payload = {"outcome": outcome}
    if reviewer_note is not None:
        payload["reviewer_note"] = reviewer_note
    resp = api_client.decide_appeal(appeal_id, payload, TEST_USERS["platform_admin_headers"])
    return get_success_data(resp)


def setup_suspended_account(business_name: str = "Susp Corp", with_campaign: bool = True) -> dict:
    """Verified ACTIVE account (optionally with one ACTIVE campaign), then suspended."""
    ctx = create_verified_account(business_name)
    account = ctx["account"]
    campaign = None
    if with_campaign:
        campaign = create_and_activate_campaign(account, name="C1", daily_budget_cents=1000)
    suspend_account(account)
    account = refresh_account(account)
    return {"account": account, "campaign": campaign, "billing_profile": ctx["billing_profile"]}
