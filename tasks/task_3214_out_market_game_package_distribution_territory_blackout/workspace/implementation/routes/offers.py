"""Offers: create, list, get, withdraw."""
from flask import Blueprint, request

from db import db, parse_iso
from errors import err_invalid_request, err_already_terminal, err_invalid_state
from middleware import require_roles
from paginate import parse_pagination, paginate
from response import success
from services import new_resource, touch, get_or_404
from validate import (
    body_json, req_string, req_enum, req_int, req_bool, req_datetime,
)

bp = Blueprint("offers", __name__)


@bp.post("/offers")
@require_roles("PlatformAdmin")
def create_offer(auth):
    body = body_json()
    season_id = req_string(body, "season_id")
    get_or_404(db.seasons, season_id)
    plan_tier = req_enum(body, "plan_tier", {"BASE", "PREMIUM", "STUDENT"})
    base_price_cents = req_int(body, "base_price_cents", minimum=1)
    includes_multiview = req_bool(body, "includes_multiview")
    includes_companion = req_bool(body, "includes_companion")
    valid_from = req_datetime(body, "valid_from")
    valid_until = req_datetime(body, "valid_until")
    if parse_iso(valid_until) <= parse_iso(valid_from):
        raise err_invalid_request("valid_until must be after valid_from")

    offer = new_resource()
    offer.update({
        "season_id": season_id,
        "plan_tier": plan_tier,
        "base_price_cents": base_price_cents,
        "includes_multiview": includes_multiview,
        "includes_companion": includes_companion,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "status": "ACTIVE",
    })
    db.offers[offer["id"]] = offer
    return success(offer, status=201)


@bp.get("/offers")
@require_roles("PlatformAdmin", "LeagueOps", "SupportAgent", "Subscriber")
def list_offers(auth):
    limit, offset = parse_pagination()
    season_id = request.args.get("season_id")
    plan_tier = request.args.get("plan_tier")
    status = request.args.get("status")
    items = sorted(db.offers.values(), key=lambda r: r["created_at"])
    if season_id is not None:
        items = [o for o in items if o["season_id"] == season_id]
    if plan_tier is not None:
        items = [o for o in items if o["plan_tier"] == plan_tier]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    window, page = paginate(items, limit, offset)
    return success(window, pagination=page)


@bp.get("/offers/<oid>")
@require_roles("PlatformAdmin", "LeagueOps", "SupportAgent", "Subscriber")
def get_offer(oid, auth):
    offer = get_or_404(db.offers, oid)
    return success(offer)


@bp.post("/offers/<oid>/withdraw")
@require_roles("PlatformAdmin")
def withdraw_offer(oid, auth):
    offer = get_or_404(db.offers, oid)
    if offer["status"] == "WITHDRAWN":
        raise err_already_terminal()
    if offer["status"] != "ACTIVE":
        raise err_invalid_state()
    offer["status"] = "WITHDRAWN"
    touch(offer)
    return success(offer)
