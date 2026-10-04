"""Offer endpoints (PRD 3.4)."""
from db import db
from errors import not_found, invalid_request
from middleware import (
    require_auth,
    body_json,
    get_str,
    get_int,
    get_enum,
    get_bool,
    pagination_params,
    sort_by_created,
)
from response import success_object, success_array
from serializers import offer as ser_offer
from services import make_record, touch, get_location, get_offer_nested
from . import offers_bp

OFFER_KINDS = ["HAPPY_HOUR", "APP_ONLY", "PROMO"]
DISCOUNT_TYPES = ["HALF_PRICE_DRINKS", "PERCENT_OFF_ORDER", "FIXED_OFF_CENTS"]
OFFER_READ_ROLES = ["ShiftManager", "PlatformAdmin", "Customer"]


def _validate_window(value, name):
    if not isinstance(value, str):
        invalid_request("{} must be an HH:MM string".format(name))
    parts = value.split(":")
    if len(parts) != 2:
        invalid_request("{} must be an HH:MM string".format(name))
    try:
        h = int(parts[0])
        m = int(parts[1])
    except ValueError:
        invalid_request("{} must be an HH:MM string".format(name))
    if not (0 <= h <= 23 and 0 <= m <= 59):
        invalid_request("{} must be within 00:00-23:59".format(name))
    return value


@offers_bp.route("/locations/<locationId>/offers", methods=["POST"])
def create_offer(locationId):
    require_auth(["ShiftManager", "PlatformAdmin"])
    loc = get_location(locationId)
    body = body_json()
    code = get_str(body, "code", required=True)
    kind = get_enum(body, "kind", OFFER_KINDS, required=True)
    discount_type = get_enum(body, "discount_type", DISCOUNT_TYPES, required=True)
    discount_value = get_int(body, "discount_value", required=True, minimum=0)
    if discount_type == "PERCENT_OFF_ORDER" and not (1 <= discount_value <= 90):
        invalid_request("discount_value for PERCENT_OFF_ORDER must be between 1 and 90")
    window_start = _validate_window(body.get("window_start_local"), "window_start_local")
    if window_start is None:
        invalid_request("window_start_local is required")
    window_end = _validate_window(body.get("window_end_local"), "window_end_local")
    if window_end is None:
        invalid_request("window_end_local is required")
    app_only = get_bool(body, "app_only", default=False)
    rec = make_record()
    rec.update(
        {
            "location_id": loc["id"],
            "code": code,
            "kind": kind,
            "discount_type": discount_type,
            "discount_value": discount_value,
            "window_start_local": window_start,
            "window_end_local": window_end,
            "app_only": app_only,
            "status": "ACTIVE",
        }
    )
    db.offers[rec["id"]] = rec
    return success_object(ser_offer(rec), 201)


@offers_bp.route("/locations/<locationId>/offers", methods=["GET"])
def list_offers(locationId):
    require_auth(OFFER_READ_ROLES)
    from flask import request

    get_location(locationId)
    status = request.args.get("status")
    kind = request.args.get("kind")
    if status is not None and status not in ("ACTIVE", "DISABLED"):
        invalid_request("status must be ACTIVE or DISABLED")
    if kind is not None and kind not in OFFER_KINDS:
        invalid_request("kind must be a valid offer kind")
    offers = [o for o in db.offers.values() if o["location_id"] == locationId]
    if status is not None:
        offers = [o for o in offers if o["status"] == status]
    if kind is not None:
        offers = [o for o in offers if o["kind"] == kind]
    offers = sort_by_created(offers)
    limit, offset = pagination_params()
    total = len(offers)
    page = offers[offset : offset + limit]
    return success_array([ser_offer(o) for o in page], limit, offset, total)


@offers_bp.route("/locations/<locationId>/offers/<offerId>", methods=["GET"])
def get_offer(locationId, offerId):
    require_auth(OFFER_READ_ROLES)
    loc, offer = get_offer_nested(locationId, offerId)
    return success_object(ser_offer(offer))


@offers_bp.route("/locations/<locationId>/offers/<offerId>/disable", methods=["POST"])
def disable_offer(locationId, offerId):
    require_auth(["ShiftManager", "PlatformAdmin"])
    loc, offer = get_offer_nested(locationId, offerId)
    offer["status"] = "DISABLED"
    touch(offer)
    return success_object(ser_offer(offer))
