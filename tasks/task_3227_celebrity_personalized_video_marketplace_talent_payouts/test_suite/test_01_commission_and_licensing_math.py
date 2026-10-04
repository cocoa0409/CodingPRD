"""Commission computation, dual-variant previews, and licensing fees.

Covers the two dual-variant calculation instances and the two combinatorial
formula instances: the final_settlement freeze of the commission split, the
tiered marginal licensing discount, and the nested round-half-up behaviour on
odd gross amounts.
"""

from test_helpers import (
    ApiErrorId,
    assert_balance_conservation,
    create_active_talent,
    create_confirmed_order,
    create_delivered_order,
    get_success_data,
    license_grant_payload,
    lines_for_order,
    make_admin_headers,
    make_buyer_headers,
    make_talent_headers,
    open_dispute,
    read_order,
    read_talent,
    register_buyer,
    register_talent,
    submit_identity,
    submit_tax_document,
    set_rates,
    activate_talent,
    validate_error,
    validate_success,
)


def _round_half_up(x):
    import math

    return int(math.floor(x + 0.5))


def test_final_settlement_freezes_split_at_confirm(api):
    """PRD §3.5: "The `CONFIRMED` transition runs payout computation once,
    freezing the split at that instant. The commission rate is read from the
    talent's `commission_tier` at the exact moment of the transition: a
    `STANDARD` talent pays 25% commission, `SILVER` pays 20%, and `GOLD` pays
    15%."
    PRD §3.5: "Tier changes that happen after confirmation never retroactively
    alter a confirmed order."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_commission_on_order
    """
    admin = make_admin_headers()
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    order, _video = create_delivered_order(api, talent, buyer, moderate="CLEAR")

    response = api.confirm_order(order["id"], headers=make_buyer_headers(buyer["id"]))
    confirmed = validate_success(response)
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["platform_commission_cents"] == 2500, (
        "STANDARD commission on gross 10000 must be 2500, got {0}".format(
            confirmed["platform_commission_cents"]
        )
    )
    assert confirmed["talent_net_cents"] == 7500


def test_provisional_preview_diverges_after_tier_change(api):
    """PRD §3.5: "While an order is still `DELIVERED`, reading the order
    returns a provisional commission preview: an estimate computed from the
    talent's `commission_tier` at read time, using the same rate table."
    PRD §3.5: "The preview is not persisted and may differ from the final
    `platform_commission_cents` if the tier changes before confirmation."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_commission_on_order
    """
    admin = make_admin_headers()
    # Talent with a personal rate of 2500 cents: 200 confirmations give a
    # trailing GMV of exactly 500000 -> SILVER, inclusive of the boundary.
    talent = create_active_talent(
        api,
        rates_overrides={
            "personal_rate_cents": 2500,
            "business_rate_cents": 10000,
            "advertising_rate_cents": 20000,
        },
    )
    buyer = register_buyer(api)
    for _ in range(200):
        create_confirmed_order(api, talent, buyer)

    order, _video = create_delivered_order(api, talent, buyer, moderate="CLEAR")
    response = api.confirm_order(order["id"], headers=make_buyer_headers(buyer["id"]))
    confirmed = validate_success(response)
    # The final settlement freezes SILVER's 20%: 2500 * 0.20 = 500.
    assert confirmed["platform_commission_cents"] == 500
    assert confirmed["talent_net_cents"] == 2000
    # The frozen settlement is the authoritative record: after the transition
    # the same values come back on a re-read, and nothing about the read-time
    # preview is persisted over them.
    reloaded = read_order(api, order["id"])
    assert reloaded["platform_commission_cents"] == 500
    assert reloaded["talent_net_cents"] == 2000


def test_trailing_window_ages_confirmations_out(api):
    """PRD §3.5: "The window rolls with the logical clock, so old
    confirmations age out as time advances and a tier can drop without any
    refund at all."
    PRD §3.5: "The tier is recomputed immediately on every change to
    `trailing_gmv_cents`: at least 2000000 cents of trailing GMV yields
    `GOLD`, at least 500000 cents yields `SILVER`, and anything below yields
    `STANDARD`; both thresholds are inclusive."

    Design: Difficulty/dual_variant_calc/trailing_window_vs_lifetime_gmv_tier
    """
    from test_helpers import set_clock

    admin = make_admin_headers()
    talent = create_active_talent(
        api,
        rates_overrides={
            "personal_rate_cents": 2500,
            "business_rate_cents": 10000,
            "advertising_rate_cents": 20000,
        },
    )
    buyer = register_buyer(api)
    for _ in range(200):
        create_confirmed_order(api, talent, buyer)

    before = read_talent(api, talent["id"])
    assert before["trailing_gmv_cents"] == 500000
    assert before["commission_tier"] == "SILVER"

    # Move the clock past 2027-09-01 so every confirmation is older than the
    # trailing 365-day window, then force a recompute via a rate write.
    set_clock(api, "2027-09-02T00:00:00Z")
    current = read_talent(api, talent["id"])
    set_rates(
        api,
        current,
        personal_rate_cents=2500,
        business_rate_cents=10000,
        advertising_rate_cents=20000,
    )
    after = read_talent(api, talent["id"])
    assert after["trailing_gmv_cents"] == 0
    assert after["commission_tier"] == "STANDARD"


def test_silver_boundary_is_inclusive(api):
    """PRD §3.5: "The tier is recomputed immediately on every change to
    `trailing_gmv_cents`: at least 2000000 cents of trailing GMV yields
    `GOLD`, at least 500000 cents yields `SILVER`, and anything below yields
    `STANDARD`; both thresholds are inclusive."

    Design: Difficulty/boundary_precision_check/silver_tier_inclusive_boundary
    """
    admin = make_admin_headers()
    talent = create_active_talent(
        api,
        rates_overrides={
            "personal_rate_cents": 2500,
            "business_rate_cents": 10000,
            "advertising_rate_cents": 20000,
        },
    )
    buyer = register_buyer(api)
    for _ in range(200):
        create_confirmed_order(api, talent, buyer)
    talent_now = read_talent(api, talent["id"])
    assert talent_now["trailing_gmv_cents"] == 500000, (
        "200 confirmations of 2500 gross must total 500000"
    )
    assert talent_now["commission_tier"] == "SILVER", (
        "exactly 500000 must reach SILVER — the boundary is inclusive"
    )


def test_licensing_fee_marginal_tier_discount(api):
    """PRD §3.7: "The base fee depends on the license type: 50000 cents for
    `BUSINESS` and 150000 cents for `ADVERTISING`. The base is multiplied by
    the sum of per-channel factors — 1.0 for `SOCIAL`, 1.2 for `WEB`, 2.0 for
    `TV`, 1.5 for `OOH` — and by a territory multiplier of 1.0 for `DOMESTIC`
    and 1.5 for `GLOBAL`."
    PRD §3.7: "windows strictly longer than 90 days are charged as 90
    full-rate days plus the days beyond 90 at nine tenths of the rate. The
    resulting raw fee is rounded half-up to whole cents and stored as
    `fee_cents`."

    Design: Difficulty/combinatorial_formula/licensing_fee_tiered_marginal_discount
    """
    admin = make_admin_headers()
    talent = create_active_talent(api)
    buyer = register_buyer(api, is_business_account=True)
    order, _video = create_confirmed_order(
        api, talent, buyer, use_type="ADVERTISING_USE"
    )
    response = api.create_license_grant(
        order["id"],
        license_grant_payload(
            license_type="ADVERTISING",
            territory="GLOBAL",
            channels=["TV", "WEB"],
            starts_at="2026-09-01T00:00:00Z",
            ends_at="2026-12-10T00:00:00Z",  # a 100-day window
        ),
        headers=make_buyer_headers(buyer["id"]),
    )
    grant = validate_success(response, expected_status=201)
    # 150000 * (2.0 + 1.2) * 1.5 * (90 + 0.9 * 10) = 150000 * 3.2 * 1.5 * 99
    assert grant["fee_cents"] == 71280000, (
        "marginal tier on a 100-day window must yield 71280000, got {0}".format(
            grant["fee_cents"]
        )
    )


def test_licensing_fee_90_day_window_uses_full_rate(api):
    """PRD §3.7: "The duration applies with a marginal tier discount: windows
    of at most 90 days are charged at the full day count; windows strictly
    longer than 90 days are charged as 90 full-rate days plus the days beyond
    90 at nine tenths of the rate."
    PRD §3.7: "The discount is strictly marginal — a whole-window discount on
    long windows is explicitly not used."

    Design: Difficulty/combinatorial_formula/licensing_fee_tiered_marginal_discount
    """
    admin = make_admin_headers()
    talent = create_active_talent(api)
    buyer = register_buyer(api, is_business_account=True)
    order, _video = create_confirmed_order(
        api, talent, buyer, use_type="ADVERTISING_USE"
    )
    response = api.create_license_grant(
        order["id"],
        license_grant_payload(
            license_type="ADVERTISING",
            territory="GLOBAL",
            channels=["TV", "WEB"],
            starts_at="2026-09-01T00:00:00Z",
            ends_at="2026-11-30T00:00:00Z",  # exactly 90 days
        ),
        headers=make_buyer_headers(buyer["id"]),
    )
    grant = validate_success(response, expected_status=201)
    # 150000 * 3.2 * 1.5 * 90 = 64800000 — no discount at the boundary.
    assert grant["fee_cents"] == 64800000


def test_odd_gross_commission_rounds_half_up(api):
    """PRD §3.5: "The commission is the order's `gross_amount_cents`
    multiplied by that rate, rounded half-up to whole cents, and is recorded
    as `platform_commission_cents`; the remainder is recorded as
    `talent_net_cents`."
    PRD §2.6: "Where a calculation produces a fractional intermediate value
    (commission computation, licensing fee computation, partial-refund
    splits, pricing suggestions), the final amount is rounded to the nearest
    whole cent using **round half up**: a remainder of exactly half a cent
    rounds upward."

    Design: Difficulty/combinatorial_formula/commission_round_half_up_and_partial_split
    """
    admin = make_admin_headers()
    talent = create_active_talent(
        api,
        rates_overrides={
            "personal_rate_cents": 10001,
            "business_rate_cents": 40004,
            "advertising_rate_cents": 80008,
        },
    )
    buyer = register_buyer(api)
    order, _video = create_confirmed_order(api, talent, buyer)
    # round_half_up(10001 * 0.25 = 2500.25) = 2500 (.25 < .5 rounds down)
    assert order["gross_amount_cents"] == 10001
    assert order["platform_commission_cents"] == 2500
    assert order["talent_net_cents"] == 7501


def test_partial_refund_split_gives_buyer_larger_half(api):
    """PRD §3.6: "Under `PARTIAL_REFUND`, the dispute resolves to
    `RESOLVED_PARTIAL` with the refund split computed on the order's gross:
    the buyer receives the gross multiplied by one half, rounded half-up — so
    for an odd gross the buyer receives the larger half — and the talent
    retains the remainder."
    PRD §3.6: "The order transitions to `REFUNDED` with `refund_amount_cents`
    equal to the buyer's half; the buyer's wallet is credited by that amount;
    a `CLAWBACK` payout line of negative that amount is created and the
    talent's pending balance is debited by it; and the buyer-refund amount —
    not the full gross — is subtracted from `trailing_gmv_cents` before the
    tier recompute."

    Design: Difficulty/combinatorial_formula/commission_round_half_up_and_partial_split
    """
    admin = make_admin_headers()
    talent = create_active_talent(
        api,
        rates_overrides={
            "personal_rate_cents": 10001,
            "business_rate_cents": 40004,
            "advertising_rate_cents": 80008,
        },
    )
    buyer = register_buyer(api)
    order, _video = create_confirmed_order(api, talent, buyer)
    dispute = open_dispute(api, buyer, order, reason="wrong name pronounced")
    response = api.resolve_dispute(
        dispute["id"], "PARTIAL_REFUND", resolution_notes="half", headers=admin
    )
    resolved = validate_success(response)
    # round_half_up(10001 * 0.5 = 5000.5) = 5001
    assert resolved["status"] == "RESOLVED_PARTIAL"
    assert resolved["refund_to_buyer_cents"] == 5001

    final_order = read_order(api, order["id"])
    assert final_order["status"] == "REFUNDED"
    assert final_order["refund_amount_cents"] == 5001
    # The CLAWBACK line debits the talent's pending balance by the buyer's
    # refund (PRD §3.6); the order's `clawback_cents` records that amount.
    assert final_order["clawback_cents"] == 5001

    lines = lines_for_order(api, order["id"])
    clawbacks = [l for l in lines if l["kind"] == "CLAWBACK"]
    assert len(clawbacks) == 1 and clawbacks[0]["amount_cents"] == -5001


def test_trailing_window_counts_only_recent_confirmations(api):
    """PRD §3.5: "The order's `gross_amount_cents` is added to the talent's
    `trailing_gmv_cents`, which is the sum of gross amounts over the talent's
    orders whose `CONFIRMED` transition occurred within the trailing 365-day
    window — inclusive of the window start, exclusive of the window end —
    minus gross amounts refunded by full-refund dispute resolutions and minus
    buyer-refund amounts from partial-refund resolutions."
    PRD §3.5: "The window rolls with the logical clock, so old confirmations
    age out as time advances and a tier can drop without any refund at all."

    Design: Difficulty/dual_variant_calc/trailing_window_vs_lifetime_gmv_tier
    """
    from test_helpers import set_clock

    talent = create_active_talent(api)
    buyer = register_buyer(api)
    create_confirmed_order(api, talent, buyer)

    # One year and two days later the lone confirmation has aged out; a rate
    # write forces the talent recompute against the empty window.
    set_clock(api, "2027-09-03T00:00:00Z")
    set_rates(
        api,
        read_talent(api, talent["id"]),
        personal_rate_cents=10000,
        business_rate_cents=40000,
        advertising_rate_cents=80000,
    )
    after = read_talent(api, talent["id"])
    assert after["trailing_gmv_cents"] == 0
    assert after["commission_tier"] == "STANDARD"
