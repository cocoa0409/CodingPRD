"""Merit Scholarship Awards API — Flask entry point.

In-memory store (module-level dicts, empty at boot), logical clock starting
at 2026-09-01T00:00:00Z. Reads PORT (default 10000), binds 0.0.0.0.
"""

import os
import traceback

from flask import Flask, jsonify

from errors import ApiError
from helpers import auth_before_request, error_body
import routes_agreements
import routes_applications
import routes_awards
import routes_clock
import routes_cycles
import routes_entries
import routes_notifications
import routes_registry


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.before_request(auth_before_request)

    for module in (
        routes_cycles,
        routes_registry,
        routes_entries,
        routes_applications,
        routes_agreements,
        routes_awards,
        routes_notifications,
        routes_clock,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def handle_not_found(exc):
        return jsonify(error_body("ERR_NOT_FOUND", "resource not found")), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return jsonify(error_body("ERR_NOT_FOUND", "method not allowed")), 405

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        traceback.print_exc()
        return jsonify(error_body("ERR_INTERNAL", "internal error: %s" % exc)), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
