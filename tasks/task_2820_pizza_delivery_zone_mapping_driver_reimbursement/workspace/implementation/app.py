"""Store Operations API (PRD: pizza delivery zone mapping and driver
reimbursement). Everything is held in plain in-memory dicts; nothing is seeded
at startup, and every entity is built through the declared endpoints."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ERROR_STATUS, ApiError, _default_message
from routes import (
    clock_routes,
    complaints,
    dispatches,
    drivers,
    fleet,
    orders,
    stores,
    zones,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for module in (
        stores,
        zones,
        drivers,
        fleet,
        orders,
        dispatches,
        complaints,
        clock_routes,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        status = ERROR_STATUS.get(exc.error_id, 400)
        message = exc.message or _default_message(exc.error_id)
        return response.error(exc.error_id, message, status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return response.error("ERR_NOT_FOUND", "No such endpoint.", 404)
        if exc.code == 405:
            return response.error(
                "ERR_METHOD_NOT_ALLOWED", "That method is not allowed here.", 405
            )
        if exc.code and exc.code < 500:
            return response.error(
                "ERR_INVALID_REQUEST", exc.description or "Malformed request.", 400
            )
        return response.error("ERR_INTERNAL", "Internal server error.", 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return response.error("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
