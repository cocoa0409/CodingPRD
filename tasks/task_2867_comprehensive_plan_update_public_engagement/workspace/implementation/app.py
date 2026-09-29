"""Comprehensive Plan Update API.

Flask application factory plus the logical-clock control endpoint. All state
lives in process memory (see db.py); every boot starts completely empty.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import constants as K
import validation as V
from db import db, iso
from errors import ApiError
from response import authenticate, error_response, ok
from routes import (capacity, elements, engagement, environmental, hearings,
                    implementation, plans)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(plans.bp)
    app.register_blueprint(capacity.bp)
    app.register_blueprint(elements.bp)
    app.register_blueprint(engagement.bp)
    app.register_blueprint(environmental.bp)
    app.register_blueprint(hearings.bp)
    app.register_blueprint(implementation.bp)

    @app.post("/_clock/set_current_utc")
    def set_clock():
        authenticate(K.ALL_ROLES)
        data = V.body()
        instant = V.get_instant(data, "to_iso8601")
        # Setting the clock mutates no entity; it may move forward or backward.
        db.clock = instant
        return ok({"current_utc": iso(db.clock)})

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        if err.code == 404:
            return error_response(ApiError("ERR_NOT_FOUND"))
        if err.code == 405:
            return error_response(ApiError("ERR_METHOD_NOT_ALLOWED"))
        if err.code in (400, 415):
            return error_response(ApiError("ERR_INVALID_REQUEST"))
        return error_response(ApiError("ERR_INTERNAL", str(err), err.code or 500))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(ApiError("ERR_INTERNAL", str(err), 500))

    return app


application = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    application.run(host="0.0.0.0", port=port, threaded=True, debug=False,
                    use_reloader=False)
