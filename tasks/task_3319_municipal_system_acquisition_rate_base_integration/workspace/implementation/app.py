"""Flask entry point. Registers blueprints, converts ApiError into the
standard error envelope, and runs the dev server on $PORT (default 10000).
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response

import routes_clock
import routes_targets
import routes_assessments
import routes_capital_items
import routes_valuation
import routes_council
import routes_regulatory
import routes_accounts
import routes_transitions
import routes_employees
import routes_tariffs


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    for module in (routes_clock, routes_targets, routes_assessments,
                   routes_capital_items, routes_valuation, routes_council,
                   routes_regulatory, routes_accounts, routes_transitions,
                   routes_employees, routes_tariffs):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(ApiError("ERR_INVALID_REQUEST", 422, str(err)))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
