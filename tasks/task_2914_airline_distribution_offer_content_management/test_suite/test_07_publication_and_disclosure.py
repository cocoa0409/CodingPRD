"""Publication and the empty-required-disclosure-set boundary."""

from test_helpers import (
    DISTRIBUTION_MANAGER_HEADERS,
    ITEM_SCOPE_ALL,
    OFFER_ORDERED,
    OFFER_PUBLISHED,
    PAYMENT_AUTHORIZED,
    assert_offer_money,
    assert_version_bumped_by,
    fixtures as fx,
    validate_success,
)


def _offer_on_a_channel_without_disclosure_codes(api):
    channel = fx.create_full_channel(
        api,
        channel_code="CH_EMPTY",
        content_markup_pct=0.08,
        required_disclosure_codes=[],
    )
    fx.add_surcharge_rule(
        api,
        channel["id"],
        surcharge_code="FLAT_FEE",
        item_scope=ITEM_SCOPE_ALL,
        rate_pct=0.03,
        threshold_cents=0,
        min_cents=0,
        max_cents=1000000,
    )
    partner = fx.create_alpha_agency(api)
    agreement = fx.create_signed_agreement(
        api, partner["id"], channel["id"], partner["version"]
    )
    filing = fx.create_active_filing(
        api, fare_basis_code="YEMPT01", base_amount_cents=20000
    )
    offer = fx.construct_offer(api, channel["id"], partner["id"], filing["id"])
    return channel, partner, agreement, offer


def test_publish_with_no_acknowledgement_field_succeeds_when_nothing_is_required(api):
    """PRD §2.11: "The empty-required-set boundary is deliberate and must be honoured:
    when a channel's `required_disclosure_codes` is empty, the missing set is empty for
    any acknowledgement whatsoever — including an entirely omitted
    `disclosure_ack_codes` — so both publish and order creation succeed, and the
    published offer records `disclosure_complete` as true with
    `acknowledged_disclosure_codes` as an empty array."
    PRD §3.5: "A newly constructed offer sits in `CONSTRUCTED` with
    `acknowledged_disclosure_codes` empty and `disclosure_complete` false."

    Design: Difficulty/boundary_precision_check/empty_required_disclosure_codes_publish_succeeds_with_omitted_ack
    """
    _channel, _partner, _agreement, offer = _offer_on_a_channel_without_disclosure_codes(api)

    assert offer["acknowledged_disclosure_codes"] == []
    assert offer["disclosure_complete"] is False
    # 20,000 * 1.08 = 21,600 exactly; the ALL rule fires from a zero threshold.
    assert_offer_money(offer, subtotal_cents=21600, surcharge_cents=648, item_count=2)

    published = validate_success(
        api.publish_offer(offer["id"], {}, headers=DISTRIBUTION_MANAGER_HEADERS)
    )
    assert published["status"] == OFFER_PUBLISHED
    assert published["acknowledged_disclosure_codes"] == []
    assert published["disclosure_complete"] is True
    assert_version_bumped_by(offer, published, 1)
    # Publication reprices nothing.
    assert published["total_cents"] == 22248


def test_order_creation_with_no_acknowledgement_field_succeeds_too(api):
    """PRD §2.11: "Each of those requests may carry `disclosure_ack_codes`, an array of
    strings; when the field is omitted the service treats it as an empty array."
    PRD §2.11: "On order creation the check is a gate only: no acknowledgement field is
    written onto the order beyond the `disclosure_ack_codes` the caller supplied, and no
    field on the offer is touched."

    Design: Difficulty/boundary_precision_check/empty_required_disclosure_codes_publish_succeeds_with_omitted_ack
    """
    _channel, _partner, _agreement, offer = _offer_on_a_channel_without_disclosure_codes(api)
    published = fx.publish_offer(api, offer["id"])
    assert published["disclosure_complete"] is True

    order = fx.create_order(api, offer["id"])
    assert order["payment_status"] == PAYMENT_AUTHORIZED
    assert order["net_revenue_cents"] == 22248
    assert order["paid_amount_cents"] == 0
    assert order["refunded_amount_cents"] == 0

    ordered_offer = fx.read_offer(api, offer["id"])
    assert ordered_offer["status"] == OFFER_ORDERED
    # The acknowledgement recorded at publish time is untouched by the order.
    assert ordered_offer["acknowledged_disclosure_codes"] == []
    assert ordered_offer["disclosure_complete"] is True
