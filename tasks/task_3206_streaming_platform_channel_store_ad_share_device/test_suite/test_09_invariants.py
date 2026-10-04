"""Invariant tests: slot conservation across resplit and money conservation
across a post-finalize refund."""
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    create_publisher,
    create_published_channel,
    create_ad_slot_grant,
    create_viewer,
    create_subscription,
    generate_statement,
    set_clock,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


def test_slot_conservation_across_resplit_under_standing_penalty():
    """PRD §3.4: "The invariant `publisher_slots + platform_slots ==
    total_slots` holds at creation and after every resplit."
    PRD §3.4: "At resplit the effective share is recomputed from the
    publisher's current `default_ad_share_bps`, minus five hundred basis
    points if the publisher's `standing` is currently `SUSPENDED`, floored at
    zero; the same floor-division split then recomputes `publisher_slots` and
    `platform_slots`, conserving the invariant, and the grant's `version`
    increments by 1."

    Design: Difficulty/compensating_invariant/slot_conservation_across_resplit_under_standing_penalty
    """
    publisher = create_publisher(legal_name="Inv Pub",
                                 default_ad_share_bps=7000)
    channel = create_published_channel(publisher)
    grant = create_ad_slot_grant(channel["id"], period="2026-09",
                                 total_slots=1001)
    assert grant["publisher_slots"] == 700
    assert grant["platform_slots"] == 301
    assert grant["publisher_slots"] + grant["platform_slots"] == 1001

    get_success_data(api_client.set_publisher_standing(
        publisher["id"], {"to_standing": "SUSPENDED", "reason": "audit"},
        ADMIN,
    ))

    resp = api_client.resplit_ad_slot_grant(
        grant["id"], {"expected_grant_version": grant["version"]}, ADMIN,
    )
    resplit = validate_success(resp)
    assert resplit["publisher_slots"] == 650, (
        f"floor(1001 * 6500/10000) = floor(650.65) = 650, got "
        f"{resplit['publisher_slots']}"
    )
    assert resplit["platform_slots"] == 351
    assert resplit["publisher_slots"] + resplit["platform_slots"] == 1001


def test_statement_money_conservation_across_post_finalize_refund():
    """PRD §3.6: "A refund also stamps `refunded_at` from the logical clock,
    and this timestamp governs statement attribution: the refund counts
    against the statement period containing `refunded_at`, regardless of when
    the original charge occurred (§3.7)."
    PRD §3.7: "`refund_cents` is the sum of `price_cents` over subscriptions
    refunded within the period (their `refunded_at` falls in the period),
    regardless of when they were created."

    Design: Difficulty/compensating_invariant/statement_money_conservation_across_post_finalize_refund
    """
    publisher = create_publisher(legal_name="Money Pub",
                                 billing_model="GROSS_SHARE")
    channel = create_published_channel(publisher)
    viewer = create_viewer(email="mv@x.com")
    subscription = create_subscription(channel["id"], viewer["id"],
                                       price_cents=10000)

    st1 = generate_statement(publisher["id"], "2026-09")
    get_success_data(api_client.finalize_statement(st1["id"], ADMIN))
    st1_final = get_success_data(api_client.get_statement(st1["id"], ADMIN))
    assert st1_final["subscription_gross_cents"] == 10000
    assert st1_final["refund_cents"] == 0
    assert st1_final["sub_payout_cents"] == 8000
    assert st1_final["platform_sub_fee_cents"] == 2000
    assert (
        st1_final["sub_payout_cents"] + st1_final["platform_sub_fee_cents"]
        == st1_final["subscription_gross_cents"] - st1_final["refund_cents"]
    )

    set_clock("2026-10-01T00:00:00Z")
    get_success_data(api_client.refund_subscription(subscription["id"], ADMIN))

    st2 = generate_statement(publisher["id"], "2026-10")
    get_success_data(api_client.finalize_statement(st2["id"], ADMIN))
    st2_final = get_success_data(api_client.get_statement(st2["id"], ADMIN))
    assert st2_final["subscription_gross_cents"] == 0
    assert st2_final["refund_cents"] == 10000
    assert st2_final["sub_payout_cents"] == -8000, (
        f"compensating negative payout; got {st2_final['sub_payout_cents']}"
    )
    assert st2_final["platform_sub_fee_cents"] == -2000

    base_total = (
        (st1_final["subscription_gross_cents"] - st1_final["refund_cents"])
        + (st2_final["subscription_gross_cents"] - st2_final["refund_cents"])
    )
    payout_total = (
        st1_final["sub_payout_cents"] + st2_final["sub_payout_cents"]
    )
    fee_total = (
        st1_final["platform_sub_fee_cents"]
        + st2_final["platform_sub_fee_cents"]
    )
    assert base_total == 0
    assert payout_total == 0
    assert fee_total == 0


def test_outstanding_balance_accrues_and_clears_on_settle():
    """PRD §3.7: "If the locked net is negative, the publisher owes the
    platform: `outstanding_balance_cents` increases by the negated net.
    Settlement — moving a `FINALIZED` statement to `SETTLED` — is the
    platform's acknowledgment that the obligation is discharged; if the net
    was negative, `outstanding_balance_cents` decreases by the negated net,
    floored at zero."

    Design: Difficulty/compensating_invariant/statement_money_conservation_across_post_finalize_refund
    """
    publisher = create_publisher(legal_name="Money Pub 2",
                                 billing_model="GROSS_SHARE")
    channel = create_published_channel(publisher)
    viewer = create_viewer(email="mv2@x.com")
    subscription = create_subscription(channel["id"], viewer["id"],
                                       price_cents=10000)

    st1 = generate_statement(publisher["id"], "2026-09")
    get_success_data(api_client.finalize_statement(st1["id"], ADMIN))

    set_clock("2026-10-01T00:00:00Z")
    get_success_data(api_client.refund_subscription(subscription["id"], ADMIN))
    st2 = generate_statement(publisher["id"], "2026-10")
    get_success_data(api_client.finalize_statement(st2["id"], ADMIN))

    after_finalize = get_success_data(
        api_client.get_publisher(publisher["id"], ADMIN)
    )
    assert after_finalize["outstanding_balance_cents"] == 8000

    get_success_data(api_client.settle_statement(st2["id"], ADMIN))
    after_settle = get_success_data(
        api_client.get_publisher(publisher["id"], ADMIN)
    )
    assert after_settle["outstanding_balance_cents"] == 0
