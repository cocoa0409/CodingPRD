"""RBAC, cross-cutting complexity, and consistency corner tests (breadth
queue B, rbac / cross_cutting_complexity_layers / consistency_model)."""
import pytest

from test_helpers import (
    ApiErrorId,
    SYS,
    bootstrap_org_and_admin,
    create_org,
    create_admin,
    create_plan,
    create_product_version,
    create_reseller,
    create_active_subscription,
    create_end_user,
    create_device,
    create_reseller_order_payload,
    mint_seat_for_active_subscription,
    assign_seat,
    list_seat_entitlements,
    get_seat,
    get_product_version,
    set_clock,
    setup_assigned_seat,
    validate_success,
    validate_error,
    make_org_admin_headers,
    make_reseller_agent_headers,
    make_end_user_headers,
)


def test_enduser_cannot_assign_seat(api):
    """PRD: "A request whose role is not on the endpoint's authorized role list
    is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)." — seat assignment is an
    OrgAdmin-only action.

    Design: Corner/rbac/enduser_cannot_assign_seat
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="RB1", org_type="TEAM", primary_admin_id=ba0["id"])
    admin = create_admin(org["id"], email="oa@rb1.com", full_name="Org Admin")
    headers = make_org_admin_headers(admin["id"])
    plan = create_plan(code="PXRB1", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20)
    create_product_version(plan["id"])
    sub = create_active_subscription(org["id"], plan["id"], seats_purchased=1)
    seat = mint_seat_for_active_subscription(sub)
    user = create_end_user(org["id"], headers, email="u@rb1.com")
    resp = api.assign_seat(seat["id"], {"end_user_id": user["id"]},
                           make_end_user_headers(user["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_orgadmin_cannot_touch_other_org(api):
    """PRD: "When an entity-backed role's `X-User-ID` fails to resolve to an
    entity instance in the correct scope — wrong organization, wrong reseller,
    wrong user — the request is rejected with `ERR_IDENTITY_MISMATCH` (HTTP
    403)."

    Design: Corner/rbac/orgadmin_cannot_touch_other_org
    """
    b0, ba0 = bootstrap_org_and_admin()
    org1 = create_org(name="RB2", org_type="TEAM", primary_admin_id=ba0["id"])
    admin1 = create_admin(org1["id"], email="oa@rb2.com", full_name="Org Admin")
    headers1 = make_org_admin_headers(admin1["id"])
    org2 = create_org(name="RB2B", org_type="TEAM", primary_admin_id=ba0["id"])
    plan = create_plan(code="PRB2", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20)
    create_product_version(plan["id"])
    sub2 = create_active_subscription(org2["id"], plan["id"], seats_purchased=1)
    seat2 = mint_seat_for_active_subscription(sub2)
    resp = api.create_end_user(
        {"email": "u2@rb2b.com", "full_name": "User 2", "org_id": org2["id"]},
        SYS)
    user2 = validate_success(resp, expected_status=201)
    resp = api.assign_seat(seat2["id"], {"end_user_id": user2["id"]}, headers1)
    validate_error(resp, ApiErrorId.ERR_IDENTITY_MISMATCH)


def test_reseller_agent_cannot_fulfill_other_resellers_order(api):
    """PRD: "only by an agent whose own reseller identity equals the order's
    `reseller_id`" and PRD: "When an entity-backed role's `X-User-ID` fails to
    resolve to an entity instance in the correct scope — wrong organization,
    wrong reseller, wrong user — the request is rejected with
    `ERR_IDENTITY_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/reseller_agent_cannot_fulfill_other_resellers_order
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="RB3", org_type="TEAM", primary_admin_id=ba0["id"])
    create_admin(org["id"], email="oa@rb3.com", full_name="Org Admin")
    plan = create_plan(code="PRB3", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20)
    ra = create_reseller(name="RA", region="NA", tier="GOLD")
    rb = create_reseller(name="RB", region="NA", tier="PLATINUM")
    resp = api.create_reseller_order(
        create_reseller_order_payload(org_id=org["id"], plan_id=plan["id"],
                                      seats=2, region="NA"),
        SYS)
    order = validate_success(resp, expected_status=201)
    assert order["reseller_id"] == rb["id"]  # PLATINUM wins routing
    resp = api.fulfill_reseller_order(order["id"],
                                      make_reseller_agent_headers(ra["id"]))
    validate_error(resp, ApiErrorId.ERR_IDENTITY_MISMATCH)
    assert api.get_reseller_order(order["id"], SYS).json()["data"]["status"] \
        == "ROUTED"


def test_missing_auth_headers_returns_401(api):
    """PRD: "A request missing either header, or carrying a malformed value, is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_401
    """
    resp = api.list_organizations({}, params=None)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_version_increments_on_every_mutation(api):
    """PRD: "`version` (integer): a system-managed integer that increments by
    exactly 1 with every modification to the resource, including state
    transitions and cascade-driven updates."

    A minted seat (version 1) assigned once reports version 2.

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_mutation
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="CC1", org_type="TEAM", primary_admin_id=ba0["id"])
    admin = create_admin(org["id"], email="oa@cc1.com", full_name="Org Admin")
    headers = make_org_admin_headers(admin["id"])
    plan = create_plan(code="PXCC1", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20)
    create_product_version(plan["id"])
    sub = create_active_subscription(org["id"], plan["id"], seats_purchased=1)
    seat = mint_seat_for_active_subscription(sub)
    assert seat["version"] == 1
    user = create_end_user(org["id"], headers, email="u@cc1.com")
    assign_seat(seat["id"], user["id"], headers)
    seat_after = get_seat(seat["id"])
    assert seat_after["version"] == 2, (
        f"Seat version must be 2 after mint + assign, got "
        f"{seat_after['version']}")


def test_forced_upgrade_migration_on_activation_after_deadline(api):
    """PRD: "An entitlement whose product version is in `FORCED_UPGRADE` past
    its deadline cannot activate as-is; instead, if the clock is at or past the
    `forced_upgrade_deadline`, activation silently re-points the entitlement's
    `product_version_id` to the plan's latest `AVAILABLE` version — the one
    with the greatest `release_date`, ties broken by earlier `created_at` — and
    then proceeds."

    Design: Corner/cross_cutting_complexity_layers/forced_upgrade_migration_on_activation_after_deadline
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="CC2", org_type="TEAM", primary_admin_id=ba0["id"])
    admin = create_admin(org["id"], email="oa@cc2.com", full_name="Org Admin")
    headers = make_org_admin_headers(admin["id"])
    plan = create_plan(code="PCC2", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20)
    pv_old = create_product_version(plan["id"], version_label="2026.1",
                                    release_date="2026-01-15T00:00:00Z")
    sub = create_active_subscription(org["id"], plan["id"], seats_purchased=1)
    seat = mint_seat_for_active_subscription(sub)
    user = create_end_user(org["id"], headers, email="u@cc2.com")
    assign_seat(seat["id"], user["id"], headers)
    ent_id = list_seat_entitlements(seat["id"])[0]["id"]
    assert api.get_entitlement(ent_id, SYS).json()["data"][
        "product_version_id"] == pv_old["id"]
    pv_new = create_product_version(plan["id"], version_label="2026.2",
                                    release_date="2026-06-15T00:00:00Z")
    validate_success(api.deprecate_product_version(pv_old["id"], SYS))
    validate_success(api.force_upgrade_product_version(
        pv_old["id"], {"forced_upgrade_deadline": "2026-09-10T00:00:00Z"}, SYS))
    device = create_device(user["id"], fingerprint="fp-cc2", label="L")
    set_clock("2026-09-15T00:00:00Z")
    resp = api.activate_entitlement(ent_id, {"device_id": device["id"]},
                                    make_end_user_headers(user["id"]))
    data = validate_success(resp)
    assert data["status"] == "ACTIVE"
    assert data["product_version_id"] == pv_new["id"], (
        f"Post-deadline activation must migrate to the latest AVAILABLE "
        f"version; got {data['product_version_id']}")


def test_derived_storage_pool_reconciles_on_reclaim(api):
    """PRD: "The pool is recomputed whenever a subscription's active status
    changes, a seat is assigned or reclaimed, or a cloud-services add-on is
    topped up or cancelled." and PRD: "Finalization ... recomputes both the
    organization's storage pool and its compliance posture."

    1 assigned seat on a 100 GB/seat plan gives pool 100; after reclaim
    finalization the pool returns to 0.

    Design: Corner/cross_cutting_complexity_layers/derived_storage_pool_reconciles_on_reclaim
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="CC3", org_type="ENTERPRISE", primary_admin_id=ba0["id"])
    admin = create_admin(org["id"], email="oa@cc3.com", full_name="Org Admin")
    headers = make_org_admin_headers(admin["id"])
    plan = create_plan(code="PCC3", segment="ENTERPRISE", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=100)
    create_product_version(plan["id"])
    sub = create_active_subscription(org["id"], plan["id"], seats_purchased=1)
    seat = mint_seat_for_active_subscription(sub)
    user = create_end_user(org["id"], headers, email="u@cc3.com")
    assign_seat(seat["id"], user["id"], headers)
    assert api.get_organization(org["id"], SYS).json()["data"][
        "storage_pool_gb"] == 100
    api.reclaim_seat(seat["id"], headers)
    set_clock("2026-09-02T00:00:01Z")
    api.finalize_reclaim_seat(seat["id"], headers)
    org_after = api.get_organization(org["id"], SYS).json()["data"]
    assert org_after["storage_pool_gb"] == 0, (
        f"Pool must drop to 0 after reclaim finalize, got "
        f"{org_after['storage_pool_gb']}")


def test_immediate_consistency_after_assign(api):
    """PRD: "the server transitions the affected children automatically as
    part of the same operation, without requiring an explicit client request
    on each child" — the assign response and a subsequent read agree
    immediately.

    Design: Corner/consistency_model/immediate_consistency_after_assign
    """
    ctx = setup_assigned_seat(org_name="CM1")
    seat_after = get_seat(ctx["seat"]["id"])
    assert seat_after["status"] == "ASSIGNED"
    assert seat_after["end_user_id"] == ctx["user"]["id"]
