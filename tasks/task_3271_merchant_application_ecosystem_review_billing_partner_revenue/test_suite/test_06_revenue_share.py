"""Revenue-share, accrual, proration, and invoice invariant tests
(difficulty design: dual_variant_calc, combinatorial_formula,
boundary_precision_check, compensating_invariant)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_approved_charge,
    create_installation_payload,
    create_merchant,
    get_success_data,
    issue_invoice,
    make_admin_headers,
    make_developer_headers,
    make_merchant_headers,
    mark_invoice_paid,
    open_invoice,
    set_clock,
    setup_active_installation,
    setup_issued_invoice,
    setup_listed_app,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# dual_variant_calc / developer_accrual_provisional_includes_unpaid_final_excludes
# ---------------------------------------------------------------------------

def test_provisional_accrual_includes_unpaid_invoiced_charge(api):
    """PRD §3.8: "The `PROVISIONAL` variant, written at issue time, accrues
    every charge of the developer with status `INVOICED` whose
    `billing_cycle` matches the invoice's cycle, including cycles whose
    invoice is still issued-but-unpaid — it assumes all invoiced charges will
    collect."
    PRD §2.12: "Each developer account carries a computed
    `lifetime_gross_cents`, defined as the sum of `final_amount_cents` over
    every charge across all apps owned by that developer whose status is
    `INVOICED` or `SETTLED`."

    Design: Difficulty/dual_variant_calc/developer_accrual_provisional_includes_unpaid_final_excludes
    """
    developer, app, version, merchant, installation = setup_active_installation(
        company="D1"
    )
    c1 = create_approved_charge(installation, developer, merchant, 120000000)
    c2 = create_approved_charge(installation, developer, merchant, 20000000)
    invoice = issue_invoice(open_invoice(merchant, cycle="2026-09"))
    # PROVISIONAL: both INVOICED charges accrue even though the invoice is
    # issued-but-unpaid.
    developer = get_success_data(api.get_developer(developer["id"], make_admin_headers()))
    assert developer["lifetime_gross_cents"] == 140000000, (
        f"expected 140000000 after issue, got {developer['lifetime_gross_cents']}"
    )
    entries, _ = validate_paginated(
        api.list_developer_ledger_entries(developer["id"], make_admin_headers())
    )
    assert entries, "expected at least one ledger entry after issue"
    assert entries[0]["entry_variant"] == "PROVISIONAL", (
        f"expected PROVISIONAL entries at issue time, got {entries[0]['entry_variant']}"
    )


def test_final_accrual_excludes_reversed_charge_on_mark_paid(api):
    """PRD §3.8: "The `FINAL` variant, written when an invoice is paid or when
    a charge inside an issued invoice is reversed, accrues only charges with
    status `SETTLED` plus `INVOICED` charges whose owning invoice is already
    `PAID`; reversed charges and charges on still-unpaid invoices are
    excluded. When the `FINAL` variant runs, it supersedes the `PROVISIONAL`
    entry for the same cycle (the `entry_variant` marker on each ledger row
    distinguishes the two)"

    Design: Difficulty/dual_variant_calc/developer_accrual_provisional_includes_unpaid_final_excludes
    """
    developer, app, version, merchant, installation = setup_active_installation(
        company="D1"
    )
    c1 = create_approved_charge(installation, developer, merchant, 120000000)
    c2 = create_approved_charge(installation, developer, merchant, 20000000)
    invoice = issue_invoice(open_invoice(merchant, cycle="2026-09"))
    # Reverse the 20000000-cent sibling while the invoice is still ISSUED.
    validate_success(api.reverse_charge(c2["id"], {}, make_admin_headers()))
    mark_invoice_paid(invoice)
    developer = get_success_data(api.get_developer(developer["id"], make_admin_headers()))
    assert developer["lifetime_gross_cents"] == 120000000, (
        f"expected 120000000 (FINAL excluded the reversed 20000000-cent "
        f"charge), got {developer['lifetime_gross_cents']}"
    )
    # Tier crossed T0 (100000000) at invoice time: share is 15% of 120000000.
    c1_after = get_success_data(api.get_billing_charge(c1["id"], make_admin_headers()))
    assert c1_after["platform_share_cents"] == 18000000, (
        f"expected platform_share_cents 18000000, got "
        f"{c1_after['platform_share_cents']}"
    )
    entries, _ = validate_paginated(
        api.list_developer_ledger_entries(developer["id"], make_admin_headers())
    )
    # §3.8: the FINAL variant "supersedes the PROVISIONAL entry for the same
    # cycle (the entry_variant marker on each ledger row distinguishes the
    # two)" — a FINAL accrual row for the cycle must exist. (PRD §2.3 pins
    # default list ordering to created_at-ascending, so the FINAL row is
    # not the first element; nothing in PRD orders ledger lists otherwise.)
    assert any(
        e["entry_variant"] == "FINAL" and e["entry_type"] == "ACCRUAL"
        for e in entries
    ), (
        f"expected a FINAL ACCRUAL entry superseding the PROVISIONAL, got "
        f"{[(e['entry_variant'], e['entry_type']) for e in entries]}"
    )


# ---------------------------------------------------------------------------
# dual_variant_calc / storefront_performance_mean_vs_budget_dual_window
# ---------------------------------------------------------------------------

def test_performance_window_excludes_stale_sample_keeps_compliant(api):
    """PRD §3.7: "The window is the seven-day interval ending at the new
    sample's `sampled_at`, inclusive of the window end and exclusive of the
    window start. The mean `storefront_load_ms` is computed across every
    sample of the installation whose `sampled_at` falls within the window,
    expressed to two decimal places with round-half-up. The impact for the
    window is twice that mean, rounded to the nearest integer millisecond with
    round-half-up. When the impact is at most the 200-millisecond budget —
    including exactly 200, since the boundary is inclusive — the app's
    `performance_state` remains or returns to `COMPLIANT`."

    Design: Difficulty/dual_variant_calc/storefront_performance_mean_vs_budget_dual_window
    """
    developer, app, version, merchant, installation = setup_active_installation(
        company="D2", category="ANALYTICS"
    )
    dev_headers = make_developer_headers(developer["id"])
    # Stale outlier: 8 days before the trigger sample.
    api.create_performance_sample(
        installation["id"],
        {"storefront_load_ms": 400, "sampled_at": "2026-09-01T00:00:00Z"},
        dev_headers,
    )
    api.create_performance_sample(
        installation["id"],
        {"storefront_load_ms": 100, "sampled_at": "2026-09-09T00:00:00Z"},
        dev_headers,
    )
    app_after = get_success_data(api.get_app(app["id"], dev_headers))
    # Window (2026-09-02, 2026-09-09] holds only the 100ms sample:
    # mean 100.00 -> impact 200 <= 200 -> COMPLIANT. A lifetime average over
    # (400, 100) would have produced impact 500 and DEGRADED.
    assert app_after["performance_state"] == "COMPLIANT", (
        f"expected COMPLIANT, got {app_after['performance_state']}"
    )


def test_performance_window_includes_stale_sample_under_lifetime_reading(api):
    """PRD §3.7: "When the impact exceeds the budget, the app's
    `performance_state` transitions to `DEGRADED` and a governance strike with
    reason `PERFORMANCE_BREACH` is opened against the app."

    The mirror scenario: with BOTH samples inside the same 7-day window the
    mean is (400+100)/2 = 250 -> impact 500 > 200, so the windowed reading
    must DEGRADE — proving the evaluation is windowed, not lifetime.

    Design: Difficulty/dual_variant_calc/storefront_performance_mean_vs_budget_dual_window
    """
    developer, app, version, merchant, installation = setup_active_installation(
        company="D2B", category="ANALYTICS"
    )
    dev_headers = make_developer_headers(developer["id"])
    api.create_performance_sample(
        installation["id"],
        {"storefront_load_ms": 400, "sampled_at": "2026-09-08T00:00:00Z"},
        dev_headers,
    )
    api.create_performance_sample(
        installation["id"],
        {"storefront_load_ms": 100, "sampled_at": "2026-09-09T00:00:00Z"},
        dev_headers,
    )
    app_after = get_success_data(api.get_app(app["id"], dev_headers))
    assert app_after["performance_state"] == "DEGRADED", (
        f"expected DEGRADED (window mean 250 -> impact 500 > 200), got "
        f"{app_after['performance_state']}"
    )


# ---------------------------------------------------------------------------
# combinatorial_formula / charge_net_computation_pinned_evaluation_order
# ---------------------------------------------------------------------------

def test_launch10_discount_applied_before_share(api):
    """PRD §3.6: "When the charge is `ONE_TIME` and the `discount_code` is the
    literal string `LAUNCH10`, the `discount_amount_cents` is ten percent of
    `base_amount_cents`, rounded half-up to integer cents; otherwise
    `discount_amount_cents` is zero. The evaluation order is pinned — the
    discount is computed first, then the platform share, then the developer
    net — so the discount rounds before the share is computed. The
    `final_amount_cents` is `base_amount_cents` minus `discount_amount_cents`.
    The platform's share is computed at the app's `revenue_share_tier` in
    force at the moment the charge is invoiced (not at charge creation): a
    `T0` app yields a share of zero, a `T1` app yields fifteen percent, and a
    `T2` app yields twenty percent."

    Design: Difficulty/combinatorial_formula/charge_net_computation_pinned_evaluation_order
    """
    developer, app, version, merchant, installation = setup_active_installation(
        company="D3", category="FINANCE"
    )
    charge = validate_success(
        api.create_billing_charge(
            installation["id"],
            {"charge_type": "ONE_TIME", "base_amount_cents": 10000,
             "description": "setup fee", "discount_code": "LAUNCH10"},
            make_developer_headers(developer["id"]),
        ),
        expected_status=201,
    )
    assert charge["discount_amount_cents"] == 1000, (
        f"expected discount 1000, got {charge['discount_amount_cents']}"
    )
    assert charge["final_amount_cents"] == 9000, (
        f"expected final 9000, got {charge['final_amount_cents']}"
    )
    assert charge["platform_share_cents"] == 0, (
        f"expected share 0 at T0, got {charge['platform_share_cents']}"
    )
    assert charge["developer_net_cents"] == 9000, (
        f"expected net 9000, got {charge['developer_net_cents']}"
    )


def test_launch10_discount_share_finalized_at_invoice_time(api):
    """PRD §3.6: "At creation the share fields are populated provisionally
    using the tier currently in force; they are recomputed and finalized when
    the charge is invoiced."
    PRD §3.6: "The `platform_share_cents` is the tier's rate applied to
    `final_amount_cents` and rounded half-up to integer cents, and the
    `developer_net_cents` is `final_amount_cents` minus
    `platform_share_cents`."

    Design: Difficulty/combinatorial_formula/charge_net_computation_pinned_evaluation_order
    """
    # Pin the developer into T1 before invoicing: one 100000001-cent paid
    # charge pushes lifetime gross to 100000001 (> 100000000 -> T1).
    developer, app, version, merchant, installation = setup_active_installation(
        company="D3B", category="FINANCE"
    )
    seed = create_approved_charge(installation, developer, merchant, 100000001)
    invoice = issue_invoice(open_invoice(merchant, cycle="2026-09"))
    mark_invoice_paid(invoice)
    # Now create the discounted ONE_TIME charge in a later cycle and invoice it.
    set_clock("2026-10-05T00:00:00Z")
    charge = validate_success(
        api.create_billing_charge(
            installation["id"],
            {"charge_type": "ONE_TIME", "base_amount_cents": 10000,
             "description": "setup fee", "discount_code": "LAUNCH10"},
            make_developer_headers(developer["id"]),
        ),
        expected_status=201,
    )
    validate_success(
        api.approve_charge(charge["id"], {}, make_merchant_headers(merchant["id"]))
    )
    invoice2 = open_invoice(merchant, cycle="2026-10")
    issue_invoice(invoice2)
    charge_after = get_success_data(
        api.get_billing_charge(charge["id"], make_admin_headers())
    )
    assert charge_after["final_amount_cents"] == 9000, (
        f"expected final 9000, got {charge_after['final_amount_cents']}"
    )
    # Tier at invoice time is T1 (0.15): share = round(9000 * 0.15) = 1350.
    assert charge_after["platform_share_cents"] == 1350, (
        f"expected share 1350 at T1, got {charge_after['platform_share_cents']}"
    )
    assert charge_after["developer_net_cents"] == 7650, (
        f"expected net 7650, got {charge_after['developer_net_cents']}"
    )


# ---------------------------------------------------------------------------
# combinatorial_formula / usage_proration_aggregation_over_mixed_charges
# ---------------------------------------------------------------------------

def test_usage_proration_aggregated_with_flat_charges(api):
    """PRD §3.6: "the number of whole days elapsed between `installed_at` and
    the current logical time is computed (any partial day is discarded), the
    result is capped at thirty, and the capped amount is `base_amount_cents`
    multiplied by that capped day count and divided by thirty, rounded half-up
    to integer cents."
    PRD §2.11: "The invoice's `total_cents` is a derived aggregate: it is the
    sum of `final_amount_cents` across charges whose `billing_cycle` equals
    the invoice's `cycle`, whose installation belongs to the invoice's
    merchant, and whose status is `INVOICED`."

    Design: Difficulty/combinatorial_formula/usage_proration_aggregation_over_mixed_charges
    """
    developer, app, version, merchant, installation = setup_active_installation(
        company="D4", category="FULFILLMENT", plan_tier="ENTERPRISE"
    )
    # installed_at = 2026-09-01T00:00:00Z (default clock); advance 15 days.
    set_clock("2026-09-16T00:00:00Z")
    usage_charge = create_approved_charge(
        installation, developer, merchant, 1000, charge_type="USAGE"
    )
    assert usage_charge["final_amount_cents"] == 500, (
        f"expected prorated 500 (1000 * 15/30), got "
        f"{usage_charge['final_amount_cents']}"
    )
    create_approved_charge(installation, developer, merchant, 600)
    create_approved_charge(installation, developer, merchant, 4000)
    create_approved_charge(installation, developer, merchant, 5000)
    invoice = issue_invoice(open_invoice(merchant, cycle="2026-09"))
    assert invoice["total_cents"] == 10100, (
        f"expected 10100 (500 + 600 + 4000 + 5000), got {invoice['total_cents']}"
    )


def test_usage_proration_partial_day_discarded(api):
    """PRD §3.6: "the number of whole days elapsed between `installed_at` and
    the current logical time is computed (any partial day is discarded)"

    Design: Difficulty/combinatorial_formula/usage_proration_aggregation_over_mixed_charges
    """
    developer, app, version, merchant, installation = setup_active_installation(
        company="D4B", category="FULFILLMENT"
    )
    # installed_at = 2026-09-01T00:00:00Z; advance exactly 10 whole days plus a
    # partial day (12 hours) — the partial day must be discarded.
    set_clock("2026-09-11T12:00:00Z")
    usage_charge = validate_success(
        api.create_billing_charge(
            installation["id"],
            {"charge_type": "USAGE", "base_amount_cents": 900, "description": "u"},
            make_developer_headers(developer["id"]),
        ),
        expected_status=201,
    )
    # floor(10.5) = 10 days -> round(900 * 10/30) = 300.
    assert usage_charge["final_amount_cents"] == 300, (
        f"expected 300 (900 * 10/30, partial day discarded), got "
        f"{usage_charge['final_amount_cents']}"
    )


# ---------------------------------------------------------------------------
# boundary_precision_check / revenue_share_tier_boundary_1000000_exact
# ---------------------------------------------------------------------------

def test_tier_boundary_exactly_1000000_stays_t0(api):
    """PRD §2.12: "A developer whose lifetime gross is at most 100000000 cents
    (one million dollars) is in tier `T0` — the platform takes zero revenue
    share. Exactly 100000000 cents still qualifies for `T0`."

    Design: Difficulty/boundary_precision_check/revenue_share_tier_boundary_1000000_exact
    """
    developer, app, version, merchant, installation = setup_active_installation(
        company="D11", category="FULFILLMENT"
    )
    c_a = create_approved_charge(installation, developer, merchant, 60000000)
    c_b = create_approved_charge(installation, developer, merchant, 40000000)
    invoice = issue_invoice(open_invoice(merchant, cycle="2026-09"))
    mark_invoice_paid(invoice)
    developer = get_success_data(api.get_developer(developer["id"], make_admin_headers()))
    assert developer["lifetime_gross_cents"] == 100000000, (
        f"expected 100000000, got {developer['lifetime_gross_cents']}"
    )
    app_after = get_success_data(
        api.get_app(app["id"], make_developer_headers(developer["id"]))
    )
    assert app_after["revenue_share_tier"] == "T0", (
        f"expected T0 at exactly 100000000 (inclusive-down), got "
        f"{app_after['revenue_share_tier']}"
    )
    c_b_after = get_success_data(api.get_billing_charge(c_b["id"], make_admin_headers()))
    assert c_b_after["platform_share_cents"] == 0, (
        f"expected share 0 at T0, got {c_b_after['platform_share_cents']}"
    )


def test_tier_boundary_first_cent_above_flips_t1(api):
    """PRD §2.12: "A developer whose lifetime gross is greater than 100000000
    cents and at most 1000000000 cents (ten million dollars) is in tier `T1`.
    The first cent above the boundary — 100000001 — already places the
    developer in `T1`."

    Design: Difficulty/boundary_precision_check/revenue_share_tier_boundary_1000000_exact
    """
    developer, app, version, merchant, installation = setup_active_installation(
        company="D11B", category="FULFILLMENT"
    )
    create_approved_charge(installation, developer, merchant, 100000001)
    invoice = issue_invoice(open_invoice(merchant, cycle="2026-09"))
    mark_invoice_paid(invoice)
    developer = get_success_data(api.get_developer(developer["id"], make_admin_headers()))
    assert developer["lifetime_gross_cents"] == 100000001, (
        f"expected 100000001, got {developer['lifetime_gross_cents']}"
    )
    app_after = get_success_data(
        api.get_app(app["id"], make_developer_headers(developer["id"]))
    )
    assert app_after["revenue_share_tier"] == "T1", (
        f"expected T1 at 100000001, got {app_after['revenue_share_tier']}"
    )


# ---------------------------------------------------------------------------
# boundary_precision_check / performance_budget_inclusive_boundary
# ---------------------------------------------------------------------------

def test_performance_impact_exactly_at_budget_compliant(api):
    """PRD §2.13: "The boundary is inclusive: impact exactly equal to 200
    milliseconds is compliant and does not trigger any state change."

    Design: Difficulty/boundary_precision_check/performance_budget_inclusive_boundary
    """
    developer, app, version, merchant, installation = setup_active_installation(
        company="D12", category="MARKETING"
    )
    dev_headers = make_developer_headers(developer["id"])
    api.create_performance_sample(
        installation["id"],
        {"storefront_load_ms": 100, "sampled_at": "2026-09-05T00:00:00Z"},
        dev_headers,
    )
    app_after = get_success_data(api.get_app(app["id"], dev_headers))
    # impact == 2 * 100 == 200 == BUDGET_MS; inclusive boundary -> COMPLIANT.
    assert app_after["performance_state"] == "COMPLIANT", (
        f"expected COMPLIANT at impact 200, got {app_after['performance_state']}"
    )


def test_performance_impact_one_over_budget_degrades(api):
    """PRD §3.7: "When the impact exceeds the budget, the app's
    `performance_state` transitions to `DEGRADED` and a governance strike with
    reason `PERFORMANCE_BREACH` is opened against the app."

    Design: Difficulty/boundary_precision_check/performance_budget_inclusive_boundary
    """
    developer, app, version, merchant, installation = setup_active_installation(
        company="D12B", category="MARKETING"
    )
    dev_headers = make_developer_headers(developer["id"])
    # Mean of (100, 101) = 100.50 -> impact = round(2 * 100.50) = 201 > 200.
    api.create_performance_sample(
        installation["id"],
        {"storefront_load_ms": 100, "sampled_at": "2026-09-05T00:00:00Z"},
        dev_headers,
    )
    api.create_performance_sample(
        installation["id"],
        {"storefront_load_ms": 101, "sampled_at": "2026-09-05T01:00:00Z"},
        dev_headers,
    )
    app_after = get_success_data(api.get_app(app["id"], dev_headers))
    assert app_after["performance_state"] == "DEGRADED", (
        f"expected DEGRADED at impact 201, got {app_after['performance_state']}"
    )


# ---------------------------------------------------------------------------
# compensating_invariant / charge_reverse_restores_invoice_total_and_lifetime_gross
# ---------------------------------------------------------------------------

def test_reverse_invoiced_charge_recomputes_total(api):
    """PRD §3.8: "An `INVOICED → REVERSED` transition appends a `REVERSAL`
    ledger entry whose `amount_cents` is the negation of the charge's
    `final_amount_cents`, reruns the `FINAL` variant of the developer accrual
    for the developer (superseding the cycle's `PROVISIONAL` entry), and
    recomputes the invoice's `total_cents` over the remaining `INVOICED`
    charges."

    Design: Difficulty/compensating_invariant/charge_reverse_restores_invoice_total_and_lifetime_gross
    """
    developer, app, version, merchant, installation = setup_active_installation(
        company="D17"
    )
    c_a = create_approved_charge(installation, developer, merchant, 9000)
    create_approved_charge(installation, developer, merchant, 4000)
    invoice = issue_invoice(open_invoice(merchant, cycle="2026-09"))
    assert invoice["total_cents"] == 13000, (
        f"expected 13000 at issue, got {invoice['total_cents']}"
    )
    validate_success(api.reverse_charge(c_a["id"], {}, make_admin_headers()))
    invoice_after = get_success_data(api.get_invoice(invoice["id"], make_admin_headers()))
    assert invoice_after["total_cents"] == 4000, (
        f"expected 4000 after reversal, got {invoice_after['total_cents']}"
    )


def test_reverse_invoiced_charge_restores_lifetime_gross(api):
    """PRD §3.8: "An `INVOICED → REVERSED` transition appends a `REVERSAL`
    ledger entry whose `amount_cents` is the negation of the charge's
    `final_amount_cents`, reruns the `FINAL` variant of the developer accrual
    for the developer (superseding the cycle's `PROVISIONAL` entry), and
    recomputes the invoice's `total_cents` over the remaining `INVOICED`
    charges."
    PRD §2.12: "Each developer account carries a computed
    `lifetime_gross_cents`, defined as the sum of `final_amount_cents` over
    every charge across all apps owned by that developer whose status is
    `INVOICED` or `SETTLED`."

    Design: Difficulty/compensating_invariant/charge_reverse_restores_invoice_total_and_lifetime_gross
    """
    developer, app, version, merchant, installation = setup_active_installation(
        company="D17B"
    )
    c_a = create_approved_charge(installation, developer, merchant, 9000)
    create_approved_charge(installation, developer, merchant, 4000)
    invoice = issue_invoice(open_invoice(merchant, cycle="2026-09"))
    validate_success(api.reverse_charge(c_a["id"], {}, make_admin_headers()))
    developer = get_success_data(api.get_developer(developer["id"], make_admin_headers()))
    # The REVERSAL entry exactly cancels the 9000 accrual: 4000 remains.
    assert developer["lifetime_gross_cents"] == 4000, (
        f"expected lifetime_gross_cents 4000 after reversal, got "
        f"{developer['lifetime_gross_cents']}"
    )


# ---------------------------------------------------------------------------
# compensating_invariant / suspend_reinstate_restores_installation_active_set
# ---------------------------------------------------------------------------

def _suspend_reinstate_roundtrip(api, company):
    developer, app, version = setup_listed_app(company=company, category="ANALYTICS")
    merchant_a = create_merchant(shop_domain=f"{company.lower()}a.myshop.com")
    merchant_b = create_merchant(shop_domain=f"{company.lower()}b.myshop.com")
    inst_a = validate_success(
        api.create_installation(
            create_installation_payload(app["id"], merchant_a["id"]),
            make_merchant_headers(merchant_a["id"]),
        ),
        expected_status=201,
    )
    inst_a = get_success_data(
        api.consent_installation(inst_a["id"], {}, make_merchant_headers(merchant_a["id"]))
    )
    inst_b = validate_success(
        api.create_installation(
            create_installation_payload(app["id"], merchant_b["id"]),
            make_merchant_headers(merchant_b["id"]),
        ),
        expected_status=201,
    )
    inst_b = get_success_data(
        api.consent_installation(inst_b["id"], {}, make_merchant_headers(merchant_b["id"]))
    )
    validate_success(api.suspend_app(app["id"], {}, make_admin_headers()))
    validate_success(api.reinstate_app(app["id"], {}, make_admin_headers()))
    return developer, app, inst_a, inst_b


def test_suspend_reinstate_restores_installations(api):
    """PRD §3.11: "On success the app transitions `SUSPENDED → LISTED`, its
    `listing_status` returns to `LISTED`, every installation of the app
    currently in `SUSPENDED` transitions back to `ACTIVE`, and the app's
    `version` increments."

    Design: Difficulty/compensating_invariant/suspend_reinstate_restores_installation_active_set
    """
    developer, app, inst_a, inst_b = _suspend_reinstate_roundtrip(api, "D18")
    inst_a_after = get_success_data(api.get_installation(inst_a["id"], make_admin_headers()))
    inst_b_after = get_success_data(api.get_installation(inst_b["id"], make_admin_headers()))
    assert inst_a_after["status"] == "ACTIVE", (
        f"expected ACTIVE after round trip, got {inst_a_after['status']}"
    )
    assert inst_b_after["status"] == "ACTIVE", (
        f"expected ACTIVE after round trip, got {inst_b_after['status']}"
    )


def test_suspend_reinstate_preserves_active_installation_count(api):
    """PRD §3.11: "On success the app transitions `SUSPENDED → LISTED`, its
    `listing_status` returns to `LISTED`, every installation of the app
    currently in `SUSPENDED` transitions back to `ACTIVE`, and the app's
    `version` increments."

    Design: Difficulty/compensating_invariant/suspend_reinstate_restores_installation_active_set
    """
    developer, app, inst_a, inst_b = _suspend_reinstate_roundtrip(api, "D18B")
    installations, _ = validate_paginated(
        api.list_app_installations(
            app["id"], make_admin_headers(), params={"status": "ACTIVE"}
        )
    )
    assert len(installations) == 2, (
        f"expected 2 ACTIVE installations after the forward+compensating "
        f"pair, got {len(installations)}"
    )
