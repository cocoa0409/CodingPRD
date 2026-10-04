"""Application entry point: app factory, error handlers, blueprint
registration. Storage is in-memory only and starts empty on every boot."""
import os
import traceback

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND
from response import error_response
from routes import (
    admin, certifications, fieldeval, inspections, licenses, manufacturers,
    projects, substitutions, withdrawals,
)

API_PREFIX = "/certification"

BLUEPRINTS = (
    admin.bp,
    manufacturers.bp,
    projects.bp,
    certifications.bp,
    substitutions.bp,
    inspections.bp,
    licenses.bp,
    fieldeval.bp,
    withdrawals.bp,
)


def create_app():
    app = Flask(__name__)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response(ApiError(ERR_NOT_FOUND, "resource not found"))

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response(ApiError(ERR_NOT_FOUND, "resource not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        traceback.print_exc()
        response, _status = error_response(ApiError(ERR_NOT_FOUND, str(err)))
        return response, 500

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
