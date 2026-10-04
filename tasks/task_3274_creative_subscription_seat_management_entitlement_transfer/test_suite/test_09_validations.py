"""Validation violation corner tests (breadth queue B, validations section)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    SYS,
    bootstrap_org_and_admin,
    create_org,
    create_admin,
    create_plan,
    create_product_version,
    create_active_subscription,
    create_end_user,
    create_deployment_package_payload,
    mint_seat,
    mint_seat_for_active_subscription,
    assign_seat,
    get_seat,
    get_product_version,
    get_transfer_request,
    get_subscription,
    validate_success,
    validate_error,
    make_org_admin_headers,
    make_deployment_admin_headers,
)


def test_offline_activation_on_named_user_mode_rejected(api):
    """PRD: "an offline-activation request is honored only when the plan's
    `allows_offline_activation` is true and the package's `deployment_mode` is
    `SERIALIZED` (else `ERR_OFFLINE_ACTIVATION_NOT_ALLOWED`, and the same check
    also guards package creation)"

    Design: Corner/validations/offline_activation_on_named_user_mode_rejected
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="V1", org_type="TEAM", primary_admin_id=ba0["id"])
    create_admin(org["id"], email="oa@v1.com", full_name="Org Admin")
    deploy_admin = create_admin(org["id"], email="da@v1.com",
                                full_name="Deploy Admin",
                                admin_kind="DEPLOYMENT_ADMIN")
    plan = create_plan(code="PV1", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20,
                       deployment_modes=["NAMED_USER", "SERIALIZED"],
                       allows_offline_activation=True)
    resp = api.create_deployment_package(
        create_deployment_package_payload(
            org_id=org["id"], created_by_admin_id=deploy_admin["id"],
            name="Pk", plan_id=plan["id"], deployment_mode="NAMED_USER",
            offline_activation=True),
        make_deployment_admin_headers(deploy_admin["id"]))
    validate_error(resp, ApiErrorId.ERR_OFFLINE_ACTIVATION_NOT_ALLOWED)


def test_cross_org_assign_rejected(api):
    """PRD: "the target user must belong to the same organization as the
    subscription (else `ERR_CROSS_ORG_REFERENCE`)"

    Design: Corner/validations/cross_org_assign_rejected
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="V2", org_type="TEAM", primary_admin_id=ba0["id"])
    admin = create_admin(org["id"], email="oa@v2.com", full_name="Org Admin")
    headers = make_org_admin_headers(admin["id"])
    plan = create_plan(code="PXV2", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20)
    create_product_version(plan["id"])
    sub = create_active_subscription(org["id"], plan["id"], seats_purchased=1)
    seat = mint_seat_for_active_subscription(sub)
    org2 = create_org(name="V2B", org_type="TEAM", primary_admin_id=ba0["id"])
    resp = api.create_end_user(
        {"email": "u2@v2b.com", "full_name": "User 2", "org_id": org2["id"]},
        SYS)
    user2 = validate_success(resp, expected_status=201)
    resp = api.assign_seat(seat["id"], {"end_user_id": user2["id"]}, headers)
    validate_error(resp, ApiErrorId.ERR_CROSS_ORG_REFERENCE)
    assert get_seat(seat["id"])["status"] == "UNASSIGNED"


def test_duplicate_plan_seat_rejected(api):
    """PRD: "no other seat under the same plan in this organization may
    already be `ASSIGNED` to that user — one seat per user per plan per
    organization, violations drawing `ERR_DUPLICATE_PLAN_SEAT`."

    Design: Corner/validations/duplicate_plan_seat_rejected
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="V3", org_type="TEAM", primary_admin_id=ba0["id"])
    admin = create_admin(org["id"], email="oa@v3.com", full_name="Org Admin")
    headers = make_org_admin_headers(admin["id"])
    plan = create_plan(code="PXV3", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20)
    create_product_version(plan["id"])
    sub = create_active_subscription(org["id"], plan["id"], seats_purchased=2)
    seat1 = mint_seat_for_active_subscription(sub)
    user = create_end_user(org["id"], headers, email="u@v3.com")
    assign_seat(seat1["id"], user["id"], headers)
    sub = get_subscription(sub["id"])
    seat2 = mint_seat(sub["id"], sub["version"])
    resp = api.assign_seat(seat2["id"], {"end_user_id": user["id"]}, headers)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PLAN_SEAT)
    assert get_seat(seat2["id"])["status"] == "UNASSIGNED"


def test_seat_capacity_exceeded_at_boundary(api):
    """PRD: "`seats_assigned` must be strictly below `seats_purchased` (else
    `ERR_SEAT_CAPACITY_EXCEEDED`)"

    With seats_assigned == seats_purchased == 1, one more assignment is at the
    boundary and must be rejected.

    Design: Corner/validations/seat_capacity_exceeded_at_boundary
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="V4", org_type="TEAM", primary_admin_id=ba0["id"])
    admin = create_admin(org["id"], email="oa@v4.com", full_name="Org Admin")
    headers = make_org_admin_headers(admin["id"])
    plan = create_plan(code="PXV4", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20)
    create_product_version(plan["id"])
    sub = create_active_subscription(org["id"], plan["id"], seats_purchased=1)
    seat1 = mint_seat_for_active_subscription(sub)
    user1 = create_end_user(org["id"], headers, email="u@v4.com")
    assign_seat(seat1["id"], user1["id"], headers)
    sub = get_subscription(sub["id"])
    seat2 = mint_seat(sub["id"], sub["version"])
    user2 = create_end_user(org["id"], headers, email="u2@v4.com")
    resp = api.assign_seat(seat2["id"], {"end_user_id": user2["id"]}, headers)
    validate_error(resp, ApiErrorId.ERR_SEAT_CAPACITY_EXCEEDED)


def test_no_available_version_on_deprecate_last(api):
    """PRD: "Deprecating a version is only permitted while at least one other
    version of the same plan remains `AVAILABLE`; the attempt that would
    strand a plan with no available version is rejected with
    `ERR_NO_AVAILABLE_VERSION`."

    Design: Corner/validations/no_available_version_on_deprecate_last
    """
    b0, ba0 = bootstrap_org_and_admin()
    plan = create_plan(code="PV5", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20)
    pv = create_product_version(plan["id"], version_label="2026.1",
                                release_date="2026-01-15T00:00:00Z")
    resp = api.deprecate_product_version(pv["id"], SYS)
    validate_error(resp, ApiErrorId.ERR_NO_AVAILABLE_VERSION)
    assert get_product_version(pv["id"])["availability"] == "AVAILABLE"


def test_existence_precedes_state_on_wrong_path_id(api):
    """PRD: "Path-resource existence, validated left-to-right along the URL
    (`ERR_NOT_FOUND`)." — a state-transition call against a non-existent
    subscription id is rejected as not-found.

    Design: Corner/validations/existence_precedes_state_on_wrong_path_id
    """
    bootstrap_org_and_admin()
    resp = api.activate_subscription(NON_EXISTENT_UUID, SYS)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_occ_stale_version_returns_412(api):
    """PRD: "If the subscription's current `version` has advanced beyond the
    supplied value — because another writer assigned a seat, settled an
    invoice, or amended the subscription since the client last read it — the
    create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/validations/occ_stale_version_returns_412
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="V7", org_type="TEAM", primary_admin_id=ba0["id"])
    create_admin(org["id"], email="oa@v7.com", full_name="Org Admin")
    plan = create_plan(code="PXV7", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20)
    create_product_version(plan["id"])
    sub = create_active_subscription(org["id"], plan["id"], seats_purchased=1)
    mint_seat(sub["id"], sub["version"])  # advances the subscription version
    current = get_subscription(sub["id"])
    stale = current["version"] - 1
    resp = api.create_seat(
        {"subscription_id": sub["id"],
         "expected_subscription_version": stale},
        SYS)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_segregation_of_duties_on_transfer_approve(api):
    """PRD: "A transfer request's approving or rejecting administrator must be
    a different admin than the `requested_by_admin_id` recorded on the
    request" and PRD: "Violations of either rule are rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/validations/segregation_of_duties_on_transfer_approve
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="V8", org_type="TEAM", primary_admin_id=ba0["id"])
    admin1 = create_admin(org["id"], email="oa@v8.com", full_name="Org Admin",
                          admin_kind="SYSTEM_ADMIN")
    create_admin(org["id"], email="oa2@v8.com", full_name="Org Admin 2",
                 admin_kind="PRODUCT_ADMIN")
    h1 = make_org_admin_headers(admin1["id"])
    plan = create_plan(code="PXV8", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20)
    create_product_version(plan["id"])
    sub = create_active_subscription(org["id"], plan["id"], seats_purchased=1)
    seat = mint_seat_for_active_subscription(sub)
    user = create_end_user(org["id"], h1, email="u@v8.com")
    user2 = create_end_user(org["id"], h1, email="u2@v8.com")
    seat = assign_seat(seat["id"], user["id"], h1)
    resp = api.create_transfer_request(
        {"org_id": org["id"], "seat_id": seat["id"], "to_user_id": user2["id"],
         "requested_by_admin_id": admin1["id"],
         "expected_seat_version": seat["version"]}, h1)
    tr = validate_success(resp, expected_status=201)
    resp = api.approve_transfer_request(tr["id"], h1)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert get_transfer_request(tr["id"])["status"] == "PENDING_APPROVAL"
