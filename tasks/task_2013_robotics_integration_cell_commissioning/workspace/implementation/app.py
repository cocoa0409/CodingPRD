"""Robotics Integration & Cell Commissioning API — entry point.

Binds 0.0.0.0:$PORT (default 10000) per INSTRUCTION.md. The in-memory store starts
empty on every boot; no seeding.
"""
import os

from flask import Flask

import response
from errors import ApiError, ERR_NOT_FOUND
from routes import (assessments, clock, guarantees, ledger, orgs, packages,
                    plans, programs, projects, selections, sessions, sites,
                    studies, tests)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (orgs, sites, projects, studies, assessments, selections,
                   programs, tests, packages, plans, sessions, guarantees,
                   ledger, clock):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return response.error(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_not_found(_err):
        return response.error(ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(405)
    def handle_method_not_allowed(_err):
        return response.error(ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return response.error("ERR_INTERNAL", 500, f"Unexpected server error: {err}")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            debug=False, threaded=True, use_reloader=False)
