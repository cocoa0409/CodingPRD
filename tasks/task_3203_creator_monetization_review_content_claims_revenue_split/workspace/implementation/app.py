"""Creator Monetization Claims API -- application entry point.

The store is in-memory only and starts empty on every boot: nothing is seeded,
preloaded or persisted.  A fresh `start.sh` invocation therefore wipes every
byte of state.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError, ERRORS
from response import error_body
from routes import register_routes

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

register_routes(app)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_body(exc.error_id, exc.message), exc.http_status


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, HTTPException):
        if exc.code == 404:
            return error_body("ERR_CHANNEL_NOT_FOUND", "No such resource."), 404
        if exc.code == 405:
            return error_body("ERR_INVALID_STATE", "Method not allowed."), 405
        return error_body("ERR_INVALID_STATE", exc.description or str(exc)), exc.code or 500
    app.logger.exception("unhandled error")
    return error_body("ERR_INVALID_STATE", str(exc)), 500


@app.after_request
def add_headers(response):
    response.headers["Content-Type"] = "application/json"
    return response


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)