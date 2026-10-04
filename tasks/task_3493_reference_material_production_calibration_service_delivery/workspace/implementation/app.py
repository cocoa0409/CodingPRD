"""Application entry point: blueprint registration and error handlers.

The store starts empty on every boot; nothing is seeded. All state arrives
through the API surface.
"""

import os

from flask import Flask

from routes_certificates import bp as certificates_bp
from routes_clock import bp as clock_bp
from routes_calibration import bp as calibration_bp
from routes_lots import bp as lots_bp
from routes_methods import bp as methods_bp
from routes_programs import bp as programs_bp
from routes_pt import bp as pt_bp
from routes_sales import bp as sales_bp
from util import (
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ApiError,
    error_response,
)


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False

    for bp in (
        programs_bp,
        lots_bp,
        methods_bp,
        certificates_bp,
        sales_bp,
        calibration_bp,
        pt_bp,
        clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _not_found(_err):
        return error_response(ApiError(ERR_NOT_FOUND, 404, "resource not found"))

    @app.errorhandler(405)
    def _method_not_allowed(_err):
        return error_response(
            ApiError(ERR_INVALID_REQUEST, 400, "method not allowed")
        )

    @app.errorhandler(Exception)
    def _unexpected(err):
        return error_response(
            ApiError("ERR_INTERNAL", 500, "internal error: {}".format(err))
        )

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
