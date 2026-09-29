"""Pooled Employer Plan administration API (PRD task_2936).

Python + Flask, in-memory only. Every collection starts empty on every boot --
there is no seeding, no file, no database and no cache. The harness relaunches
this process before each individual test, so a fresh process is a fresh world.
"""

import os

from flask import Flask

import envelope
import store
from errors import ApiError

import routes_setup
import routes_employer
import routes_payroll
import routes_compliance
import routes_exit


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_setup.bp)
    app.register_blueprint(routes_employer.bp)
    app.register_blueprint(routes_payroll.bp)
    app.register_blueprint(routes_compliance.bp)
    app.register_blueprint(routes_exit.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error_response(exc.error_id, exc.message)

    @app.errorhandler(404)
    def _not_found(_exc):
        return envelope.error_response(
            "ERR_NOT_FOUND", "No endpoint matches the requested path."
        )

    @app.errorhandler(405)
    def _method_not_allowed(_exc):
        return envelope.error_response(
            "ERR_METHOD_NOT_ALLOWED",
            "The requested method is not allowed for this path.",
        )

    @app.errorhandler(400)
    def _bad_request(_exc):
        return envelope.error_response(
            "ERR_VALIDATION", "The request body or query string is malformed."
        )

    @app.errorhandler(415)
    def _unsupported_media(_exc):
        return envelope.error_response(
            "ERR_VALIDATION", "The request body or query string is malformed."
        )

    @app.errorhandler(Exception)
    def _unexpected(exc):
        if isinstance(exc, ApiError):
            return envelope.error_response(exc.error_id, exc.message)
        # Never masquerade an internal defect as a business rejection: report it
        # as a 500 inside the standard envelope so it stays diagnosable.
        return envelope.respond(
            {
                "meta": envelope._meta(),
                "response_type": "error",
                "data": {
                    "error_id": "ERR_INTERNAL",
                    "message": "%s: %s" % (type(exc).__name__, exc),
                },
            },
            500,
        )

    return app


store.reset()
app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
