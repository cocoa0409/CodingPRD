"""Biller-channel constraints, plan-change scope reconciliation, tier
mismatch, cross-entity gates, and duplicate-subscription coverage."""
from test_helpers import (
    TEST_USERS,
    create_bundle_plan,
    create_plan,
    create_standalone_plan,
    get_profile,
    get_subscription,
    list_subscription_entitlements,
    purchase_subscription,
    set_clock,
    setup_account_with_billing,
    setup_account_with_profiles,
    setup_active_bundle_subscription,
    setup_active_standalone_subscription,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    create_billing_account,
    create_profile,
    register_account,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SUPPORT = TEST_USERS["support_headers"]
DISTRIBUTOR = TEST_USERS["distributor_ops_headers"]


def test_app_store_immediate_cancel_rejected(api):
    """PRD §3.8: "And an app-store-billed subscription can never cancel
    immediately, because the store controls refund timing — such a request is
    rejected with ERR_IMMEDIATE_CANCEL_NOT_ALLOWED (HTTP 422)."
    PRD §3.8: "By default the cancellation takes effect at period end —
    cancel_effective_at is set to the billing account's period_end — but the
    caller may pass immediate_effect as true to cancel at the current logical
    clock instant instead."

    Design: Corner/validations/app_store_immediate_cancel_rejected
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="val1@x.com", biller_type="APP_STORE"
    )
    rejected = api.cancel_subscription(sub["id"], {"immediate_effect": True}, hdrs)
    validate_error(rejected, "ERR_IMMEDIATE_CANCEL_NOT_ALLOWED", 422)
    ok = api.cancel_subscription(sub["id"], {"immediate_effect": False}, hdrs)
    data = validate_success(ok, 200)
    assert data["cancel_effective_at"] is not None and data[
        "cancel_effective_at"
    ].startswith("2026-10-02T00:00:00"), (
        f"cancel_effective_at must be the 31-day period_end 2026-10-02, "
        f"got {data['cancel_effective_at']}"
    )


def test_app_store_cross_kind_plan_change_blocked(api):
    """PRD §3.7: "App-store-billed subscriptions face a further structural
    rule: they may only move between plans of the same plan_kind; an app-store
    subscriber asking to jump from standalone to bundle or back is rejected
    with ERR_BILLER_UPGRADE_PATH_BLOCKED (HTTP 422), because cross-kind moves
    for that channel must be handled by the store."

    Design: Corner/validations/app_store_cross_kind_plan_change_blocked
    """
    create_standalone_plan(plan_code="HULU_ADS", service="HULU", price=899)
    create_bundle_plan(plan_code="DUO_ADS", price=1099, ad_tier="AD_SUPPORTED")
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="val2@x.com", biller_type="APP_STORE"
    )
    blocked = api.plan_change(
        sub["id"],
        {
            "new_plan_code": "DUO_ADS",
            "expected_subscription_version": sub["version"],
        },
        hdrs,
    )
    validate_error(blocked, "ERR_BILLER_UPGRADE_PATH_BLOCKED", 422)
    ok = api.plan_change(
        sub["id"],
        {
            "new_plan_code": "HULU_ADS",
            "expected_subscription_version": sub["version"],
        },
        hdrs,
    )
    changed = validate_success(ok, 200)
    assert changed["plan_code"] == "HULU_ADS"


def test_purchase_plan_not_allowed_by_biller(api, distributor_ops_headers):
    """PRD §3.4: "Third-party channels constrain the sale: when the billing
    account's biller_type is APP_STORE, the plan's allow_app_store_billing
    must be true, and for DISTRIBUTOR the plan's allow_distributor_billing
    must be true; otherwise the purchase fails with
    ERR_BILLER_PLAN_NOT_ALLOWED (HTTP 422)."

    Design: Corner/validations/purchase_plan_not_allowed_by_biller
    """
    create_plan(
        plan_code="INTERNAL_ONLY", plan_kind="STANDALONE", service_scope=["DPLUS"],
        ad_tier="AD_SUPPORTED", monthly_price_cents=799,
        allow_app_store_billing=True, allow_distributor_billing=False,
    )
    account = register_account(email="val3@x.com")
    billing = create_billing_account(
        account, biller_type="DISTRIBUTOR", biller_reference="dist-77",
        headers=distributor_ops_headers,
    )
    from test_helpers import make_subscriber_headers

    hdrs = make_subscriber_headers(account["id"])
    profile = create_profile(account, service="DPLUS")
    resp = api.create_subscription(
        {
            "subscriber_account_id": account["id"],
            "billing_account_id": billing["id"],
            "plan_code": "INTERNAL_ONLY",
            "dplus_service_profile_id": profile["id"],
        },
        distributor_ops_headers,
    )
    validate_error(resp, "ERR_BILLER_PLAN_NOT_ALLOWED", 422)


def test_legacy_plan_new_purchase_rejected(api):
    """PRD §3.1: "a legacy plan rejects new purchases and plan changes into it
    with ERR_PLAN_LEGACY_ONLY (HTTP 422), with a single exception — a
    subscriber whose grandfathered_plan_code already equals that plan code may
    plan-change back into it."

    Design: Corner/validations/legacy_plan_new_purchase_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    create_plan(
        plan_code="LEGACY_OLD", plan_kind="STANDALONE", service_scope=["DPLUS"],
        ad_tier="AD_SUPPORTED", monthly_price_cents=599,
        allow_app_store_billing=True, allow_distributor_billing=True,
        is_legacy=True,
    )
    create_standalone_plan(plan_code="DPLUS_ADS", service="DPLUS", price=799)
    account, billing, hdrs = setup_account_with_billing(email="val8@x.com")
    profile = create_profile(account, service="DPLUS")
    rejected = api.create_subscription(
        {
            "subscriber_account_id": account["id"],
            "billing_account_id": billing["id"],
            "plan_code": "LEGACY_OLD",
            "dplus_service_profile_id": profile["id"],
        },
        hdrs,
    )
    validate_error(rejected, "ERR_PLAN_LEGACY_ONLY", 422)
    ok = api.create_subscription(
        {
            "subscriber_account_id": account["id"],
            "billing_account_id": billing["id"],
            "plan_code": "DPLUS_ADS",
            "dplus_service_profile_id": profile["id"],
        },
        hdrs,
    )
    validate_success(ok, 201)


def test_duplicate_billing_account_rejected(api):
    """PRD §3.4: "The biller_type is immutable after creation, and a
    subscriber attempting to create a second billing account is rejected with
    ERR_DUPLICATE_BILLING_ACCOUNT (HTTP 409)."

    Design: Corner/validations/duplicate_billing_account_rejected
    """
    account, billing, hdrs = setup_account_with_billing(email="val7@x.com")
    resp = api.create_billing_account(
        account["id"],
        {"biller_type": "APP_STORE", "biller_reference": "rcpt-9"},
        hdrs,
    )
    validate_error(resp, "ERR_DUPLICATE_BILLING_ACCOUNT", 409)


def test_reference_not_found_unknown_plan_code(api):
    """PRD §2.8: "Identifiers referenced inside a request body — a plan_code,
    an offer_code, a profile id, a subscription id, or a billing account id —
    are checked after the path resolves; a body reference that does not exist
    fails with ERR_REFERENCE_NOT_FOUND (HTTP 404)."

    Design: Corner/errors/reference_not_found_unknown_plan_code
    """
    account, billing, hdrs = setup_account_with_billing(email="err1@x.com")
    profile = create_profile(account, service="DPLUS")
    resp = api.create_subscription(
        {
            "subscriber_account_id": account["id"],
            "billing_account_id": billing["id"],
            "plan_code": "NO_SUCH_PLAN",
            "dplus_service_profile_id": profile["id"],
        },
        hdrs,
    )
    validate_error(resp, "ERR_REFERENCE_NOT_FOUND", 404)


def test_clock_regression_rejected(api, platform_admin_headers):
    """PRD §2.5: "The clock is monotonic: attempting to set it to a timestamp
    earlier than the current logical clock is rejected with
    ERR_CLOCK_REGRESSION (HTTP 422)."

    Design: Corner/errors/clock_regression_rejected
    """
    set_clock("2026-09-10T00:00:00Z")
    resp = api.set_clock("2026-09-05T00:00:00Z", platform_admin_headers)
    validate_error(resp, "ERR_CLOCK_REGRESSION", 422)


def test_account_close_blocked_by_active_subscription(api):
    """PRD §2.11: "Closing is itself only possible once every subscription of
    the account has reached a terminal lifecycle — an attempt with any
    subscription still in PENDING_ENTITLEMENT, ACTIVE, PAST_DUE, or
    CANCEL_SCHEDULED is rejected with ERR_ACTIVE_SUBSCRIPTIONS_REMAIN
    (HTTP 409)."
    PRD §3.2: "On closure, every profile of the account moves to UNLINKED, and
    every retention redemption still in ACTIVE status on the account's
    subscriptions is moved to VOIDED."

    Design: Corner/validations/account_close_blocked_by_active_subscription
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="val9@x.com"
    )
    blocked = api.close_account(account["id"], hdrs)
    validate_error(blocked, "ERR_ACTIVE_SUBSCRIPTIONS_REMAIN", 409)
    validate_success(
        api.cancel_subscription(sub["id"], {"immediate_effect": True}, hdrs), 200
    )
    set_clock("2026-09-02T00:00:00Z")
    closed = api.close_account(account["id"], hdrs)
    data = validate_success(closed, 200)
    assert data["account_status"] == "CLOSED"
    assert get_profile(profile["id"], hdrs)["profile_status"] == "UNLINKED"


def test_plan_change_reconciles_entitlement_scope(api):
    """PRD §3.7: "On a successful change, the subscription's version
    increments by 1, price_cents is recomputed per §3.5 — the grandfathered
    price reapplies exactly when the new plan code equals the account's
    grandfathered_plan_code — and the entitlements are reconciled to the new
    plan's scope: services newly in scope spawn fresh entitlements that
    provision straight to ACTIVE, while services leaving the scope have their
    entitlements REVOKED."
    PRD §2.9: "When the last ACTIVE entitlement on a profile disappears — by
    suspension, revocation, or cancellation — the profile itself drops from
    LINKED to SUSPENDED; when any entitlement on a suspended profile returns
    to ACTIVE and no other blocking condition holds, the profile rises back to
    LINKED."

    Design: Corner/endpoints/plan_change_reconciles_entitlement_scope
    """
    create_standalone_plan(plan_code="DPLUS_ADS", service="DPLUS", price=799)
    account, billing, profiles, sub, hdrs = setup_active_bundle_subscription(
        email="ep2@x.com"
    )
    resp = api.plan_change(
        sub["id"],
        {
            "new_plan_code": "DPLUS_ADS",
            "expected_subscription_version": sub["version"],
        },
        hdrs,
    )
    changed = validate_success(resp, 200)
    assert changed["plan_code"] == "DPLUS_ADS"
    assert changed["version"] == sub["version"] + 1
    ents = list_subscription_entitlements(sub["id"], hdrs)
    by_service = {e["service"]: e["entitlement_status"] for e in ents}
    assert by_service["DPLUS"] == "ACTIVE"
    assert by_service["HULU"] == "REVOKED"
    assert get_profile(profiles["HULU"]["id"], hdrs)["profile_status"] == "SUSPENDED"
    assert get_profile(profiles["DPLUS"]["id"], hdrs)["profile_status"] == "LINKED"


def test_tier_mismatch_flag_and_clear_on_plan_change(api):
    """PRD §3.6: "Whenever both profiles are LINKED and the entitlements they
    carry derive from subscriptions whose plan ad_tier values disagree — one
    AD_SUPPORTED, one AD_FREE — every entitlement serving the lower-tier
    service is flagged: its mismatch_flag becomes true."
    PRD §3.6: "When a plan change brings the tiers back into agreement, the
    flag clears on all entitlements of the affected profile."

    Design: Corner/state_machines/tier_mismatch_flag_and_clear_on_plan_change
    """
    set_clock("2026-09-01T00:00:00Z")
    create_bundle_plan(plan_code="DUO_ADS", price=1099, ad_tier="AD_SUPPORTED")
    create_bundle_plan(plan_code="DUO_PREMIUM", price=1999, ad_tier="AD_FREE")
    create_standalone_plan(
        plan_code="DPLUS_PREMIUM", service="DPLUS", price=1199, ad_tier="AD_FREE"
    )
    account, billing, profiles, hdrs = setup_account_with_profiles(email="sm9@x.com")
    bundle = purchase_subscription(
        account, billing, "DUO_ADS",
        dplus_profile=profiles["DPLUS"], hulu_profile=profiles["HULU"],
    )
    purchase_subscription(
        account, billing, "DPLUS_PREMIUM", dplus_profile=profiles["DPLUS"]
    )
    ents_before = list_subscription_entitlements(bundle["id"], hdrs)
    assert len(ents_before) == 2
    # PRD pins the flag to "every entitlement serving the lower-tier service";
    # with a mixed-tier DPLUS profile (AD_SUPPORTED bundle + AD_FREE
    # standalone) the PRD does not uniquely determine whether the DPLUS or the
    # HULU side counts as the lower-tier service, but under either reading the
    # disagreement is flagged on the lower-tier side of the bundle.
    assert any(e["mismatch_flag"] is True for e in ents_before), (
        f"tier disagreement must flag the lower-tier side, got {[e['mismatch_flag'] for e in ents_before]}"
    )
    current = get_subscription(bundle["id"], hdrs)
    changed = api.plan_change(
        bundle["id"],
        {
            "new_plan_code": "DUO_PREMIUM",
            "expected_subscription_version": current["version"],
        },
        hdrs,
    )
    validate_success(changed, 200)
    assert get_subscription(bundle["id"], hdrs)["plan_code"] == "DUO_PREMIUM"
    ents_after = list_subscription_entitlements(bundle["id"], hdrs)
    assert all(e["mismatch_flag"] is False for e in ents_after), (
        f"flags must clear after tier agreement, got {[e['mismatch_flag'] for e in ents_after]}"
    )


def test_entitlements_reverse_reachability_from_profile(api):
    """PRD §3.13: "An entitlements listing is available both from the
    subscription side and from the profile side, the latter aggregating
    entitlements granted to a profile from any subscription."
    PRD §3.8: "When an account holds both a bundle and a standalone covering
    the same service, the profile for that service stays LINKED as long as at
    least one ACTIVE entitlement for that service survives from any source
    subscription."

    Design: Corner/endpoints/entitlements_reverse_reachability_from_profile
    """
    set_clock("2026-09-01T00:00:00Z")
    create_bundle_plan(plan_code="DUO_ADS", price=1099, ad_tier="AD_SUPPORTED")
    create_standalone_plan(plan_code="DPLUS_ADS", service="DPLUS", price=799)
    account, billing, profiles, hdrs = setup_account_with_profiles(email="ep3@x.com")
    purchase_subscription(
        account, billing, "DUO_ADS",
        dplus_profile=profiles["DPLUS"], hulu_profile=profiles["HULU"],
    )
    purchase_subscription(
        account, billing, "DPLUS_ADS", dplus_profile=profiles["DPLUS"]
    )
    resp = api.list_profile_entitlements(profiles["DPLUS"]["id"], hdrs)
    ents = validate_success(resp, 200)
    assert len(ents) == 2, f"profile must aggregate 2 entitlements, got {len(ents)}"
    assert all(e["service"] == "DPLUS" for e in ents)
    assert all(e["entitlement_status"] == "ACTIVE" for e in ents)


def test_duplicate_active_subscription_period_overlap(api):
    """PRD §3.4: "the account may not already hold a non-terminal subscription
    on the same plan code (else ERR_DUPLICATE_ACTIVE_SUBSCRIPTION, HTTP 409)."
    PRD §2.5: "Advancing the clock fires every transition gated on time —
    most importantly, a subscription in CANCEL_SCHEDULED whose
    cancel_effective_at has been reached finalizes to CANCELLED."

    Design: Difficulty/resource_temporal_overlap/duplicate_active_subscription_period_overlap
    """
    account, billing, profile, sub1, hdrs = setup_active_standalone_subscription(
        email="ov1@x.com"
    )
    validate_success(
        api.cancel_subscription(sub1["id"], {"immediate_effect": False}, hdrs), 200
    )
    blocked = api.create_subscription(
        {
            "subscriber_account_id": account["id"],
            "billing_account_id": billing["id"],
            "plan_code": "DPLUS_ADS",
            "dplus_service_profile_id": profile["id"],
        },
        hdrs,
    )
    validate_error(blocked, "ERR_DUPLICATE_ACTIVE_SUBSCRIPTION", 409)
    set_clock("2026-10-01T00:00:00Z")
    assert get_subscription(sub1["id"], hdrs)["lifecycle_status"] == "CANCELLED"
    ok = api.create_subscription(
        {
            "subscriber_account_id": account["id"],
            "billing_account_id": billing["id"],
            "plan_code": "DPLUS_ADS",
            "dplus_service_profile_id": profile["id"],
        },
        hdrs,
    )
    sub2 = validate_success(ok, 201)
    assert sub2["lifecycle_status"] == "ACTIVE"


def test_duplicate_active_subscription_while_active_rejected(api):
    """PRD §3.4: "the account may not already hold a non-terminal subscription
    on the same plan code (else ERR_DUPLICATE_ACTIVE_SUBSCRIPTION, HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/duplicate_active_subscription_period_overlap
    """
    account, billing, profile, sub1, hdrs = setup_active_standalone_subscription(
        email="ov1b@x.com"
    )
    resp = api.create_subscription(
        {
            "subscriber_account_id": account["id"],
            "billing_account_id": billing["id"],
            "plan_code": "DPLUS_ADS",
            "dplus_service_profile_id": profile["id"],
        },
        hdrs,
    )
    validate_error(resp, "ERR_DUPLICATE_ACTIVE_SUBSCRIPTION", 409)
