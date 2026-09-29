"""Esports Org Operations API.

Flask application factory and the global error envelope.  Storage is in-memory only and
starts completely EMPTY on every boot -- nothing is ever seeded.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
import routes_core
import routes_moves
import routes_offers
import routes_practice
import routes_prizes
import routes_sponsorship
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_offers.bp)
    app.register_blueprint(routes_practice.bp)
    app.register_blueprint(routes_sponsorship.bp)
    app.register_blueprint(routes_prizes.bp)
    app.register_blueprint(routes_moves.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        # An unrouted path or an unsupported method still returns the standard envelope.
        if exc.code == 404:
            return response.error_response("ERR_NOT_FOUND", "Resource not found.", 404)
        if exc.code == 405:
            return response.error_response(
                "ERR_METHOD_NOT_ALLOWED", "Method not allowed for this path.", 405)
        if exc.code == 400:
            return response.error_response(
                "ERR_INVALID_REQUEST", "Malformed request.", 400)
        return response.error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request could not be processed.",
            exc.code or 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return response.error_response("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
