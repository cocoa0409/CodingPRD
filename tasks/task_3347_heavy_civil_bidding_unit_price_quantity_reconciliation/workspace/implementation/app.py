"""Heavy Civil Bidding & Unit-Price Quantity Reconciliation API.

Entry point: registers every route, enforces the authentication and permission
bands ahead of all other checks, and serves the standard response envelope.

The store is in-memory and starts empty on every boot; nothing is seeded.
"""

import os
import traceback

from flask import Flask, request
from werkzeug.exceptions import HTTPException

import routes_admin
import routes_bid
import routes_delivery
from errors import ApiError
from response import error_response, object_response

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

ROUTE_META = {}


def _make_view(handler):
    def view(**kwargs):
        return handler(**kwargs)
    view.__name__ = "view_" + handler.__name__
    return view


def register(module):
    for method, rule, roles, auth_required, handler in module.ROUTES:
        endpoint = "%s %s" % (method, rule)
        app.add_url_rule(rule, endpoint=endpoint, view_func=_make_view(handler),
                         methods=[method])
        ROUTE_META[endpoint] = {"roles": tuple(roles), "auth": bool(auth_required)}


register(routes_admin)
register(routes_bid)
register(routes_delivery)


@app.before_request
def enforce_authentication():
    """Band one of the evaluation order: presence outranks permission."""
    meta = ROUTE_META.get(request.endpoint)
    if meta is None or not meta["auth"]:
        return None
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not role.strip() or not user_id or not user_id.strip():
        raise ApiError("ERR_UNAUTHENTICATED",
                       "Both X-User-ID and X-User-Role headers are required.", 401)
    if role not in meta["roles"]:
        raise ApiError("ERR_FORBIDDEN",
                       "The role %s is not permitted on this operation." % role, 403)
    return None


@app.errorhandler(ApiError)
def handle_api_error(error):
    return error_response(error)


@app.errorhandler(HTTPException)
def handle_http_exception(error):
    if error.code == 404:
        return error_response(ApiError("ERR_PROJECT_NOT_FOUND",
                                       "The requested resource does not exist.", 404))
    if error.code == 405:
        return error_response(ApiError("ERR_INVALID_REQUEST",
                                       "The method is not allowed on this resource.", 405))
    return error_response(ApiError("ERR_INVALID_REQUEST", error.description or "Bad request.",
                                   error.code or 400))


@app.errorhandler(Exception)
def handle_unexpected(error):
    traceback.print_exc()
    return error_response(ApiError("ERR_INVALID_REQUEST",
                                   "The request could not be processed.", 500))


@app.route("/", methods=["GET"])
def root():
    return object_response({"service": "heavy-civil-bidding-unit-price-reconciliation"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
