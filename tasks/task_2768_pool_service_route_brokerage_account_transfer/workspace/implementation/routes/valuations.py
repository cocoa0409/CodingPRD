"""Valuation snapshots are read-only; they are written by the listing endpoints."""

from flask import Blueprint, request

from auth import begin, guard_listing
from responses import list_response, object_response, pagination
from serializers import valuation_json
from services import get_valuation
from store import ordered, store
from validators import bad, path_uuid

bp = Blueprint("valuations", __name__)


@bp.get("/route-valuations/<identifier>")
def read_valuation(identifier):
    begin("Broker", "PlatformAdmin", "Seller", "Buyer")
    existing = store.route_valuations.get(identifier)
    if existing is not None:
        guard_listing(store.route_listings.get(existing["listing_id"]))
    path_uuid(identifier)
    return object_response(valuation_json(get_valuation(identifier)))


@bp.get("/route-valuations")
def list_valuations():
    begin("Broker", "PlatformAdmin", "Seller", "Buyer")
    limit, offset = pagination()
    listing_id = request.args.get("listing_id")
    basis = request.args.get("basis")
    superseded = request.args.get("is_superseded")
    flag = None
    if superseded is not None:
        if superseded.lower() in ("true", "1"):
            flag = True
        elif superseded.lower() in ("false", "0"):
            flag = False
        else:
            bad("Query parameter 'is_superseded' must be a boolean.")

    def keep(row):
        if listing_id is not None and row["listing_id"] != listing_id:
            return False
        if basis is not None and row["basis"] != basis:
            return False
        if flag is not None and row["is_superseded"] is not flag:
            return False
        return True

    return list_response(ordered(store.route_valuations, keep), valuation_json, limit, offset)
