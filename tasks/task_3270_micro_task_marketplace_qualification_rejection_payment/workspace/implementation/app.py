"""Micro-Task Marketplace API - application entry point.

Mounted at /mkt. Storage is in-memory only; the store starts empty on every
boot and every entity is constructed through the declared API surface.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error as error_body
from routes.assignments import bp as assignments_bp
from routes.hits import bp as hits_bp
from routes.payouts import bp as payouts_bp
from routes.requesters import bp as requesters_bp
from routes.workers import bp as workers_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(requesters_bp)
app.register_blueprint(workers_bp)
app.register_blueprint(hits_bp)
app.register_blueprint(assignments_bp)
app.register_blueprint(payouts_bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_body(exc.error_id, exc.message), exc.http_status


@app.errorhandler(HTTPException)
def handle_http_error(exc):
    """Render framework-level failures inside the standard error envelope."""
    if exc.code == 404:
        return error_body("ERR_NOT_FOUND", "The requested path does not exist."), 404
    if exc.code == 405:
        return error_body("ERR_INVALID_REQUEST", "Method not allowed for this path."), 405
    if exc.code in (400, 415, 422):
        return error_body("ERR_INVALID_REQUEST", "Malformed request body."), 400
    return error_body("ERR_INVALID_REQUEST", exc.description or "Request failed."), exc.code


@app.errorhandler(Exception)
def handle_unexpected(exc):
    """Never leak a stack trace: any unhandled fault surfaces as a 400 envelope."""
    if isinstance(exc, ApiError):
        return error_body(exc.error_id, exc.message), exc.http_status
    if isinstance(exc, HTTPException):
        return handle_http_error(exc)
    return error_body("ERR_INVALID_REQUEST", "Malformed or unusable request body."), 400


@app.get("/health")
def health():
    return {"status": "ok"}, 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))