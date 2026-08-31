"""Trail Maintenance Stewardship API - Flask entry point.

Storage is in-memory only and starts EMPTY on every boot: nothing is seeded,
preloaded or hardcoded.  Every entity is built through the declared endpoints.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import routes_adoption
import routes_core
import routes_hazard
import routes_incident
import routes_material
import routes_party
import routes_permit
from envelope import error_body
from errors import ApiError

API_PREFIX = "/stewardship"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (routes_core, routes_adoption, routes_hazard, routes_permit,
                   routes_party, routes_material, routes_incident):
        app.register_blueprint(module.bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return jsonify(error_body("ERR_INVALID_REQUEST", "Unknown route.")), 404
        if exc.code == 405:
            return jsonify(error_body("ERR_INVALID_REQUEST", "Method not allowed.")), 405
        if exc.code and 400 <= exc.code < 500:
            return jsonify(error_body("ERR_INVALID_REQUEST", exc.description or "Bad request.")), exc.code
        return jsonify(error_body("ERR_INVALID_REQUEST", "Server error.")), exc.code or 500

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("unhandled error")
        return jsonify(error_body("ERR_INVALID_REQUEST", str(exc))), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
