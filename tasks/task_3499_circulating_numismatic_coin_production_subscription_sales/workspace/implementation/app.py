"""US Mint Coinage API — Flask entry point.

Mounts the platform clock endpoint (outside the /mint prefix) and all
business resources under /mint. The store boots empty on every process
start; the logical clock reads 2026-09-01T00:00:00Z until set.
"""
import os

from flask import Flask

import routes_bullion
import routes_clock
import routes_denominations
import routes_errorcoins
import routes_lots
import routes_orders
import routes_products
import routes_programs
import routes_reports
import routes_runs
import routes_subscriptions
from errors import ApiError
from helpers import error_envelope


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (routes_clock, routes_denominations, routes_lots,
                   routes_runs, routes_errorcoins, routes_programs,
                   routes_products, routes_orders, routes_subscriptions,
                   routes_bullion, routes_reports):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(e):
        return error_envelope(e)

    @app.errorhandler(404)
    def _handle_404(e):
        return error_envelope(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def _handle_405(e):
        return error_envelope(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_envelope(e)
        return error_envelope(ApiError("ERR_INTERNAL", 500, str(e)))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
