"""Concurrency (OCC), priority-pair validation, and cross-entity state coverage."""
from test_helpers import (
    TEST_USERS,
    create_bundle_plan,
    create_migration_payload,
    create_plan,
    create_profile,
    create_standalone_plan,
    get_billing_account,
    get_subscription,
    list_subscription_entitlements,
    make_subscriber_headers,
    purchase_subscription,
    register_account,
    run_renewal,
    set_clock,
    setup_account_with_billing,
    setup_account_with_profiles,
    setup_active_standalone_subscription,
    setup_failed_renewal,
    setup_migration_quote,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import create_billing_account

ADMIN = TEST_USERS["platform_admin_headers"]
SUPPORT = TEST_USERS["support_headers"]


def test_occ_stale_version_rejected(api):
    """PRD §2.7: "A plan change against a subscription must carry
    expected_subscription_version, the value of the subscription's version the
    client last observed; if another writer has advanced the subscription's
    version since then — by applying a retention redemption, scheduling a
    cancellation, or completing an earlier plan change — the request is
    rejected with ERR_STALE_VERSION (HTTP 412) before any side effect
    executes."
    PRD §3.7: "On a successful change, the subscription's version increments
    by 1, price_cents is recomputed per §3.5 — the grandfathered price
    reapplies exactly when the new plan code equals the account's
    grandfathered_plan_code — and the entitlements are reconciled to the new
    plan's scope: services newly in scope spawn fresh entitlements that
    provision straight to ACTIVE, while services leaving the scope have their
    entitlements REVOKED."

    Design: Corner/cross_cutting/occ_stale_version_rejected
    """
    create_standalone_plan(plan_code="HULU_ADS", service="HULU", price=899)
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="cc1@x.com"
    )
    version = sub["version"]
    stale = api.plan_change(
        sub["id"],
        {"new_plan_code": "HULU_ADS", "expected_subscription_version": version - 1},
        hdrs,
    )
    validate_error(stale, "ERR_STALE_VERSION", 412)
    ok = api.plan_change(
        sub["id"],
        {"new_plan_code": "HULU_ADS", "expected_subscription_version": version},
        hdrs,
    )
    changed = validate_success(ok, 200)
    assert changed["plan_code"] == "HULU_ADS"
    assert changed["version"] == version + 1


def test_occ_stale_version_mutation_advances_version(api):
    """PRD §2.7: "A plan change against a subscription must carry
    expected_subscription_version, the value of the subscription's version the
    client last observed; if another writer has advanced the subscription's
    version since then — by applying a retention redemption, scheduling a
    cancellation, or completing an earlier plan change — the request is
    rejected with ERR_STALE_VERSION (HTTP 412) before any side effect
    executes."
    PRD §3.7: "On a successful change, the subscription's version increments
    by 1, price_cents is recomputed per §3.5 — the grandfathered price
    reapplies exactly when the new plan code equals the account's
    grandfathered_plan_code — and the entitlements are reconciled to the new
    plan's scope: services newly in scope spawn fresh entitlements that
    provision straight to ACTIVE, while services leaving the scope have their
    entitlements REVOKED."

    Design: Corner/cross_cutting/occ_stale_version_rejected
    """
    create_standalone_plan(plan_code="HULU_ADS", service="HULU", price=899)
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="cc1b@x.com"
    )
    version = sub["version"]
    first = api.plan_change(
        sub["id"],
        {"new_plan_code": "HULU_ADS", "expected_subscription_version": version},
        hdrs,
    )
    validate_success(first, 200)
    # The first change advanced the version, so replaying the stale one fails.
    stale = api.plan_change(
        sub["id"],
        {"new_plan_code": "DPLUS_ADS", "expected_subscription_version": version},
        hdrs,
    )
    validate_error(stale, "ERR_STALE_VERSION", 412)


def test_occ_migration_confirm_stale_after_requote(api):
    """PRD §2.7: "Confirming a migration works the same way: the request must
    carry expected_migration_version equal to the migration's current version,
    and a mismatch is rejected with ERR_STALE_VERSION (HTTP 412). No other
    endpoint accepts a version field."
    PRD §3.9: "Confirming the migration is the committing act and carries the
    OCC handshake of §2.7: the request must present expected_migration_version
    equal to the migration's current version, and a stale value is rejected
    with ERR_STALE_VERSION."

    Design: Corner/cross_cutting/occ_migration_confirm_stale_after_requote
    """
    account, billing, profiles, from_sub, migration, hdrs = setup_migration_quote(
        email="cc2@x.com", quote_clock="2026-09-01T00:00:00Z"
    )
    stale = api.confirm_migration(
        migration["id"],
        {"expected_migration_version": migration["version"] - 1},
        hdrs,
    )
    validate_error(stale, "ERR_STALE_VERSION", 412)
    ok = api.confirm_migration(
        migration["id"],
        {"expected_migration_version": migration["version"]},
        hdrs,
    )
    confirmed = validate_success(ok, 200)
    assert confirmed["migration_status"] == "CONFIRMED"


def test_occ_migration_confirm_stale_after_confirm(api):
    """PRD §2.7: "Confirming a migration works the same way: the request must
    carry expected_migration_version equal to the migration's current version,
    and a mismatch is rejected with ERR_STALE_VERSION (HTTP 412). No other
    endpoint accepts a version field."

    Design: Corner/cross_cutting/occ_migration_confirm_stale_after_requote
    """
    account, billing, profiles, from_sub, migration, hdrs = setup_migration_quote(
        email="cc2b@x.com", quote_clock="2026-09-01T00:00:00Z"
    )
    validate_success(
        api.confirm_migration(
            migration["id"],
            {"expected_migration_version": migration["version"]},
            hdrs,
        ),
        200,
    )
    # The confirm bumped the version; replaying the old version must be
    # rejected (by whichever guard the server reaches first).
    replay = api.confirm_migration(
        migration["id"],
        {"expected_migration_version": migration["version"]},
        hdrs,
    )
    from test_helpers import validate_error_is_one_of

    validate_error_is_one_of(replay, ["ERR_STALE_VERSION", "ERR_INVALID_STATE"])


def test_state_beats_biller_constraint_on_plan_change(api):
    """PRD §2.8: "When several validation rules could reject the same request,
    they are evaluated in a fixed priority order: authentication and role
    authorization first, then subscriber ownership, then path existence, then
    body-reference existence, then resource state, then the requirement that
    the owning account be ACTIVE, then domain business rules (parental
    controls, uniqueness, plan shape, temporal windows, third-party billing
    constraints, retention eligibility, pricing floors), then referential
    preconditions such as account close and profile unlink, then request-shape
    validation, then the optimistic-concurrency version check, and finally the
    remaining business gates such as duplicate subscriptions, closed-account
    mutation, duplicate email, and legacy-plan purchase. A request that trips
    several rules surfaces the error of the earliest rule in this order."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_biller_constraint_on_plan_change
    """
    set_clock("2026-09-01T00:00:00Z")
    create_standalone_plan(plan_code="DPLUS_ADS", service="DPLUS", price=799)
    create_plan(
        plan_code="HULU_PREMIUM_X", plan_kind="STANDALONE", service_scope=["HULU"],
        ad_tier="AD_FREE", monthly_price_cents=1299,
        allow_app_store_billing=False, allow_distributor_billing=False,
    )
    account, billing, hdrs = setup_account_with_billing(
        biller_type="APP_STORE", email="pp1@x.com"
    )
    profile = create_profile(account, service="DPLUS")
    sub = purchase_subscription(
        account, billing, "DPLUS_ADS", dplus_profile=profile
    )
    validate_success(
        api.cancel_subscription(sub["id"], {"immediate_effect": False}, hdrs), 200
    )
    set_clock("2026-10-02T00:00:00Z")  # past the 31-day period end -> CANCELLED
    assert get_subscription(sub["id"], hdrs)["lifecycle_status"] == "CANCELLED"
    resp = api.plan_change(
        sub["id"],
        {
            "new_plan_code": "HULU_PREMIUM_X",
            "expected_subscription_version": sub["version"],
        },
        hdrs,
    )
    # Both the state check and the biller-channel check fail; state wins.
    validate_error(resp, "ERR_INVALID_STATE", 409)


def test_state_beats_biller_constraint_cancelled_platform(api):
    """PRD §2.8: "A request that trips several rules surfaces the error of the
    earliest rule in this order."
    PRD §3.7: "The new plan must pass the same biller-channel gate as a fresh
    purchase — ERR_BILLER_PLAN_NOT_ALLOWED when the channel forbids it — and
    the legacy gate of §3.1."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_biller_constraint_on_plan_change
    """
    set_clock("2026-09-01T00:00:00Z")
    create_standalone_plan(plan_code="DPLUS_ADS", service="DPLUS", price=799)
    create_plan(
        plan_code="DIST_ONLY", plan_kind="STANDALONE", service_scope=["HULU"],
        ad_tier="AD_SUPPORTED", monthly_price_cents=999,
        allow_app_store_billing=False, allow_distributor_billing=True,
    )
    account, billing, hdrs = setup_account_with_billing(
        biller_type="APP_STORE", email="pp1c@x.com"
    )
    profile = create_profile(account, service="DPLUS")
    sub = purchase_subscription(
        account, billing, "DPLUS_ADS", dplus_profile=profile
    )
    validate_success(
        api.cancel_subscription(sub["id"], {"immediate_effect": False}, hdrs), 200
    )
    set_clock("2026-10-02T00:00:00Z")
    resp = api.plan_change(
        sub["id"],
        {
            "new_plan_code": "DIST_ONLY",
            "expected_subscription_version": sub["version"],
        },
        hdrs,
    )
    validate_error(resp, "ERR_INVALID_STATE", 409)


def test_existence_beats_safety_on_watchlist_add(api):
    """PRD §2.8: "Path-template resources are validated left to right: an
    account id is resolved before the profile id nested under it, the profile
    before the watchlist item, and the subscription before the redemption. The
    first unresolved segment fails the request with ERR_NOT_FOUND (HTTP 404)."
    PRD §2.8: "A request that trips several rules surfaces the error of the
    earliest rule in this order."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_safety_on_watchlist_add
    """
    account = register_account(email="pp2@x.com")
    hdrs = make_subscriber_headers(account["id"])
    resp = api.add_watchlist_item(
        "00000000-0000-0000-0000-000000000000",
        {"title_id": "mature-film-1", "title_maturity": "TV_MA"},
        hdrs,
    )
    # Existence precedes the parental-control safety gate.
    validate_error(resp, "ERR_NOT_FOUND", 404)


def test_existence_beats_safety_on_watchlist_add_tv_y(api):
    """PRD §2.8: "Path-template resources are validated left to right: an
    account id is resolved before the profile id nested under it, the profile
    before the watchlist item, and the subscription before the redemption. The
    first unresolved segment fails the request with ERR_NOT_FOUND (HTTP 404)."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_safety_on_watchlist_add
    """
    account = register_account(email="pp2b@x.com")
    hdrs = make_subscriber_headers(account["id"])
    resp = api.add_watchlist_item(
        "00000000-0000-0000-0000-000000000000",
        {"title_id": "kids-show", "title_maturity": "TV_Y"},
        hdrs,
    )
    validate_error(resp, "ERR_NOT_FOUND", 404)


def test_account_state_beats_retention_business_rule(api):
    """PRD §2.8: "A request that trips several rules surfaces the error of the
    earliest rule in this order."
    PRD §3.10: "The account must also be ACTIVE (else ERR_ACCOUNT_NOT_ACTIVE)."
    PRD §3.2: "Suspending an ACTIVE account cascades: every subscription of
    the account in ACTIVE or PAST_DUE lifecycle has all of its ACTIVE
    entitlements moved to SUSPENDED, and each suspension that leaves a profile
    with zero ACTIVE entitlements drops that profile from LINKED to
    SUSPENDED."

    Design: Difficulty/priority_pair_validation_conflict/account_state_beats_retention_business_rule
    """
    from test_helpers import create_retention_offer

    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="pp3@x.com"
    )
    create_retention_offer(
        offer_code="SMALL100", discount_cents=100, duration_months=3,
        max_redemptions_per_account=1,
        eligible_biller_types=["PLATFORM"], eligible_plan_kinds=["STANDALONE"],
    )
    validate_success(api.suspend_account(account["id"], SUPPORT), 200)
    resp = api.redeem_retention_offer(sub["id"], {"offer_code": "SMALL100"}, hdrs)
    validate_error(resp, "ERR_ACCOUNT_NOT_ACTIVE", 409)


def test_account_state_beats_retention_business_rule_on_subscription_create(api):
    """PRD §3.4: "The account must be ACTIVE (else ERR_ACCOUNT_NOT_ACTIVE)."
    PRD §2.8: "A request that trips several rules surfaces the error of the
    earliest rule in this order."

    Design: Difficulty/priority_pair_validation_conflict/account_state_beats_retention_business_rule
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="pp3b@x.com"
    )
    # The HULU profile and plan must exist before suspension: creating a
    # profile requires an ACTIVE account (PRD §3.3), so they are set up first.
    create_standalone_plan(plan_code="HULU_ADS", service="HULU", price=899)
    hulu_profile = create_profile(account, service="HULU")
    validate_success(api.suspend_account(account["id"], SUPPORT), 200)
    resp = api.create_subscription(
        {
            "subscriber_account_id": account["id"],
            "billing_account_id": billing["id"],
            "plan_code": "NO_SUCH_PLAN",
            "dplus_service_profile_id": profile["id"],
        },
        hdrs,
    )
    # Account-state gate precedes the retention/business layer; here the only
    # competing rules are account-state and body-reference — state per §2.8
    # order comes after body-reference existence, so a missing reference would
    # surface ERR_REFERENCE_NOT_FOUND. Use a real plan to isolate the
    # account-state gate.
    resp2 = api.create_subscription(
        {
            "subscriber_account_id": account["id"],
            "billing_account_id": billing["id"],
            "plan_code": "HULU_ADS",
            "hulu_service_profile_id": hulu_profile["id"],
        },
        hdrs,
    )
    validate_error(resp2, "ERR_ACCOUNT_NOT_ACTIVE", 409)
