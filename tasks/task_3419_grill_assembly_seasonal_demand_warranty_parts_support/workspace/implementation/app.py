"""Grill Seasonal Ops API — Flask entry point. Boots with empty in-memory state;
the logical clock starts at DEFAULT_CLOCK_ISO (never wall clock)."""

import os

from flask import Flask

import routes_allocations
import routes_assemblers
import routes_channels
import routes_claims
import routes_clock_seasons
import routes_devices
import routes_jobs
import routes_models
import routes_orders
import routes_parts
import routes_sales
from errors import ApiError
from util import error_response

BLUEPRINTS = (
    routes_clock_seasons.bp,
    routes_models.bp,
    routes_channels.bp,
    routes_allocations.bp,
    routes_assemblers.bp,
    routes_jobs.bp,
    routes_sales.bp,
    routes_claims.bp,
    routes_parts.bp,
    routes_orders.bp,
    routes_devices.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_unknown_route(err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "route not found"))

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response(ApiError("ERR_METHOD_NOT_ALLOWED", 405, "method not allowed"))

    @app.errorhandler(500)
    def handle_internal_error(err):
        return error_response(ApiError("ERR_VALIDATION", 500, "internal server error"))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
