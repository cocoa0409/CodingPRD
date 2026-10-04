"""Entry point: Flask app assembly, error handlers, route registration."""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError

import routes_accounts
import routes_catalog
import routes_clock
import routes_contracts
import routes_forecasts
import routes_instruments
import routes_licenses
import routes_lots
import routes_orders
import routes_programs
import routes_runs
import routes_transitions

app = Flask(__name__)

for module in (
    routes_accounts,
    routes_catalog,
    routes_clock,
    routes_contracts,
    routes_forecasts,
    routes_instruments,
    routes_licenses,
    routes_lots,
    routes_orders,
    routes_programs,
    routes_runs,
    routes_transitions,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(HTTPException)
def handle_http_error(err):
    # Unknown paths / methods still answer in the standard error envelope.
    if err.code == 404:
        mapped = ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    elif err.code == 405:
        mapped = ApiError("ERR_INVALID_REQUEST", 405, "Method not allowed")
    elif err.code == 400:
        mapped = ApiError("ERR_INVALID_REQUEST", 400, "Malformed request")
    else:
        mapped = ApiError("ERR_INVALID_REQUEST", err.code or 500, err.name)
    return error_response(mapped)


@app.errorhandler(Exception)
def handle_unexpected(err):
    mapped = ApiError("ERR_INTERNAL", 500, "Internal server error")
    return error_response(mapped)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
