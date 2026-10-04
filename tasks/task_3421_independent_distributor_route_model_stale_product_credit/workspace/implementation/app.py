"""Entry point: Flask app assembly, error handlers, route registration."""
import os
import traceback

from flask import Flask

import response
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INTERNAL

import routes_core
import routes_territories
import routes_distributors
import routes_agreements
import routes_financing
import routes_orders
import routes_claims
import routes_transfers


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (
        routes_core, routes_territories, routes_distributors, routes_agreements,
        routes_financing, routes_orders, routes_claims, routes_transfers,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return response.error(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(err):
        return response.error(ERR_NOT_FOUND[0], "Resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return response.error(ERR_INVALID_REQUEST[0], "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        traceback.print_exc()
        return response.error(ERR_INTERNAL[0], f"Internal error: {err}", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
