"""Union Grievance & Arbitration Tracking API — Flask entry point.

Storage is in-memory only and starts completely empty on every boot: no
entity is seeded, preloaded or hardcoded here or in any imported module.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from core import ApiError, error_body
import routes_arbitration
import routes_config
import routes_grievance
import routes_settlement

API_PREFIX = "/labor-relations"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_config.bp, url_prefix=API_PREFIX)
    app.register_blueprint(routes_grievance.bp, url_prefix=API_PREFIX)
    app.register_blueprint(routes_settlement.bp, url_prefix=API_PREFIX)
    app.register_blueprint(routes_arbitration.bp, url_prefix=API_PREFIX)
    # The logical-clock control is the one route outside the API prefix.
    app.register_blueprint(routes_config.clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 404:
            return jsonify(error_body("ERR_NOT_FOUND", "Resource not found.")), 404
        if exc.code == 405:
            return jsonify(
                error_body("ERR_METHOD_NOT_ALLOWED", "Method not allowed.")), 405
        if exc.code and 400 <= exc.code < 500:
            return jsonify(
                error_body("ERR_INVALID_REQUEST", exc.description or "Bad request.")), exc.code
        return jsonify(error_body("ERR_INTERNAL", "Internal server error.")), exc.code or 500

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("unhandled error")
        return jsonify(error_body("ERR_INTERNAL", "Internal server error.")), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
