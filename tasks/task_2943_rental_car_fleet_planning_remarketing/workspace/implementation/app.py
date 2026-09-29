"""Rental Fleet Planning & Remarketing API.

A single-process Flask application with plain in-memory storage. Nothing is
seeded: every entity is created through the declared endpoints, and restarting
the process wipes every byte of state.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_config
import routes_consignment
import routes_damage
import routes_ledger
import routes_order
import routes_plan
import routes_policy
import routes_task
import routes_vehicle
from envelope import error_body, error_response
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    try:
        app.json.sort_keys = False
    except AttributeError:  # pragma: no cover - older Flask
        pass

    for module in (
        routes_config,
        routes_policy,
        routes_plan,
        routes_vehicle,
        routes_task,
        routes_order,
        routes_damage,
        routes_consignment,
        routes_ledger,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        if exc.code == 405:
            return error_body(
                "ERR_METHOD_NOT_ALLOWED", "The method is not allowed for this path.", 405
            )
        if exc.code == 404:
            return error_body("ERR_NOT_FOUND", "No route matches this path.", 404)
        return error_body("ERR_INVALID_REQUEST", exc.description or "Invalid request.", 422)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):  # pragma: no cover - defensive
        return error_body("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
