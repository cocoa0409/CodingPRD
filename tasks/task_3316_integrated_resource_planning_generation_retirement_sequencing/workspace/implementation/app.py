"""Flask application entry point for the Integrated Resource Planning API."""

import os

from flask import Flask

from errors import ApiError
from response import error_response

import routes_clock
import routes_plans
import routes_forecasts
import routes_resources
import routes_candidates
import routes_portfolios
import routes_positions
import routes_snapshots
import routes_retirement
import routes_comments
import routes_intervenors
import routes_sensitivities
import routes_commitments
import routes_deviations


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for module in (
        routes_clock, routes_plans, routes_forecasts, routes_resources,
        routes_candidates, routes_portfolios, routes_positions, routes_snapshots,
        routes_retirement, routes_comments, routes_intervenors,
        routes_sensitivities, routes_commitments, routes_deviations,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response("ERR_NOT_FOUND", "Route not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
