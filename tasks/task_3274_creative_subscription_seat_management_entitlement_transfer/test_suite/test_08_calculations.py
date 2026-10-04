"""Calculation corner tests (breadth queue B, calculations section)."""
import pytest

from test_helpers import (
    ApiErrorId,
    SYS,
    bootstrap_org_and_admin,
    create_org,
    create_admin,
    create_plan,
    create_product_version,
    create_active_subscription,
    create_end_user,
    create_add_on,
    mint_seat_for_active_subscription,
    assign_seat,
    create_asset,
    list_seat_entitlements,
    get_organization,
    get_end_user,
    validate_success,
    validate_error,
    validate_paginated,
    make_org_admin_headers,
)


def test_org_storage_pool_aggregation_correct(api):
    """PRD: "each add-on contributes its `quota_total` directly, since each
    cloud-services quota unit is exactly 1 GB." and PRD: "each subscription
    contributes `seats_assigned` multiplied by its plan's
    `storage_gb_per_seat`"

    1 assigned seat x 100 GB + 500-unit CLOUD_SERVICES add-on = 600 GB.

    Design: Corner/calculations/org_storage_pool_aggregation_correct
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="CL1", org_type="ENTERPRISE", primary_admin_id=ba0["id"])
    admin = create_admin(org["id"], email="oa@cl1.com", full_name="Org Admin")
    headers = make_org_admin_headers(admin["id"])
    plan = create_plan(code="PC1", segment="ENTERPRISE", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=100)
    create_product_version(plan["id"])
    sub = create_active_subscription(org["id"], plan["id"], seats_purchased=1)
    seat = mint_seat_for_active_subscription(sub)
    user = create_end_user(org["id"], headers, email="u@cl1.com")
    assign_seat(seat["id"], user["id"], headers)
    create_add_on(sub["id"], headers, kind="CLOUD_SERVICES", quota_total=500,
                  overage_unit_price_cents=10)
    org_after = get_organization(org["id"])
    assert org_after["storage_pool_gb"] == 600, (
        f"Expected storage_pool_gb 600, got {org_after['storage_pool_gb']}")


def test_user_storage_used_sum_then_ceil(api):
    """PRD: "the megabyte sizes of their assets in `ACTIVE` or `IN_TRANSFER`
    status are summed first, and the single total is then converted to
    gigabytes with a ceiling at 1024 MB per GB."

    Two 1200 MB assets: ceil(2400/1024) = 3 GB (per-line rounding would give
    ceil(1200/1024) + ceil(1200/1024) = 2 + 2 = 4).

    Design: Corner/calculations/user_storage_used_sum_then_ceil
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="CL2", org_type="TEAM", primary_admin_id=ba0["id"])
    admin = create_admin(org["id"], email="oa@cl2.com", full_name="Org Admin")
    headers = make_org_admin_headers(admin["id"])
    user = create_end_user(org["id"], headers, email="u@cl2.com")
    create_asset(user["id"], headers, title="A1", size_mb=1200)
    create_asset(user["id"], headers, title="A2", size_mb=1200)
    user_after = get_end_user(user["id"])
    assert user_after["storage_used_gb"] == 3, (
        f"Sum-then-ceil of 2400 MB must give 3 GB, got "
        f"{user_after['storage_used_gb']}")


def test_addon_overage_waterfall(api):
    """PRD: "`quota_used` is the smaller of the cumulative consumed units and
    `quota_total`; the overage units are the excess of cumulative consumption
    over `quota_total`, or zero when there is no excess" and "When consumption
    pushes `quota_used` to reach `quota_total`, the metering sweep flips the
    add-on `ACTIVE → EXHAUSTED`"

    Quota 100; consume 60 then 50: quota_used caps at 100, status EXHAUSTED.

    Design: Corner/calculations/addon_overage_waterfall
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="CL3", org_type="TEAM", primary_admin_id=ba0["id"])
    admin = create_admin(org["id"], email="oa@cl3.com", full_name="Org Admin")
    headers = make_org_admin_headers(admin["id"])
    plan = create_plan(code="PXCL3", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20)
    create_product_version(plan["id"])
    sub = create_active_subscription(org["id"], plan["id"], seats_purchased=1)
    addon = create_add_on(sub["id"], headers, kind="STOCK_CREDITS",
                          quota_total=100, overage_unit_price_cents=300)
    validate_success(
        api.consume_add_on_service(addon["id"], {"units": 60}, headers))
    resp = api.consume_add_on_service(addon["id"], {"units": 50}, headers)
    data = validate_success(resp)
    assert data["quota_used"] == 100, (
        f"quota_used must cap at quota_total 100, got {data['quota_used']}")
    assert data["status"] == "EXHAUSTED", (
        f"Add-on must be EXHAUSTED once quota is consumed, got "
        f"{data['status']}")


def test_default_product_version_tie_break(api):
    """PRD: "among the plan's versions whose `availability` is `AVAILABLE`,
    the default is the one with the greatest `release_date`; ties are broken
    by earlier `created_at`. This default is consulted both when a seat
    assignment creates a fresh entitlement"

    PV1 (release 2026-01) and PV2 (release 2026-06) both AVAILABLE: the
    entitlement created at assignment points to PV2.

    Design: Corner/calculations/default_product_version_tie_break
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="CL4", org_type="TEAM", primary_admin_id=ba0["id"])
    admin = create_admin(org["id"], email="oa@cl4.com", full_name="Org Admin")
    headers = make_org_admin_headers(admin["id"])
    plan = create_plan(code="PC4", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20)
    create_product_version(plan["id"], version_label="2026.1",
                           release_date="2026-01-15T00:00:00Z")
    pv2 = create_product_version(plan["id"], version_label="2026.2",
                                 release_date="2026-06-15T00:00:00Z")
    sub = create_active_subscription(org["id"], plan["id"], seats_purchased=1)
    seat = mint_seat_for_active_subscription(sub)
    user = create_end_user(org["id"], headers, email="u@cl4.com")
    assign_seat(seat["id"], user["id"], headers)
    entitlements = list_seat_entitlements(seat["id"])
    assert len(entitlements) >= 1
    assert entitlements[0]["product_version_id"] == pv2["id"], (
        f"Default version must be the AVAILABLE version with the greatest "
        f"release_date; got {entitlements[0]['product_version_id']}")
