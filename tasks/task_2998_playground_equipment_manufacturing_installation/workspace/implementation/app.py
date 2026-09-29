"""Playground Equipment Manufacturing & Installation API.

Flask application factory and process entry point.  All state lives in plain
in-memory dictionaries inside store.py: nothing is seeded, nothing is persisted,
and every fresh process starts with an empty world and the logical clock parked
at the mandatory default 2026-08-01T00:00:00Z (PRD section 2.5).
"""

import os
import sys
import traceback

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_areas
import routes_clock
import routes_installers
import routes_jobs
import routes_orders
import routes_pledges
import routes_projects
import routes_quotes
import routes_renderings
import routes_standards
import routes_warranty
from envelope import error_response
from errors import ApiError

BLUEPRINTS = (
    routes_standards.bp,
    routes_projects.bp,
    routes_areas.bp,
    routes_renderings.bp,
    routes_quotes.bp,
    routes_pledges.bp,
    routes_orders.bp,
    routes_installers.bp,
    routes_jobs.bp,
    routes_warranty.bp,
    routes_clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.config["PROPAGATE_EXCEPTIONS"] = False
    try:
        app.json.sort_keys = False
    except Exception:  # pragma: no cover - older Flask
        app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        status = exc.code or 500
        if status == 404:
            message = "No such route."
        elif status == 405:
            message = "Method not allowed for this route."
        else:
            message = exc.description or "Request rejected."
        return error_response("ERR_INVALID_REQUEST", message, status)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        traceback.print_exc(file=sys.stderr)
        return error_response("ERR_INTERNAL_ERROR", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
