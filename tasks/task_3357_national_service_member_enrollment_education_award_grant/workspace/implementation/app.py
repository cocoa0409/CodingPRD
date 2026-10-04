import os

from flask import Flask

import util
from errors import ApiError
from routes import (
    allowances,
    applications,
    awards,
    clock_routes,
    competitions,
    compliance,
    education,
    enrollments,
    grievances,
    hours,
    measures,
    members,
    organizations,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (
        clock_routes,
        organizations,
        competitions,
        applications,
        awards,
        members,
        enrollments,
        hours,
        allowances,
        education,
        compliance,
        grievances,
        measures,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return util.error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(_err):
        return util.error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_err):
        return util.error_response(
            "ERR_INVALID_REQUEST", "Method not allowed", 405
        )

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return util.error_response("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
    )
