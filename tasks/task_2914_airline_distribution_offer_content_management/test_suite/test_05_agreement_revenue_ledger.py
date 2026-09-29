"""The revenue ledger's two movements and what an applied refund restores."""

from test_helpers import (
    FULFILLMENT_CANCELLED,
    PAYMENT_REFUNDED,
    REQUEST_TYPE_REFUND,
    SR_APPLIED,
    TIER_2,
    agency_headers,
    assert_settlement,
    fixtures as fx,
)

BIG_BASIS = "YNDC02"
BIG_BASE_CENTS = 5000000


def _two_paid_orders(api):
    """A big order and a small a la carte order, both captured on the same agreement."""
    channel = fx.create_ndc_channel(api)
    partner = fx.create_alpha_agency(api)
    fx.create_ndc_catalogue(api)
    small_filing = fx.create_ndc_filing(api)
    big_filing = fx.create_ndc_filing(
        api, fare_basis_code=BIG_BASIS, base_amount_cents=BIG_BASE_CENTS
    )
    agreement = fx.create_signed_agreement(
        api,
        partner["id"],
        channel["id"],
        partner["version"],
        proposed_incentive_pct=0.025,
        incentive_cap_cents=1000000,
    )
    headers = agency_headers(partner["id"])

    big_offer = fx.construct_offer(
        api, channel["id"], partner["id"], big_filing["id"], headers=headers
    )
    fx.publish_offer(api, big_offer["id"], fx.NDC_DISCLOSURE_CODES, headers=headers)
    big_order = fx.create_order(
        api, big_offer["id"], fx.NDC_DISCLOSURE_CODES, headers=headers
    )
    # 5,000,000 * 1.035 = 5,175,000 plus the ALL surcharge clamped to 1,200.
    assert big_order["net_revenue_cents"] == 5176200
    fx.capture_payment(api, big_order["id"], 5176200, headers=headers)

    small_offer = fx.construct_offer(
        api,
        channel["id"],
        partner["id"],
        small_filing["id"],
        headers=headers,
        ancillary_codes=[fx.ANCILLARY_BAG, fx.ANCILLARY_SEAT, fx.ANCILLARY_WIFI],
    )
    fx.publish_offer(api, small_offer["id"], fx.NDC_DISCLOSURE_CODES, headers=headers)
    small_order = fx.create_order(
        api,
        small_offer["id"],
        fx.NDC_DISCLOSURE_CODES,
        headers=headers,
        message_count=4,
        segment_count=2,
    )
    assert small_order["net_revenue_cents"] == 59560
    fx.capture_payment(api, small_order["id"], 59560, headers=headers)

    return {
        "channel": channel,
        "partner": partner,
        "agreement": agreement,
        "headers": headers,
        "big_order": big_order,
        "small_order": small_order,
    }


def test_applied_refund_returns_the_ledger_to_its_pre_capture_balance(api):
    """PRD §3.3: "The ledger moves in exactly two situations: it increases by an order's
    `net_revenue_cents` when that order's payment is captured, and it decreases by the
    same figure when a refund is applied to a previously paid order."
    PRD §3.7: "Hop two follows because the order has left the paid revenue base: the
    channel's `booking_count` decreases by 1 and the agreement's
    `cumulative_net_revenue_cents` decreases by the order's `net_revenue_cents`."

    Design: Difficulty/compensating_invariant/capture_then_refund_apply_restores_agreement_revenue_ledger
    """
    world = _two_paid_orders(api)

    after_both = fx.read_agreement(api, world["agreement"]["id"])
    assert after_both["cumulative_net_revenue_cents"] == 5235760
    # 50,000 + 235,760 * 0.025 = 55,894, scaled by the channel's 1.25 multiplier.
    assert after_both["incentive_accrued_cents"] == 69868

    request = fx.open_service_request(
        api, world["small_order"]["id"], REQUEST_TYPE_REFUND, headers=world["headers"]
    )
    fx.approve_service_request(api, request["id"])
    applied = fx.apply_service_request(api, request["id"])
    assert applied["status"] == SR_APPLIED

    restored = fx.read_agreement(api, world["agreement"]["id"])
    # Exactly the balance the big order alone had produced.
    assert restored["cumulative_net_revenue_cents"] == 5176200
    # 50,000 + 176,200 * 0.025 = 54,405, scaled by 1.25 -> 68,006.25 -> 68,006.
    assert restored["incentive_accrued_cents"] == 68006
    assert restored["incentive_tier"] == TIER_2
    assert restored["tier_downgrade_count"] == 0

    order = fx.read_order(api, world["small_order"]["id"], headers=world["headers"])
    assert order["payment_status"] == PAYMENT_REFUNDED
    assert order["fulfillment_status"] == FULFILLMENT_CANCELLED
    assert order["refunded_amount_cents"] == 46340
    # The frozen revenue figure never moves, even once the money is returned.
    assert order["net_revenue_cents"] == 59560


def test_clawback_is_recorded_but_never_subtracted_from_the_accrual(api):
    """PRD §3.7: "The clawback figure is recorded for audit and **is never subtracted
    from** the agreement's `incentive_accrued_cents`."
    PRD §3.7: "Hop four follows from the accrual change: the channel's
    distribution-cost figures re-run, rewriting `activity_cost_cents`,
    `cost_per_booking_flat_cents` and `cost_per_booking_activity_cents`, and because it
    runs after hop three it necessarily sees the new accrual rather than the old one."

    Design: Difficulty/compensating_invariant/capture_then_refund_apply_restores_agreement_revenue_ledger
    """
    world = _two_paid_orders(api)

    request = fx.open_service_request(
        api, world["small_order"]["id"], REQUEST_TYPE_REFUND, headers=world["headers"]
    )
    approved = fx.approve_service_request(api, request["id"])
    # Refundable lines: fare 46,585 and the refundable bag 7,255.
    assert_settlement(
        approved,
        refundable_base_cents=53840,
        cancellation_fee_cents=7500,
        refund_total_cents=46340,
        incentive_clawback_cents=1159,
    )

    fx.apply_service_request(api, request["id"])

    agreement = fx.read_agreement(api, world["agreement"]["id"])
    assert agreement["incentive_accrued_cents"] == 68006
    # Subtracting the clawback from the pre-refund accrual would have given 68,709.
    assert agreement["incentive_accrued_cents"] != 69868 - 1159

    channel = fx.read_channel(api, world["channel"]["id"])
    assert channel["booking_count"] == 1
    # 12 * 1 + 40 * 1 for the surviving paid order, plus the recomputed accrual.
    assert channel["activity_cost_cents"] == 68058
    assert channel["cost_per_booking_activity_cents"] == 68058
    assert channel["cost_per_booking_flat_cents"] == 400000
