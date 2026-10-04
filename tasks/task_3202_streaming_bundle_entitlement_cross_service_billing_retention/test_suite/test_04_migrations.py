"""Migration proration, confirm cascade, and migration lifecycle coverage."""
from test_helpers import (
    TEST_USERS,
    create_bundle_plan,
    create_migration_payload,
    get_account,
    list_subscription_entitlements,
    set_clock,
    setup_active_bundle_subscription,
    setup_active_standalone_subscription,
    setup_migration_quote,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import create_profile, create_standalone_plan, purchase_subscription

ADMIN = TEST_USERS["platform_admin_headers"]


def test_migration_proration_quote_vs_confirm_clock_gap(api):
    """PRD §3.9: "The elapsed days are the whole-day count from period_start
    to the quote instant; the remaining days are days_total minus the elapsed
    days; the credit is the monthly figure multiplied by the remaining days
    and divided by days_total, rounded down to whole cents. The result is
    stored as proration_credit_cents with proration_method_used recorded as
    CHRONOLOGICAL_REMAINING."
    PRD §3.9: "At confirm, the credit is recomputed with the forward-looking
    variant and can shrink relative to the quote."

    Design: Difficulty/dual_variant_calc/migration_proration_quote_vs_confirm_clock_gap
    """
    account, billing, profiles, from_sub, migration, hdrs = setup_migration_quote(
        email="dv1@x.com"
    )
    # Quote at 2026-09-06: floor(799 * 25 / 30) = 665.
    assert migration["proration_credit_cents"] == 665, (
        f"quote credit must be 665, got {migration['proration_credit_cents']}"
    )
    assert migration["proration_method_used"] == "CHRONOLOGICAL_REMAINING"
    set_clock("2026-09-11T00:00:00Z")
    resp = api.confirm_migration(
        migration["id"], {"expected_migration_version": migration["version"]}, hdrs
    )
    confirmed = validate_success(resp, 200)
    # Confirm at 2026-09-11: floor(799 * 20 / 30) = 532.
    assert confirmed["proration_credit_cents"] == 532, (
        f"confirm credit must be 532, got {confirmed['proration_credit_cents']}"
    )
    assert confirmed["proration_method_used"] == "FORWARD_LOOKING_PERIOD"
    assert get_account(account["id"], hdrs)["account_credit_cents"] == 532


def test_migration_proration_confirm_after_renewal_consumed_credit(api):
    """PRD §3.9: "The same day arithmetic runs against the confirm instant to
    produce a base credit; then every invoice of the source subscription —
    ISSUED or PAID — whose period_start is at or after the migration row's
    created_at contributes its credit_applied_cents to a consumed total; the
    confirmed credit is the base minus the consumed amount, floored at zero."
    PRD §3.9: "The source subscription moves from ACTIVE to MIGRATED_OUT and
    its entitlements are revoked."

    Design: Difficulty/dual_variant_calc/migration_proration_confirm_after_renewal_consumed_credit
    """
    account, billing, profiles, from_sub, migration, hdrs = setup_migration_quote(
        email="dv2@x.com"
    )
    set_clock("2026-09-11T00:00:00Z")
    resp = api.confirm_migration(
        migration["id"], {"expected_migration_version": migration["version"]}, hdrs
    )
    confirmed = validate_success(resp, 200)
    # No intervening invoices: credit is purely the clock-shifted base.
    assert confirmed["proration_credit_cents"] == 532
    assert confirmed["migration_status"] == "CONFIRMED"
    from_after = validate_success(api.get_subscription(from_sub["id"], hdrs), 200)
    assert from_after["lifecycle_status"] == "MIGRATED_OUT"
    assert get_account(account["id"], hdrs)["account_credit_cents"] == 532


def test_grandfathered_lock_initial_vs_relock_after_full_churn(api):
    """PRD §3.5: "First, if the account's grandfathered_price_cents is still
    null, the lock is written: grandfathered_plan_code becomes the activating
    subscription's plan code and grandfathered_price_cents becomes that plan's
    current monthly_price_cents list price."
    PRD §3.5: "When every prior subscription has gone terminal — all CANCELLED
    or MIGRATED_OUT — a subsequent new subscription reaching ACTIVE re-locks at
    its own plan's current list price, discarding the stale lock."

    Design: Difficulty/dual_variant_calc/grandfathered_lock_initial_vs_relock_after_full_churn
    """
    account, billing, profile, sub1, hdrs = setup_active_standalone_subscription(
        email="dv3@x.com"
    )
    acct = get_account(account["id"], hdrs)
    assert acct["grandfathered_plan_code"] == "DPLUS_ADS"
    assert acct["grandfathered_price_cents"] == 799
    create_standalone_plan(plan_code="DPLUS_ADS_V2", service="DPLUS", price=899)
    validate_success(
        api.cancel_subscription(sub1["id"], {"immediate_effect": True}, hdrs), 200
    )
    set_clock("2026-09-02T00:00:00Z")
    assert get_account(account["id"], hdrs)["grandfathered_price_cents"] == 799
    sub2 = purchase_subscription(
        account, billing, "DPLUS_ADS_V2", dplus_profile=profile
    )
    acct_after = get_account(account["id"], hdrs)
    assert acct_after["grandfathered_plan_code"] == "DPLUS_ADS_V2"
    assert acct_after["grandfathered_price_cents"] == 899
    assert sub2["price_cents"] == 899


def test_grandfathered_lock_not_rederived_while_subscription_lives(api):
    """PRD §3.5: "The lock is never re-derived while any subscription of the
    account is in PENDING_ENTITLEMENT, ACTIVE, PAST_DUE, or CANCEL_SCHEDULED."

    Design: Difficulty/dual_variant_calc/grandfathered_lock_initial_vs_relock_after_full_churn
    """
    account, billing, profile, sub1, hdrs = setup_active_standalone_subscription(
        email="dv3b@x.com"
    )
    create_standalone_plan(plan_code="DPLUS_ADS_V2", service="DPLUS", price=899)
    # While sub1 is still ACTIVE, a second subscription must NOT re-lock.
    sub2 = purchase_subscription(
        account, billing, "DPLUS_ADS_V2", dplus_profile=profile
    )
    acct = get_account(account["id"], hdrs)
    assert acct["grandfathered_plan_code"] == "DPLUS_ADS"
    assert acct["grandfathered_price_cents"] == 799
    # sub2's plan code does not match the lock, so it bills at list price.
    assert sub2["price_cents"] == 899


def test_migration_confirm_three_hop_cascade(api):
    """PRD §3.9: "The source subscription moves from ACTIVE to MIGRATED_OUT
    and its entitlements are revoked. The new bundle subscription is created
    in PENDING_ENTITLEMENT with entitlements spawned per the target plan's
    scope and provisioned synchronously to ACTIVE, which bubbles the new
    subscription to ACTIVE; its migration_id points back to the migration, as
    does the source subscription's."

    Design: Difficulty/transitive_cascade/migration_confirm_three_hop_cascade
    """
    account, billing, profiles, from_sub, migration, hdrs = setup_migration_quote(
        email="tc2@x.com"
    )
    resp = api.confirm_migration(
        migration["id"], {"expected_migration_version": migration["version"]}, hdrs
    )
    confirmed = validate_success(resp, 200)
    to_sub_id = confirmed["to_subscription_id"]
    assert to_sub_id, "confirm must produce a to_subscription_id"
    from_after = validate_success(api.get_subscription(from_sub["id"], hdrs), 200)
    assert from_after["lifecycle_status"] == "MIGRATED_OUT"
    to_sub = validate_success(api.get_subscription(to_sub_id, hdrs), 200)
    assert to_sub["lifecycle_status"] == "ACTIVE"
    assert to_sub["plan_code"] == "DUO_PREMIUM"
    from_ents = list_subscription_entitlements(from_sub["id"], hdrs)
    assert all(e["entitlement_status"] == "REVOKED" for e in from_ents)
    to_ents = list_subscription_entitlements(to_sub_id, hdrs)
    assert len(to_ents) == 2
    assert sorted(e["service"] for e in to_ents) == ["DPLUS", "HULU"]
    assert all(e["entitlement_status"] == "ACTIVE" for e in to_ents)
    dplus = validate_success(api.get_service_profile(profiles["DPLUS"]["id"], hdrs), 200)
    hulu = validate_success(api.get_service_profile(profiles["HULU"]["id"], hdrs), 200)
    assert dplus["profile_status"] == "LINKED"
    assert hulu["profile_status"] == "LINKED"


def test_migration_confirm_posts_credit_and_audit_invoice(api):
    """PRD §3.9: "The recomputed credit is posted to the account's
    account_credit_cents, a MIGRATION_ADJUSTMENT invoice with gross_cents of 0
    and credit_applied_cents of 0 is issued as the audit anchor, and the
    migration's version increments by 1."

    Design: Difficulty/transitive_cascade/migration_confirm_three_hop_cascade
    """
    account, billing, profiles, from_sub, migration, hdrs = setup_migration_quote(
        email="tc2b@x.com"
    )
    version_before = migration["version"]
    resp = api.confirm_migration(
        migration["id"], {"expected_migration_version": version_before}, hdrs
    )
    confirmed = validate_success(resp, 200)
    assert confirmed["version"] == version_before + 1
    assert confirmed["proration_credit_cents"] == 665  # quote/confirm same instant
    assert get_account(account["id"], hdrs)["account_credit_cents"] == 665
    invoices = validate_success(
        api.list_billing_account_invoices(billing["id"], hdrs), 200
    )
    adjustments = [i for i in invoices if i["invoice_kind"] == "MIGRATION_ADJUSTMENT"]
    assert len(adjustments) == 1, f"expected exactly one MIGRATION_ADJUSTMENT invoice, got {len(adjustments)}"
    assert adjustments[0]["gross_cents"] == 0
    assert adjustments[0]["credit_applied_cents"] == 0


def test_migration_void_terminal_then_confirm_rejected(api):
    """PRD §3.9: "Voiding a quoted migration — explicitly, or automatically
    when the source subscription leaves ACTIVE before confirm — discards the
    quote with no ledger movement. Both CONFIRMED and VOIDED are terminal; a
    migration never leaves either state."
    PRD §5: "ERR_INVALID_STATE | 409".

    Design: Corner/state_machines/migration_void_terminal_then_confirm_rejected
    """
    account, billing, profiles, from_sub, migration, hdrs = setup_migration_quote(
        email="sm5@x.com", quote_clock="2026-09-01T00:00:00Z"
    )
    validate_success(api.void_migration(migration["id"], hdrs), 200)
    resp = api.confirm_migration(
        migration["id"], {"expected_migration_version": migration["version"]}, hdrs
    )
    validate_error(resp, "ERR_INVALID_STATE", 409)


def test_migration_shape_source_must_be_standalone(api):
    """PRD §3.9: "The source must be a subscription on a STANDALONE plan and
    the target a BUNDLE plan — any other pairing is rejected with
    ERR_MIGRATION_SHAPE (HTTP 422); the source must be ACTIVE at quote time or
    the quote fails with ERR_MIGRATION_SOURCE_NOT_ACTIVE (HTTP 409); the owning
    account must be ACTIVE (else ERR_ACCOUNT_NOT_ACTIVE); and the target plan
    must be sellable through the account's biller (else
    ERR_BILLER_PLAN_NOT_ALLOWED)."

    Design: Corner/validations/migration_shape_source_must_be_standalone
    """
    create_bundle_plan(plan_code="DUO_PREMIUM")
    account, billing, profiles, sub, hdrs = setup_active_bundle_subscription(
        email="val4@x.com"
    )
    resp = api.create_migration(
        create_migration_payload(sub["id"], "DUO_PREMIUM"), hdrs
    )
    validate_error(resp, "ERR_MIGRATION_SHAPE", 422)


def test_migration_confirm_exactly_at_period_end_rejected(api):
    """PRD §3.9: "Confirming is valid only inside the quoted period — the
    current logical clock must be strictly before the source subscription's
    period_end; an attempt at or after that instant fails with
    ERR_MIGRATION_WINDOW_CLOSED (HTTP 422)."

    Design: Difficulty/boundary_precision_check/migration_confirm_exactly_at_period_end_rejected
    """
    account, billing, profiles, from_sub, migration, hdrs = setup_migration_quote(
        email="bp1@x.com"
    )
    set_clock("2026-10-01T00:00:00Z")
    resp = api.confirm_migration(
        migration["id"], {"expected_migration_version": migration["version"]}, hdrs
    )
    validate_error(resp, "ERR_MIGRATION_WINDOW_CLOSED", 422)
    mig = validate_success(api.get_migration(migration["id"], hdrs), 200)
    assert mig["migration_status"] == "QUOTED"


def test_migration_confirm_one_second_before_period_end_succeeds(api):
    """PRD §3.9: "Confirming is valid only inside the quoted period — the
    current logical clock must be strictly before the source subscription's
    period_end; an attempt at or after that instant fails with
    ERR_MIGRATION_WINDOW_CLOSED (HTTP 422)."

    Design: Difficulty/boundary_precision_check/migration_confirm_exactly_at_period_end_rejected
    """
    account, billing, profiles, from_sub, migration, hdrs = setup_migration_quote(
        email="bp1b@x.com"
    )
    set_clock("2026-09-30T23:59:59Z")
    resp = api.confirm_migration(
        migration["id"], {"expected_migration_version": migration["version"]}, hdrs
    )
    confirmed = validate_success(resp, 200)
    assert confirmed["migration_status"] == "CONFIRMED"


def test_proration_third_party_31_day_period(api):
    """PRD §2.10: "Period length depends on who collects the money: exactly 30
    days for a PLATFORM biller, exactly 31 days for APP_STORE and DISTRIBUTOR
    billers."
    PRD §3.9: "Let days_total be the whole-day length of the source
    subscription's current billing period — 30 days for PLATFORM, 31 days for
    third-party billers — and let the monthly figure be the source
    subscription's effective monthly price under §3.5 (the grandfathered price
    when locked, else the plan list price)."

    Design: Corner/calculations/proration_third_party_31_day_period
    """
    create_bundle_plan(plan_code="DUO_PREMIUM")
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="calc1@x.com", biller_type="APP_STORE"
    )
    billing_now = validate_success(api.get_billing_account(billing["id"], hdrs), 200)
    assert billing_now["period_end"].startswith("2026-10-02T00:00:00"), (
        f"APP_STORE period_end must be 31 days out (2026-10-02), got {billing_now['period_end']}"
    )
    set_clock("2026-09-06T00:00:00Z")
    resp = api.create_migration(
        create_migration_payload(sub["id"], "DUO_PREMIUM"), hdrs
    )
    migration = validate_success(resp, 201)
    # floor(799 * 26 / 31) = 670.
    assert migration["proration_credit_cents"] == 670, (
        f"31-day proration must be 670, got {migration['proration_credit_cents']}"
    )


def test_migration_quote_uses_chronological_variant(api):
    """PRD §3.9: "The elapsed days are the whole-day count from period_start
    to the quote instant; the remaining days are days_total minus the elapsed
    days; the credit is the monthly figure multiplied by the remaining days
    and divided by days_total, rounded down to whole cents. The result is
    stored as proration_credit_cents with proration_method_used recorded as
    CHRONOLOGICAL_REMAINING."

    Design: Difficulty/dual_variant_calc/migration_proration_quote_vs_confirm_clock_gap
    """
    account, billing, profiles, from_sub, migration, hdrs = setup_migration_quote(
        email="dv1c@x.com"
    )
    # Quoted at 2026-09-06 in a 30-day PLATFORM period: floor(799*25/30)=665.
    assert migration["migration_status"] == "QUOTED"
    assert migration["proration_credit_cents"] == 665
    assert migration["proration_method_used"] == "CHRONOLOGICAL_REMAINING"
    # The quote is not a ledger movement: no credit is posted before confirm.
    assert get_account(account["id"], hdrs)["account_credit_cents"] == 0


def test_migration_confirm_consumed_credit_shrinks_below_quote(api):
    """PRD §3.9: "At confirm, the credit is recomputed with the
    forward-looking variant and can shrink relative to the quote. The same day
    arithmetic runs against the confirm instant to produce a base credit; then
    every invoice of the source subscription — ISSUED or PAID — whose
    period_start is at or after the migration row's created_at contributes its
    credit_applied_cents to a consumed total; the confirmed credit is the base
    minus the consumed amount, floored at zero."
    PRD §3.9: "The source must be a subscription on a STANDALONE plan and
    the target a BUNDLE plan — any other pairing is rejected with
    ERR_MIGRATION_SHAPE (HTTP 422); the source must be ACTIVE at quote time or
    the quote fails with ERR_MIGRATION_SOURCE_NOT_ACTIVE (HTTP 409); the owning
    account must be ACTIVE (else ERR_ACCOUNT_NOT_ACTIVE); and the target plan
    must be sellable through the account's biller (else
    ERR_BILLER_PLAN_NOT_ALLOWED)."

    Design: Difficulty/dual_variant_calc/migration_proration_confirm_after_renewal_consumed_credit
    """
    # Quote and confirm at the SAME clock instant: no clock movement, no
    # intervening invoices, so the confirm variant reproduces the quote value
    # exactly (consumed == 0, base unchanged).
    account, billing, profiles, from_sub, migration, hdrs = setup_migration_quote(
        email="dv2b@x.com"
    )
    quoted_credit = migration["proration_credit_cents"]
    resp = api.confirm_migration(
        migration["id"], {"expected_migration_version": migration["version"]}, hdrs
    )
    confirmed = validate_success(resp, 200)
    assert confirmed["proration_credit_cents"] == quoted_credit
    assert confirmed["proration_method_used"] == "FORWARD_LOOKING_PERIOD"
    assert confirmed["migration_status"] == "CONFIRMED"
    from_after = validate_success(api.get_subscription(from_sub["id"], hdrs), 200)
    assert from_after["lifecycle_status"] == "MIGRATED_OUT"
