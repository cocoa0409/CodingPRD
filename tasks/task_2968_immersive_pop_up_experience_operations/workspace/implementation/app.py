"""Immersive Pop-Up Experience Operations API — entry point.

Storage is in-memory only and starts empty on every boot: no entity is seeded,
preloaded or hardcoded anywhere in this process.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.clock import bp as clock_bp
from routes.venues import bp as venues_bp
from routes.agreements import bp as agreements_bp
from routes.submissions import bp as submissions_bp
from routes.runs import bp as runs_bp
from routes.rooms import bp as rooms_bp
from routes.slots import bp as slots_bp
from routes.guests import bp as guests_bp
from routes.orders import bp as orders_bp
from routes.staff import bp as staff_bp
from routes.shifts import bp as shifts_bp
from routes.inspections import bp as inspections_bp
from routes.kits import bp as kits_bp
from routes.statements import bp as statements_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for bp in (clock_bp, venues_bp, agreements_bp, submissions_bp, runs_bp,
               rooms_bp, slots_bp, guests_bp, orders_bp, staff_bp, shifts_bp,
               inspections_bp, kits_bp, statements_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "No such route.", 404)
        if exc.code == 405:
            return error_response("ERR_NOT_FOUND",
                                  "That method is not allowed on this route.", 405)
        if exc.code in (400, 415):
            return error_response("ERR_VALIDATION",
                                  "The request body could not be parsed.", 422)
        return error_response("ERR_INTERNAL", exc.description or "Error", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        return error_response("ERR_INTERNAL", str(exc) or "Internal error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
