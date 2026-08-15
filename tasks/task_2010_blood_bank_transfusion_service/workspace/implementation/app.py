"""Blood Bank & Transfusion Service API — Flask entry point.

Reads PORT (default 10000), binds 0.0.0.0, runs in the foreground.
All state is in-memory and starts empty on every boot; the logical clock
starts at 2026-08-01T00:00:00Z (PRD 2.4).
"""

import os

from flask import Flask

import errors as E
from envelope import error_response
from errors import ApiError
from routes_admin import bp as admin_bp
from routes_supply import bp as supply_bp
from routes_clinical import bp as clinical_bp
from routes_quality import bp as quality_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(admin_bp)
app.register_blueprint(supply_bp)
app.register_blueprint(clinical_bp)
app.register_blueprint(quality_bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_not_found(_exc):
    return error_response(E.ERR_NOT_FOUND, "Route or resource not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(_exc):
    return error_response(E.ERR_NOT_FOUND, "Route or resource not found", 404)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)
    app.logger.exception("Unhandled error: %s", exc)
    return error_response("ERR_INTERNAL", f"Internal server error: {exc}", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
