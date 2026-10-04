"""Application entry point: blueprint registration and error handlers."""
import os

from flask import Flask

import routes_catalog
import routes_facilities
import routes_orders
import routes_oversight
import routes_shipments
from responses import ApiError, error_response


def create_app():
    app = Flask(__name__)
    app.register_blueprint(routes_facilities.bp)
    app.register_blueprint(routes_catalog.bp)
    app.register_blueprint(routes_orders.bp)
    app.register_blueprint(routes_shipments.bp)
    app.register_blueprint(routes_oversight.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Never leak a bare 500 HTML page; surface a structured client error.
        return error_response(ApiError("ERR_INVALID_REQUEST", 400, str(err)))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
