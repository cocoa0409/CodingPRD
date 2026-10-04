"""Purchase, cancellation, and entitlement lifecycle coverage."""
from test_helpers import (
    TEST_USERS,
    get_account,
    get_billing_account,
    get_profile,
    get_subscription,
    list_subscription_entitlements,
    make_subscriber_headers,
    register_account,
    create_plan,
    create_standalone_plan,
    create_bundle_plan,
    create_billing_account_payload,
    create_profile,
    create_service_profile_payload,
    create_subscriber_account_payload,
    create_subscription_payload,
    set_clock,
    setup_account_with_billing,
    setup_account_with_profiles,
    setup_active_bundle_subscription,
    setup_active_standalone_subscription,
    purchase_subscription,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]
DISTRIBUTOR = TEST_USERS["distributor_ops_headers"]


def test_subscription_initial_state_pending_then_active(api):
    """PRD §3.4: "A successful purchase does several things atomically. The
    subscription is created in PENDING_ENTITLEMENT with billing_dimension
    PAID_UP; one entitlement per service in the plan's scope is created
    against the named profiles and provisioned synchronously — each moves
    from PROVISIONING to ACTIVE provided its profile is LINKED and the
    entitlement's service is in the plan's scope. When every spawned
    entitlement has reached ACTIVE — none remaining in PROVISIONING and the
    active count equal to the number of services in the plan's scope — the
    subscription bubbles up from PENDING_ENTITLEMENT to ACTIVE."

    Design: Corner/state_machines/subscription_initial_state_pending_then_active
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="sm1@x.com"
    )
    assert sub["lifecycle_status"] == "ACTIVE", (
        f"create response must already be ACTIVE, got {sub['lifecycle_status']}"
    )
    ents = list_subscription_entitlements(sub["id"], hdrs)
    assert len(ents) == 1 and ents[0]["entitlement_status"] == "ACTIVE"


def test_cancel_terminal_subscription_returns_invalid_state(api):
    """PRD §5: "ERR_INVALID_STATE | 409".
    PRD §3.8: "Once the logical clock reaches cancel_effective_at, the
    subscription finalizes to CANCELLED and rescinding is no longer reachable —
    a late rescind hits the state gate and is rejected with ERR_INVALID_STATE
    (HTTP 409)."
    PRD §3.8: "Cancelling a subscription from ACTIVE or PAST_DUE schedules it:
    the lifecycle moves to CANCEL_SCHEDULED."

    Design: Corner/state_machines/cancel_terminal_subscription_returns_invalid_state
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="sm2@x.com"
    )
    validate_success(api.cancel_subscription(sub["id"], {"immediate_effect": True}, hdrs), 200)
    set_clock("2026-09-02T00:00:00Z")
    assert get_subscription(sub["id"], hdrs)["lifecycle_status"] == "CANCELLED"
    resp = api.cancel_subscription(sub["id"], {"immediate_effect": True}, hdrs)
    validate_error(resp, "ERR_INVALID_STATE", 409)
    assert get_subscription(sub["id"], hdrs)["lifecycle_status"] == "CANCELLED"


def test_double_cancel_idempotency_second_fails(api):
    """PRD §3.8: "Cancelling a subscription from ACTIVE or PAST_DUE schedules
    it: the lifecycle moves to CANCEL_SCHEDULED."
    PRD §5: "ERR_INVALID_STATE | 409".

    Design: Corner/state_machines/double_cancel_idempotency_second_fails
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="sm3@x.com"
    )
    first = api.cancel_subscription(sub["id"], {"immediate_effect": False}, hdrs)
    data = validate_success(first, 200)
    assert data["lifecycle_status"] == "CANCEL_SCHEDULED"
    second = api.cancel_subscription(sub["id"], {"immediate_effect": False}, hdrs)
    validate_error(second, "ERR_INVALID_STATE", 409)
    assert get_subscription(sub["id"], hdrs)["lifecycle_status"] == "CANCEL_SCHEDULED"


def test_rescind_after_finalization_returns_invalid_state(api):
    """PRD §3.8: "Once the logical clock reaches cancel_effective_at, the
    subscription finalizes to CANCELLED and rescinding is no longer reachable —
    a late rescind hits the state gate and is rejected with ERR_INVALID_STATE
    (HTTP 409)."

    Design: Corner/state_machines/rescind_after_finalization_returns_invalid_state
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="sm4@x.com"
    )
    validate_success(api.cancel_subscription(sub["id"], {"immediate_effect": False}, hdrs), 200)
    set_clock("2026-10-01T00:00:00Z")
    assert get_subscription(sub["id"], hdrs)["lifecycle_status"] == "CANCELLED"
    resp = api.rescind_cancellation(sub["id"], hdrs)
    validate_error(resp, "ERR_INVALID_STATE", 409)


def test_invoice_retry_on_paid_returns_invalid_state(api):
    """PRD §3.11: "Retrying a failed invoice is open to the subscriber or
    operator within the grace window — the current logical clock must be
    strictly before period_end plus 7 days, and at exactly that instant the
    window is closed (ERR_GRACE_WINDOW_CLOSED); the billing account must also
    not be HARD_FAILED."
    PRD §5: "ERR_INVALID_STATE | 409".

    Design: Corner/state_machines/invoice_retry_on_paid_returns_invalid_state
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="sm6@x.com"
    )
    invoices_resp = api.list_billing_account_invoices(billing["id"], hdrs)
    invoices = validate_success(invoices_resp, 200)
    assert len(invoices) >= 1
    initial = invoices[0]
    assert initial["invoice_status"] == "PAID"
    resp = api.retry_payment(initial["id"], hdrs)
    validate_error(resp, "ERR_INVALID_STATE", 409)


def test_bundle_cancel_revokes_both_components(api):
    """PRD §3.8: "The interdependent-component rule decides what dies with the
    subscription. Finalizing a BUNDLE subscription revokes all of its
    entitlements at cancel_effective_at — both services die together."
    PRD §2.9: "When the last `ACTIVE` entitlement on a profile disappears — by
    suspension, revocation, or cancellation — the profile itself drops from
    `LINKED` to `SUSPENDED`; when any entitlement on a suspended profile
    returns to `ACTIVE` and no other blocking condition holds, the profile
    rises back to `LINKED`."

    Design: Corner/state_machines/bundle_cancel_revokes_both_components
    """
    account, billing, profiles, sub, hdrs = setup_active_bundle_subscription(
        email="sm7@x.com"
    )
    validate_success(api.cancel_subscription(sub["id"], {"immediate_effect": True}, hdrs), 200)
    set_clock("2026-09-02T00:00:00Z")
    ents = list_subscription_entitlements(sub["id"], hdrs)
    assert len(ents) == 2
    assert all(e["entitlement_status"] == "REVOKED" for e in ents), (
        f"both bundle entitlements must be REVOKED, got {[e['entitlement_status'] for e in ents]}"
    )
    assert get_profile(profiles["DPLUS"]["id"], hdrs)["profile_status"] == "SUSPENDED"
    assert get_profile(profiles["HULU"]["id"], hdrs)["profile_status"] == "SUSPENDED"


def test_standalone_cancel_leaves_bundle_untouched(api):
    """PRD §3.8: "Finalizing a STANDALONE subscription revokes only its own
    single-service entitlement; a bundle subscription on the same account is
    untouched, and cancelling a standalone never implicitly breaks up a
    bundle. When an account holds both a bundle and a standalone covering the
    same service, the profile for that service stays LINKED as long as at
    least one ACTIVE entitlement for that service survives from any source
    subscription."

    Design: Corner/state_machines/standalone_cancel_leaves_bundle_untouched
    """
    set_clock("2026-09-01T00:00:00Z")
    create_bundle_plan(plan_code="DUO_ADS", price=1099, ad_tier="AD_SUPPORTED")
    create_standalone_plan(plan_code="DPLUS_ADS", service="DPLUS", price=799)
    account, billing, profiles, hdrs = setup_account_with_profiles(
        email="sm8@x.com"
    )
    bundle = purchase_subscription(
        account, billing, "DUO_ADS",
        dplus_profile=profiles["DPLUS"], hulu_profile=profiles["HULU"],
    )
    stand = purchase_subscription(
        account, billing, "DPLUS_ADS", dplus_profile=profiles["DPLUS"]
    )
    validate_success(api.cancel_subscription(stand["id"], {"immediate_effect": True}, hdrs), 200)
    set_clock("2026-09-02T00:00:00Z")
    assert get_subscription(stand["id"], hdrs)["lifecycle_status"] == "CANCELLED"
    assert get_subscription(bundle["id"], hdrs)["lifecycle_status"] == "ACTIVE"
    assert get_profile(profiles["DPLUS"]["id"], hdrs)["profile_status"] == "LINKED"
    ents = list_subscription_entitlements(stand["id"], hdrs)
    assert len(ents) == 1 and ents[0]["entitlement_status"] == "REVOKED"


def test_scheduled_cancel_fires_exactly_at_effective_at(api):
    """PRD §2.5: "Advancing the clock fires every transition gated on time —
    most importantly, a subscription in CANCEL_SCHEDULED whose
    cancel_effective_at has been reached finalizes to CANCELLED."
    PRD §3.8: "By default the cancellation takes effect at period end —
    `cancel_effective_at` is set to the billing account's `period_end` — but
    the caller may pass `immediate_effect` as true to cancel at the current
    logical clock instant instead."

    Design: Corner/cross_cutting/scheduled_cancel_fires_exactly_at_effective_at
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="cc3@x.com"
    )
    validate_success(api.cancel_subscription(sub["id"], {"immediate_effect": False}, hdrs), 200)
    set_clock("2026-09-30T23:59:59Z")
    assert get_subscription(sub["id"], hdrs)["lifecycle_status"] == "CANCEL_SCHEDULED"
    set_clock("2026-10-01T00:00:00Z")
    assert get_subscription(sub["id"], hdrs)["lifecycle_status"] == "CANCELLED"


def test_subscription_parallel_dimensions_diverge(api):
    """PRD §3.11: "On a failed outcome the invoice moves to FAILED and the
    dunning cascade begins: the billing account drops from CURRENT to PAST_DUE
    with consecutive_failure_count incremented by 1; the subscription's
    billing_dimension moves from PAID_UP to GRACE and its lifecycle from
    ACTIVE to PAST_DUE; every ACTIVE entitlement of the subscription suspends;
    and each profile left with zero active entitlements drops from LINKED to
    SUSPENDED."
    PRD §3.8: "A past-due subscription can cancel only at period end:
    immediate_effect must be false from PAST_DUE."

    Design: Difficulty/non_linear_state_machine/subscription_parallel_dimensions_diverge
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="nl1@x.com"
    )
    set_clock("2026-10-01T00:00:00Z")
    run = api.run_renewal({"billing_account_id": billing["id"], "outcome": "FAILED"}, ADMIN)
    assert run.status_code == 200, f"setup renewal failed: {run.text}"
    mid = get_subscription(sub["id"], hdrs)
    assert mid["lifecycle_status"] == "PAST_DUE"
    assert mid["billing_dimension"] == "GRACE"
    resp = api.cancel_subscription(sub["id"], {"immediate_effect": False}, hdrs)
    data = validate_success(resp, 200)
    assert data["lifecycle_status"] == "CANCEL_SCHEDULED"
    assert data["billing_dimension"] == "GRACE", (
        "cancel from PAST_DUE must leave the billing dimension in GRACE — "
        "the two dimensions are independent axes"
    )
    assert data["cancel_effective_at"] is not None and data[
        "cancel_effective_at"
    ].startswith("2026-10-01T00:00:00"), (
        f"cancel_effective_at must be the (unadvanced) period_end 2026-10-01, "
        f"got {data['cancel_effective_at']}"
    )


def test_parallel_dimensions_recover_together_on_payment(api):
    """PRD §3.11: "A successful retry pays the invoice, runs revenue
    allocation for it, and unwinds the cascade: consecutive_failure_count
    resets to 0, the billing account returns to CURRENT, the subscription
    returns to PAID_UP and ACTIVE, suspended entitlements reactivate, and
    affected profiles return to LINKED."

    Design: Difficulty/non_linear_state_machine/subscription_parallel_dimensions_diverge
    """
    account, billing, profile, sub, hdrs = setup_active_standalone_subscription(
        email="nl1b@x.com"
    )
    set_clock("2026-10-01T00:00:00Z")
    run = api.run_renewal({"billing_account_id": billing["id"], "outcome": "FAILED"}, ADMIN)
    assert run.status_code == 200, f"setup renewal failed: {run.text}"
    invoice_id = validate_success(run, 200)["invoice_id"]
    validate_success(api.retry_payment(invoice_id, hdrs), 200)
    after = get_subscription(sub["id"], hdrs)
    assert after["lifecycle_status"] == "ACTIVE"
    assert after["billing_dimension"] == "PAID_UP"
