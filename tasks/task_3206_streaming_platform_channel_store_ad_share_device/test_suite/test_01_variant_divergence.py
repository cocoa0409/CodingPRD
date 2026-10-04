"""Variant-divergence tests: identical inputs, two valid algorithms,
different cents (subscription payout and device subsidy recovery)."""
from test_helpers import (
    api_client,
    validate_success,
    create_publisher,
    create_published_channel,
    create_viewer,
    create_subscription,
    create_manufacturer,
    create_certified_model,
    create_activated_unit,
    finalize_statement,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
ADOPS = TEST_USERS["adops_headers"]


def test_subscription_payout_gross_share_variant():
    """PRD §3.7: "Under the `GROSS_SHARE` variant, the publisher's
    `sub_payout_cents` is the base multiplied by the publisher's share — 10000
    minus the applied fee basis points — divided by 10000, rounded half-up; the
    processing fee is invisible to the payout."

    Design: Difficulty/dual_variant_calc/subscription_payout_gross_vs_net_variant_divergence
    """
    publisher = create_publisher(
        legal_name="Gross Pub",
        default_ad_share_bps=7000,
        billing_model="GROSS_SHARE",
    )
    channel = create_published_channel(publisher)
    viewer = create_viewer(email="vg@x.com")
    create_subscription(channel["id"], viewer["id"], price_cents=999)

    statement = finalize_statement(publisher["id"], "2026-09")

    assert statement["subscription_gross_cents"] == 999
    assert statement["charge_count"] == 1
    assert statement["applied_tier"] == "STANDARD"
    assert statement["applied_fee_bps"] == 2000
    assert statement["sub_payout_cents"] == 799, (
        f"GROSS_SHARE payout must be round_half_up(999 * 8000/10000) = 799, "
        f"got {statement['sub_payout_cents']}"
    )
    assert statement["platform_sub_fee_cents"] == 200


def test_subscription_payout_net_of_fees_variant():
    """PRD §3.7: "Under the `NET_OF_FEES` variant, a processing fee of 55
    cents per charge is deducted first — 55 multiplied by `charge_count` — and
    the share is applied to what remains, again rounded half-up; given the same
    data, this variant yields a strictly smaller payout whenever there is at
    least one charge and the fee rate is below the whole."

    Design: Difficulty/dual_variant_calc/subscription_payout_gross_vs_net_variant_divergence
    """
    publisher = create_publisher(
        legal_name="Net Pub",
        default_ad_share_bps=7000,
        billing_model="NET_OF_FEES",
    )
    channel = create_published_channel(publisher)
    viewer = create_viewer(email="vn@x.com")
    create_subscription(channel["id"], viewer["id"], price_cents=999)

    statement = finalize_statement(publisher["id"], "2026-09")

    assert statement["subscription_gross_cents"] == 999
    assert statement["charge_count"] == 1
    assert statement["sub_payout_cents"] == 755, (
        f"NET_OF_FEES payout must be round_half_up((999 - 55) * 8000/10000) "
        f"= 755, got {statement['sub_payout_cents']}"
    )
    assert statement["platform_sub_fee_cents"] == 244


def test_device_subsidy_recovery_straight_line_variant():
    """PRD §3.10: "Under `STRAIGHT_LINE`, `AdOps` accrues one month of
    recovery at a time: the monthly amount is the floor of `subsidy_cents`
    divided by 24 — twenty-four monthly installments — and each accrual
    recovers the smaller of that monthly amount and the subsidy still
    outstanding (the subsidy minus what is already recovered and written
    off)."

    Design: Difficulty/dual_variant_calc/device_subsidy_recovery_straight_line_vs_monetization_divergence
    """
    manufacturer = create_manufacturer(legal_name="Acme TV")
    model = create_certified_model(
        manufacturer, recovery_policy="STRAIGHT_LINE", model_code="SL-100",
        bench_code="LAB_BENCH_1",
    )
    viewer = create_viewer(email="v1@x.com")
    unit = create_activated_unit(
        manufacturer, model["id"], viewer["id"],
        serial_number="S-1", hardware_cost_cents=20000, sale_price_cents=9999,
    )
    assert unit["subsidy_cents"] == 10001

    resp = api_client.accrue_straight_line(unit["id"], ADOPS)
    updated = validate_success(resp)

    assert updated["subsidy_recovered_cents"] == 416, (
        f"floor(10001/24) = 416, got {updated['subsidy_recovered_cents']}"
    )
    assert updated["subsidy_outstanding_cents"] == 9585
    assert (
        updated["subsidy_cents"]
        == updated["subsidy_recovered_cents"]
        + updated["subsidy_written_off_cents"]
        + updated["subsidy_outstanding_cents"]
    )


def test_device_subsidy_recovery_monetization_variant():
    """PRD §3.10: "Under `MONETIZATION`, `AdOps` records attributed ad
    `revenue_cents` against the unit, and the recovery is 3500 basis points of
    that revenue — thirty-five percent — rounded half-up to the nearest cent,
    then capped at the subsidy still outstanding."

    Design: Difficulty/dual_variant_calc/device_subsidy_recovery_straight_line_vs_monetization_divergence
    """
    manufacturer = create_manufacturer(legal_name="Monet TV")
    model = create_certified_model(
        manufacturer, recovery_policy="MONETIZATION", model_code="MN-100",
        bench_code="LAB_BENCH_2",
    )
    viewer = create_viewer(email="v2@x.com")
    unit = create_activated_unit(
        manufacturer, model["id"], viewer["id"],
        serial_number="M-1", hardware_cost_cents=20000, sale_price_cents=9999,
    )
    assert unit["subsidy_cents"] == 10001

    resp = api_client.record_device_ad_revenue(
        unit["id"], {"revenue_cents": 10000}, ADOPS,
    )
    updated = validate_success(resp)

    assert updated["subsidy_recovered_cents"] == 3500, (
        f"round_half_up(10000 * 3500/10000) = 3500, "
        f"got {updated['subsidy_recovered_cents']}"
    )
    assert updated["subsidy_outstanding_cents"] == 6501
    assert (
        updated["subsidy_cents"]
        == updated["subsidy_recovered_cents"]
        + updated["subsidy_written_off_cents"]
        + updated["subsidy_outstanding_cents"]
    )
