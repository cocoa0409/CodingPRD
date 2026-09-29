"""NIL Collective Administration API.

Entry point: registers every blueprint, installs the error envelope handlers and
serves on 0.0.0.0:$PORT. The in-memory store starts completely empty on every
boot; nothing is seeded, preloaded or hardcoded here.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
from errors import ApiError
from routes import athletes as athletes_routes
from routes import clock_routes
from routes import collectives as collectives_routes
from routes import commitments as commitments_routes
from routes import comms as comms_routes
from routes import contracts as contracts_routes
from routes import contributions as contributions_routes
from routes import deliverables as deliverables_routes
from routes import donors as donors_routes
from routes import releases as releases_routes
from routes import tiers as tiers_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (clock_routes, collectives_routes, tiers_routes, donors_routes,
                   commitments_routes, contributions_routes, athletes_routes,
                   contracts_routes, deliverables_routes, releases_routes,
                   comms_routes):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return envelope.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return envelope.error_response(
                "ERR_INVALID_REQUEST", "The requested resource path does not exist.", 404)
        if exc.code == 405:
            return envelope.error_response(
                "ERR_INVALID_REQUEST",
                "The HTTP method is not allowed on this resource path.", 405)
        if exc.code == 400:
            return envelope.error_response(
                "ERR_INVALID_REQUEST", "The request could not be parsed.", 400)
        return envelope.error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request failed.", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return envelope.error_response(
            "ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)
