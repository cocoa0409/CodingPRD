"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_plan_payload(
    plan_code=None,
    plan_kind="STANDALONE",
    service_scope=None,
    ad_tier="AD_SUPPORTED",
    monthly_price_cents=799,
    component_weights=None,
    allow_app_store_billing=True,
    allow_distributor_billing=True,
    **overrides,
) -> dict:
    if plan_code is None:
        plan_code = f"PLAN_{_seq()}"
    if service_scope is None:
        service_scope = ["DPLUS"]
    payload = {
        "plan_code": plan_code,
        "plan_kind": plan_kind,
        "service_scope": service_scope,
        "ad_tier": ad_tier,
        "monthly_price_cents": monthly_price_cents,
        "allow_app_store_billing": allow_app_store_billing,
        "allow_distributor_billing": allow_distributor_billing,
    }
    if component_weights is not None:
        payload["component_weights"] = component_weights
    payload.update(overrides)
    return payload


def create_subscriber_account_payload(email=None, full_name=None, **overrides) -> dict:
    n = _seq()
    payload = {
        "email": email or f"user{n}@example.com",
        "full_name": full_name or f"Test User {n}",
    }
    payload.update(overrides)
    return payload


def create_service_profile_payload(service="DPLUS", **overrides) -> dict:
    payload = {"service": service}
    payload.update(overrides)
    return payload


def create_billing_account_payload(
    biller_type="PLATFORM", biller_reference="platform", **overrides
) -> dict:
    payload = {
        "biller_type": biller_type,
        "biller_reference": biller_reference,
    }
    payload.update(overrides)
    return payload


def create_subscription_payload(
    subscriber_account_id,
    billing_account_id,
    plan_code,
    dplus_service_profile_id=None,
    hulu_service_profile_id=None,
    **overrides,
) -> dict:
    payload = {
        "subscriber_account_id": subscriber_account_id,
        "billing_account_id": billing_account_id,
        "plan_code": plan_code,
    }
    if dplus_service_profile_id is not None:
        payload["dplus_service_profile_id"] = dplus_service_profile_id
    if hulu_service_profile_id is not None:
        payload["hulu_service_profile_id"] = hulu_service_profile_id
    payload.update(overrides)
    return payload


def create_migration_payload(from_subscription_id, target_plan_code, **overrides) -> dict:
    payload = {
        "from_subscription_id": from_subscription_id,
        "target_plan_code": target_plan_code,
    }
    payload.update(overrides)
    return payload


def create_retention_offer_payload(
    offer_code=None,
    discount_cents=100,
    duration_months=1,
    max_redemptions_per_account=1,
    eligible_biller_types=None,
    eligible_plan_kinds=None,
    **overrides,
) -> dict:
    if offer_code is None:
        offer_code = f"OFFER_{_seq()}"
    if eligible_biller_types is None:
        eligible_biller_types = ["PLATFORM"]
    if eligible_plan_kinds is None:
        eligible_plan_kinds = ["STANDALONE"]
    payload = {
        "offer_code": offer_code,
        "discount_cents": discount_cents,
        "duration_months": duration_months,
        "max_redemptions_per_account": max_redemptions_per_account,
        "eligible_biller_types": eligible_biller_types,
        "eligible_plan_kinds": eligible_plan_kinds,
    }
    payload.update(overrides)
    return payload


def add_watchlist_item_payload(title_id=None, title_maturity="TV_G", **overrides) -> dict:
    payload = {
        "title_id": title_id or f"title-{_seq()}",
        "title_maturity": title_maturity,
    }
    payload.update(overrides)
    return payload
