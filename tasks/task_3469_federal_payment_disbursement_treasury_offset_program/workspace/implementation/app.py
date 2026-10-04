"""Application entry point: blueprint registration and error handling.

The API is mounted at the service root with no versioned path prefix
(SCAFFOLD api_prefix is ""). All 40 PRD §4 routes live in routes/ modules.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response
from routes import (
    agreements,
    clock,
    collections,
    creditors,
    debts,
    dnp,
    offsets,
    payees,
    payment_files,
    payments,
    policies,
    refunds,
    reverse,
)


def create_app():
    # static_folder=None: the surface is exactly the 40 PRD §4 routes, nothing
    # else (Flask would otherwise register a default /static/<path> route).
    app = Flask(__name__, static_folder=None)

    for module in (
        clock,
        creditors,
        payees,
        policies,
        debts,
        payment_files,
        payments,
        offsets,
        refunds,
        collections,
        reverse,
        agreements,
        dnp,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        if isinstance(err, HTTPException):
            status = err.code or 500
            error_id = {
                400: ERR_INVALID_REQUEST,
                404: ERR_NOT_FOUND,
                405: ERR_NOT_FOUND,
            }.get(status, "ERR_INTERNAL")
            return error_response(ApiError(error_id, status, err.name))
        return error_response(ApiError("ERR_INTERNAL", 500, "Internal server error"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
    )
