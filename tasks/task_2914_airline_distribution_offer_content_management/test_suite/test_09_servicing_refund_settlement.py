"""Servicing: the pinned refund settlement, its four-hop apply cascade and parity."""

from test_helpers import (
    DISTRIBUTION_MANAGER_HEADERS,
    FULFILLMENT_CANCELLED,
    PAYMENT_PAID,
    PAYMENT_REFUNDED,
    FULFILLMENT_TICKETED,
    REQUEST_TYPE_CHANGE,
    REQUEST_TYPE_REFUND,
    SR_APPLIED,
    SR_APPROVED,
    SR_SUBMITTED,
    TIER_1,
    TIER_2,
    agency_headers,
    assert_settlement,
    fixtures as fx,
    validate_error,
)
from test_helpers import ApiErrorId

FARE_BASIS = "YSRV01"


def _paid_ndc_order(api):
    """The a la carte offer priced at 59,560 with both surcharge rules in play."""
    channel = fx.create_ndc_channel(api)
    partner = fx.create_alpha_agency(api)
    fx.create_ndc_catalogue(api)
    filing = fx.create_ndc_filing(api)
    agreement = fx.create_signed_agreement(
        api,
        partner["id"],
        channel["id"],
        partner["version"],
        proposed_incentive_pct=0.025,
        incentive_cap_cents=1000000,
    )
    headers = agency_headers(partner["id"])
    offer = fx.construct_offer(
        api,
        channel["id"],
        partner["id"],
        filing["id"],
        headers=headers,
        ancillary_codes=[fx.ANCILLARY_BAG, fx.ANCILLARY_SEAT, fx.ANCILLARY_WIFI],
    )
    fx.publish_offer(api, offer["id"], fx.NDC_DISCLOSURE_CODES, headers=headers)
    order = fx.create_order(
        api, offer["id"], fx.NDC_DISCLOSURE_CODES, headers=headers, message_count=4, segment_count=2
    )
    fx.capture_payment(api, order["id"], 59560, headers=headers)
    return channel, partner, agreement, order, headers


def test_approval_quantifies_the_refund_in_the_pinned_step_order(api):
    """PRD §3.7: "`refundable_base_cents` is the sum of `net_amount_cents` over the
    priced lines of the order's offer whose `refundable` flag is true."
    PRD §3.7: "When the base is at or above 50,000 cents and strictly below 200,000
    cents, the fee is a flat 7,500 cents."
    PRD §3.7: "`incentive_clawback_cents` is the refund total multiplied by the rate of
    the tier the agreement carries *at this moment*, before the refund cascade has moved
    anything: 0.010 when the agreement's `incentive_tier` is `TIER_1`, 0.025 when it is
    `TIER_2`, and 0.040 when it is `TIER_3`, with the product rounded half up to whole
    cents."
    PRD §3.7: "When the request's `request_type` is `REFUND`, approval runs the
    settlement calculation below and writes all four figures onto the request while
    leaving the order completely untouched — the money has been computed, not moved."

    Design: Difficulty/combinatorial_formula/refund_settlement_pinned_step_order_fee_then_total_then_clawback
    """
    channel, _partner, agreement, order, headers = _paid_ndc_order(api)

    ledger = fx.read_agreement(api, agreement["id"])
    assert ledger["incentive_tier"] == TIER_1
    # 59,560 * 0.010 = 595.60, scaled by the channel's 1.25 multiplier -> 744.5 -> 745.
    assert ledger["incentive_accrued_cents"] == 745

    request = fx.open_service_request(
        api, order["id"], REQUEST_TYPE_REFUND, headers=headers
    )
    assert request["status"] == SR_SUBMITTED
    assert request["order_id"] == order["id"]
    assert_settlement(request, 0, 0, 0, 0)

    approved = fx.approve_service_request(api, request["id"])
    assert approved["status"] == SR_APPROVED
    # Refundable lines only: the fare 46,585 plus the refundable bag 7,255. The seat,
    # the wifi and both surcharge lines are non-refundable.
    assert_settlement(
        approved,
        refundable_base_cents=53840,
        cancellation_fee_cents=7500,
        refund_total_cents=46340,
        incentive_clawback_cents=463,
    )

    # Nothing has moved: the money was computed, not paid back.
    untouched = fx.read_order(api, order["id"], headers=headers)
    assert untouched["payment_status"] == PAYMENT_PAID
    assert untouched["refunded_amount_cents"] == 0
    assert untouched["version"] == order["version"] + 1  # only the capture bumped it
    assert fx.read_channel(api, channel["id"])["booking_count"] == 1
    assert fx.read_agreement(api, agreement["id"])["incentive_accrued_cents"] == 745


def test_a_base_smaller_than_its_own_fee_refunds_nothing(api):
    """PRD §3.7: "When the refundable base is strictly below 50,000 cents,
    `cancellation_fee_cents` is a flat 2,500 cents."
    PRD §3.7: "`refund_total_cents` is the refundable base less the cancellation fee,
    floored at zero — a base smaller than its own flat fee refunds nothing rather than
    going negative."
    PRD §3.7: "Surcharge lines always carry `refundable` false and are therefore never
    refunded; the fare line is refundable exactly when the source filing's `refundable`
    was true; and à la carte and bundled ancillary lines are refundable exactly when
    their source ancillary product's `refundable` was true."

    Design: Difficulty/combinatorial_formula/refund_settlement_pinned_step_order_fee_then_total_then_clawback
    """
    channel = fx.create_ndc_channel(api, with_surcharge_rules=False)
    partner = fx.create_alpha_agency(api)
    fx.create_ancillary(
        api,
        ancillary_code="TINY",
        name="Priority tag",
        list_amount_cents=2000,
        min_content_tier_rank=1,
        refundable=True,
    )
    filing = fx.create_ndc_filing(api, refundable=False)
    fx.create_signed_agreement(api, partner["id"], channel["id"], partner["version"])
    headers = agency_headers(partner["id"])

    offer = fx.construct_offer(
        api,
        channel["id"],
        partner["id"],
        filing["id"],
        headers=headers,
        ancillary_codes=["TINY"],
    )
    # 46,585 non-refundable fare plus a 2,070 refundable extra.
    assert offer["total_cents"] == 48655
    fx.publish_offer(api, offer["id"], fx.NDC_DISCLOSURE_CODES, headers=headers)
    order = fx.create_order(api, offer["id"], fx.NDC_DISCLOSURE_CODES, headers=headers)
    fx.capture_payment(api, order["id"], 48655, headers=headers)

    request = fx.open_service_request(
        api, order["id"], REQUEST_TYPE_REFUND, headers=headers
    )
    approved = fx.approve_service_request(api, request["id"])
    assert_settlement(
        approved,
        refundable_base_cents=2070,
        cancellation_fee_cents=2500,
        refund_total_cents=0,
        incentive_clawback_cents=0,
    )
    assert fx.read_channel(api, channel["id"])["booking_count"] == 1


def test_a_base_of_exactly_two_hundred_thousand_draws_the_proportional_fee(api):
    """PRD §3.7: "When the base is at or above 200,000 cents, the fee is the base
    multiplied by 0.05, rounded half up to whole cents."
    PRD §3.7: "The two floors are inclusive on entry, so a base of exactly 50,000 cents
    draws the middle flat fee and a base of exactly 200,000 cents draws the proportional
    fee."

    Design: Difficulty/combinatorial_formula/refund_settlement_pinned_step_order_fee_then_total_then_clawback
    """
    channel = fx.create_full_channel(
        api,
        channel_code="CH_FEE",
        content_markup_pct=0.0,
        incentive_multiplier=1.0,
        required_disclosure_codes=[],
    )
    partner = fx.create_alpha_agency(api)
    fx.create_signed_agreement(api, partner["id"], channel["id"], partner["version"])
    filing = fx.create_active_filing(
        api, fare_basis_code=FARE_BASIS, base_amount_cents=200000, refundable=True
    )
    offer = fx.construct_offer(api, channel["id"], partner["id"], filing["id"])
    assert offer["total_cents"] == 200000
    fx.publish_offer(api, offer["id"])
    order = fx.create_order(api, offer["id"])
    fx.capture_payment(api, order["id"], 200000)

    request = fx.open_service_request(api, order["id"], REQUEST_TYPE_REFUND)
    approved = fx.approve_service_request(api, request["id"])
    assert_settlement(
        approved,
        refundable_base_cents=200000,
        cancellation_fee_cents=10000,
        refund_total_cents=190000,
        incentive_clawback_cents=1900,
    )


def _paid_big_order(api):
    """One large order on the aggregator channel: total 5,176,200, agreement in TIER_2."""
    channel = fx.create_ndc_channel(api)
    partner = fx.create_alpha_agency(api)
    filing = fx.create_ndc_filing(
        api, fare_basis_code="YSRV02", base_amount_cents=5000000
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
    offer = fx.construct_offer(
        api, channel["id"], partner["id"], filing["id"], headers=headers
    )
    fx.publish_offer(api, offer["id"], fx.NDC_DISCLOSURE_CODES, headers=headers)
    order = fx.create_order(
        api, offer["id"], fx.NDC_DISCLOSURE_CODES, headers=headers
    )
    assert order["net_revenue_cents"] == 5176200
    fx.capture_payment(api, order["id"], 5176200, headers=headers)
    return channel, partner, agreement, order, headers


def test_applying_a_refund_runs_all_four_hops_in_causal_order(api):
    """PRD §3.7: "Hop one moves the order itself: `payment_status` becomes `REFUNDED`,
    `refunded_amount_cents` becomes the request's `refund_total_cents`, and
    `fulfillment_status` is forced to `CANCELLED`."
    PRD §3.7: "Hop two follows because the order has left the paid revenue base: the
    channel's `booking_count` decreases by 1 and the agreement's
    `cumulative_net_revenue_cents` decreases by the order's `net_revenue_cents`."
    PRD §3.7: "Hop three follows from that revenue decrement: the incentive accrual
    re-runs on the new balance, rewriting `incentive_accrued_cents` and `incentive_tier`,
    and if the recomputed tier ranks strictly below the tier that was stored,
    `tier_downgrade_count` increases by 1 — this is the only path on which that counter
    ever moves."

    Design: Difficulty/transitive_cascade/refund_apply_cascades_four_hops_order_channel_agreement_cost
    """
    channel, _partner, agreement, order, headers = _paid_big_order(api)

    before = fx.read_agreement(api, agreement["id"])
    assert before["cumulative_net_revenue_cents"] == 5176200
    assert before["incentive_tier"] == TIER_2
    assert before["incentive_accrued_cents"] == 68006
    assert before["tier_downgrade_count"] == 0

    request = fx.open_service_request(
        api, order["id"], REQUEST_TYPE_REFUND, headers=headers
    )
    approved = fx.approve_service_request(api, request["id"])
    # Only the fare line is refundable: 5,175,000. The clamped surcharge is not.
    assert_settlement(
        approved,
        refundable_base_cents=5175000,
        cancellation_fee_cents=258750,
        refund_total_cents=4916250,
        incentive_clawback_cents=122906,
    )

    fx.apply_service_request(api, request["id"])

    # Hop one.
    refunded = fx.read_order(api, order["id"], headers=headers)
    assert refunded["payment_status"] == PAYMENT_REFUNDED
    assert refunded["refunded_amount_cents"] == 4916250
    assert refunded["fulfillment_status"] == FULFILLMENT_CANCELLED

    # Hops two and three.
    after = fx.read_agreement(api, agreement["id"])
    assert after["cumulative_net_revenue_cents"] == 0
    assert after["incentive_accrued_cents"] == 0
    assert after["incentive_tier"] == TIER_1
    assert after["tier_downgrade_count"] == 1


def test_the_cost_recomputation_hop_sees_the_emptied_ledger(api):
    """PRD §3.7: "Hop four follows from the accrual change: the channel's
    distribution-cost figures re-run, rewriting `activity_cost_cents`,
    `cost_per_booking_flat_cents` and `cost_per_booking_activity_cents`, and because it
    runs after hop three it necessarily sees the new accrual rather than the old one."
    PRD §3.9: "Then the per-booking figure, stored in `cost_per_booking_activity_cents`,
    is 0 when the paid-booking count is 0, and otherwise `activity_cost_cents` divided by
    the paid-booking count, rounded half up to whole cents."

    Design: Difficulty/transitive_cascade/refund_apply_cascades_four_hops_order_channel_agreement_cost
    """
    channel, _partner, _agreement, order, headers = _paid_big_order(api)

    before = fx.read_channel(api, channel["id"])
    assert before["booking_count"] == 1
    # 12 * 1 + 40 * 1 of traffic plus the 68,006 accrual then standing.
    assert before["activity_cost_cents"] == 68058
    assert before["cost_per_booking_flat_cents"] == 400000

    request = fx.open_service_request(
        api, order["id"], REQUEST_TYPE_REFUND, headers=headers
    )
    fx.approve_service_request(api, request["id"])
    fx.apply_service_request(api, request["id"])

    after = fx.read_channel(api, channel["id"])
    assert after["booking_count"] == 0
    # No paid order contributes traffic and the accrual has been rewritten to 0.
    assert after["activity_cost_cents"] == 0
    assert after["cost_per_booking_flat_cents"] == 0
    assert after["cost_per_booking_activity_cents"] == 0


def _paid_order_on(api, channel):
    partner = fx.create_alpha_agency(api)
    fx.create_signed_agreement(api, partner["id"], channel["id"], partner["version"])
    filing = fx.create_active_filing(
        api, fare_basis_code="YPAR01", base_amount_cents=100000, refundable=True
    )
    offer = fx.construct_offer(api, channel["id"], partner["id"], filing["id"])
    fx.publish_offer(api, offer["id"])
    order = fx.create_order(api, offer["id"])
    fx.capture_payment(api, order["id"], 100000)
    return partner, order


def test_refund_apply_is_blocked_until_the_channel_carries_refund_parity(api):
    """PRD §3.7: "Channel parity is verified first: applying a refund requires the
    channel's `servicing_parity_refund` to be true and applying a change requires its
    `servicing_parity_change` to be true, with either shortfall reported as
    `ERR_SERVICING_NOT_SUPPORTED_ON_CHANNEL`."
    PRD §3.1: "The content-policy revision accepts any subset of `content_tier`,
    `servicing_parity_change`, `servicing_parity_refund` and `required_disclosure_codes`,
    recomputes `content_tier_rank` from the new tier, refreshes `updated_at` and
    increases the channel's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/refund_apply_requires_channel_refund_parity_state
    """
    channel = fx.create_full_channel(
        api,
        channel_code="CH_PARITY",
        content_markup_pct=0.0,
        incentive_multiplier=1.0,
        servicing_parity_change=True,
        servicing_parity_refund=False,
        required_disclosure_codes=[],
    )
    _partner, order = _paid_order_on(api, channel)

    request = fx.open_service_request(api, order["id"], REQUEST_TYPE_REFUND)
    approved = fx.approve_service_request(api, request["id"])
    assert_settlement(
        approved,
        refundable_base_cents=100000,
        cancellation_fee_cents=7500,
        refund_total_cents=92500,
        incentive_clawback_cents=925,
    )

    blocked = api.apply_service_request(
        request["id"], {}, headers=DISTRIBUTION_MANAGER_HEADERS
    )
    validate_error(blocked, ApiErrorId.SERVICING_NOT_SUPPORTED_ON_CHANNEL)

    still_approved = fx.read_service_request(api, request["id"], order["id"])
    assert still_approved["status"] == SR_APPROVED
    assert still_approved["version"] == approved["version"]
    assert fx.read_order(api, order["id"])["payment_status"] == PAYMENT_PAID

    before_revision = fx.read_channel(api, channel["id"])
    revised = fx.revise_content_policy(api, channel["id"], servicing_parity_refund=True)
    assert revised["servicing_parity_refund"] is True
    assert revised["version"] == before_revision["version"] + 1

    applied = fx.apply_service_request(api, request["id"])
    assert applied["status"] == SR_APPLIED
    refunded = fx.read_order(api, order["id"])
    assert refunded["payment_status"] == PAYMENT_REFUNDED
    assert refunded["refunded_amount_cents"] == 92500


def test_the_two_parity_flags_gate_their_own_branches_only(api):
    """PRD §3.7: "Channel parity is verified first: applying a refund requires the
    channel's `servicing_parity_refund` to be true and applying a change requires its
    `servicing_parity_change` to be true, with either shortfall reported as
    `ERR_SERVICING_NOT_SUPPORTED_ON_CHANNEL`."
    PRD §3.7: "When the `request_type` is `CHANGE` or `VOID`, approval writes nothing:
    all four settlement figures stay at 0, because neither branch has a refund amount to
    compute."

    Design: Difficulty/cross_entity_state_dependency/refund_apply_requires_channel_refund_parity_state
    """
    channel = fx.create_full_channel(
        api,
        channel_code="CH_PARITY2",
        content_markup_pct=0.0,
        incentive_multiplier=1.0,
        servicing_parity_change=False,
        servicing_parity_refund=True,
        required_disclosure_codes=[],
    )
    _partner, order = _paid_order_on(api, channel)
    ticketed = fx.ticket_order(api, order["id"])
    assert ticketed["fulfillment_status"] == FULFILLMENT_TICKETED

    change = fx.open_service_request(api, order["id"], REQUEST_TYPE_CHANGE)
    approved_change = fx.approve_service_request(api, change["id"])
    assert_settlement(approved_change, 0, 0, 0, 0)
    blocked = api.apply_service_request(
        change["id"], {}, headers=DISTRIBUTION_MANAGER_HEADERS
    )
    validate_error(blocked, ApiErrorId.SERVICING_NOT_SUPPORTED_ON_CHANNEL)
    assert fx.read_order(api, order["id"])["fulfillment_status"] == FULFILLMENT_TICKETED

    # The refund branch is gated by the other flag, which this channel does carry.
    refund = fx.open_service_request(api, order["id"], REQUEST_TYPE_REFUND)
    fx.approve_service_request(api, refund["id"])
    applied = fx.apply_service_request(api, refund["id"])
    assert applied["status"] == SR_APPLIED

    final = fx.read_order(api, order["id"])
    assert final["payment_status"] == PAYMENT_REFUNDED
    assert final["fulfillment_status"] == FULFILLMENT_CANCELLED
    # The change never applied, so it never added its extra distribution message.
    assert final["message_count"] == 1
    assert fx.read_service_request(api, change["id"], order["id"])["status"] == SR_APPROVED
