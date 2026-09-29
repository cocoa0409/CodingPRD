"""Crime Laboratory Case Management & Backlog Reduction API.

In-memory only: every table lives in the process-local dicts of store.py and no
entity data is ever seeded. A fresh process starts empty with its logical clock
at exactly 2026-08-01T00:00:00Z.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_casework
import routes_court
import routes_intake
import routes_quality
import routes_reads
import routes_registry
import routes_vendor
from envelope import error_response
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    app.register_blueprint(routes_registry.bp)
    app.register_blueprint(routes_intake.bp)
    app.register_blueprint(routes_casework.bp)
    app.register_blueprint(routes_vendor.bp)
    app.register_blueprint(routes_quality.bp)
    app.register_blueprint(routes_court.bp)
    app.register_blueprint(routes_reads.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 401:
            return error_response(
                "ERR_UNAUTHENTICATED", "Authentication is required.", 401)
        if exc.code == 403:
            return error_response(
                "ERR_UNAUTHORIZED", "The caller's role may not do this.", 403)
        if exc.code == 404:
            return error_response(
                "ERR_INVALID_REQUEST", "No such resource path.", 404)
        if exc.code == 405:
            return error_response(
                "ERR_INVALID_REQUEST",
                "The HTTP method is not allowed on this path.", 405)
        if exc.code in (400, 415, 422):
            return error_response(
                "ERR_INVALID_REQUEST", "The request could not be parsed.", 400)
        return error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request failed.",
            exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response(
            "ERR_INVALID_REQUEST", "Unexpected server condition: %s" % exc, 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
