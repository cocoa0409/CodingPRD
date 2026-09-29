"""Distribution cost per booking: the two variants the service publishes side by side."""

from test_helpers import (
    AUDITOR_HEADERS,
    DISTRIBUTION_MANAGER_HEADERS,
    agency_headers,
    fixtures as fx,
    validate_success,
)


def _paid_and_authorized_orders(api):
    """Build the aggregator channel, a signed agreement, and two orders on it.

    The first order (a la carte, total 59560) is captured; the second (bundle,
    total 57037) is left AUTHORIZED so the caller can capture it as the trigger.
    """
    channel = fx.create_ndc_channel(api)
    partner = fx.create_alpha_agency(api)
    catalogue = fx.create_ndc_catalogue(api)
    filing = fx.create_ndc_filing(api)
    agreement = fx.create_signed_agreement(
        api,
        partner["id"],
        channel["id"],
        partner["version"],
        proposed_incentive_pct=0.025,
        incentive_cap_cents=1000000,
        target_net_revenue_cents=5000000,
    )
    headers = agency_headers(partner["id"])

    offer_a = fx.construct_offer(
        api,
        channel["id"],
        partner["id"],
        filing["id"],
        headers=headers,
        ancillary_codes=[fx.ANCILLARY_BAG, fx.ANCILLARY_SEAT, fx.ANCILLARY_WIFI],
    )
    fx.publish_offer(api, offer_a["id"], fx.NDC_DISCLOSURE_CODES, headers=headers)
    order_a = fx.create_order(
        api,
        offer_a["id"],
        fx.NDC_DISCLOSURE_CODES,
        headers=headers,
        message_count=4,
        segment_count=2,
    )
    fx.capture_payment(api, order_a["id"], 59560, headers=headers)

    offer_b = fx.construct_offer(
        api,
        channel["id"],
        partner["id"],
        filing["id"],
        headers=headers,
        bundle_id=catalogue["bundle"]["id"],
    )
    fx.publish_offer(api, offer_b["id"], fx.NDC_DISCLOSURE_CODES, headers=headers)
    order_b = fx.create_order(
        api,
        offer_b["id"],
        fx.NDC_DISCLOSURE_CODES,
        headers=headers,
        message_count=2,
        segment_count=3,
    )
    return {
        "channel": channel,
        "partner": partner,
        "agreement": agreement,
        "headers": headers,
        "offer_a": offer_a,
        "order_a": order_a,
        "offer_b": offer_b,
        "order_b": order_b,
    }


def test_cost_per_booking_variants_diverge_on_the_same_paid_orders(api):
    """PRD §3.9: "Its result, stored in `cost_per_booking_flat_cents`, is 0 when the
    paid-booking count is 0, and otherwise the channel's `monthly_platform_fee_cents`
    divided by the paid-booking count, rounded half up to whole cents."
    PRD §3.9: "First the channel's `activity_cost_cents` is assembled: for every order
    on the channel whose `payment_status` is `PAID`, the service adds the channel's
    `per_message_cost_cents` multiplied by that order's `message_count` plus the
    channel's `per_segment_fee_cents` multiplied by that order's `segment_count`; to
    that transaction total it adds the sum of `incentive_accrued_cents` over every
    agency agreement on this channel whose `status` is `SIGNED`."

    Design: Difficulty/dual_variant_calc/channel_cost_variants_diverge_on_identical_paid_order_population
    """
    world = _paid_and_authorized_orders(api)

    order_b = validate_success(
        api.post_order_payment(
            world["order_b"]["id"],
            {"action": "CAPTURE", "payment_amount_cents": 57037},
            headers=world["headers"],
        )
    )
    assert order_b["payment_status"] == "PAID"

    order_a = fx.read_order(api, world["order_a"]["id"], headers=world["headers"])
    assert order_a["net_revenue_cents"] == 59560
    assert order_b["net_revenue_cents"] == 57037

    agreement = fx.read_agreement(api, world["agreement"]["id"])
    assert agreement["cumulative_net_revenue_cents"] == 116597
    assert agreement["incentive_accrued_cents"] == 1457

    channel = fx.read_channel(api, world["channel"]["id"])
    assert channel["booking_count"] == 2
    # 400000 spread over two bookings.
    assert channel["cost_per_booking_flat_cents"] == 200000
    # (12*4 + 40*2) + (12*2 + 40*3) + 1457 signed-agreement accrual.
    assert channel["activity_cost_cents"] == 1729
    assert channel["cost_per_booking_activity_cents"] == 865
    assert (
        channel["cost_per_booking_flat_cents"] - channel["cost_per_booking_activity_cents"]
        == 199135
    )


def test_each_cost_variant_ignores_the_other_variant_inputs(api):
    """PRD §3.9: "This variant ignores `message_count`, `segment_count` and incentive
    accrual entirely, which is why a channel with a single booking carries the whole
    monthly fee on that one booking."
    PRD §3.9: "This variant ignores `monthly_platform_fee_cents` entirely and charges
    instead per message, per segment, and for the incentive the airline has committed
    to on that channel — so the same set of bookings routinely produces a different
    per-booking figure under `ACTIVITY_BASED` than under `CHANNEL_AVERAGE`."

    Design: Difficulty/dual_variant_calc/channel_cost_variants_diverge_on_identical_paid_order_population
    """
    world = _paid_and_authorized_orders(api)

    # One PAID order so far: the accounting view charges the whole monthly fee to it,
    # while the traced view charges 12*4 + 40*2 plus the signed agreement's accrual.
    channel = fx.read_channel(api, world["channel"]["id"])
    assert channel["booking_count"] == 1
    assert channel["cost_per_booking_flat_cents"] == 400000
    assert channel["activity_cost_cents"] == 873
    assert channel["cost_per_booking_activity_cents"] == 873

    fx.capture_payment(api, world["order_b"]["id"], 57037, headers=world["headers"])

    channel = fx.read_channel(api, world["channel"]["id"])
    assert channel["booking_count"] == 2
    # The monthly fee did not change, only the divisor.
    assert channel["cost_per_booking_flat_cents"] == 200000
    # The traced view grew by the second order's messages and segments and by the
    # re-accrued incentive.
    assert channel["activity_cost_cents"] == 1729
    assert channel["cost_per_booking_activity_cents"] == 865


def test_distribution_cost_ledger_is_readable_by_a_compliance_auditor(api):
    """PRD §3.9: "Reading a channel returns both figures together with the underlying
    `activity_cost_cents` and `booking_count`, which is the report a `ComplianceAuditor`
    or a `DistributionManager` uses to compare a legacy distribution link against a
    direct or aggregator connection."

    Design: Difficulty/dual_variant_calc/channel_cost_variants_diverge_on_identical_paid_order_population
    """
    world = _paid_and_authorized_orders(api)
    fx.capture_payment(api, world["order_b"]["id"], 57037, headers=world["headers"])

    channel = validate_success(
        api.get_channel(world["channel"]["id"], headers=AUDITOR_HEADERS)
    )
    assert channel["booking_count"] == 2
    assert channel["activity_cost_cents"] == 1729
    assert channel["cost_per_booking_flat_cents"] == 200000
    assert channel["cost_per_booking_activity_cents"] == 865

    manager_view = validate_success(
        api.get_channel(world["channel"]["id"], headers=DISTRIBUTION_MANAGER_HEADERS)
    )
    assert manager_view["cost_per_booking_flat_cents"] == 200000
    assert manager_view["cost_per_booking_activity_cents"] == 865
