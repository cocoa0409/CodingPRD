"""Seized Asset Custody, Valuation & Disposition API — Flask entry point.

Mounts all 38 business endpoints under /custody plus the unprefixed logical
clock endpoint POST /_clock/set_current_utc at the app root. The store is
purely in-memory and starts empty on every boot (no seeding).
"""

import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_payload
import routes_assets
import routes_cases
import routes_distributions
import routes_expenses
import routes_interests
import routes_isr
import routes_ops
import routes_sales
import routes_transfers
import routes_valuations


def create_app():
    app = Flask(__name__)

    for module in (
        routes_cases,
        routes_assets,
        routes_transfers,
        routes_valuations,
        routes_expenses,
        routes_isr,
        routes_interests,
        routes_sales,
        routes_distributions,
        routes_ops,
    ):
        app.register_blueprint(module.bp)
    routes_ops.register_clock_route(app)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_payload(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def handle_not_found(exc):
        return (
            jsonify(error_payload("ERR_NOT_FOUND", "Resource not found")),
            404,
        )

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return (
            jsonify(error_payload("ERR_NOT_FOUND", "Method not allowed")),
            405,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return jsonify(error_payload("ERR_INTERNAL", str(exc))), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
