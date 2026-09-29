"""CTE Program of Study Federal Reporting API.

Boots a completely empty in-memory store on every process start: no seeding,
no persistence, no disk state. Every entity is created through the API.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_committees
import routes_courses
import routes_educators
import routes_grants
import routes_indicators
import routes_plans
import routes_programs
import routes_students
from envelope import error
from errors import ApiError


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.json.sort_keys = False

    for module in (routes_programs, routes_courses, routes_students,
                   routes_committees, routes_grants, routes_indicators,
                   routes_plans, routes_educators):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return error("ERR_NOT_FOUND", "No route matches the requested path.", 404)

    @app.errorhandler(405)
    def _bad_method(exc):
        return error("ERR_INVALID_REQUEST",
                     "The HTTP method is not allowed for this path.", 405)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return error("ERR_INVALID_REQUEST",
                         "The request could not be parsed.", 400)
        return error("ERR_INVALID_REQUEST", exc.description or "Request failed.",
                     exc.code or 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        app.logger.exception("unhandled error")
        return error("ERR_INTERNAL", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
