"""Orders, their two independent status dimensions and servicing (PRD 3.6, 3.7)."""
from flask import Blueprint

import calc
import validators as v
from auth import (ALL_ROLES, ROLE_AGENCY, ROLE_COMPLIANCE_AUDITOR,
                  ROLE_DISTRIBUTION_MANAGER, ROLE_PLATFORM_ADMIN, authenticate)
from envelope import paginate, pagination, respond_list, respond_object
from errors import ApiError
from routing import precheck_ref, resolve_owned
from serializers import order_out, service_request_out
from services import (lazy_expire_offer, offer_items_for, recompute_agreement_accrual,
                      recompute_booking_count, recompute_channel_costs,
                      signed_agreement_for)
from store import bump, common_fields, db, sort_key

bp = Blueprint("orders", __name__)

PAYMENT_STATES = ("AUTHORIZED", "PAID", "VOIDED", "REFUNDED")
FULFILLMENT_STATES = ("RESERVED", "TICKETED", "FLOWN", "CANCELLED", "CHANGED")
PAYMENT_ACTIONS = ("CAPTURE", "VOID")
FULFILLMENT_ACTIONS = ("TICKET", "FLY", "CANCEL")
REQUEST_TYPES = ("CHANGE", "REFUND", "VOID")
REQUEST_STATES = ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED", "APPLIED")
REVIEW_ACTIONS = ("START_REVIEW", "APPROVE", "REJECT")


@bp.post("/orders")
def create_order():
    actor = authenticate([ROLE_AGENCY, ROLE_DISTRIBUTION_MANAGER])
    body = v.json_body()
    precheck_ref(actor, body, "offer_id", db.offers)
    offer_id = v.req_string(body, "offer_id", 1, None)
    ack_codes = v.opt_str_array(body, "disclosure_ack_codes", [])
    corporate_tracking_ref = v.opt_string(body, "corporate_tracking_ref", 1, 120)
    message_count = v.opt_int(body, "message_count", 1, None, 1)
    segment_count = v.opt_int(body, "segment_count", 1, None, 1)

    offer = db.offers.get(offer_id)
    if offer is None:
        raise ApiError("ERR_OFFER_NOT_FOUND", "offer_id does not resolve.")

    # Step 7: lazy expiry, then refuse.
    lazy_expire_offer(offer)
    if offer["status"] == "EXPIRED":
        raise ApiError("ERR_OFFER_EXPIRED", "The offer has reached expires_at.")
    # Step 9.
    if offer["status"] != "PUBLISHED":
        raise ApiError("ERR_OFFER_NOT_PUBLISHED", "The offer is not PUBLISHED.")

    channel = db.channels[offer["channel_id"]]
    partner = db.partners[offer["partner_id"]]
    agreement = None
    if partner["partner_type"] == "TRAVEL_AGENCY":
        agreement = signed_agreement_for(partner["id"], channel["id"])
        if agreement is None:
            raise ApiError("ERR_AGREEMENT_NOT_SIGNED",
                           "No SIGNED agreement exists for this partner and channel.")

    # Step 15: acknowledgement never carries forward from publish time.
    missing = calc.missing_disclosure_codes(channel["required_disclosure_codes"],
                                           ack_codes)
    if missing:
        raise ApiError("ERR_DISCLOSURE_INCOMPLETE",
                       "Unacknowledged disclosure codes: %s" % ", ".join(missing))

    contract = None
    if offer["corporate_contract_id"] is not None:
        contract = db.contracts.get(offer["corporate_contract_id"])
    if contract is not None and contract["traceability_required"]:
        if corporate_tracking_ref is None:
            raise ApiError("ERR_CORPORATE_TRACKING_REF_MISSING",
                           "The contract requires a corporate_tracking_ref.")
        if not corporate_tracking_ref.startswith(contract["tracking_ref_prefix"]):
            raise ApiError("ERR_CORPORATE_TRACKING_REF_INVALID",
                           "corporate_tracking_ref carries the wrong prefix.")

    order = common_fields()
    order.update({
        "offer_id": offer["id"],
        "channel_id": channel["id"],
        "partner_id": partner["id"],
        "agency_agreement_id": agreement["id"] if agreement is not None else None,
        "corporate_tracking_ref": corporate_tracking_ref,
        "disclosure_ack_codes": list(ack_codes),
        "message_count": message_count,
        "segment_count": segment_count,
        "paid_amount_cents": 0,
        "refunded_amount_cents": 0,
        "net_revenue_cents": offer["total_cents"],
        "payment_status": "AUTHORIZED",
        "fulfillment_status": "RESERVED",
    })
    db.orders[order["id"]] = order

    offer["status"] = "ORDERED"
    bump(offer)
    return respond_object(order_out(order), 201)


@bp.get("/orders/<order_id>")
def read_order(order_id):
    actor = authenticate(ALL_ROLES)
    pending, order = resolve_owned(db.orders, order_id, "ERR_ORDER_NOT_FOUND", actor)
    pending.raise_if_missing()
    return respond_object(order_out(order))


@bp.get("/orders")
def list_orders():
    authenticate([ROLE_PLATFORM_ADMIN, ROLE_DISTRIBUTION_MANAGER,
                  ROLE_COMPLIANCE_AUDITOR, ROLE_AGENCY])
    limit, offset = pagination()
    channel_id = v.query_string("channel_id")
    partner_id = v.query_string("partner_id")
    offer_id = v.query_string("offer_id")
    agency_agreement_id = v.query_string("agency_agreement_id")
    payment_status = v.query_enum("payment_status", PAYMENT_STATES)
    fulfillment_status = v.query_enum("fulfillment_status", FULFILLMENT_STATES)

    rows = []
    for order in db.orders.values():
        if channel_id is not None and order["channel_id"] != channel_id:
            continue
        if partner_id is not None and order["partner_id"] != partner_id:
            continue
        if offer_id is not None and order["offer_id"] != offer_id:
            continue
        if (agency_agreement_id is not None
                and order["agency_agreement_id"] != agency_agreement_id):
            continue
        if payment_status is not None and order["payment_status"] != payment_status:
            continue
        if (fulfillment_status is not None
                and order["fulfillment_status"] != fulfillment_status):
            continue
        rows.append(order)
    rows.sort(key=sort_key)
    page, total = paginate(rows, limit, offset)
    return respond_list([order_out(o) for o in page], limit, offset, total)


@bp.post("/orders/<order_id>/payment")
def advance_payment(order_id):
    actor = authenticate([ROLE_AGENCY, ROLE_DISTRIBUTION_MANAGER])
    pending, order = resolve_owned(db.orders, order_id, "ERR_ORDER_NOT_FOUND", actor)
    body = v.json_body()
    action = v.req_enum(body, "action", PAYMENT_ACTIONS)
    if action == "CAPTURE":
        payment_amount_cents = v.req_int(body, "payment_amount_cents", 0, None)
    else:
        payment_amount_cents = v.opt_int(body, "payment_amount_cents", 0, None)
    pending.raise_if_missing()

    if order["payment_status"] != "AUTHORIZED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "%s is not legal from payment_status %s."
                       % (action, order["payment_status"]))

    channel = db.channels[order["channel_id"]]
    if action == "CAPTURE":
        # Step 32: the capture must match the offer total the order froze.
        if payment_amount_cents != order["net_revenue_cents"]:
            raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH",
                           "payment_amount_cents does not match the offer total.")
        order["payment_status"] = "PAID"
        order["paid_amount_cents"] = payment_amount_cents
        bump(order)
        # Pinned cascade order: booking count, then accrual, then channel costs.
        recompute_booking_count(channel)
        if order["agency_agreement_id"] is not None:
            agreement = db.agreements[order["agency_agreement_id"]]
            agreement["cumulative_net_revenue_cents"] = (
                agreement["cumulative_net_revenue_cents"] + order["net_revenue_cents"])
            recompute_agreement_accrual(agreement, count_downgrade=False)
        recompute_channel_costs(channel)
    else:
        order["payment_status"] = "VOIDED"
        order["fulfillment_status"] = "CANCELLED"
        bump(order)
    return respond_object(order_out(order))


@bp.post("/orders/<order_id>/fulfillment")
def advance_fulfillment(order_id):
    actor = authenticate([ROLE_AGENCY, ROLE_DISTRIBUTION_MANAGER])
    pending, order = resolve_owned(db.orders, order_id, "ERR_ORDER_NOT_FOUND", actor)
    body = v.json_body()
    action = v.req_enum(body, "action", FULFILLMENT_ACTIONS)
    pending.raise_if_missing()

    # An agency cannot declare its own passenger flown.
    if action == "FLY" and actor.role != ROLE_DISTRIBUTION_MANAGER:
        raise ApiError("ERR_UNAUTHORIZED", "Only a DistributionManager may fly an order.")

    current = order["fulfillment_status"]
    legal = {
        "TICKET": ("RESERVED",),
        "FLY": ("TICKETED",),
        "CANCEL": ("RESERVED", "TICKETED"),
    }[action]
    if current not in legal:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "%s is not legal from fulfillment_status %s." % (action, current))

    if action == "TICKET":
        if order["payment_status"] != "PAID":
            raise ApiError("ERR_ORDER_NOT_PAID", "Ticketing requires a PAID order.")
        order["fulfillment_status"] = "TICKETED"
    elif action == "FLY":
        order["fulfillment_status"] = "FLOWN"
    else:
        order["fulfillment_status"] = "CANCELLED"
    bump(order)
    return respond_object(order_out(order))


@bp.post("/orders/<order_id>/service-requests")
def open_service_request(order_id):
    actor = authenticate([ROLE_AGENCY, ROLE_DISTRIBUTION_MANAGER])
    pending, order = resolve_owned(db.orders, order_id, "ERR_ORDER_NOT_FOUND", actor)
    body = v.json_body()
    request_type = v.req_enum(body, "request_type", REQUEST_TYPES)
    requested_change_note = v.opt_string(body, "requested_change_note", 0, 240)
    pending.raise_if_missing()

    if request_type == "CHANGE" and order["fulfillment_status"] != "TICKETED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "A change may only be opened against a TICKETED order.")
    if request_type == "REFUND" and order["payment_status"] != "PAID":
        raise ApiError("ERR_ORDER_NOT_PAID", "A refund requires a PAID order.")
    if request_type == "VOID" and order["payment_status"] != "AUTHORIZED":
        raise ApiError("ERR_ORDER_NOT_PAID", "A void requires an AUTHORIZED order.")

    sr = common_fields()
    sr.update({
        "order_id": order["id"],
        "request_type": request_type,
        "requested_change_note": requested_change_note,
        "refundable_base_cents": 0,
        "cancellation_fee_cents": 0,
        "refund_total_cents": 0,
        "incentive_clawback_cents": 0,
        "submitted_by_user_id": actor.user_id,
        "reviewed_by_user_id": None,
        "status": "SUBMITTED",
    })
    db.service_requests[sr["id"]] = sr
    return respond_object(service_request_out(sr), 201)


@bp.get("/orders/<order_id>/service-requests")
def list_service_requests(order_id):
    actor = authenticate([ROLE_PLATFORM_ADMIN, ROLE_DISTRIBUTION_MANAGER,
                          ROLE_COMPLIANCE_AUDITOR, ROLE_AGENCY])
    limit, offset = pagination()
    status = v.query_enum("status", REQUEST_STATES)
    request_type = v.query_enum("request_type", REQUEST_TYPES)
    pending, order = resolve_owned(db.orders, order_id, "ERR_ORDER_NOT_FOUND", actor)
    pending.raise_if_missing()

    rows = []
    for sr in db.service_requests.values():
        if sr["order_id"] != order["id"]:
            continue
        if status is not None and sr["status"] != status:
            continue
        if request_type is not None and sr["request_type"] != request_type:
            continue
        rows.append(sr)
    rows.sort(key=sort_key)
    page, total = paginate(rows, limit, offset)
    return respond_list([service_request_out(s) for s in page], limit, offset, total)
