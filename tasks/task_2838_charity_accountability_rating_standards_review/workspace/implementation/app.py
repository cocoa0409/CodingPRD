"""Charity Accountability Rating Standards Review API - entry point."""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import middleware
from errors import ApiError
from response import error_body

# importing the route modules registers every endpoint on middleware.ROUTES
from routes import (  # noqa: F401
    appeals,
    complaints,
    corrections,
    cycles,
    filings,
    governance,
    methodology,
    ops,
    organizations,
    publications,
)

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

middleware.attach(app)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return jsonify(error_body(exc.error_id, exc.message)), exc.http_status


@app.errorhandler(HTTPException)
def handle_http_error(exc):
    if exc.code == 404:
        return (
            jsonify(error_body("ERR_ORGANIZATION_NOT_FOUND", "Unknown resource.")),
            404,
        )
    if exc.code == 405:
        return (
            jsonify(error_body("ERR_INVALID_REQUEST", "Method not allowed here.")),
            405,
        )
    if exc.code in (400, 415):
        return (
            jsonify(error_body("ERR_INVALID_REQUEST", "Malformed request.")),
            400,
        )
    return (
        jsonify(error_body("ERR_INVALID_REQUEST", exc.description or "Request failed.")),
        exc.code or 500,
    )


@app.errorhandler(Exception)
def handle_unexpected(exc):
    app.logger.exception("unhandled error")
    return (
        jsonify(error_body("ERR_INVALID_REQUEST", "Unexpected server error.")),
        500,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
