"""Instant savings offer endpoints."""

from flask import Blueprint, request

from db import STORE, new_entity
from errors import (
    ApiError,
    ERR_CATALOG_ITEM_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_OFFER_WINDOW_CONFLICT,
    ERR_OFFER_WINDOW_INVALID,
)
from logic import get_club, get_offer, is_int, parse_iso, serialize, sort_items
from middleware import get_context, get_body, require_role, require_fields, get_pagination, paginate
from response import success

bp = Blueprint("offers", __name__)


@bp.post("/clubs/<club_id>/instant-savings-offers")
def create_offer(club_id):
    _, role = get_context()
    require_role(role, ["ClubManager"])
    club = get_club(club_id)
    body = get_body()
    require_fields(body, ["catalog_item_id", "discount_cents", "valid_from_iso",
                          "valid_to_iso", "per_member_limit"])

    item = STORE.catalog_items.get(body["catalog_item_id"])
    if not item or item["club_id"] != club["id"]:
        raise ApiError(ERR_CATALOG_ITEM_NOT_FOUND,
                       "Catalog item id does not exist in this club.", 404)
    if not is_int(body["discount_cents"]) or body["discount_cents"] < 0:
        raise ApiError(ERR_INVALID_REQUEST, "discount_cents must be an integer >= 0.", 400)
    if not is_int(body["per_member_limit"]) or body["per_member_limit"] < 1:
        raise ApiError(ERR_INVALID_REQUEST, "per_member_limit must be an integer >= 1.", 400)
    tier_eligibility = body.get("tier_eligibility", "ALL")
    if tier_eligibility not in ("ALL", "PLUS_ONLY"):
        raise ApiError(ERR_INVALID_REQUEST, "tier_eligibility must be ALL or PLUS_ONLY.", 400)

    valid_from = parse_iso(body["valid_from_iso"], "valid_from_iso")
    valid_to = parse_iso(body["valid_to_iso"], "valid_to_iso")
    if valid_to < valid_from:
        raise ApiError(ERR_OFFER_WINDOW_INVALID,
                       "Offer valid_to_iso is earlier than valid_from_iso.", 400)

    # Closed-interval overlap per (club, item), touching endpoints conflict.
    for o in STORE.offers.values():
        if o["club_id"] != club["id"] or o["catalog_item_id"] != item["id"]:
            continue
        ex_from = parse_iso(o["valid_from_iso"])
        ex_to = parse_iso(o["valid_to_iso"])
        if valid_from <= ex_to and ex_from <= valid_to:
            raise ApiError(ERR_OFFER_WINDOW_CONFLICT,
                           "Offer window overlaps an existing offer for this club and item.", 409)

    offer = new_entity()
    offer.update({
        "club_id": club["id"],
        "catalog_item_id": item["id"],
        "discount_cents": body["discount_cents"],
        "valid_from_iso": body["valid_from_iso"],
        "valid_to_iso": body["valid_to_iso"],
        "tier_eligibility": tier_eligibility,
        "per_member_limit": body["per_member_limit"],
    })
    STORE.offers[offer["id"]] = offer
    return success(serialize(offer), status=201)


@bp.get("/instant-savings-offers/<offer_id>")
def get_offer_route(offer_id):
    get_context()
    return success(serialize(get_offer(offer_id)))


@bp.get("/instant-savings-offers")
def list_offers():
    get_context()
    limit, offset = get_pagination(request.args)
    offers = list(STORE.offers.values())
    for f in ("club_id", "catalog_item_id"):
        v = request.args.get(f)
        if v is not None:
            offers = [o for o in offers if o[f] == v]
    offers = sort_items(offers)
    page, page_meta = paginate(offers, limit, offset)
    return success([serialize(o) for o in page], response_type="array", pagination=page_meta)
