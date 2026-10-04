"""Flask application entry point.

Boots cleanly from a fresh process on every invocation; the store is
in-memory only (db.py) and starts empty — no seeding of any kind.
"""
import os
from flask import Flask, request

from errors import ApiError
from response import error_response
from routes import (
    locations_bp,
    catalog_bp,
    customers_bp,
    stalls_bp,
    orders_bp,
    offers_bp,
    service_targets_bp,
    carhops_bp,
    runs_bp,
    tips_bp,
    flat_bp,
    clock_bp,
)

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(err):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.message, err.http_status)
    return error_response("ERR_INVALID_REQUEST", "Malformed request", 422)


for bp in (
    locations_bp,
    catalog_bp,
    customers_bp,
    stalls_bp,
    orders_bp,
    offers_bp,
    service_targets_bp,
    carhops_bp,
    runs_bp,
    tips_bp,
    flat_bp,
    clock_bp,
):
    app.register_blueprint(bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
