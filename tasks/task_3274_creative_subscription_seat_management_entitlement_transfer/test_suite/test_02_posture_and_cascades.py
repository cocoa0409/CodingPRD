"""Org compliance posture and cascading consistency tests (depth queue A)."""
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
    create_asset,
    mint_seat_for_active_subscription,
    assign_seat,
    open_audit,
    get_organization,
    get_subscription,
    get_seat,
    get_end_user,
    get_asset,
    get_entitlement,
    list_seat_entitlements,
    setup_activated_entitlement,
    set_clock,
    validate_success,
    make_org_admin_headers,
)


def test_open_audit_shifts_posture_to_under_audit(api):
    """PRD: "otherwise it is `UNDER_AUDIT` if any audit of the organization is
    in `OPEN` or `FINDINGS_RAISED`; otherwise it is `COMPLIANT`."

    Design: Difficulty/combinatorial_formula/compliance_posture_four_way_precedence_branch
    """
    ctx_org = bootstrap_org_and_admin()
    b0, ba0 = ctx_org
    org = create_org(name="O3", org_type="TEAM", primary_admin_id=ba0["id"])
    admin = create_admin(org["id"], email="oa3@o3.com", full_name="Admin Three")
    plan = create_plan(code="P3", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20)
    create_product_version(plan["id"])
    sub = create_active_subscription(org["id"], plan["id"], seats_purchased=1)
    audit = open_audit(org["id"], admin["id"])
    assert audit["status"] == "OPEN"
    org_after = get_organization(org["id"])
    assert org_after["compliance_posture"] == "UNDER_AUDIT", (
        f"Expected UNDER_AUDIT, got {org_after['compliance_posture']}")


def test_findings_without_overallocation_stays_under_audit(api):
    """PRD: "the organization is `FROZEN` if any of its compliance audits is in
    `FINDINGS_RAISED` and the organization has at least one over-allocated seat"

    Raised findings alone (no over-allocation) leave the org UNDER_AUDIT:
    the FROZEN branch requires both inputs.

    Design: Difficulty/combinatorial_formula/compliance_posture_four_way_precedence_branch
    """
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name="O3B", org_type="TEAM", primary_admin_id=ba0["id"])
    admin = create_admin(org["id"], email="oa3b@o3.com", full_name="Admin")
    plan = create_plan(code="P3B", segment="TEAM", billing_model="MONTHLY",
                       monthly_price_cents=3000, annual_monthly_price_cents=3000,
                       storage_gb_per_seat=20)
    create_product_version(plan["id"])
    create_active_subscription(org["id"], plan["id"], seats_purchased=1)
    audit = open_audit(org["id"], admin["id"])
    resp = api.raise_audit_findings(audit["id"], {"findings_count": 1}, SYS)
    data = validate_success(resp)
    assert data["status"] == "FINDINGS_RAISED"
    org_after = get_organization(org["id"])
    assert org_after["compliance_posture"] == "UNDER_AUDIT", (
        f"Expected UNDER_AUDIT (no over-allocation), got "
        f"{org_after['compliance_posture']}")


def test_past_due_sweep_suspends_entitlements(api):
    """PRD: "when the logical clock advances past a monthly invoice's due date
    and the invoice is unpaid, an `ACTIVE` subscription moves to `PAST_DUE`. The
    cascade suspends every non-terminal entitlement of every seat under the
    subscription (`ACTIVE → SUSPENDED` on each; devices keep their local grace)"

    MONTHLY subscription activated at 2026-09-01; clock to 2026-10-02 passes
    the second invoice's due date.

    Design: Difficulty/transitive_cascade/past_due_subscription_suspends_entitlements_and_posture_chain
    """
    ctx = setup_activated_entitlement(org_name="O6")
    ent_id = ctx["entitlement"]["id"]
    assert ctx["entitlement"]["status"] == "ACTIVE"
    set_clock("2026-10-02T00:00:00Z")
    sub_after = get_subscription(ctx["subscription"]["id"])
    assert sub_after["status"] == "PAST_DUE", (
        f"Expected PAST_DUE after clock sweep, got {sub_after['status']}")
    ent_after = get_entitlement(ent_id)
    assert ent_after["status"] == "SUSPENDED", (
        f"Expected entitlement SUSPENDED, got {ent_after['status']}")


def test_settle_reactivates_suspended_entitlements(api):
    """PRD: "Settling the account — a `SystemAdmin` action requiring the
    organization to be `ACTIVE` — returns the subscription `PAST_DUE → ACTIVE`,
    flips each suspended entitlement back `SUSPENDED → ACTIVE`, and recomputes
    posture again."

    Design: Difficulty/transitive_cascade/past_due_subscription_suspends_entitlements_and_posture_chain
    """
    ctx = setup_activated_entitlement(org_name="O6S")
    ent_id = ctx["entitlement"]["id"]
    set_clock("2026-10-02T00:00:00Z")
    sub_mid = get_subscription(ctx["subscription"]["id"])
    assert sub_mid["status"] == "PAST_DUE"
    assert get_entitlement(ent_id)["status"] == "SUSPENDED"
    resp = api.settle_subscription(ctx["subscription"]["id"], SYS)
    data = validate_success(resp)
    assert data["status"] == "ACTIVE"
    ent_after = get_entitlement(ent_id)
    assert ent_after["status"] == "ACTIVE", (
        f"Expected entitlement ACTIVE after settle, got {ent_after['status']}")


def _departed_setup(api, org_name="O7"):
    """Org + ACTIVE sub (1 seat) + seat assigned to user who owns a 1500 MB
    asset; user deactivated (seat in PENDING_RECLAIM within grace)."""
    b0, ba0 = bootstrap_org_and_admin()
    org = create_org(name=org_name, org_type="TEAM", primary_admin_id=ba0["id"])
    admin = create_admin(org["id"], email=f"oa@{org_name}.com", full_name="Admin")
    admin_headers = make_org_admin_headers(admin["id"])
    plan = create_plan(code=f"{org_name}-P", segment="TEAM",
                       billing_model="MONTHLY", monthly_price_cents=3000,
                       annual_monthly_price_cents=3000, storage_gb_per_seat=20)
    create_product_version(plan["id"])
    sub = create_active_subscription(org["id"], plan["id"], seats_purchased=1)
    seat = mint_seat_for_active_subscription(sub)
    user = create_end_user(org["id"], admin_headers, email=f"u@{org_name}.com")
    seat = assign_seat(seat["id"], user["id"], admin_headers)
    asset = create_asset(user["id"], admin_headers, title="Design File",
                         size_mb=1500)
    resp = api.deactivate_end_user(user["id"], admin_headers)
    validate_success(resp)
    return {"org": org, "admin": admin, "admin_headers": admin_headers,
            "plan": plan, "subscription": sub, "seat": seat, "user": user,
            "asset": asset}


def test_mark_departed_finalizes_reclaim_revokes_and_orphans(api):
    """PRD: "Marking the user `DEPARTED` is the point of no return: every seat
    still in `PENDING_RECLAIM` for this user is finalized immediately regardless
    of remaining grace, becoming `RECLAIMED` with its entitlement revoked and
    the subscription's `seats_assigned` decremented; and every asset the user
    still owns in `ACTIVE` status becomes `ORPHANED`"

    Design: Difficulty/transitive_cascade/user_departure_finalizes_seat_revokes_entitlement_orphans_asset
    """
    ctx = _departed_setup(api)
    seat_id = ctx["seat"]["id"]
    entitlements = list_seat_entitlements(seat_id)
    ent_id = entitlements[0]["id"]
    resp = api.mark_departed_end_user(ctx["user"]["id"], ctx["admin_headers"])
    data = validate_success(resp)
    assert data["status"] == "DEPARTED"
    assert get_seat(seat_id)["status"] == "RECLAIMED"
    assert get_entitlement(ent_id)["status"] == "REVOKED"
    assert get_asset(ctx["asset"]["id"])["status"] == "ORPHANED"
    assert get_subscription(ctx["subscription"]["id"])["seats_assigned"] == 0


def test_mark_departed_nulls_seat_assignee(api):
    """PRD: "Finalization moves the seat `PENDING_RECLAIM → RECLAIMED`, nulls
    out `end_user_id`, `assigned_at`, and `pending_reclaim_not_before`"

    Departure finalizes the pending reclaim immediately, so the seat's
    assignee fields are nulled even though the grace period has not lapsed.

    Design: Difficulty/transitive_cascade/user_departure_finalizes_seat_revokes_entitlement_orphans_asset
    """
    ctx = _departed_setup(api, org_name="O7B")
    api.mark_departed_end_user(ctx["user"]["id"], ctx["admin_headers"])
    seat_after = get_seat(ctx["seat"]["id"])
    assert seat_after["status"] == "RECLAIMED"
    assert seat_after["end_user_id"] is None, (
        f"Expected end_user_id null, got {seat_after['end_user_id']}")
