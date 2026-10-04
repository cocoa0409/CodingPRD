"""Enforcement Consent Orders & Consumer Redress Distribution API.

Flask entry point: blueprint registration, envelope-shaped error handlers,
and the 0.0.0.0:$PORT foreground server.
"""
import os
import traceback

from flask import Flask

import envelope
import errors
from routes_checks import bp as checks_bp
from routes_cids import bp as cids_bp
from routes_claims import bp as claims_bp
from routes_clock import bp as clock_bp
from routes_companies import bp as companies_bp
from routes_funds import bp as funds_bp
from routes_investigations import bp as investigations_bp
from routes_judgments import bp as judgments_bp
from routes_orders import bp as orders_bp
from routes_penalties import bp as penalties_bp
from routes_reports import bp as reports_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (
        clock_bp,
        companies_bp,
        investigations_bp,
        cids_bp,
        orders_bp,
        reports_bp,
        penalties_bp,
        judgments_bp,
        funds_bp,
        claims_bp,
        checks_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return envelope.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return envelope.error(
            "ERR_NOT_FOUND", "The requested path does not exist", 404
        )

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return envelope.error(
            "ERR_METHOD_NOT_ALLOWED",
            "The method is not allowed for this path",
            405,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        traceback.print_exc()
        return envelope.error("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
    )
