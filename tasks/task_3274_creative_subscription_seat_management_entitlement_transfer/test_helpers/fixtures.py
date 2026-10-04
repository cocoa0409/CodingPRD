"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints: each test runs against a freshly restarted server with an empty
database, so nothing is carried over.

Bootstrap pattern: an Organization requires a primary_admin_id, but Admin
creation requires an org_id. The bootstrap org B0 is created with the
placeholder UUID as primary_admin_id, then a real admin BA0 is created inside
B0; downstream orgs use BA0's id as their primary_admin_id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    BOOTSTRAP_ADMIN_PLACEHOLDER,
    create_organization_payload,
    create_admin_payload,
    create_end_user_payload,
    create_reseller_payload,
    create_plan_payload,
    create_product_version_payload,
    create_subscription_payload,
    create_device_payload,
    create_asset_payload,
    create_transfer_request_payload,
    create_cancellation_request_payload,
    create_add_on_service_payload,
    create_compliance_audit_payload,
)
from .test_users import (
    TEST_USERS,
    make_org_admin_headers,
    make_deployment_admin_headers,
    make_reseller_agent_headers,
    make_end_user_headers,
)

SYS = TEST_USERS["system_admin_headers"]


def bootstrap_org_and_admin():
    """Create bootstrap org B0 (placeholder primary_admin_id) and admin BA0.

    Returns (b0, ba0).
    """
    resp = api_client.create_organization(
        create_organization_payload(name="B0", org_type="INDIVIDUAL",
                                    primary_admin_id=BOOTSTRAP_ADMIN_PLACEHOLDER),
        SYS)
    b0 = get_success_data(resp)
    resp = api_client.create_admin(
        create_admin_payload(email="ba0@b0.com", full_name="Boot",
                             admin_kind="SYSTEM_ADMIN", org_id=b0["id"]),
        SYS)
    ba0 = get_success_data(resp)
    return b0, ba0


def create_org(name="Org", org_type="TEAM", primary_admin_id=None):
    """Create an organization. Returns the Organization dict."""
    resp = api_client.create_organization(
        create_organization_payload(name=name, org_type=org_type,
                                    primary_admin_id=primary_admin_id
                                    or BOOTSTRAP_ADMIN_PLACEHOLDER),
        SYS)
    return get_success_data(resp)


def create_admin(org_id, email="admin@org.com", full_name="Admin",
                 admin_kind="SYSTEM_ADMIN"):
    """Create an admin in an org. Returns the Admin dict."""
    resp = api_client.create_admin(
        create_admin_payload(email=email, full_name=full_name,
                             admin_kind=admin_kind, org_id=org_id),
        SYS)
    return get_success_data(resp)


def create_org_with_admin(name="Org", org_type="TEAM", admin_kind="SYSTEM_ADMIN",
                          admin_email="oa@org.com"):
    """Bootstrap + one real org + one admin inside it.

    Returns dict with keys: b0, ba0, org, admin, admin_headers.
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name=name, org_type=org_type, primary_admin_id=ba0["id"])
    admin = create_admin(org["id"], email=admin_email, admin_kind=admin_kind)
    return {
        "b0": b0,
        "ba0": ba0,
        "org": org,
        "admin": admin,
        "admin_headers": make_org_admin_headers(admin["id"]),
    }


def create_plan(code="P", segment="TEAM", billing_model="MONTHLY",
                monthly_price_cents=3000, annual_monthly_price_cents=3000,
                storage_gb_per_seat=20, seat_limit=-1,
                deployment_modes=None, allows_offline_activation=False,
                max_devices_per_seat=2, cancellation_window_days=14,
                etf_rate_pct=0, **extra):
    """Create a plan. Returns the Plan dict."""
    payload = create_plan_payload(
        code=code, segment=segment, billing_model=billing_model,
        monthly_price_cents=monthly_price_cents,
        annual_monthly_price_cents=annual_monthly_price_cents,
        storage_gb_per_seat=storage_gb_per_seat, seat_limit=seat_limit,
        deployment_modes=deployment_modes or ["NAMED_USER"],
        allows_offline_activation=allows_offline_activation,
        max_devices_per_seat=max_devices_per_seat,
        cancellation_window_days=cancellation_window_days,
        etf_rate_pct=etf_rate_pct, **extra)
    resp = api_client.create_plan(payload, SYS)
    return get_success_data(resp)


def create_product_version(plan_id, version_label="2026.1",
                           release_date="2026-01-15T00:00:00Z"):
    """Create an AVAILABLE product version. Returns the ProductVersion dict."""
    resp = api_client.create_product_version(
        create_product_version_payload(plan_id=plan_id, version_label=version_label,
                                       release_date=release_date),
        SYS)
    return get_success_data(resp)


def create_reseller(name="R", region="NA", tier="GOLD"):
    """Create an ACTIVE reseller. Returns the Reseller dict."""
    resp = api_client.create_reseller(
        create_reseller_payload(name=name, region=region, tier=tier), SYS)
    return get_success_data(resp)


def create_subscription(org_id, plan_id, seats_purchased=1, reseller_id=None):
    """Create a PENDING_PAYMENT subscription. Returns the Subscription dict."""
    payload = create_subscription_payload(org_id=org_id, plan_id=plan_id,
                                          seats_purchased=seats_purchased)
    if reseller_id is not None:
        payload["reseller_id"] = reseller_id
    resp = api_client.create_subscription(payload, SYS)
    return get_success_data(resp)


def activate_subscription(subscription_id):
    """Activate a PENDING_PAYMENT subscription. Returns the ACTIVE Subscription."""
    resp = api_client.activate_subscription(subscription_id, SYS)
    return get_success_data(resp)


def create_active_subscription(org_id, plan_id, seats_purchased=1, reseller_id=None):
    """Create + activate a subscription. Returns the ACTIVE Subscription dict."""
    sub = create_subscription(org_id, plan_id, seats_purchased, reseller_id)
    return activate_subscription(sub["id"])


def mint_seat(subscription_id, expected_subscription_version):
    """Mint one extra seat against a subscription (OCC-guarded). Returns the Seat."""
    resp = api_client.create_seat(
        {"subscription_id": subscription_id,
         "expected_subscription_version": expected_subscription_version},
        SYS)
    return get_success_data(resp)


def mint_seat_for_active_subscription(subscription):
    """Mint a seat using the subscription's current version. Returns the Seat."""
    return mint_seat(subscription["id"], subscription["version"])


def create_end_user(org_id, admin_headers, email="user@org.com",
                    full_name="User"):
    """Create an ACTIVE end user in an org. Returns the EndUser dict."""
    resp = api_client.create_end_user(
        create_end_user_payload(email=email, full_name=full_name, org_id=org_id),
        admin_headers)
    return get_success_data(resp)


def create_device(end_user_id, fingerprint="fp-1", label="Laptop", headers=None):
    """Register a device for an end user (EndUser identity by default)."""
    if headers is None:
        headers = make_end_user_headers(end_user_id)
    resp = api_client.create_device(
        create_device_payload(end_user_id=end_user_id,
                              device_fingerprint=fingerprint, label=label),
        headers)
    return get_success_data(resp)


def assign_seat(seat_id, end_user_id, admin_headers):
    """Assign an UNASSIGNED or RECLAIMED seat. Returns the ASSIGNED Seat."""
    resp = api_client.assign_seat(seat_id, {"end_user_id": end_user_id},
                                  admin_headers)
    return get_success_data(resp)


def list_seat_entitlements(seat_id, params=None):
    """List entitlements for a seat. Returns the data list."""
    query = {"seat_id": seat_id}
    if params:
        query.update(params)
    resp = api_client.list_entitlements(SYS, params=query)
    body = resp.json()
    return body.get("data", [])


def get_entitlement(entitlement_id):
    resp = api_client.get_entitlement(entitlement_id, SYS)
    return get_success_data(resp)


def get_seat(seat_id):
    resp = api_client.get_seat(seat_id, SYS)
    return get_success_data(resp)


def get_subscription(subscription_id):
    resp = api_client.get_subscription(subscription_id, SYS)
    return get_success_data(resp)


def get_organization(org_id):
    resp = api_client.get_organization(org_id, SYS)
    return get_success_data(resp)


def get_end_user(user_id):
    resp = api_client.get_end_user(user_id, SYS)
    return get_success_data(resp)


def get_asset(asset_id):
    resp = api_client.get_asset(asset_id, SYS)
    return get_success_data(resp)


def get_product_version(version_id):
    resp = api_client.get_product_version(version_id, SYS)
    return get_success_data(resp)


def set_clock(to_iso8601):
    """Advance the logical clock (runs pending sweeps). Returns response data."""
    resp = api_client.set_clock(to_iso8601, SYS)
    return get_success_data(resp)


def setup_org_with_active_subscription(org_name="Org", seats_purchased=1,
                                       plan_overrides=None, reseller=None):
    """Org + admin + plan + AVAILABLE version + ACTIVE subscription.

    Returns dict: org, admin, admin_headers, plan, subscription.
    """
    ctx = create_org_with_admin(name=org_name)
    plan = create_plan(code=f"{org_name}-PLAN", **(plan_overrides or {}))
    create_product_version(plan["id"])
    sub = create_active_subscription(ctx["org"]["id"], plan["id"],
                                     seats_purchased=seats_purchased,
                                     reseller_id=reseller["id"] if reseller else None)
    ctx.update({"plan": plan, "subscription": sub})
    return ctx


def setup_assigned_seat(org_name="Org", seats_purchased=1, plan_overrides=None,
                        user_email="u@org.com"):
    """ACTIVE subscription + one minted seat ASSIGNED to a fresh ACTIVE user.

    Returns dict: org, admin, admin_headers, plan, subscription, seat, user.
    """
    ctx = setup_org_with_active_subscription(
        org_name=org_name, seats_purchased=seats_purchased,
        plan_overrides=plan_overrides)
    seat = mint_seat_for_active_subscription(ctx["subscription"])
    user = create_end_user(ctx["org"]["id"], ctx["admin_headers"],
                           email=user_email)
    seat = assign_seat(seat["id"], user["id"], ctx["admin_headers"])
    ctx.update({"seat": seat, "user": user})
    return ctx


def setup_activated_entitlement(org_name="Org", plan_overrides=None):
    """Assigned seat + device + entitlement activated on the device.

    Returns dict with seat, user, device, entitlement added to the base ctx.
    """
    ctx = setup_assigned_seat(org_name=org_name, plan_overrides=plan_overrides)
    device = create_device(ctx["user"]["id"], fingerprint=f"fp-{org_name}",
                           label="Laptop")
    entitlements = list_seat_entitlements(ctx["seat"]["id"])
    entitlement = entitlements[0]
    resp = api_client.activate_entitlement(
        entitlement["id"], {"device_id": device["id"]},
        make_end_user_headers(ctx["user"]["id"]))
    entitlement = get_success_data(resp)
    ctx.update({"device": device, "entitlement": entitlement})
    return ctx


def reclaim_assigned_seat(ctx):
    """Begin reclaim on ctx's seat. Returns the PENDING_RECLAIM Seat."""
    resp = api_client.reclaim_seat(ctx["seat"]["id"], ctx["admin_headers"])
    return get_success_data(resp)


def finalize_reclaim(seat_id, admin_headers):
    resp = api_client.finalize_reclaim_seat(seat_id, admin_headers)
    return get_success_data(resp)


def get_transfer_request(tr_id):
    resp = api_client.get_transfer_request(tr_id, SYS)
    return get_success_data(resp)


def create_transfer_request(ctx, to_user_id, requester_admin_id, requester_headers):
    """Create a transfer request for ctx's seat using its current version.

    Returns the TransferRequest dict.
    """
    seat = get_seat(ctx["seat"]["id"])
    resp = api_client.create_transfer_request(
        create_transfer_request_payload(
            org_id=ctx["org"]["id"], seat_id=seat["id"], to_user_id=to_user_id,
            requested_by_admin_id=requester_admin_id,
            expected_seat_version=seat["version"]),
        requester_headers)
    return get_success_data(resp)


def create_cancellation_request(subscription_id, requester_admin_id, admin_headers):
    """Open a PENDING cancellation request. Returns the CancellationRequest."""
    resp = api_client.create_cancellation_request(
        create_cancellation_request_payload(
            subscription_id=subscription_id,
            requested_by_admin_id=requester_admin_id),
        admin_headers)
    return get_success_data(resp)


def create_asset(owner_user_id, admin_headers, title="Asset", size_mb=100):
    resp = api_client.create_asset(
        create_asset_payload(owner_user_id=owner_user_id, title=title,
                             size_mb=size_mb),
        admin_headers)
    return get_success_data(resp)


def create_add_on(subscription_id, admin_headers, kind="STOCK_CREDITS",
                  quota_total=100, overage_unit_price_cents=0):
    resp = api_client.create_add_on_service(
        create_add_on_service_payload(
            subscription_id=subscription_id, kind=kind, quota_total=quota_total,
            overage_unit_price_cents=overage_unit_price_cents),
        admin_headers)
    return get_success_data(resp)


def open_audit(org_id, opened_by_admin_id):
    resp = api_client.create_compliance_audit(
        create_compliance_audit_payload(org_id=org_id,
                                        opened_by_admin_id=opened_by_admin_id),
        SYS)
    return get_success_data(resp)
