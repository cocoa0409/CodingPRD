"""Entry point: Flask app, error handlers, route registration."""

import os
import traceback

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error as error_response
from routes import (
    associates,
    batches,
    beef_deliveries,
    clock,
    commissaries,
    menu_items,
    orders,
    postings,
    production,
    routes as routes_mod,
    shifts,
    stores,
    suppliers,
)

API_PREFIX = "/v1"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        clock.bp,
        suppliers.bp,
        commissaries.bp,
        routes_mod.bp,
        menu_items.bp,
        stores.bp,
        batches.bp,
        orders.bp,
        associates.bp,
        postings.bp,
        shifts.bp,
        beef_deliveries.bp,
        production.bp,
    ):
        app.register_blueprint(bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return error_response(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return error_response(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        traceback.print_exc()
        return error_response(ERR_INVALID_REQUEST, "Unexpected error: %s" % exc, 400)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    try:
        from waitress import serve
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
    else:
        serve(app, host="0.0.0.0", port=port, threads=8, connection_limit=200)
