"""Lab Consumable Service Contracts API — Flask entry point.

Mounts every route module under /lab, translates ApiError into the standard
error envelope, and binds 0.0.0.0:$PORT (default 10000) in the foreground.
"""
import os

from flask import Flask

from errors import ApiError
from response import api_error_response, error_response
from routes import (
    accounts,
    agreements,
    catalog,
    clock,
    contracts,
    engineers,
    instruments,
    loaners,
    orders,
    service_requests,
    surges,
)

app = Flask(__name__)

for module in (
    accounts,
    agreements,
    instruments,
    contracts,
    engineers,
    service_requests,
    loaners,
    catalog,
    orders,
    surges,
    clock,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def _handle_api_error(exc):
    return api_error_response(exc)


@app.errorhandler(404)
def _handle_not_found(_exc):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def _handle_method_not_allowed(_exc):
    return error_response("ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed")


@app.errorhandler(Exception)
def _handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return api_error_response(exc)
    return error_response("ERR_INTERNAL", 500, "Internal server error")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
