"""Rate quote endpoints: read, view, decline."""

from flask import request

from db import clock_now, db, serialize, touch
from errors import ApiError
from middleware import current_actor, roles_required
from response import array_response, object_response, paginate
from services.carriers import sync_carrier
from services.common import get_quote, refresh_quote
from constants import utc


def register(app):
    @app.route("/v1/rate-quotes", methods=["GET"])
    @roles_required("Shipper", "Carrier", "PlatformAdmin")
    def list_quotes():
        rows = list(db.quotes.values())
        for field in ("load_id", "status", "quote_kind"):
            value = request.args.get(field)
            if value:
                rows = [row for row in rows if row.get(field) == value]
        rows.sort(key=lambda row: row["created_at"])
        window, pagination = paginate(rows, request.args)
        return array_response([serialize("RateQuote", row) for row in window], pagination)

    @app.route("/v1/rate-quotes/<quote_id>", methods=["GET"])
    @roles_required("Shipper", "Carrier", "PlatformAdmin")
    def get_quote_route(quote_id):
        quote = get_quote(quote_id)
        refresh_quote(quote)
        return object_response(serialize("RateQuote", quote))

    @app.route("/v1/rate-quotes/<quote_id>/view", methods=["POST"])
    @roles_required("Carrier")
    def view_quote(quote_id):
        role, identity = current_actor()
        quote = get_quote(quote_id)
        carrier = db.carriers.get(identity)
        if carrier is None:
            raise ApiError("ERR_CARRIER_NOT_FOUND")
        sync_carrier(carrier)
        load = db.loads.get(quote["load_id"])
        if not utc(quote["acceptance_deadline"]) > clock_now():
            raise ApiError("ERR_QUOTE_EXPIRED")
        if load is None or load["status"] != "POSTED":
            raise ApiError("ERR_QUOTE_NOT_VIEWABLE")
        if quote["status"] not in ("ACTIVE", "VIEWED"):
            raise ApiError("ERR_INVALID_STATE")
        if identity not in quote["viewed_carrier_ids"]:
            quote["viewed_carrier_ids"].append(identity)
        quote["status"] = "VIEWED"
        touch(quote)
        return object_response(serialize("RateQuote", quote))

    @app.route("/v1/rate-quotes/<quote_id>/decline", methods=["POST"])
    @roles_required("Carrier")
    def decline_quote(quote_id):
        role, identity = current_actor()
        quote = get_quote(quote_id)
        carrier = db.carriers.get(identity)
        if carrier is None:
            raise ApiError("ERR_CARRIER_NOT_FOUND")
        sync_carrier(carrier)
        if quote["status"] != "VIEWED":
            raise ApiError("ERR_INVALID_STATE")
        if identity in quote["declined_carrier_ids"]:
            raise ApiError("ERR_INVALID_STATE",
                           "The carrier has already declined this quote.")
        quote["declined_carrier_ids"].append(identity)
        quote["status"] = "DECLINED"
        touch(quote)
        return object_response(serialize("RateQuote", quote))