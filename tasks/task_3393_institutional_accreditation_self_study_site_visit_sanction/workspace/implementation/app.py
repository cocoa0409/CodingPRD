"""Entry point: Flask app factory, blueprint registration, error handlers."""
import os

from flask import Flask

from errors import ApiError
from response import error_envelope

import routes_arguments
import routes_changes
import routes_clock
import routes_cycles
import routes_eligibility
import routes_indicators
import routes_institutions
import routes_outcomes
import routes_panels
import routes_reviewers
import routes_teams


def create_app():
    app = Flask(__name__)
    for module in (routes_institutions, routes_eligibility, routes_cycles,
                   routes_arguments, routes_reviewers, routes_teams,
                   routes_panels, routes_outcomes, routes_changes,
                   routes_indicators, routes_clock):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_envelope(err)

    @app.errorhandler(404)
    def handle_not_found(err):
        from errors import ERR_VALIDATION
        return error_envelope(ApiError("ERR_NOT_FOUND", 404, "Unknown route"))

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_envelope(ApiError("ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed"))

    @app.errorhandler(500)
    def handle_internal_error(err):
        return error_envelope(ApiError("ERR_INTERNAL", 500, "Internal server error"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
