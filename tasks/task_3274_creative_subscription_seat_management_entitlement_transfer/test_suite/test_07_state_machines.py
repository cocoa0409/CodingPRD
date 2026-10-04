"""State-machine corner tests (breadth queue B, state_machines section)."""
import pytest

from test_helpers import (
    ApiErrorId,
    SYS,
    bootstrap_org_and_admin,
    create_org,
    create_admin,
    create_plan,
    create_product_version,
    create_subscription,
    activate_subscription,
    create_active_subscription,
    create_end_user,
    create_device,
    create_cancellation_request,
    create_deployment_package_payload,
    mint_seat_for_active_subscription,
    assign_seat,
    list_seat_entitlements,
    get_entitlement,
    get_seat,
    get_transfer_request,
    set_clock,
    setup_assigned_seat,
    validate_success,
    validate_error,
    make_org_admin_headers,
    make_deployment_admin_headers,
    make_end_user_headers,
)


def test_seat_initial_state_unassigned(api):
    """PRD: "A **Seat** belongs to a subscription (its `subscription_id`) and
    is born `UNASSIGNED`; its `end_user_id` and `assigned_at` are null until
    assigned"

    Design: Corner/state_machines/seat_initial_state_unassigned
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="SM1", org_type="TEAM", primary_admin_id=ba0["id"])
    create_admin(org["id"], email="oa@sm1.com", full_name="Org Admin")
    plan = create_plan(code="PXSM1", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20)
    create_product_version(plan["id"])
    sub = create_active_subscription(org["id"], plan["id"], seats_purchased=1)
    seat = mint_seat_for_active_subscription(sub)
    assert seat["status"] == "UNASSIGNED"
    assert seat["end_user_id"] is None
    assert seat["assigned_at"] is None


def test_subscription_terminal_lockdown_cancelled_in_window(api):
    """PRD: "`CANCELLED_IN_WINDOW`, `CANCELLED_ETF`, and `EXPIRED` are the
    subscription's terminal states." and PRD: "Target-entity state
    compatibility with the requested transition (`ERR_INVALID_STATE`)."

    Settle from terminal CANCELLED_IN_WINDOW is rejected.

    Design: Corner/state_machines/subscription_terminal_lockdown_cancelled_in_window
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="SM2", org_type="TEAM", primary_admin_id=ba0["id"])
    admin = create_admin(org["id"], email="oa@sm2.com", full_name="Org Admin")
    headers = make_org_admin_headers(admin["id"])
    plan = create_plan(code="PXSM2", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20, cancellation_window_days=14)
    create_product_version(plan["id"])
    sub = activate_subscription(
        create_subscription(org["id"], plan["id"], seats_purchased=1)["id"])
    cr = create_cancellation_request(sub["id"], admin["id"], headers)
    set_clock("2026-09-02T00:00:00Z")
    resp = api.finalize_cancellation_request(cr["id"], SYS)
    validate_success(resp)
    resp = api.settle_subscription(sub["id"], SYS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert api.get_subscription(sub["id"], SYS).json()["data"]["status"] == \
        "CANCELLED_IN_WINDOW"


def test_transfer_request_invalid_from_executed(api):
    """PRD: "`REJECTED`, `EXECUTED`, and `EXPIRED` are terminal for the
    request." and PRD: "Target-entity state compatibility with the requested
    transition (`ERR_INVALID_STATE`)."

    Approving an EXECUTED transfer request is rejected.

    Design: Corner/state_machines/transfer_request_invalid_from_executed
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="SM3", org_type="TEAM", primary_admin_id=ba0["id"])
    admin1 = create_admin(org["id"], email="oa@sm3.com", full_name="Org Admin",
                          admin_kind="SYSTEM_ADMIN")
    admin2 = create_admin(org["id"], email="oa2@sm3.com",
                          full_name="Org Admin 2", admin_kind="PRODUCT_ADMIN")
    h1 = make_org_admin_headers(admin1["id"])
    h2 = make_org_admin_headers(admin2["id"])
    plan = create_plan(code="PXSM3", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20)
    create_product_version(plan["id"])
    sub = create_active_subscription(org["id"], plan["id"], seats_purchased=1)
    seat = mint_seat_for_active_subscription(sub)
    user = create_end_user(org["id"], h1, email="u@sm3.com")
    user2 = create_end_user(org["id"], h1, email="u2@sm3.com")
    seat = assign_seat(seat["id"], user["id"], h1)
    resp = api.create_transfer_request(
        {"org_id": org["id"], "seat_id": seat["id"], "to_user_id": user2["id"],
         "requested_by_admin_id": admin1["id"],
         "expected_seat_version": seat["version"]}, h1)
    tr = validate_success(resp, expected_status=201)
    validate_success(api.approve_transfer_request(tr["id"], h2))
    validate_success(api.execute_transfer_request(tr["id"], SYS))
    resp = api.approve_transfer_request(tr["id"], h2)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_transfer_request(tr["id"])["status"] == "EXECUTED"


def test_package_valid_transition_draft_to_pending_approval(api):
    """PRD: "A package is born `DRAFT`; its review lifecycle runs `DRAFT →
    PENDING_APPROVAL → APPROVED → PUBLISHED → RETIRED`, with `REJECTED` as the
    review's negative exit."

    Design: Corner/state_machines/package_valid_transition_draft_to_pending_approval
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="SM4", org_type="TEAM", primary_admin_id=ba0["id"])
    create_admin(org["id"], email="oa@sm4.com", full_name="Org Admin")
    deploy_admin = create_admin(org["id"], email="da@sm4.com",
                                full_name="Deploy Admin",
                                admin_kind="DEPLOYMENT_ADMIN")
    da_headers = make_deployment_admin_headers(deploy_admin["id"])
    plan = create_plan(code="P4SM", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20, deployment_modes=["NAMED_USER"])
    resp = api.create_deployment_package(
        create_deployment_package_payload(
            org_id=org["id"], created_by_admin_id=deploy_admin["id"],
            name="Pkg1", plan_id=plan["id"], deployment_mode="NAMED_USER"),
        da_headers)
    pkg = validate_success(resp, expected_status=201)
    assert pkg["status"] == "DRAFT"
    resp = api.submit_deployment_package(pkg["id"], da_headers)
    data = validate_success(resp)
    assert data["status"] == "PENDING_APPROVAL"


def test_entitlement_activate_side_effect_device_link(api):
    """PRD: "A successful activation stamps `device_id` with the request's
    device and advances the entitlement's `version`."

    Design: Corner/state_machines/entitlement_activate_side_effect_device_link
    """
    ctx = setup_assigned_seat(org_name="SM5")
    device = create_device(ctx["user"]["id"], fingerprint="fp-sm5", label="L1")
    ent_id = list_seat_entitlements(ctx["seat"]["id"])[0]["id"]
    resp = api.activate_entitlement(ent_id, {"device_id": device["id"]},
                                    make_end_user_headers(ctx["user"]["id"]))
    data = validate_success(resp)
    assert data["status"] == "ACTIVE"
    assert data["device_id"] == device["id"]


def test_reclaim_finalize_before_grace_returns_error(api):
    """PRD: "Once the logical clock reaches `pending_reclaim_not_before`, the
    reclaim can be finalized; attempting to finalize early is rejected with
    `ERR_RECLAIM_GRACE_ACTIVE`."

    Reclaim begins at the 2026-09-01T00:00:00Z default clock with a 24-hour
    grace; finalizing at 23:00 the same day is early.

    Design: Corner/state_machines/reclaim_finalize_before_grace_returns_error
    """
    ctx = setup_assigned_seat(org_name="SM6")
    api.reclaim_seat(ctx["seat"]["id"], ctx["admin_headers"])
    set_clock("2026-09-01T23:00:00Z")
    resp = api.finalize_reclaim_seat(ctx["seat"]["id"], ctx["admin_headers"])
    validate_error(resp, ApiErrorId.ERR_RECLAIM_GRACE_ACTIVE)
    assert get_seat(ctx["seat"]["id"])["status"] == "PENDING_RECLAIM"
