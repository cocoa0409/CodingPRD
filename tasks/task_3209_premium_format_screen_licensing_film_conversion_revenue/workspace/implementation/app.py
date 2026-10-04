"""Flask app entry point."""
from __future__ import annotations

import os

from flask import Flask, jsonify

from errors import ApiError, ERR_INVALID_REQUEST
from util import error_body

import routes_markets
import routes_agreements
import routes_auditoriums
import routes_studios_films
import routes_conversions
import routes_windows
import routes_slots
import routes_reports
import routes_statements
import routes_qa
import routes_clock


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for module in (
        routes_markets, routes_agreements, routes_auditoriums, routes_studios_films,
        routes_conversions, routes_windows, routes_slots, routes_reports,
        routes_statements, routes_qa, routes_clock,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return jsonify(error_body(err.error_id, err.message)), err.http_status

    @app.errorhandler(404)
    def handle_404(err):
        return jsonify(error_body(ERR_INVALID_REQUEST, "Not found")), 404

    @app.errorhandler(405)
    def handle_405(err):
        return jsonify(error_body(ERR_INVALID_REQUEST, "Method not allowed")), 405

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        import traceback
        traceback.print_exc()
        return jsonify(error_body(ERR_INVALID_REQUEST, f"Internal error: {err}")), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
