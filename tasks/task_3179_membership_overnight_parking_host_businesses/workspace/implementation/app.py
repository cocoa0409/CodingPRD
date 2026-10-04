"""Entry point: the Flask application, error handlers and the boot-time reset.

The store starts empty on every boot -- nothing is seeded, preloaded or
hardcoded here.  The logical clock starts at 2026-09-01T00:00:00Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
import store
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["PROPAGATE_EXCEPTIONS"] = False
app.config["JSON_SORT_KEYS"] = False

from routes import api  # noqa: E402  (registered after the app exists)

app.register_blueprint(api)


@app.errorhandler(ApiError)
def handle_api_error(error):
    body, status = envelope.error_body(error)
    return body, status, {"Content-Type": "application/json"}


@app.errorhandler(HTTPException)
def handle_http_error(error):
    mapping = {
        400: "ERR_INVALID_REQUEST",
        401: "ERR_UNAUTHENTICATED",
        403: "ERR_UNAUTHORIZED",
        404: "ERR_RESOURCE_NOT_FOUND",
        405: "ERR_RESOURCE_NOT_FOUND",
        409: "ERR_INVALID_STATE",
        412: "ERR_STALE_HOST_VERSION",
        415: "ERR_INVALID_REQUEST",
        422: "ERR_INVALID_REQUEST",
    }
    error_id = mapping.get(error.code, "ERR_INVALID_REQUEST")
    body, status = envelope.error_body(ApiError(error_id, error.description))
    return body, status, {"Content-Type": "application/json"}


@app.errorhandler(Exception)
def handle_unexpected(error):
    if isinstance(error, ApiError):
        body, status = envelope.error_body(error)
        return body, status, {"Content-Type": "application/json"}
    body, status = envelope.error_body(
        ApiError("ERR_INVALID_REQUEST", "The request could not be processed.")
    )
    return body, status, {"Content-Type": "application/json"}


@app.before_request
def _fresh_boot_guard():
    """Nothing to do per request; the store is emptied once, at import time."""
    return None


# Every fresh process starts with empty tables and the boot clock instant.
store.reset()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        use_reloader=False,
    )