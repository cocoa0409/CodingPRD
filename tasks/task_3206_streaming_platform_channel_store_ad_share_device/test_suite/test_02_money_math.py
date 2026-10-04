"""Money-math tests: combinatorial statement netting and pinned rounding
order for ad revenue."""
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    ApiErrorId,
    create_publisher,
    create_published_channel,
    create_viewer,
    create_subscription,
    create_ad_slot_grant,
    create_active_campaign,
    generate_statement,
    set_clock,
    make_publisher_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
ADOPS = TEST_USERS["adops_headers"]


def _finalize_statement(statement_id):
    get_success_data(api_client.finalize_statement(statement_id, ADMIN))
    return get_success_data(api_client.get_statement(statement_id, ADMIN))


def test_statement_net_payout_combines_all_inputs_with_penalty():
    """PRD §3.1: "a publisher in `SUSPENDED` standing at statement
    finalization time pays a platform fee five hundred basis points above its
    tier rate, and any ad-grant resplit computed while the publisher is
    suspended applies the same five-hundred-basis-point penalty to the
    publisher's share (§3.4)."
    PRD §3.7: "The statement's `net_payout_cents` is then the subscription
    payout plus the ad payout minus the placement spend, and it too may be
    negative."

    Design: Difficulty/combinatorial_formula/statement_net_payout_tier_penalty_and_four_inputs
    """
    publisher = create_publisher(
        legal_name="Combo Pub", default_ad_share_bps=7000,
        billing_model="GROSS_SHARE",
    )
    channel = create_published_channel(publisher)

    grant = create_ad_slot_grant(channel["id"], period="2026-09",
                                 total_slots=1000)
    resp = api_client.record_ad_slot_revenue(
        grant["id"], {"slot_revenue_entries": [1001, 1001]}, ADOPS,
    )
    validate_success(resp)

    viewer = create_viewer(email="s1@x.com")
    create_subscription(channel["id"], viewer["id"], price_cents=30000)
    create_subscription(channel["id"], viewer["id"], price_cents=30000)
    create_subscription(channel["id"], viewer["id"], price_cents=30000)
    refunded = create_subscription(channel["id"], viewer["id"],
                                   price_cents=10000)
    get_success_data(api_client.refund_subscription(refunded["id"], ADMIN))

    campaign = create_active_campaign(publisher, channel["id"],
                                      budget_cents=100000)
    resp = api_client.record_campaign_impressions(
        campaign["id"], {"impression_count": 5000, "cpm_cents": 1000}, ADOPS,
    )
    validate_success(resp)

    get_success_data(api_client.set_publisher_standing(
        publisher["id"], {"to_standing": "SUSPENDED", "reason": "fraud review"},
        ADMIN,
    ))

    statement = generate_statement(publisher["id"], "2026-09")
    final = _finalize_statement(statement["id"])

    assert final["subscription_gross_cents"] == 100000
    assert final["refund_cents"] == 10000
    assert final["charge_count"] == 4
    assert final["applied_tier"] == "STANDARD"
    assert final["applied_fee_bps"] == 2500, (
        f"2000 tier + 500 SUSPENDED penalty = 2500, got "
        f"{final['applied_fee_bps']}"
    )
    assert final["sub_payout_cents"] == 67500, (
        f"round_half_up(90000 * 7500/10000) = 67500, got "
        f"{final['sub_payout_cents']}"
    )
    assert final["platform_sub_fee_cents"] == 22500
    assert final["ad_gross_cents"] == 2002
    assert final["ad_payout_cents"] == 1402
    assert final["platform_ad_fee_cents"] == 600
    assert final["placement_spend_cents"] == 5000
    assert final["net_payout_cents"] == 63902, (
        f"67500 + 1402 - 5000 = 63902, got {final['net_payout_cents']}"
    )


def test_statement_net_payout_negative_balance_accrues():
    """PRD §3.7: "Finalization moves the statement from `OPEN` to `FINALIZED`
    and locks every amount. If the locked net is negative, the publisher owes
    the platform: `outstanding_balance_cents` increases by the negated net."

    Design: Difficulty/combinatorial_formula/statement_net_payout_tier_penalty_and_four_inputs
    """
    publisher = create_publisher(legal_name="Neg Pub")
    channel = create_published_channel(publisher)
    # A campaign spends 200000 in the period with no subscription revenue,
    # so the net is -200000.
    campaign = create_active_campaign(publisher, channel["id"],
                                      budget_cents=200000)
    resp = api_client.record_campaign_impressions(
        campaign["id"], {"impression_count": 200000, "cpm_cents": 1000},
        ADOPS,
    )
    validate_success(resp)

    statement = generate_statement(publisher["id"], "2026-09")
    final = _finalize_statement(statement["id"])

    assert final["net_payout_cents"] == -200000
    refreshed = get_success_data(api_client.get_publisher(publisher["id"], ADMIN))
    assert refreshed["outstanding_balance_cents"] == 200000, (
        f"negative net -200000 must accrue to outstanding_balance_cents, "
        f"got {refreshed['outstanding_balance_cents']}"
    )


def test_ad_revenue_per_entry_rounding_then_sum():
    """PRD §3.4: "Sum-then-round is never acceptable: with entries of one
    cent, one cent, and one cent at 3333 basis points, the pinned
    per-entry-then-sum answer is a publisher payout of zero, where the
    counterfactual sum-then-round would yield one cent."

    Design: Difficulty/combinatorial_formula/ad_revenue_per_entry_rounding_then_sum_pinned
    """
    publisher = create_publisher(legal_name="Round Pub",
                                 default_ad_share_bps=3333)
    channel = create_published_channel(publisher)
    grant = create_ad_slot_grant(channel["id"], period="2026-09",
                                 total_slots=100)

    resp = api_client.record_ad_slot_revenue(
        grant["id"], {"slot_revenue_entries": [1, 1, 1]}, ADOPS,
    )
    updated = validate_success(resp)

    assert updated["ad_gross_cents"] == 3
    assert updated["publisher_payout_cents"] == 0, (
        "per-entry round_half_up(1 * 3333/10000) = 0 three times; "
        f"got {updated['publisher_payout_cents']}"
    )


def test_ad_revenue_accumulates_across_batches():
    """PRD §3.4: "The rounding order is pinned and audit-critical: for each
    entry, processed in array order, the publisher's payout from that entry is
    computed first — the entry amount multiplied by `publisher_share_bps`,
    divided by 10000, rounded half-up to the nearest cent — and only then are
    the per-entry payouts summed into the grant's `publisher_payout_cents`."

    Design: Difficulty/combinatorial_formula/ad_revenue_per_entry_rounding_then_sum_pinned
    """
    publisher = create_publisher(legal_name="Round Pub 2",
                                 default_ad_share_bps=3333)
    channel = create_published_channel(publisher)
    grant = create_ad_slot_grant(channel["id"], period="2026-09",
                                 total_slots=100)

    # Two batches; each entry rounds per-entry: 3 * 3333/10000 = 0.9999 -> 1
    # per entry.
    resp = api_client.record_ad_slot_revenue(
        grant["id"], {"slot_revenue_entries": [3, 3]}, ADOPS,
    )
    validate_success(resp)
    resp = api_client.record_ad_slot_revenue(
        grant["id"], {"slot_revenue_entries": [3]}, ADOPS,
    )
    updated = validate_success(resp)

    assert updated["ad_gross_cents"] == 9
    assert updated["publisher_payout_cents"] == 3, (
        f"3 entries of round_half_up(3*3333/10000)=1 each; got "
        f"{updated['publisher_payout_cents']}"
    )
