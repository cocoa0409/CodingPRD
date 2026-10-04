"""Entry point: app factory, error handlers, blueprint registration."""
import os

from flask import Flask

from helpers import ApiError, api_error_response

import routes_clock
import routes_brands
import routes_licensing
import routes_audits
import routes_varieties
import routes_models
import routes_facilities
import routes_runs
import routes_households
import routes_brewers
import routes_service
import routes_retail
import routes_statements


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for mod in (
        routes_clock, routes_brands, routes_licensing, routes_audits,
        routes_varieties, routes_models, routes_facilities, routes_runs,
        routes_households, routes_brewers, routes_service, routes_retail,
        routes_statements,
    ):
        app.register_blueprint(mod.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return api_error_response(err)

    @app.errorhandler(404)
    def handle_not_found(_e):
        return api_error_response(
            ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_method_not_allowed(_e):
        return api_error_response(
            ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return api_error_response(
            ApiError("ERR_INTERNAL", 500, "Internal error: %s" % (err,)))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
