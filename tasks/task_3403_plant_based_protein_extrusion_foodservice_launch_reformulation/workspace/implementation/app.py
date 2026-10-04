# Entry point: Flask app factory, error handlers, blueprint registration.
# The store starts empty on every boot; nothing is seeded at startup.
import os

from flask import Flask

from errors import ApiError, err
from response import error_response

import routes_batches
import routes_clock
import routes_forecasts
import routes_labels
import routes_lines
import routes_lots
import routes_products
import routes_programs
import routes_runs
import routes_suppliers
import routes_writedowns


def create_app():
    app = Flask(__name__)

    app.register_blueprint(routes_clock.bp)
    app.register_blueprint(routes_suppliers.bp)
    app.register_blueprint(routes_lots.bp)
    app.register_blueprint(routes_lines.bp)
    app.register_blueprint(routes_products.bp)
    app.register_blueprint(routes_labels.bp)
    app.register_blueprint(routes_labels.bp_nested)
    app.register_blueprint(routes_runs.bp)
    app.register_blueprint(routes_programs.bp)
    app.register_blueprint(routes_batches.bp)
    app.register_blueprint(routes_forecasts.bp)
    app.register_blueprint(routes_writedowns.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def handle_not_found(e):
        return error_response(err("ERR_NOT_FOUND", "resource not found"))

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return error_response(err("ERR_NOT_FOUND", "method not allowed"))

    @app.errorhandler(500)
    def handle_internal_error(e):
        return error_response(err("ERR_INVALID_REQUEST", "internal error"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
