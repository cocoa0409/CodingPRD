"""Oilseed Crush Origination API — Flask entry point.

In-memory store, logical clock booting at 2026-09-01T00:00:00Z, no seeding.
"""
import os

from flask import Flask

from envelope import error_body
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    import routes_clock
    import routes_contracts
    import routes_elevators
    import routes_freight
    import routes_hedges
    import routes_reference
    import routes_runs
    import routes_sales
    import routes_tickets

    for module in (routes_clock, routes_reference, routes_elevators,
                   routes_contracts, routes_tickets, routes_freight,
                   routes_runs, routes_hedges, routes_sales):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_body(err.error_id, err.message, err.status)

    @app.errorhandler(404)
    def handle_not_found(_err):
        return error_body("ERR_INVALID_REQUEST", "route not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_err):
        return error_body("ERR_INVALID_REQUEST", "method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_body("ERR_INVALID_REQUEST", "unexpected error: %s" % err, 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
