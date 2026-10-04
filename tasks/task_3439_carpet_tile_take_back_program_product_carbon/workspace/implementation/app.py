"""Carpet Tile Take-Back & Product Carbon Accounting API — entry point.

Python + Flask, in-memory only (module-level store; a fresh process wipes all
state). Listens on 0.0.0.0:$PORT (default 10000) per INSTRUCTION.md.
"""
import os
import traceback

from flask import Flask

from envelope import error_response
from errors import ApiError
from routes_claims import bp as claims_bp
from routes_clock import bp as clock_bp
from routes_collections import bp as collections_bp
from routes_feedstock import bp as feedstock_bp
from routes_orders import bp as orders_bp
from routes_packages import bp as packages_bp
from routes_reports import bp as reports_bp
from routes_sites import bp as sites_bp
from routes_takebacks import bp as takebacks_bp
from routes_targets import bp as targets_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in (
        collections_bp,
        feedstock_bp,
        sites_bp,
        orders_bp,
        takebacks_bp,
        reports_bp,
        claims_bp,
        targets_bp,
        packages_bp,
        clock_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _not_found(_err):
        # Unmatched route — no declared resource vocabulary applies.
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Route not found"))

    @app.errorhandler(405)
    def _method_not_allowed(_err):
        return error_response(
            ApiError("ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed on this route")
        )

    @app.errorhandler(Exception)
    def _internal(err):
        traceback.print_exc()
        return error_response(ApiError("ERR_INTERNAL", 500, "Internal server error"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
