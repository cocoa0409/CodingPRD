"""Servicing request review and application (PRD 3.7)."""
from flask import Blueprint

import calc
import validators as v
from auth import ROLE_DISTRIBUTION_MANAGER, authenticate
from envelope import respond_object
from errors import ApiError
from serializers import service_request_out
from services import (offer_items_for, recompute_agreement_accrual,
                      recompute_booking_count, recompute_channel_costs)
from store import bump, db, get_or_404

bp = Blueprint("servicing", __name__)

REVIEW_ACTIONS = ("START_REVIEW", "APPROVE", "REJECT")


def _refundable_base(order):
    total = 0
    for item in offer_items_for(order["offer_id"]):
        if item["refundable"]:
            total += item["net_amount_cents"]
    return total


def _quantify_refund(sr, order):
    """PRD 3.7 steps 1-4, in the pinned evaluation order."""
    base = _refundable_base(order)
    tier = None
    if order["agency_agreement_id"] is not None:
        agreement = db.agreements.get(order["agency_agreement_id"])
        if agreement is not None:
            tier = agreement["incentive_tier"]
    base, fee, total, clawback = calc.refund_settlement(base, tier)
    sr["refundable_base_cents"] = base
    sr["cancellation_fee_cents"] = fee
    sr["refund_total_cents"] = total
    sr["incentive_clawback_cents"] = clawback


@bp.post("/service-requests/<request_id>/review")
def review_service_request(request_id):
    actor = authenticate([ROLE_DISTRIBUTION_MANAGER])
    body = v.json_body()
    action = v.req_enum(body, "action", REVIEW_ACTIONS)
    v.opt_string(body, "reason", 0, 2000)
    sr = get_or_404(db.service_requests, request_id, "ERR_SERVICE_REQUEST_NOT_FOUND")

    legal = {
        "START_REVIEW": ("SUBMITTED",),
        "APPROVE": ("UNDER_REVIEW",),
        "REJECT": ("UNDER_REVIEW",),
    }[action]
    if sr["status"] not in legal:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "%s is not legal from %s." % (action, sr["status"]))

    order = db.orders[sr["order_id"]]
    if action == "START_REVIEW":
        sr["status"] = "UNDER_REVIEW"
        sr["reviewed_by_user_id"] = actor.user_id
    elif action == "REJECT":
        # A rejection changes nothing on the order whatsoever.
        sr["status"] = "REJECTED"
    else:
        sr["status"] = "APPROVED"
        if sr["request_type"] == "REFUND":
            # The refund is quantified here, not executed.
            _quantify_refund(sr, order)
    bump(sr)
    return respond_object(service_request_out(sr))


@bp.post("/service-requests/<request_id>/apply")
def apply_service_request(request_id):
    authenticate([ROLE_DISTRIBUTION_MANAGER])
    body = v.json_body()
    v.opt_string(body, "reason", 0, 2000)
    sr = get_or_404(db.service_requests, request_id, "ERR_SERVICE_REQUEST_NOT_FOUND")

    if sr["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only an APPROVED request may be applied.")

    order = db.orders[sr["order_id"]]
    channel = db.channels[order["channel_id"]]
    request_type = sr["request_type"]

    # Step 11: a refund needs the order to be PAID still.
    if request_type == "REFUND" and order["payment_status"] != "PAID":
        raise ApiError("ERR_ORDER_NOT_PAID",
                       "The order is no longer PAID.")
    # Step 16: servicing capability parity on the channel.
    if request_type == "REFUND" and not channel["servicing_parity_refund"]:
        raise ApiError("ERR_SERVICING_NOT_SUPPORTED_ON_CHANNEL",
                       "The channel cannot refund what it sold.")
    if request_type == "CHANGE" and not channel["servicing_parity_change"]:
        raise ApiError("ERR_SERVICING_NOT_SUPPORTED_ON_CHANNEL",
                       "The channel cannot change what it sold.")

    if request_type == "REFUND":
        # Hop 1: the order itself.
        order["payment_status"] = "REFUNDED"
        order["refunded_amount_cents"] = sr["refund_total_cents"]
        order["fulfillment_status"] = "CANCELLED"
        bump(order)
        # Hop 2: the order has left the paid revenue base.
        recompute_booking_count(channel)
        agreement = None
        if order["agency_agreement_id"] is not None:
            agreement = db.agreements.get(order["agency_agreement_id"])
        if agreement is not None:
            agreement["cumulative_net_revenue_cents"] = (
                agreement["cumulative_net_revenue_cents"] - order["net_revenue_cents"])
            # Hop 3: accrual re-runs; this is the only path that counts downgrades.
            recompute_agreement_accrual(agreement, count_downgrade=True)
        # Hop 4: channel costs, which must see the new accrual.
        recompute_channel_costs(channel)
    elif request_type == "CHANGE":
        order["fulfillment_status"] = "CHANGED"
        order["message_count"] = order["message_count"] + 1
        bump(order)
        recompute_channel_costs(channel)
    else:
        order["payment_status"] = "VOIDED"
        order["fulfillment_status"] = "CANCELLED"
        bump(order)

    sr["status"] = "APPLIED"
    bump(sr)
    return respond_object(service_request_out(sr))
