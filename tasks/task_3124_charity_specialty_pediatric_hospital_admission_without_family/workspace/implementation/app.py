"""Flask application entry point."""

import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes import (applications, billing, care_plans, clock, funds, grants,
                    hospitals, outreach, policies, programs,
                    referral_sources)

PREFIX = "/charity-care"


def create_app():
    app = Flask(__name__)

    for module in (clock, hospitals, programs, referral_sources, applications,
                   policies, billing, care_plans, grants, outreach, funds):
        app.register_blueprint(module.bp, url_prefix=PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_INVALID_REQUEST", 400,
                              "The requested path does not exist")

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_INVALID_REQUEST", 400,
                              "Method not allowed for this path")

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.http_status, err.message)
        app.logger.exception("Unexpected error: %s", err)
        return error_response("ERR_INVALID_REQUEST", 400, str(err))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
