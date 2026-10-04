"""Application entry point.

The store is process-local and starts empty: nothing is seeded, preloaded or
hardcoded here. Every entity a caller needs is constructed through the declared
API surface, so a fresh boot under the per-test-server isolation mode begins
with a completely clean system.
"""

import os

from flask import Flask, jsonify

from db import db
from errors import ApiError, api_error, ERR_INVALID_REQUEST
from middleware import PLATFORM_ADMIN, principal
from request import body, check_unknown, require
from response import error as error_envelope, success_object
from routes.participants import bp as participants_bp
from routes.positions import bp as positions_bp
from routes.trades import bp as trades_bp
from routes.windows import bp as windows_bp
from timeutil import is_iso_instant

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

app.register_blueprint(participants_bp)
app.register_blueprint(windows_bp)
app.register_blueprint(trades_bp)
app.register_blueprint(positions_bp)


@app.post("/clearing/_clock/set_current_utc")
def set_current_utc():
    principal((PLATFORM_ADMIN,))
    data = body()
    check_unknown(data, ("to_iso8601",))
    to_iso8601 = require(data, "to_iso8601", type_=str)
    if not is_iso_instant(to_iso8601):
        raise api_error(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 UTC instant.")
    db.set_clock(to_iso8601)
    return jsonify(success_object({"current_utc": db.get_clock()})), 200


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return jsonify(error_envelope(exc.error_id, exc.message)), exc.http_status


@app.errorhandler(404)
def handle_not_found(_exc):
    from errors import ERR_RESOURCE_NOT_FOUND

    failure = api_error(ERR_RESOURCE_NOT_FOUND)
    return jsonify(error_envelope(failure.error_id, failure.message)), 404


@app.errorhandler(405)
def handle_method_not_allowed(_exc):
    from errors import ERR_RESOURCE_NOT_FOUND

    failure = api_error(ERR_RESOURCE_NOT_FOUND, "No route matches that method and path.")
    return jsonify(error_envelope(failure.error_id, failure.message)), 404


@app.errorhandler(500)
def handle_server_error(_exc):
    failure = api_error(ERR_INVALID_REQUEST, "The request could not be processed.")
    return jsonify(error_envelope(failure.error_id, failure.message)), 500


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return handle_api_error(exc)
    from werkzeug.exceptions import HTTPException

    if isinstance(exc, HTTPException):
        return exc
    failure = api_error(ERR_INVALID_REQUEST, "The request could not be processed.")
    return jsonify(error_envelope(failure.error_id, failure.message)), 500


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        debug=False,
        use_reloader=False,
    )