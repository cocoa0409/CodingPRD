"""Deal Desk pricing and approval service.

A Flask application whose storage is entirely in-memory: nothing is seeded,
preloaded or hardcoded at startup, so a fresh process starts with an empty
world and a logical clock reading 2026-08-01T00:00:00Z (PRD 2.5).
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import auth
import response
import routes_approvals
import routes_config
import routes_delegations
import routes_exceptions
import routes_orderforms
import routes_quotes
import routes_revrec
import routes_sweeps
import routes_terms
from errors import ApiError

BLUEPRINTS = (
    routes_config.bp,
    routes_quotes.bp,
    routes_terms.bp,
    routes_exceptions.bp,
    routes_revrec.bp,
    routes_approvals.bp,
    routes_delegations.bp,
    routes_orderforms.bp,
    routes_sweeps.bp,
)

DEFAULT_PORT = 10000


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _authenticate():
        """PRD 2.11 step 1: authentication precedes every other check."""
        auth.check_authentication()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return response.error(
            "ERR_NOT_FOUND", "No resource is served at that path.", 404
        )

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return response.error(
            "ERR_METHOD_NOT_ALLOWED",
            "That method is not allowed on this path.",
            405,
        )

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return _not_found(exc)
        if exc.code == 405:
            return _method_not_allowed(exc)
        return response.error(
            "ERR_INVALID_REQUEST", exc.description or "Malformed request.", 400
        )

    @app.errorhandler(Exception)
    def _unexpected(exc):
        app.logger.exception("unhandled error")
        return response.error("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", DEFAULT_PORT))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
