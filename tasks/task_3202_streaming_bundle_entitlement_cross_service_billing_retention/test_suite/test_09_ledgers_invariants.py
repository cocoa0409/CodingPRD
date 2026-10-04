"""Ledger invariants: revenue allocation, credit conservation, cross-entity
gates, and account-close compensation."""
from test_helpers import (
    TEST_USERS,
    create_retention_offer,
    get_account,
    get_profile,
    get_subscription,
    list_entitlements_for_profile,
    list_subscription_entitlements,
    purchase_subscription,
    redeem_offer,
    run_renewal,
    set_clock,
    setup_active_bundle_subscription,
    setup_active_standalone_subscription,
    setup_failed_renewal,
    setup_migration_quote,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SUPPORT = TEST_USERS["support_headers"]


def test_revenue_allocation_rounding_remainder_absorption(api):
    """PRD §3.12: "For a bundle, services are processed in the fixed order
    DPLUS then HULU: the DPLUS row receives the net amount multiplied by the
    DPLUS component weight, rounded half-up to whole cents, and the HULU row
    receives whatever remains — the net minus the DPLUS allocation — so the
    rows always sum exactly to net_cents."
    PRD §3.4: "The initial invoice (kind INITIAL) is issued and collected
    inline, transitioning straight from ISSUED to PAID, and revenue allocation
    rows are created for it."

    Design: Difficulty/combinatorial_formula/revenue_allocation_rounding_remainder_absorption
    """
    account, billing, profiles, sub, hdrs = setup_active_bundle_subscription(
        email="cf2@x.com"
    )
    invoices = validate_success(
        api.list_billing_account_invoices(billing["id"], hdrs), 200
    )
    initial = [i for i in invoices if i["invoice_kind"] == "INITIAL"][0]
    assert initial["net_cents"] == 1099
    rows = validate_success(
        api.list_revenue_allocations(initial["id"], ADMIN), 200
    )
    assert len(rows) == 2
    by_service = {r["service"]: r["allocated_cents"] for r in rows}
    # round_half_up(1099 * 0.45) = round_half_up(494.55) = 495; HULU absorbs.
    assert by_service["DPLUS"] == 495, f"DPLUS row must be 495, got {by_service['DPLUS']}"
    assert by_service["HULU"] == 604, f"HULU row must be 604, got {by_service['HULU']}"
    assert sum(r["allocated_cents"] for r in rows) == 1099


def test_revenue_allocation_standalone_single_row(api):
    """PRD §3.12: "For a standalone plan there is exactly one allocation row,
    crediting the entire net_cents to the covered service."
    PRD §3.4: "The initial invoice (kind INITIAL) is issued and collected
    inline, transitioning straight from ISSUED to PAID, and revenue allocation
    rows are created for it."

    Design: Difficulty/combinatorial_formula/revenue_allocation_rounding_remainder_absorption
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="cf2b@x.com"
    )
    invoices = validate_success(
        api.list_billing_account_invoices(billing["id"], hdrs), 200
    )
    initial = [i for i in invoices if i["invoice_kind"] == "INITIAL"][0]
    rows = validate_success(api.list_revenue_allocations(initial["id"], ADMIN), 200)
    assert len(rows) == 1
    assert rows[0]["service"] == "DPLUS"
    assert rows[0]["allocated_cents"] == initial["net_cents"] == 799


def test_revenue_allocation_sum_invariant_under_retry(api):
    """PRD §3.12: "When an invoice reaches PAID — whether directly on issue or
    through a retry — the collected net_cents is split across services."
    PRD §3.12: "the HULU row receives whatever remains — the net minus the
    DPLUS allocation — so the rows always sum exactly to net_cents."
    PRD §3.11: "A successful retry pays the invoice, runs revenue allocation
    for it, and unwinds the cascade: consecutive_failure_count resets to 0,
    the billing account returns to CURRENT, the subscription returns to
    PAID_UP and ACTIVE, suspended entitlements reactivate, and affected
    profiles return to LINKED."

    Design: Difficulty/compensating_invariant/revenue_allocation_sum_invariant_under_retry
    """
    account, billing, profiles, sub, hdrs = setup_active_bundle_subscription(
        email="ci2@x.com"
    )
    set_clock("2026-10-01T00:00:00Z")
    result = run_renewal(billing["id"], "FAILED")
    invoice_id = result["invoice_id"]
    validate_success(api.retry_payment(invoice_id, hdrs), 200)
    invoice = validate_success(api.get_invoice(invoice_id, hdrs), 200)
    assert invoice["invoice_status"] == "PAID"
    rows = validate_success(api.list_revenue_allocations(invoice_id, ADMIN), 200)
    assert len(rows) == 2, (
        f"exactly one row-set must exist (no double allocation), got {len(rows)}"
    )
    by_service = {r["service"]: r["allocated_cents"] for r in rows}
    assert by_service["DPLUS"] == 495
    assert by_service["HULU"] == 604
    assert sum(r["allocated_cents"] for r in rows) == invoice["net_cents"] == 1099


def test_revenue_allocation_no_rows_while_invoice_failed(api):
    """PRD §3.12: "When an invoice reaches PAID — whether directly on issue or
    through a retry — the collected net_cents is split across services."
    PRD §3.11: "On a failed outcome the invoice moves to FAILED and the
    dunning cascade begins: the billing account drops from CURRENT to PAST_DUE
    with consecutive_failure_count incremented by 1; the subscription's
    billing_dimension moves from PAID_UP to GRACE and its lifecycle from
    ACTIVE to PAST_DUE; every ACTIVE entitlement of the subscription suspends;
    and each profile left with zero active entitlements drops from LINKED to
    SUSPENDED."

    Design: Difficulty/compensating_invariant/revenue_allocation_sum_invariant_under_retry
    """
    account, billing, profiles, sub, hdrs = setup_active_bundle_subscription(
        email="ci2b@x.com"
    )
    set_clock("2026-10-01T00:00:00Z")
    result = run_renewal(billing["id"], "FAILED")
    invoice = validate_success(api.get_invoice(result["invoice_id"], hdrs), 200)
    assert invoice["invoice_status"] == "FAILED"
    # Allocation happens only when the invoice reaches PAID.
    rows = validate_success(
        api.list_revenue_allocations(result["invoice_id"], ADMIN), 200
    )
    assert rows == [] or len(rows) == 0, (
        f"a FAILED invoice must have no allocation rows, got {len(rows)}"
    )


def test_migration_credit_conserved_through_renewal(api):
    """PRD §3.11: "For each, the gross is the subscription's effective price
    per §3.5; the credit applied is the smaller of the account's
    account_credit_cents and the gross; the net is the gross minus the credit
    applied, and the account's credit balance is reduced by the amount
    consumed. A RENEWAL invoice (kind INITIAL for the first period, RENEWAL
    thereafter) records gross_cents, credit_applied_cents, and net_cents
    alongside the billed period_start and period_end. The account's
    account_credit_cents never goes negative."
    PRD §3.9: "The recomputed credit is posted to the account's
    account_credit_cents, a MIGRATION_ADJUSTMENT invoice with gross_cents of 0
    and credit_applied_cents of 0 is issued as the audit anchor, and the
    migration's version increments by 1."

    Design: Difficulty/compensating_invariant/migration_credit_conserved_through_renewal
    """
    account, billing, profiles, from_sub, migration, hdrs = setup_migration_quote(
        email="ci1@x.com", quote_clock="2026-09-01T00:00:00Z"
    )
    set_clock("2026-09-11T00:00:00Z")
    validate_success(
        api.confirm_migration(
            migration["id"],
            {"expected_migration_version": migration["version"]},
            hdrs,
        ),
        200,
    )
    assert get_account(account["id"], hdrs)["account_credit_cents"] == 532
    set_clock("2026-10-01T00:00:00Z")
    result = run_renewal(billing["id"], "SUCCEEDED")
    invoice = validate_success(api.get_invoice(result["invoice_id"], hdrs), 200)
    assert invoice["gross_cents"] == 1999
    assert invoice["credit_applied_cents"] == 532
    assert invoice["net_cents"] == 1467
    assert get_account(account["id"], hdrs)["account_credit_cents"] == 0


def test_migration_credit_partial_consumption_keeps_remainder(api):
    """PRD §3.11: "For each, the gross is the subscription's effective price
    per §3.5; the credit applied is the smaller of the account's
    account_credit_cents and the gross; the net is the gross minus the credit
    applied, and the account's credit balance is reduced by the amount
    consumed. A RENEWAL invoice (kind INITIAL for the first period, RENEWAL
    thereafter) records gross_cents, credit_applied_cents, and net_cents
    alongside the billed period_start and period_end. The account's
    account_credit_cents never goes negative."
    PRD §3.9: "The recomputed credit is posted to the account's
    account_credit_cents, a MIGRATION_ADJUSTMENT invoice with gross_cents of 0
    and credit_applied_cents of 0 is issued as the audit anchor, and the
    migration's version increments by 1."

    Design: Difficulty/compensating_invariant/migration_credit_conserved_through_renewal
    """
    # Quote at period start (full 30 days remaining) so the confirmed credit
    # floor(799 * 30 / 30) = 799 exceeds the renewal gross.
    account, billing, profiles, from_sub, migration, hdrs = setup_migration_quote(
        email="ci1b@x.com", quote_clock="2026-09-01T00:00:00Z"
    )
    validate_success(
        api.confirm_migration(
            migration["id"],
            {"expected_migration_version": migration["version"]},
            hdrs,
        ),
        200,
    )
    assert get_account(account["id"], hdrs)["account_credit_cents"] == 799
    set_clock("2026-10-01T00:00:00Z")
    result = run_renewal(billing["id"], "SUCCEEDED")
    invoice = validate_success(api.get_invoice(result["invoice_id"], hdrs), 200)
    # The renewal bills the bundle at the grandfathered-locked base for
    # DPLUS_ADS? No — the new bundle's plan code differs from the lock, so it
    # bills at the bundle list price; credit consumed is min(799, gross).
    assert invoice["credit_applied_cents"] == min(799, invoice["gross_cents"])
    assert invoice["net_cents"] == invoice["gross_cents"] - invoice["credit_applied_cents"]
    assert get_account(account["id"], hdrs)["account_credit_cents"] == (
        799 - invoice["credit_applied_cents"]
    )


def test_revenue_report_aggregates_paid_only_in_window(api):
    """PRD §3.12: "The revenue report aggregates allocations over a
    closed-open window from from_iso8601 to to_iso8601, optionally narrowed to
    one service. Only PAID invoices contribute. The report returns the
    total_cents collected in the window, a per_service breakdown, and the
    invoice_count of contributing invoices."

    Design: Corner/endpoints/revenue_report_aggregates_paid_only_in_window
    """
    account, billing, profiles, sub, hdrs = setup_active_bundle_subscription(
        email="ep1@x.com"
    )
    # Renewal fails at 2026-10-01 (window end) — FAILED invoices contribute 0.
    set_clock("2026-10-01T00:00:00Z")
    run_renewal(billing["id"], "FAILED")
    report = api.get_revenue_report(
        ADMIN,
        params={
            "from_iso8601": "2026-09-01T00:00:00Z",
            "to_iso8601": "2026-10-01T00:00:00Z",
        },
    )
    data = validate_success(report, 200)
    assert data["total_cents"] == 1099
    assert data["per_service"]["DPLUS"] == 495
    assert data["per_service"]["HULU"] == 604
    assert data["invoice_count"] == 1


def test_profile_unlink_blocked_by_entitlement_state(api):
    """PRD §3.3: "Unlinking a profile is permitted to the owning subscriber or
    support staff only when the profile carries no entitlement in
    PROVISIONING or ACTIVE status — attempting it otherwise fails with
    ERR_PROFILE_HAS_ACTIVE_ENTITLEMENTS (HTTP 409). Unlinking from either
    LINKED or SUSPENDED revokes any SUSPENDED entitlements still hanging on
    the profile and moves the profile to terminal UNLINKED."

    Design: Difficulty/cross_entity_state_dependency/profile_unlink_blocked_by_entitlement_state
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="ce1@x.com"
    )
    blocked = api.unlink_service_profile(profile["id"], hdrs)
    validate_error(blocked, "ERR_PROFILE_HAS_ACTIVE_ENTITLEMENTS", 409)
    validate_success(
        api.cancel_subscription(sub["id"], {"immediate_effect": True}, hdrs), 200
    )
    set_clock("2026-09-02T00:00:00Z")
    ok = api.unlink_service_profile(profile["id"], hdrs)
    data = validate_success(ok, 200)
    assert data["profile_status"] == "UNLINKED"


def test_profile_unlink_succeeds_with_only_suspended_entitlements(api):
    """PRD §3.3: "Unlinking a profile is permitted to the owning subscriber or
    support staff only when the profile carries no entitlement in
    PROVISIONING or ACTIVE status — attempting it otherwise fails with
    ERR_PROFILE_HAS_ACTIVE_ENTITLEMENTS (HTTP 409). Unlinking from either
    LINKED or SUSPENDED revokes any SUSPENDED entitlements still hanging on
    the profile and moves the profile to terminal UNLINKED."
    PRD §3.2: "Suspending an ACTIVE account cascades: every subscription of
    the account in ACTIVE or PAST_DUE lifecycle has all of its ACTIVE
    entitlements moved to SUSPENDED, and each suspension that leaves a profile
    with zero ACTIVE entitlements drops that profile from LINKED to
    SUSPENDED."

    Design: Difficulty/cross_entity_state_dependency/profile_unlink_blocked_by_entitlement_state
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="ce1b@x.com"
    )
    # Account suspension moves the entitlement to SUSPENDED; unlink is then
    # legal and revokes the suspended entitlement.
    validate_success(api.suspend_account(account["id"], SUPPORT), 200)
    ok = api.unlink_service_profile(profile["id"], hdrs)
    data = validate_success(ok, 200)
    assert data["profile_status"] == "UNLINKED"
    ents = list_entitlements_for_profile(profile["id"], hdrs)
    assert all(e["entitlement_status"] == "REVOKED" for e in ents)


def test_entitlement_activation_blocked_by_unlinked_profile(api):
    """PRD §3.4: "A successful purchase does several things atomically. The
    subscription is created in PENDING_ENTITLEMENT with billing_dimension
    PAID_UP; one entitlement per service in the plan's scope is created
    against the named profiles and provisioned synchronously — each moves
    from PROVISIONING to ACTIVE provided its profile is LINKED and the
    entitlement's service is in the plan's scope. When every spawned
    entitlement has reached ACTIVE — none remaining in PROVISIONING and the
    active count equal to the number of services in the plan's scope — the
    subscription bubbles up from PENDING_ENTITLEMENT to ACTIVE."
    PRD §3.2: "The account also carries three ledger fields that start empty:
    grandfathered_price_cents and grandfathered_plan_code are null until the
    first subscription activates, and account_credit_cents and
    retention_redemption_count start at 0."

    Design: Difficulty/cross_entity_state_dependency/entitlement_activation_blocked_by_unlinked_profile
    """
    set_clock("2026-09-01T00:00:00Z")
    from test_helpers import create_standalone_plan, setup_account_with_billing
    from test_helpers.fixtures import create_profile

    create_standalone_plan(plan_code="DPLUS_ADS", service="DPLUS", price=799)
    account, billing, hdrs = setup_account_with_billing(email="ce2@x.com")
    profile = create_profile(account, service="DPLUS")
    # No entitlement ever attached, so unlink is legal.
    validate_success(api.unlink_service_profile(profile["id"], hdrs), 200)
    resp = api.create_subscription(
        {
            "subscriber_account_id": account["id"],
            "billing_account_id": billing["id"],
            "plan_code": "DPLUS_ADS",
            "dplus_service_profile_id": profile["id"],
        },
        hdrs,
    )
    sub = validate_success(resp, 201)
    assert sub["lifecycle_status"] == "PENDING_ENTITLEMENT", (
        f"unlinked profile cannot provision; expected PENDING_ENTITLEMENT, "
        f"got {sub['lifecycle_status']}"
    )
    ents = list_subscription_entitlements(sub["id"], hdrs)
    assert len(ents) == 1 and ents[0]["entitlement_status"] == "PROVISIONING"
    assert get_account(account["id"], hdrs)["grandfathered_price_cents"] is None


def test_entitlement_activation_unlinked_bundle_stays_pending(api):
    """PRD §3.4: "A successful purchase does several things atomically. The
    subscription is created in PENDING_ENTITLEMENT with billing_dimension
    PAID_UP; one entitlement per service in the plan's scope is created
    against the named profiles and provisioned synchronously — each moves
    from PROVISIONING to ACTIVE provided its profile is LINKED and the
    entitlement's service is in the plan's scope. When every spawned
    entitlement has reached ACTIVE — none remaining in PROVISIONING and the
    active count equal to the number of services in the plan's scope — the
    subscription bubbles up from PENDING_ENTITLEMENT to ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/entitlement_activation_blocked_by_unlinked_profile
    """
    set_clock("2026-09-01T00:00:00Z")
    from test_helpers import create_bundle_plan, setup_account_with_billing
    from test_helpers.fixtures import create_profile

    create_bundle_plan(plan_code="DUO_ADS", price=1099, ad_tier="AD_SUPPORTED")
    account, billing, hdrs = setup_account_with_billing(email="ce2b@x.com")
    prof_d = create_profile(account, service="DPLUS")
    prof_h = create_profile(account, service="HULU")
    validate_success(api.unlink_service_profile(prof_h["id"], hdrs), 200)
    resp = api.create_subscription(
        {
            "subscriber_account_id": account["id"],
            "billing_account_id": billing["id"],
            "plan_code": "DUO_ADS",
            "dplus_service_profile_id": prof_d["id"],
            "hulu_service_profile_id": prof_h["id"],
        },
        hdrs,
    )
    sub = validate_success(resp, 201)
    assert sub["lifecycle_status"] == "PENDING_ENTITLEMENT"
    ents = list_subscription_entitlements(sub["id"], hdrs)
    by_service = {e["service"]: e["entitlement_status"] for e in ents}
    assert by_service["DPLUS"] == "ACTIVE"
    assert by_service["HULU"] == "PROVISIONING"


def test_account_reactivate_blocked_by_pastdue_subscription(api):
    """PRD §3.2: "Reactivation requires the account to be SUSPENDED and,
    critically, that no subscription of the account remains in PAST_DUE — the
    money must be fixed before the account can come back. When reactivation
    proceeds, every SUSPENDED entitlement whose subscription sits in ACTIVE
    lifecycle returns to ACTIVE, and each reactivated entitlement lifts its
    profile from SUSPENDED back to LINKED when nothing else blocks it."
    PRD §5: "ERR_INVALID_STATE | 409".

    Design: Difficulty/cross_entity_state_dependency/account_reactivate_blocked_by_pastdue_subscription
    """
    account, billing, profile, sub, invoice_id, hdrs = setup_failed_renewal(
        email="ce3@x.com"
    )
    validate_success(api.suspend_account(account["id"], SUPPORT), 200)
    blocked = api.reactivate_account(account["id"], SUPPORT)
    validate_error(blocked, "ERR_INVALID_STATE", 409)
    validate_success(api.retry_payment(invoice_id, hdrs), 200)
    assert get_subscription(sub["id"], hdrs)["lifecycle_status"] == "ACTIVE"
    ok = api.reactivate_account(account["id"], SUPPORT)
    assert validate_success(ok, 200)["account_status"] == "ACTIVE"


def test_account_reactivate_allowed_when_no_pastdue(api):
    """PRD §3.2: "Reactivation requires the account to be SUSPENDED and,
    critically, that no subscription of the account remains in PAST_DUE — the
    money must be fixed before the account can come back. When reactivation
    proceeds, every SUSPENDED entitlement whose subscription sits in ACTIVE
    lifecycle returns to ACTIVE, and each reactivated entitlement lifts its
    profile from SUSPENDED back to LINKED when nothing else blocks it."

    Design: Difficulty/cross_entity_state_dependency/account_reactivate_blocked_by_pastdue_subscription
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="ce3b@x.com"
    )
    validate_success(api.suspend_account(account["id"], SUPPORT), 200)
    ok = api.reactivate_account(account["id"], SUPPORT)
    assert validate_success(ok, 200)["account_status"] == "ACTIVE"


def test_cascading_side_effects_account_close_compensation(api):
    """PRD §3.2: "On closure, every profile of the account moves to UNLINKED,
    and every retention redemption still in ACTIVE status on the account's
    subscriptions is moved to VOIDED."
    PRD §3.10: "The account-level retention_redemption_count tracks the
    lifetime number of redemptions in ACTIVE or EXPIRED status — never VOIDED
    — and drives the eligibility cap."

    Design: Corner/cross_cutting/cascading_side_effects_account_close_compensation
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="cc4@x.com"
    )
    create_retention_offer(
        offer_code="SMALL100", discount_cents=100, duration_months=3,
        max_redemptions_per_account=1,
        eligible_biller_types=["PLATFORM"], eligible_plan_kinds=["STANDALONE"],
    )
    redemption = redeem_offer(sub["id"], "SMALL100", hdrs)
    validate_success(
        api.cancel_subscription(sub["id"], {"immediate_effect": True}, hdrs), 200
    )
    set_clock("2026-09-02T00:00:00Z")
    validate_success(api.close_account(account["id"], hdrs), 200)
    reds = validate_success(
        api.list_subscription_redemptions(sub["id"], SUPPORT), 200
    )
    target = [r for r in reds if r["id"] == redemption["id"]][0]
    assert target["redemption_status"] == "VOIDED"
    assert get_account(account["id"], hdrs)["retention_redemption_count"] == 0
