"""Renewal collection, dunning cascades, and grace-window coverage."""
from test_helpers import (
    TEST_USERS,
    create_bundle_plan,
    create_standalone_plan,
    get_account,
    get_billing_account,
    get_profile,
    get_subscription,
    list_subscription_entitlements,
    redeem_offer,
    run_renewal,
    set_clock,
    setup_account_with_profiles,
    setup_active_bundle_subscription,
    setup_active_standalone_subscription,
    create_retention_offer,
    purchase_subscription,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SUPPORT = TEST_USERS["support_headers"]


def test_renewal_failure_four_hop_cascade(api):
    """PRD §3.11: "On a failed outcome the invoice moves to FAILED and the
    dunning cascade begins: the billing account drops from CURRENT to PAST_DUE
    with consecutive_failure_count incremented by 1; the subscription's
    billing_dimension moves from PAID_UP to GRACE and its lifecycle from
    ACTIVE to PAST_DUE; every ACTIVE entitlement of the subscription suspends;
    and each profile left with zero active entitlements drops from LINKED to
    SUSPENDED."

    Design: Difficulty/transitive_cascade/renewal_failure_four_hop_cascade
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="tc1@x.com"
    )
    ent = list_subscription_entitlements(sub["id"], hdrs)[0]
    set_clock("2026-10-01T00:00:00Z")
    run_renewal(billing["id"], "FAILED")
    ba = get_billing_account(billing["id"], hdrs)
    assert ba["billing_status"] == "PAST_DUE"
    assert ba["consecutive_failure_count"] == 1
    sub_after = get_subscription(sub["id"], hdrs)
    assert sub_after["lifecycle_status"] == "PAST_DUE"
    assert sub_after["billing_dimension"] == "GRACE"
    ent_after = validate_success(api.get_entitlement(ent["id"], hdrs), 200)
    assert ent_after["entitlement_status"] == "SUSPENDED"
    assert get_profile(profile["id"], hdrs)["profile_status"] == "SUSPENDED"


def test_billing_account_status_cycle_current_pastdue_current(api):
    """PRD §2.10: "Consecutive failures are counted in
    consecutive_failure_count, which resets to 0 on any success; when a
    further failure would push that count to 3, the billing account hard-fails
    and the subscription is cancelled outright."
    PRD §3.11: "A successful retry pays the invoice, runs revenue allocation
    for it, and unwinds the cascade: consecutive_failure_count resets to 0,
    the billing account returns to CURRENT, the subscription returns to
    PAID_UP and ACTIVE, suspended entitlements reactivate, and affected
    profiles return to LINKED."

    Design: Difficulty/non_linear_state_machine/billing_account_status_cycle_current_pastdue_current
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="nl2@x.com"
    )
    set_clock("2026-10-01T00:00:00Z")
    result = run_renewal(billing["id"], "FAILED")
    assert get_billing_account(billing["id"], hdrs)["billing_status"] == "PAST_DUE"
    assert get_billing_account(billing["id"], hdrs)["consecutive_failure_count"] == 1
    validate_success(api.retry_payment(result["invoice_id"], hdrs), 200)
    ba = get_billing_account(billing["id"], hdrs)
    assert ba["billing_status"] == "CURRENT"
    assert ba["consecutive_failure_count"] == 0
    sub_after = get_subscription(sub["id"], hdrs)
    assert sub_after["billing_dimension"] == "PAID_UP"
    assert sub_after["lifecycle_status"] == "ACTIVE"


def test_billing_cycle_failure_count_increments_per_failure(api):
    """PRD §2.10: "Consecutive failures are counted in
    consecutive_failure_count, which resets to 0 on any success; when a
    further failure would push that count to 3, the billing account hard-fails
    and the subscription is cancelled outright."

    Design: Difficulty/non_linear_state_machine/billing_account_status_cycle_current_pastdue_current
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="nl2b@x.com"
    )
    set_clock("2026-10-01T00:00:00Z")
    run_renewal(billing["id"], "FAILED")
    run_renewal(billing["id"], "FAILED")
    ba = get_billing_account(billing["id"], hdrs)
    assert ba["billing_status"] == "PAST_DUE"
    assert ba["consecutive_failure_count"] == 2
    assert get_subscription(sub["id"], hdrs)["lifecycle_status"] == "PAST_DUE"


def test_entitlement_suspend_reactivate_cycle_via_account(api):
    """PRD §3.2: "Suspending an ACTIVE account cascades: every subscription of
    the account in ACTIVE or PAST_DUE lifecycle has all of its ACTIVE
    entitlements moved to SUSPENDED, and each suspension that leaves a profile
    with zero ACTIVE entitlements drops that profile from LINKED to
    SUSPENDED."
    PRD §3.2: "When reactivation proceeds, every SUSPENDED entitlement whose
    subscription sits in ACTIVE lifecycle returns to ACTIVE, and each
    reactivated entitlement lifts its profile from SUSPENDED back to LINKED
    when nothing else blocks it."

    Design: Difficulty/non_linear_state_machine/entitlement_suspend_reactivate_cycle_via_account
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="nl3@x.com"
    )
    ent = list_subscription_entitlements(sub["id"], hdrs)[0]
    validate_success(api.suspend_account(account["id"], SUPPORT), 200)
    mid = validate_success(api.get_entitlement(ent["id"], hdrs), 200)
    assert mid["entitlement_status"] == "SUSPENDED"
    assert get_profile(profile["id"], hdrs)["profile_status"] == "SUSPENDED"
    validate_success(api.reactivate_account(account["id"], SUPPORT), 200)
    ent_after = validate_success(api.get_entitlement(ent["id"], hdrs), 200)
    assert ent_after["entitlement_status"] == "ACTIVE"
    assert get_profile(profile["id"], hdrs)["profile_status"] == "LINKED"
    assert get_account(account["id"], hdrs)["account_status"] == "ACTIVE"


def test_entitlement_cycle_requires_subscription_active(api):
    """PRD §3.2: "Reactivation requires the account to be SUSPENDED and,
    critically, that no subscription of the account remains in PAST_DUE — the
    money must be fixed before the account can come back."
    PRD §3.2: "When reactivation proceeds, every SUSPENDED entitlement whose
    subscription sits in ACTIVE lifecycle returns to ACTIVE, and each
    reactivated entitlement lifts its profile from SUSPENDED back to LINKED
    when nothing else blocks it."

    Design: Difficulty/non_linear_state_machine/entitlement_suspend_reactivate_cycle_via_account
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="nl3b@x.com"
    )
    ent = list_subscription_entitlements(sub["id"], hdrs)[0]
    validate_success(api.suspend_account(account["id"], SUPPORT), 200)
    validate_success(api.reactivate_account(account["id"], SUPPORT), 200)
    ent_after = validate_success(api.get_entitlement(ent["id"], hdrs), 200)
    assert ent_after["entitlement_status"] == "ACTIVE"
    # A second suspension re-suspends the same entitlement (cycle repeats).
    validate_success(api.suspend_account(account["id"], SUPPORT), 200)
    ent_again = validate_success(api.get_entitlement(ent["id"], hdrs), 200)
    assert ent_again["entitlement_status"] == "SUSPENDED"


def test_hard_failed_three_hop_cascade_with_redemption_void(api):
    """PRD §3.11: "When a renewal failure arrives while
    consecutive_failure_count already stands at 2 — so the increment would
    bring it to 3 — the billing account goes HARD_FAILED. The subscription's
    lifecycle moves directly from PAST_DUE to CANCELLED with
    cancel_effective_at null (the cancellation is immediate), the
    billing_dimension moves from GRACE to UNPAID, every entitlement of the
    subscription in ACTIVE or SUSPENDED is revoked, profiles left without
    active entitlements suspend, and any ACTIVE retention redemption on the
    subscription is voided."

    Design: Difficulty/transitive_cascade/hard_failed_three_hop_cascade_with_redemption_void
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="tc3@x.com"
    )
    create_retention_offer(
        offer_code="SMALL100", discount_cents=100, duration_months=3,
        max_redemptions_per_account=1,
        eligible_biller_types=["PLATFORM"], eligible_plan_kinds=["STANDALONE"],
    )
    redemption = redeem_offer(sub["id"], "SMALL100", hdrs)
    set_clock("2026-10-01T00:00:00Z")
    run_renewal(billing["id"], "FAILED")
    run_renewal(billing["id"], "FAILED")
    run_renewal(billing["id"], "FAILED")
    ba = get_billing_account(billing["id"], hdrs)
    assert ba["billing_status"] == "HARD_FAILED"
    assert ba["consecutive_failure_count"] == 3
    sub_after = get_subscription(sub["id"], hdrs)
    assert sub_after["lifecycle_status"] == "CANCELLED"
    assert sub_after["billing_dimension"] == "UNPAID"
    assert sub_after["cancel_effective_at"] is None
    reds = validate_success(
        api.list_subscription_redemptions(sub["id"], hdrs), 200
    )
    target = [r for r in reds if r["id"] == redemption["id"]][0]
    assert target["redemption_status"] == "VOIDED"
    ents = list_subscription_entitlements(sub["id"], hdrs)
    assert all(e["entitlement_status"] == "REVOKED" for e in ents)


def test_hard_failed_blocks_retry_payment(api):
    """PRD §3.11: "Recovery past HARD_FAILED is impossible — the state gate
    blocks retry-payment with ERR_INVALID_STATE."

    Design: Difficulty/transitive_cascade/hard_failed_three_hop_cascade_with_redemption_void
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="tc3b@x.com"
    )
    set_clock("2026-10-01T00:00:00Z")
    last = None
    for _ in range(3):
        last = run_renewal(billing["id"], "FAILED")
    assert get_billing_account(billing["id"], hdrs)["billing_status"] == "HARD_FAILED"
    resp = api.retry_payment(last["invoice_id"], hdrs)
    validate_error(resp, "ERR_INVALID_STATE", 409)


def test_grace_window_retry_at_exact_deadline_rejected(api):
    """PRD §3.11: "Retrying a failed invoice is open to the subscriber or
    operator within the grace window — the current logical clock must be
    strictly before period_end plus 7 days, and at exactly that instant the
    window is closed (ERR_GRACE_WINDOW_CLOSED); the billing account must also
    not be HARD_FAILED."

    Design: Corner/validations/grace_window_retry_at_exact_deadline_rejected
    """
    # Account B: retry one second before the deadline succeeds.
    acc_b, bill_b, prof_b, sub_b, hdrs_b = setup_active_standalone_subscription(
        email="val10b@x.com"
    )
    # Account A: retry at exactly the deadline is rejected.
    acc_a, bill_a, prof_a, sub_a, hdrs_a = setup_active_standalone_subscription(
        email="val10a@x.com"
    )
    set_clock("2026-10-01T00:00:00Z")
    inv_a = run_renewal(bill_a["id"], "FAILED")["invoice_id"]
    inv_b = run_renewal(bill_b["id"], "FAILED")["invoice_id"]
    set_clock("2026-10-07T23:59:59Z")
    ok = api.retry_payment(inv_b, hdrs_b)
    validate_success(ok, 200)
    set_clock("2026-10-08T00:00:00Z")
    late = api.retry_payment(inv_a, hdrs_a)
    validate_error(late, "ERR_GRACE_WINDOW_CLOSED", 422)


def test_run_renewal_not_due_rejected(api):
    """PRD §3.11: "Running it for an account whose period has not ended is
    rejected with ERR_RENEWAL_NOT_DUE (HTTP 422)."

    Design: Corner/validations/run_renewal_not_due_rejected
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="val11@x.com"
    )
    resp = api.run_renewal(
        {"billing_account_id": billing["id"], "outcome": "SUCCEEDED"}, ADMIN
    )
    validate_error(resp, "ERR_RENEWAL_NOT_DUE", 422)


def test_renewal_advances_period_by_biller_constant(api):
    """PRD §3.11: "On a succeeded outcome the invoice moves to PAID; the
    billing period advances — the old period_end becomes the new period_start,
    and the new period_end lands 30 days later for PLATFORM or 31 days later
    for third-party billers; and each ACTIVE retention redemption on the
    subscription loses one month of months_remaining, expiring exactly when
    that count reaches 0."

    Design: Corner/calculations/renewal_advances_period_by_biller_constant
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="calc2@x.com"
    )
    set_clock("2026-10-01T00:00:00Z")
    run_renewal(billing["id"], "SUCCEEDED")
    ba = get_billing_account(billing["id"], hdrs)
    assert ba["period_start"].startswith("2026-10-01T00:00:00"), (
        f"period_start must advance to 2026-10-01, got {ba['period_start']}"
    )
    assert ba["period_end"].startswith("2026-10-31T00:00:00"), (
        f"period_end must advance 30 days to 2026-10-31, got {ba['period_end']}"
    )


def test_renewal_invoice_input_set_filtering(api):
    """PRD §3.11: "The run processes the billing account's due subscriptions —
    those in ACTIVE lifecycle with billing_dimension PAID_UP — in
    chronological order of each subscription's created_at, ascending, with no
    other tie-breaker."
    PRD §2.5: "Advancing the clock fires every transition gated on time —
    most importantly, a subscription in CANCEL_SCHEDULED whose
    cancel_effective_at has been reached finalizes to CANCELLED."

    Design: Corner/calculations/renewal_invoice_input_set_filtering
    """
    set_clock("2026-09-01T00:00:00Z")
    create_standalone_plan(plan_code="DPLUS_ADS", service="DPLUS", price=799)
    create_standalone_plan(plan_code="HULU_ADS", service="HULU", price=899)
    account, billing, profiles, hdrs = setup_account_with_profiles(email="calc3@x.com")
    sub_dplus = purchase_subscription(
        account, billing, "DPLUS_ADS", dplus_profile=profiles["DPLUS"]
    )
    sub_hulu = purchase_subscription(
        account, billing, "HULU_ADS", hulu_profile=profiles["HULU"]
    )
    validate_success(
        api.cancel_subscription(sub_hulu["id"], {"immediate_effect": False}, hdrs), 200
    )
    set_clock("2026-10-01T00:00:00Z")
    run_renewal(billing["id"], "SUCCEEDED")
    invoices = validate_success(
        api.list_billing_account_invoices(billing["id"], hdrs), 200
    )
    assert len(invoices) == 3, (
        f"expected 2 INITIAL + 1 RENEWAL invoice, got {len(invoices)}"
    )
    kinds = sorted(i["invoice_kind"] for i in invoices)
    assert kinds == ["INITIAL", "INITIAL", "RENEWAL"]
    assert get_subscription(sub_hulu["id"], hdrs)["lifecycle_status"] == "CANCELLED"
    assert get_subscription(sub_dplus["id"], hdrs)["lifecycle_status"] == "ACTIVE"


def test_renewal_failure_cascade_leaves_period_unadvanced(api):
    """PRD §3.11: "On a failed outcome the invoice moves to FAILED and the
    dunning cascade begins: the billing account drops from CURRENT to PAST_DUE
    with consecutive_failure_count incremented by 1; the subscription's
    billing_dimension moves from PAID_UP to GRACE and its lifecycle from
    ACTIVE to PAST_DUE; every ACTIVE entitlement of the subscription suspends;
    and each profile left with zero active entitlements drops from LINKED to
    SUSPENDED."
    PRD §3.11: "On a succeeded outcome the invoice moves to PAID; the
    billing period advances — the old period_end becomes the new period_start,
    and the new period_end lands 30 days later for PLATFORM or 31 days later
    for third-party billers; and each ACTIVE retention redemption on the
    subscription loses one month of months_remaining, expiring exactly when
    that count reaches 0."

    Design: Difficulty/transitive_cascade/renewal_failure_four_hop_cascade
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="tc1b@x.com"
    )
    set_clock("2026-10-01T00:00:00Z")
    run_renewal(billing["id"], "FAILED")
    ba = get_billing_account(billing["id"], hdrs)
    # A failed renewal must NOT advance the period (advance is a
    # success-only side effect), so the account stays due at 2026-10-01.
    assert ba["period_start"].startswith("2026-09-01T00:00:00")
    assert ba["period_end"].startswith("2026-10-01T00:00:00")
    sub_after = get_subscription(sub["id"], hdrs)
    assert sub_after["lifecycle_status"] == "PAST_DUE"
    assert sub_after["billing_dimension"] == "GRACE"
    assert get_profile(profile["id"], hdrs)["profile_status"] == "SUSPENDED"
