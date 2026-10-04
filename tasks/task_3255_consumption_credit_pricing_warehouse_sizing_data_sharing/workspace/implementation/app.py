"""Entry point for the consumption-credit warehouse governance API."""
import os
import traceback

from flask import Flask, g, request
from werkzeug.exceptions import HTTPException

from auth import authenticate
from errors import ApiError
from response import error_response

from routes import (accounts, warehouses, sessions, contracts, drawdowns,
                    storage, shares, listings, monitors, replication, clock)

app = Flask(__name__)
app.url_map.strict_slashes = False

AUTH_EXEMPT = {("POST", "/_clock/set_current_utc")}


def _register(blueprint):
    app.register_blueprint(blueprint)


for module in (accounts, warehouses, sessions, contracts, drawdowns, storage,
               shares, listings, monitors, replication, clock):
    _register(module.bp)


@app.before_request
def _authenticate():
    g.role = None
    g.user_id = None
    if (request.method, request.path) in AUTH_EXEMPT:
        return None
    role, user_id = authenticate(request.headers)
    g.role = role
    g.user_id = user_id
    return None


@app.errorhandler(ApiError)
def _api_error(exc):
    return error_response(exc)


@app.errorhandler(HTTPException)
def _http_error(exc):
    if exc.code in (404, 405):
        return error_response(ApiError("ERR_RESOURCE_NOT_FOUND",
                                       "No route matches this request.", 404))
    return error_response(ApiError("ERR_INVALID_REQUEST", exc.description or "Bad request.",
                                   exc.code or 400))


@app.errorhandler(Exception)
def _unhandled(exc):
    traceback.print_exc()
    return error_response(ApiError("ERR_INVALID_REQUEST",
                                   "The request could not be processed.", 400))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            debug=False, threaded=True, use_reloader=False)
