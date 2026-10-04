"""Listing and marketing routes (PRD 3.6)."""

from flask import Blueprint

from constants import ROLES
from routes import endpoint, json_body, query_params
from services import listings
from services.lookup import get_listing
from store import db

bp = Blueprint("listings", __name__)

COORDINATOR = ROLES[0]
HOMEOWNER = ROLES[2]


@bp.post("/knock/listings")
@endpoint([COORDINATOR], status=201)
def draft(actor):
    return listings.create_listing(json_body())


@bp.get("/knock/listings")
@endpoint([COORDINATOR])
def list_listings(actor):
    params = query_params()
    records = db.all("listings")
    for field in ("departing_property_id", "bridge_program_id", "status"):
        value = params.get(field)
        if value:
            records = [r for r in records if r.get(field) == value]
    return db.sorted_by_created(records), params


@bp.get("/knock/listings/<listing_id>")
@endpoint([COORDINATOR, HOMEOWNER])
def read(actor, listing_id):
    return get_listing(listing_id)


@bp.patch("/knock/listings/<listing_id>")
@endpoint([COORDINATOR])
def relist(actor, listing_id):
    return listings.relist(listing_id, json_body(), actor)


@bp.post("/knock/listings/<listing_id>/go-live")
@endpoint([COORDINATOR])
def go_live(actor, listing_id):
    return listings.go_live(listing_id, actor)


@bp.post("/knock/listings/<listing_id>/under-contract")
@endpoint([COORDINATOR])
def under_contract(actor, listing_id):
    return listings.under_contract(listing_id, actor)


@bp.post("/knock/listings/<listing_id>/close-sale")
@endpoint([COORDINATOR])
def close_sale(actor, listing_id):
    return listings.close_sale(listing_id, actor)