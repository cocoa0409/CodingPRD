"""Seller listings and the one recovery operation (PRD 3.2)."""

from flask import Blueprint

import constants as C
import db
import guards
import middleware as mw
import response
import serializers as ser
import validators as v
from errors import ApiError

bp = Blueprint("listings", __name__)


@bp.post("/listings")
@mw.require(C.ROLE_SELLER)
def create_listing():
    data = v.body()
    seller = guards.body_fk(db.SELLERS, data.get("seller_id"), "ERR_SELLER_NOT_FOUND")
    if seller is not None:
        mw.ensure_owner(seller["id"])
    sku = v.req_str(data, "sku", 1, 40)
    title = v.req_str(data, "title", 1, 200)
    category_code = v.req_str(data, "category_code", 2, 32)
    restricted_flag = v.req_bool(data, "restricted_flag", default=False)
    if seller is None:
        v.req_str(data, "seller_id", 1, None)
        raise ApiError("ERR_SELLER_NOT_FOUND")
    guards.ensure_not_banned(seller)

    row = db.new_row(
        "listing",
        seller_id=seller["id"],
        sku=sku,
        title=title,
        category_code=category_code,
        restricted_flag=restricted_flag,
        state="ACTIVE",
        removal_policy_category=None,
        suppressed_by_suspension=False,
    )
    db.LISTINGS[row["id"]] = row
    return response.one(row, ser.listing, 201)


@bp.post("/listings/<listing_id>/relist")
@mw.require(C.ROLE_SELLER)
def relist(listing_id):
    listing = guards.listing(listing_id)
    mw.ensure_owner(listing["seller_id"])
    seller = db.SELLERS[listing["seller_id"]]
    guards.ensure_not_banned(seller)
    if listing["state"] != "REMOVED":
        raise ApiError("ERR_LISTING_NOT_REMOVED")
    if seller["enforcement_state"] in ("RESTRICTED", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE")
    if listing["removal_policy_category"] == "RESTRICTED_PRODUCT":
        raise ApiError("ERR_LISTING_RESTRICTED_NO_RELIST")

    db.set_field(listing, "state", "ACTIVE")
    db.set_field(listing, "removal_policy_category", None)
    db.set_field(listing, "suppressed_by_suspension", False)
    return response.one(listing, ser.listing, 200)
