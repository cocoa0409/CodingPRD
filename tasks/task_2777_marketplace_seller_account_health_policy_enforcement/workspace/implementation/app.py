"""Marketplace Seller Account Health & Policy Enforcement service.

In-memory only: every dict in db.py starts empty on each boot and nothing is
ever seeded, so re-invoking start.sh wipes all state.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import (
    appeals,
    clock_routes,
    enforcement,
    holds,
    links,
    listings,
    metrics,
    plans,
    policy_rules,
    sellers,
    violations,
)

BLUEPRINTS = (
    clock_routes.bp,
    sellers.bp,
    metrics.bp,
    policy_rules.bp,
    listings.bp,
    violations.bp,
    enforcement.bp,
    plans.bp,
    appeals.bp,
    holds.bp,
    links.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return response.error_response(
                "ERR_INVALID_REQUEST", "No such route.", 404)
        if exc.code == 405:
            return response.error_response(
                "ERR_INVALID_REQUEST", "Method not allowed for this route.", 405)
        return response.error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request rejected.",
            exc.code or 400)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        return response.error_response(
            "ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
