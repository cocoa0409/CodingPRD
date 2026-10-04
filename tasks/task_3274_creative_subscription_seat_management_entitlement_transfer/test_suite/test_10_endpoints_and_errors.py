"""Endpoint action and error-catalog corner tests (breadth queue B,
endpoints + errors sections)."""
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
    create_subscription,
    create_active_subscription,
    create_end_user,
    create_reseller_order_payload,
    mint_seat_for_active_subscription,
    get_subscription,
    open_audit,
    get_organization,
    validate_success,
    validate_error,
    validate_paginated,
    make_org_admin_headers,
    make_reseller_agent_headers,
)


def test_reseller_order_routing_selector_picks_platinum_least_loaded(api):
    """PRD: "candidates are ranked by tier priority with `PLATINUM` outranking
    `GOLD` outranking `CERTIFIED`, then by the fewest currently open orders
    (orders still in `ROUTED` status), with ties broken by earlier
    `created_at`. The winning reseller's `id` is stamped onto the order's
    `reseller_id` and its tier drives the computed `discount_pct` on the order
    — 5 percent for `CERTIFIED`, 10 percent for `GOLD`, 15 percent for
    `PLATINUM`."

    Design: Corner/endpoints/reseller_order_routing_selector_picks_platinum_least_loaded
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="EP1", org_type="TEAM", primary_admin_id=ba0["id"])
    create_admin(org["id"], email="oa@ep1.com", full_name="Org Admin")
    plan = create_plan(code="PE1", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20)
    create_reseller(name="RG", region="NA", tier="GOLD")
    rp = create_reseller(name="RP", region="NA", tier="PLATINUM")
    resp = api.create_reseller_order(
        create_reseller_order_payload(org_id=org["id"], plan_id=plan["id"],
                                      seats=5, region="NA"),
        SYS)
    data = validate_success(resp, expected_status=201)
    assert data["reseller_id"] == rp["id"], (
        f"PLATINUM reseller must win routing; got {data['reseller_id']}")
    assert data["discount_pct"] == 15
    assert data["status"] == "ROUTED"


def test_reseller_fulfill_creates_pending_subscription(api):
    """PRD: "The assigned `ResellerAgent` may fulfill it — permitted only while
    the reseller is `ACTIVE` and the purchasing organization is `ACTIVE`, and
    only by an agent whose own reseller identity equals the order's
    `reseller_id` — which moves the order to `FULFILLED` and creates a new
    subscription for the organization in `PENDING_PAYMENT` status, carrying
    `reseller_id` set to the fulfilling reseller and `seats_purchased` set to
    the ordered seats."

    Design: Corner/endpoints/reseller_fulfill_creates_pending_subscription
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="EP2", org_type="TEAM", primary_admin_id=ba0["id"])
    create_admin(org["id"], email="oa@ep2.com", full_name="Org Admin")
    plan = create_plan(code="PE2", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20)
    rp = create_reseller(name="RP2", region="NA", tier="PLATINUM")
    resp = api.create_reseller_order(
        create_reseller_order_payload(org_id=org["id"], plan_id=plan["id"],
                                      seats=5, region="NA"),
        SYS)
    order = validate_success(resp, expected_status=201)
    assert order["reseller_id"] == rp["id"]
    resp = api.fulfill_reseller_order(order["id"],
                                      make_reseller_agent_headers(rp["id"]))
    data = validate_success(resp)
    assert data["status"] == "FULFILLED"
    resp = api.list_subscriptions(
        SYS, params={"org_id": org["id"], "reseller_id": rp["id"]})
    subs, meta = validate_paginated(resp)
    assert len(subs) == 1, f"Fulfillment must create exactly 1 subscription"
    assert subs[0]["status"] == "PENDING_PAYMENT"
    assert subs[0]["seats_purchased"] == 5
    assert subs[0]["reseller_id"] == rp["id"]


def test_computed_read_org_posture_after_findings(api):
    """PRD: "Raising findings — a `SystemAdmin` action supplying a
    `findings_count` — moves the audit `OPEN → FINDINGS_RAISED`" and PRD:
    "otherwise it is `UNDER_AUDIT` if any audit of the organization is in
    `OPEN` or `FINDINGS_RAISED`"

    With raised findings but no over-allocated seats, the org stays
    UNDER_AUDIT (FROZEN additionally requires over-allocation).

    Design: Corner/endpoints/computed_read_org_posture_after_findings
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="EP3", org_type="TEAM", primary_admin_id=ba0["id"])
    admin = create_admin(org["id"], email="oa@ep3.com", full_name="Org Admin")
    audit = open_audit(org["id"], admin["id"])
    resp = api.raise_audit_findings(audit["id"], {"findings_count": 2}, SYS)
    data = validate_success(resp)
    assert data["status"] == "FINDINGS_RAISED"
    org_after = get_organization(org["id"])
    assert org_after["compliance_posture"] == "UNDER_AUDIT", (
        f"Raised findings without over-allocation leave the org UNDER_AUDIT; "
        f"got {org_after['compliance_posture']}")


def test_err_reseller_suspended_triggerable(api):
    """PRD: "suspension blocks fulfillment of its routed orders and blocks
    activation of any subscription carrying its `reseller_id` — both
    operations fail with `ERR_RESELLER_SUSPENDED` when the reseller is not
    active"

    Design: Corner/errors/err_reseller_suspended_triggerable
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="ER1", org_type="TEAM", primary_admin_id=ba0["id"])
    create_admin(org["id"], email="oa@er1.com", full_name="Org Admin")
    plan = create_plan(code="PE3", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20)
    create_product_version(plan["id"])
    rs = create_reseller(name="RS", region="APAC", tier="CERTIFIED")
    sub = create_subscription(org["id"], plan["id"], seats_purchased=2,
                              reseller_id=rs["id"])
    validate_success(api.suspend_reseller(rs["id"], SYS))
    resp = api.activate_subscription(sub["id"], SYS)
    validate_error(resp, ApiErrorId.ERR_RESELLER_SUSPENDED)
    assert get_subscription(sub["id"])["status"] == "PENDING_PAYMENT"


def test_err_no_reseller_available_triggerable(api):
    """PRD: "When no active reseller exists in the order's region, creation
    fails with `ERR_NO_RESELLER_AVAILABLE`."

    Design: Corner/errors/err_no_reseller_available_triggerable
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="ER2", org_type="TEAM", primary_admin_id=ba0["id"])
    create_admin(org["id"], email="oa@er2.com", full_name="Org Admin")
    plan = create_plan(code="PE4", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20)
    # No reseller exists in LATAM.
    resp = api.create_reseller_order(
        create_reseller_order_payload(org_id=org["id"], plan_id=plan["id"],
                                      seats=3, region="LATAM"),
        SYS)
    validate_error(resp, ApiErrorId.ERR_NO_RESELLER_AVAILABLE)


def test_err_user_not_active_triggerable(api):
    """PRD: "the target user must be `ACTIVE` (else `ERR_USER_NOT_ACTIVE`)"

    Design: Corner/errors/err_user_not_active_triggerable
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="ER3", org_type="TEAM", primary_admin_id=ba0["id"])
    admin = create_admin(org["id"], email="oa@er3.com", full_name="Org Admin")
    headers = make_org_admin_headers(admin["id"])
    plan = create_plan(code="PXER3", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20)
    create_product_version(plan["id"])
    sub = create_active_subscription(org["id"], plan["id"], seats_purchased=1)
    seat = mint_seat_for_active_subscription(sub)
    user = create_end_user(org["id"], headers, email="u@er3.com")
    validate_success(api.deactivate_end_user(user["id"], headers))
    resp = api.assign_seat(seat["id"], {"end_user_id": user["id"]}, headers)
    validate_error(resp, ApiErrorId.ERR_USER_NOT_ACTIVE)
