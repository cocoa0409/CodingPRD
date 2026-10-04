"""Composite setup helpers.

Every fixture builds its preconditions from scratch via PRD-declared
endpoints (the harness restarts the server with an empty database before
each test). Setup calls use the lenient get_success_data() so failures
surface as clear "Setup failed" messages.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_billing_account_payload,
    create_migration_payload,
    create_plan_payload,
    create_retention_offer_payload,
    create_service_profile_payload,
    create_subscriber_account_payload,
    create_subscription_payload,
)
from .test_users import TEST_USERS, make_subscriber_headers

ADMIN = TEST_USERS["platform_admin_headers"]
SUPPORT = TEST_USERS["support_headers"]
DISTRIBUTOR = TEST_USERS["distributor_ops_headers"]
ANON = TEST_USERS["anonymous_headers"]


def set_clock(to_iso8601):
    """Advance the logical clock (PlatformAdmin only)."""
    resp = api_client.set_clock(to_iso8601, ADMIN)
    assert resp.status_code == 200, f"Setup failed (set_clock {to_iso8601}): {resp.text}"
    return get_success_data(resp)


def reset_clock_to_default():
    return set_clock("2026-09-01T00:00:00Z")


def create_plan(**kwargs):
    resp = api_client.create_plan(create_plan_payload(**kwargs), ADMIN)
    assert resp.status_code == 201, f"Setup failed (create_plan {kwargs}): {resp.text}"
    return get_success_data(resp)


def create_standalone_plan(
    plan_code="DPLUS_ADS", service="DPLUS", price=799, ad_tier="AD_SUPPORTED", **kw
):
    return create_plan(
        plan_code=plan_code,
        plan_kind="STANDALONE",
        service_scope=[service],
        ad_tier=ad_tier,
        monthly_price_cents=price,
        **kw,
    )


def create_bundle_plan(
    plan_code="DUO_PREMIUM",
    price=1999,
    ad_tier="AD_FREE",
    weights=None,
    **kw,
):
    return create_plan(
        plan_code=plan_code,
        plan_kind="BUNDLE",
        service_scope=["DPLUS", "HULU"],
        ad_tier=ad_tier,
        monthly_price_cents=price,
        component_weights=weights or {"DPLUS": 0.45, "HULU": 0.55},
        **kw,
    )


def create_retention_offer(**kwargs):
    resp = api_client.create_retention_offer(
        create_retention_offer_payload(**kwargs), ADMIN
    )
    assert resp.status_code == 201, (
        f"Setup failed (create_retention_offer {kwargs}): {resp.text}"
    )
    return get_success_data(resp)


def register_account(email=None, full_name=None):
    resp = api_client.create_subscriber_account(
        create_subscriber_account_payload(email=email, full_name=full_name), ANON
    )
    assert resp.status_code == 201, f"Setup failed (register_account): {resp.text}"
    return get_success_data(resp)


def sub_headers(account):
    """Ownership-correct Subscriber headers for the given account."""
    return make_subscriber_headers(account["id"])


def create_billing_account(account, biller_type="PLATFORM", biller_reference="platform",
                           headers=None):
    hdrs = headers or sub_headers(account)
    resp = api_client.create_billing_account(
        account["id"],
        create_billing_account_payload(
            biller_type=biller_type, biller_reference=biller_reference
        ),
        hdrs,
    )
    assert resp.status_code == 201, f"Setup failed (create_billing_account): {resp.text}"
    return get_success_data(resp)


def create_profile(account, service="DPLUS", **kwargs):
    resp = api_client.create_service_profile(
        account["id"],
        create_service_profile_payload(service=service, **kwargs),
        sub_headers(account),
    )
    assert resp.status_code == 201, f"Setup failed (create_profile {service}): {resp.text}"
    return get_success_data(resp)


def purchase_subscription(account, billing_account, plan_code,
                          dplus_profile=None, hulu_profile=None, headers=None):
    hdrs = headers or sub_headers(account)
    resp = api_client.create_subscription(
        create_subscription_payload(
            subscriber_account_id=account["id"],
            billing_account_id=billing_account["id"],
            plan_code=plan_code,
            dplus_service_profile_id=dplus_profile["id"] if dplus_profile else None,
            hulu_service_profile_id=hulu_profile["id"] if hulu_profile else None,
        ),
        hdrs,
    )
    assert resp.status_code == 201, (
        f"Setup failed (purchase_subscription {plan_code}): {resp.text}"
    )
    return get_success_data(resp)


def list_subscription_entitlements(subscription_id, headers):
    resp = api_client.list_subscription_entitlements(subscription_id, headers)
    assert resp.status_code == 200, f"Setup failed (list entitlements): {resp.text}"
    return get_success_data(resp)


def get_subscription(subscription_id, headers):
    resp = api_client.get_subscription(subscription_id, headers)
    assert resp.status_code == 200, f"Setup failed (get subscription): {resp.text}"
    return get_success_data(resp)


def get_account(account_id, headers=None):
    resp = api_client.get_subscriber_account(account_id, headers or ADMIN)
    assert resp.status_code == 200, f"Setup failed (get account): {resp.text}"
    return get_success_data(resp)


def get_billing_account(billing_account_id, headers=None):
    resp = api_client.get_billing_account(billing_account_id, headers or ADMIN)
    assert resp.status_code == 200, f"Setup failed (get billing account): {resp.text}"
    return get_success_data(resp)


def get_profile(profile_id, headers=None):
    resp = api_client.get_service_profile(profile_id, headers or ADMIN)
    assert resp.status_code == 200, f"Setup failed (get profile): {resp.text}"
    return get_success_data(resp)


def list_billing_invoices(billing_account_id, headers):
    resp = api_client.list_billing_account_invoices(billing_account_id, headers)
    assert resp.status_code == 200, f"Setup failed (list invoices): {resp.text}"
    return get_success_data(resp)


def run_renewal(billing_account_id, outcome):
    resp = api_client.run_renewal(
        {"billing_account_id": billing_account_id, "outcome": outcome}, ADMIN
    )
    assert resp.status_code == 200, (
        f"Setup failed (run_renewal {outcome}): {resp.text}"
    )
    return get_success_data(resp)


def redeem_offer(subscription_id, offer_code, headers):
    resp = api_client.redeem_retention_offer(
        subscription_id, {"offer_code": offer_code}, headers
    )
    assert resp.status_code == 201, f"Setup failed (redeem {offer_code}): {resp.text}"
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: full subscriber scenario (account + billing + profiles)
# ---------------------------------------------------------------------------


def setup_account_with_billing(biller_type="PLATFORM", email=None):
    """Account + one billing account. Returns (account, billing_account, hdrs)."""
    account = register_account(email=email)
    billing = create_billing_account(account, biller_type=biller_type)
    return account, billing, sub_headers(account)


def setup_account_with_profiles(biller_type="PLATFORM", email=None,
                                services=("DPLUS", "HULU")):
    """Account + billing + one profile per requested service.

    Returns (account, billing, profiles, hdrs) where profiles is a dict keyed
    by service name.
    """
    account, billing, hdrs = setup_account_with_billing(biller_type, email=email)
    profiles = {svc: create_profile(account, service=svc) for svc in services}
    return account, billing, profiles, hdrs


def setup_active_standalone_subscription(
    plan_code="DPLUS_ADS",
    service="DPLUS",
    price=799,
    ad_tier="AD_SUPPORTED",
    biller_type="PLATFORM",
    email=None,
    start_clock="2026-09-01T00:00:00Z",
):
    """Plan + account + billing + profile + ACTIVE standalone subscription.

    Returns (account, billing, profile, subscription, hdrs).
    """
    set_clock(start_clock)
    create_standalone_plan(plan_code=plan_code, service=service, price=price,
                           ad_tier=ad_tier)
    account, billing, hdrs = setup_account_with_billing(biller_type, email=email)
    profile = create_profile(account, service=service)
    kwargs = {"dplus_profile": profile} if service == "DPLUS" else {"hulu_profile": profile}
    subscription = purchase_subscription(account, billing, plan_code, **kwargs)
    return account, billing, profile, subscription, hdrs


def setup_active_bundle_subscription(
    plan_code="DUO_ADS",
    price=1099,
    ad_tier="AD_SUPPORTED",
    weights=None,
    biller_type="PLATFORM",
    email=None,
    start_clock="2026-09-01T00:00:00Z",
):
    """Bundle plan + account + billing + both profiles + ACTIVE bundle.

    Returns (account, billing, profiles, subscription, hdrs).
    """
    set_clock(start_clock)
    create_bundle_plan(plan_code=plan_code, price=price, ad_tier=ad_tier,
                       weights=weights)
    account, billing, profiles, hdrs = setup_account_with_profiles(
        biller_type, email=email
    )
    subscription = purchase_subscription(
        account, billing, plan_code,
        dplus_profile=profiles["DPLUS"], hulu_profile=profiles["HULU"],
    )
    return account, billing, profiles, subscription, hdrs


def setup_migration_quote(
    target_plan_code="DUO_PREMIUM",
    quote_clock="2026-09-06T00:00:00Z",
    from_plan_code="DPLUS_ADS",
    from_price=799,
    biller_type="PLATFORM",
    email=None,
):
    """ACTIVE standalone + bundle plan + QUOTED migration at quote_clock.

    Returns (account, billing, profiles, from_subscription, migration, hdrs).
    """
    account, billing, profiles, from_sub, hdrs = _setup_standalone_with_both_profiles(
        plan_code=from_plan_code, price=from_price, biller_type=biller_type, email=email
    )
    create_bundle_plan(plan_code=target_plan_code)
    set_clock(quote_clock)
    resp = api_client.create_migration(
        create_migration_payload(from_sub["id"], target_plan_code), hdrs
    )
    assert resp.status_code == 201, f"Setup failed (migration quote): {resp.text}"
    migration = get_success_data(resp)
    return account, billing, profiles, from_sub, migration, hdrs


def _setup_standalone_with_both_profiles(plan_code="DPLUS_ADS", price=799,
                                         biller_type="PLATFORM", email=None):
    """Standalone DPLUS plan + account + billing + BOTH profiles + ACTIVE sub."""
    set_clock("2026-09-01T00:00:00Z")
    create_standalone_plan(plan_code=plan_code, service="DPLUS", price=price)
    account, billing, profiles, hdrs = setup_account_with_profiles(
        biller_type, email=email
    )
    subscription = purchase_subscription(
        account, billing, plan_code, dplus_profile=profiles["DPLUS"]
    )
    return account, billing, profiles, subscription, hdrs


def setup_failed_renewal(
    plan_code="DPLUS_ADS",
    price=799,
    email=None,
    renewal_clock="2026-10-01T00:00:00Z",
):
    """ACTIVE standalone whose first renewal is run with outcome FAILED.

    Returns (account, billing, profile, subscription, failed_invoice_id, hdrs).
    """
    account, billing, profile, subscription, hdrs = setup_active_standalone_subscription(
        plan_code=plan_code, price=price, email=email
    )
    set_clock(renewal_clock)
    result = run_renewal(billing["id"], "FAILED")
    return account, billing, profile, subscription, result["invoice_id"], hdrs


def list_entitlements_for_profile(profile_id, headers):
    """List all entitlements granted to a profile from any subscription."""
    resp = api_client.list_profile_entitlements(profile_id, headers)
    assert resp.status_code == 200, f"Setup failed (list profile entitlements): {resp.text}"
    return get_success_data(resp)
