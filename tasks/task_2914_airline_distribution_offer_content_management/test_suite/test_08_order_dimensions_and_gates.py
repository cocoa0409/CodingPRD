"""Orders: two independent status dimensions and the signed-agreement gate."""

from test_helpers import (
    AGREEMENT_PROPOSED,
    AGREEMENT_SIGNED,
    AGREEMENT_SUPERSEDED,
    DISTRIBUTION_MANAGER_HEADERS,
    FULFILLMENT_ACTION_CANCEL,
    FULFILLMENT_ACTION_FLY,
    FULFILLMENT_ACTION_TICKET,
    FULFILLMENT_CANCELLED,
    FULFILLMENT_FLOWN,
    FULFILLMENT_RESERVED,
    FULFILLMENT_TICKETED,
    PAYMENT_ACTION_CAPTURE,
    PAYMENT_AUTHORIZED,
    PAYMENT_PAID,
    ApiErrorId,
    agency_headers,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)

FARE_BASIS = "YORD01"
FARE_CENTS = 45010


def _plain_channel(api):
    return fx.create_full_channel(
        api,
        channel_code="CH_ORDER",
        content_markup_pct=0.0,
        monthly_platform_fee_cents=0,
        per_message_cost_cents=0,
        per_segment_fee_cents=0,
        required_disclosure_codes=[],
    )


def _published_offer(api, channel, partner):
    filing = fx.create_active_filing(
        api, fare_basis_code=FARE_BASIS, base_amount_cents=FARE_CENTS
    )
    offer = fx.construct_offer(api, channel["id"], partner["id"], filing["id"])
    assert offer["total_cents"] == FARE_CENTS
    return fx.publish_offer(api, offer["id"])


def _order_ready(api):
    channel = _plain_channel(api)
    partner = fx.create_alpha_agency(api)
    agreement = fx.create_signed_agreement(
        api, partner["id"], channel["id"], partner["version"]
    )
    offer = _published_offer(api, channel, partner)
    order = fx.create_order(api, offer["id"])
    return channel, partner, agreement, order


def test_ticketing_reads_payment_but_flying_leaves_it_alone(api):
    """PRD §3.6: "The two status dimensions are genuinely independent: they are advanced
    by separate operations and neither is inferred from the other."
    PRD §3.6: "Ticketing advances `RESERVED → TICKETED` and is the one fulfilment move
    that reads the other dimension: it requires `payment_status` to be `PAID`, else
    `ERR_ORDER_NOT_PAID`."
    PRD §3.6: "Flying advances `TICKETED → FLOWN`, has no precondition, and is reserved
    to a `DistributionManager` — an agency cannot declare its own passenger flown."

    Design: Difficulty/non_linear_state_machine/order_payment_and_fulfillment_dimensions_advance_independently
    """
    _channel, partner, _agreement, order = _order_ready(api)
    headers = agency_headers(partner["id"])

    assert order["payment_status"] == PAYMENT_AUTHORIZED
    assert order["fulfillment_status"] == FULFILLMENT_RESERVED

    too_early = api.post_order_fulfillment(
        order["id"],
        f.fulfillment_payload(FULFILLMENT_ACTION_TICKET),
        headers=DISTRIBUTION_MANAGER_HEADERS,
    )
    validate_error(too_early, ApiErrorId.ORDER_NOT_PAID)
    unchanged = fx.read_order(api, order["id"])
    assert unchanged["fulfillment_status"] == FULFILLMENT_RESERVED
    assert unchanged["version"] == order["version"]

    paid = fx.capture_payment(api, order["id"], FARE_CENTS)
    assert paid["payment_status"] == PAYMENT_PAID
    assert paid["paid_amount_cents"] == FARE_CENTS
    # The capture moved only the payment dimension.
    assert paid["fulfillment_status"] == FULFILLMENT_RESERVED

    ticketed = fx.advance_fulfillment(api, order["id"], FULFILLMENT_ACTION_TICKET)
    assert ticketed["fulfillment_status"] == FULFILLMENT_TICKETED
    assert ticketed["payment_status"] == PAYMENT_PAID

    # An agency may not declare the passenger flown.
    refused = api.post_order_fulfillment(
        order["id"], f.fulfillment_payload(FULFILLMENT_ACTION_FLY), headers=headers
    )
    validate_error(refused, ApiErrorId.UNAUTHORIZED)

    flown = fx.advance_fulfillment(api, order["id"], FULFILLMENT_ACTION_FLY)
    assert flown["fulfillment_status"] == FULFILLMENT_FLOWN
    assert flown["payment_status"] == PAYMENT_PAID
    assert flown["paid_amount_cents"] == FARE_CENTS
    assert flown["refunded_amount_cents"] == 0


def test_cancelling_fulfilment_does_not_block_a_later_capture(api):
    """PRD §3.6: "Cancelling advances either `RESERVED → CANCELLED` or `TICKETED →
    CANCELLED` with no precondition, and deliberately leaves `payment_status` alone: a
    cancelled-but-paid order keeps its revenue in the agreement ledger until a refund
    servicing request is actually applied."
    PRD §3.6: "A capture advances `AUTHORIZED → PAID` and requires that
    `payment_amount_cents` equal the source offer's `total_cents` — the same figure the
    order froze into `net_revenue_cents` — with any other amount rejected as
    `ERR_PAYMENT_AMOUNT_MISMATCH`."

    Design: Difficulty/non_linear_state_machine/order_payment_and_fulfillment_dimensions_advance_independently
    """
    channel, _partner, agreement, order = _order_ready(api)

    mismatch = api.post_order_payment(
        order["id"],
        f.payment_payload(PAYMENT_ACTION_CAPTURE, FARE_CENTS - 1),
        headers=DISTRIBUTION_MANAGER_HEADERS,
    )
    validate_error(mismatch, ApiErrorId.PAYMENT_AMOUNT_MISMATCH)

    cancelled = fx.advance_fulfillment(api, order["id"], FULFILLMENT_ACTION_CANCEL)
    assert cancelled["fulfillment_status"] == FULFILLMENT_CANCELLED
    assert cancelled["payment_status"] == PAYMENT_AUTHORIZED

    # The payment dimension is still live and still capturable.
    paid = validate_success(
        api.post_order_payment(
            order["id"],
            f.payment_payload(PAYMENT_ACTION_CAPTURE, FARE_CENTS),
            headers=DISTRIBUTION_MANAGER_HEADERS,
        )
    )
    assert paid["payment_status"] == PAYMENT_PAID
    assert paid["fulfillment_status"] == FULFILLMENT_CANCELLED
    # A cancelled-but-paid order still counts as a booking and still earns incentive.
    assert fx.read_channel(api, channel["id"])["booking_count"] == 1
    assert fx.read_agreement(api, agreement["id"])["cumulative_net_revenue_cents"] == FARE_CENTS

    # Fulfilment has reached one of its terminal states.
    terminal = api.post_order_fulfillment(
        order["id"],
        f.fulfillment_payload(FULFILLMENT_ACTION_FLY),
        headers=DISTRIBUTION_MANAGER_HEADERS,
    )
    validate_error(terminal, ApiErrorId.INVALID_STATE_TRANSITION)


def test_agency_order_requires_a_signed_agreement_not_merely_a_proposed_one(api):
    """PRD §3.6: "And when the ordering partner's `partner_type` is `TRAVEL_AGENCY`, an
    agreement in `SIGNED` status must exist for the offer's partner-and-channel pair;
    without one the order is refused with `ERR_AGREEMENT_NOT_SIGNED`, which is the
    mechanism by which a suspended agency stops selling."
    PRD §3.6: "On creation the service copies `channel_id` and `partner_id` from the
    source offer — a client never supplies them — and resolves `agency_agreement_id` to
    the identifier of the `SIGNED` agreement for that partner-and-channel pair, leaving
    it null when the ordering partner is not a travel agency."

    Design: Difficulty/cross_entity_state_dependency/order_creation_requires_agreement_in_signed_state
    """
    channel = _plain_channel(api)
    partner = fx.create_alpha_agency(api)
    offer = _published_offer(api, channel, partner)

    no_agreement = api.create_order(
        f.order_payload(offer["id"]), headers=DISTRIBUTION_MANAGER_HEADERS
    )
    validate_error(no_agreement, ApiErrorId.AGREEMENT_NOT_SIGNED)

    agreement = fx.open_agreement(api, partner["id"], channel["id"], partner["version"])
    assert agreement["status"] == AGREEMENT_PROPOSED
    still_refused = api.create_order(
        f.order_payload(offer["id"]), headers=DISTRIBUTION_MANAGER_HEADERS
    )
    validate_error(still_refused, ApiErrorId.AGREEMENT_NOT_SIGNED)

    signed = fx.sign_agreement(api, agreement["id"])
    assert signed["status"] == AGREEMENT_SIGNED

    order = fx.create_order(api, offer["id"])
    assert order["agency_agreement_id"] == agreement["id"]
    assert order["channel_id"] == channel["id"]
    assert order["partner_id"] == partner["id"]
    assert order["net_revenue_cents"] == FARE_CENTS


def test_superseding_the_signed_agreement_stops_the_agency_selling(api):
    """PRD §3.3: "Every existing agreement for the same partner-and-channel pair that
    sits in `PROPOSED`, `COUNTERED` or `SIGNED` is set to `SUPERSEDED`."
    PRD §3.6: "And when the ordering partner's `partner_type` is `TRAVEL_AGENCY`, an
    agreement in `SIGNED` status must exist for the offer's partner-and-channel pair;
    without one the order is refused with `ERR_AGREEMENT_NOT_SIGNED`, which is the
    mechanism by which a suspended agency stops selling."

    Design: Difficulty/cross_entity_state_dependency/order_creation_requires_agreement_in_signed_state
    """
    channel = _plain_channel(api)
    partner = fx.create_alpha_agency(api)
    signed = fx.create_signed_agreement(
        api, partner["id"], channel["id"], partner["version"]
    )
    first_offer = _published_offer(api, channel, partner)
    first_order = fx.create_order(api, first_offer["id"])
    assert first_order["agency_agreement_id"] == signed["id"]

    # Opening a fresh agreement supersedes the signed one, leaving nothing SIGNED.
    reread_partner = fx.read_partner(api, partner["id"])
    fx.open_agreement(api, partner["id"], channel["id"], reread_partner["version"])
    assert fx.read_agreement(api, signed["id"])["status"] == AGREEMENT_SUPERSEDED

    second_filing = fx.create_active_filing(
        api, fare_basis_code="YORD02", base_amount_cents=FARE_CENTS
    )
    second_offer = fx.construct_offer(
        api, channel["id"], partner["id"], second_filing["id"]
    )
    fx.publish_offer(api, second_offer["id"])
    refused = api.create_order(
        f.order_payload(second_offer["id"]), headers=DISTRIBUTION_MANAGER_HEADERS
    )
    validate_error(refused, ApiErrorId.AGREEMENT_NOT_SIGNED)


def test_a_non_agency_partner_orders_without_any_agreement(api):
    """PRD §3.6: "On creation the service copies `channel_id` and `partner_id` from the
    source offer — a client never supplies them — and resolves `agency_agreement_id` to
    the identifier of the `SIGNED` agreement for that partner-and-channel pair, leaving
    it null when the ordering partner is not a travel agency."

    Design: Difficulty/cross_entity_state_dependency/order_creation_requires_agreement_in_signed_state
    """
    channel = _plain_channel(api)
    partner = fx.create_tech_partner(api, iata_code="TP000001")
    offer = _published_offer(api, channel, partner)

    order = fx.create_order(api, offer["id"])
    assert order["agency_agreement_id"] is None
    assert order["partner_id"] == partner["id"]
    assert order["net_revenue_cents"] == FARE_CENTS
