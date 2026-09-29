"""Aviation Hull & Liability Underwriting API.

A single Flask process holding every row in memory. Nothing is seeded: a fresh
process starts with twelve empty collections and the logical clock at the
mandated default of 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
import routes_claims
import routes_endorsements
import routes_fleet
import routes_policies
import routes_registry
import routes_war
from errors import ApiError


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_registry.bp)
    app.register_blueprint(routes_policies.bp)
    app.register_blueprint(routes_endorsements.bp)
    app.register_blueprint(routes_war.bp)
    app.register_blueprint(routes_claims.bp)
    app.register_blueprint(routes_fleet.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.fail(exc.error_id, exc.message, exc.status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return envelope.fail("ERR_NOT_FOUND", "No such resource.", 404)
        if exc.code == 405:
            return envelope.fail("ERR_METHOD_NOT_ALLOWED",
                                 "That method is not allowed on this resource.", 405)
        if exc.code == 400:
            return envelope.fail("ERR_INVALID_REQUEST", "Malformed request.", 400)
        return envelope.fail("ERR_INTERNAL", exc.description or "Request failed.",
                             exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return envelope.fail("ERR_INTERNAL", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
