"""Connected Fitness Hardware API — Flask entry point.

The store starts completely empty on every boot.  Nothing is seeded, preloaded
or registered here: every entity any test needs is built through the declared
API surface.  start.sh re-launches this process before every per-test run, so a
fresh interpreter is also a fresh, empty store.
"""

import os

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import api

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False
app.register_blueprint(api)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def handle_http_error(exc):
    """Framework-level failures map onto ERR_INVALID_REQUEST / ERR_RESOURCE_NOT_FOUND."""
    if exc.code == 404:
        return error_response(
            "ERR_RESOURCE_NOT_FOUND",
            "No handler is registered for this method and path.",
            404,
        )
    if exc.code == 405:
        return error_response(
            "ERR_INVALID_REQUEST",
            "This method is not supported for the addressed path.",
            400,
        )
    if exc.code and 400 <= exc.code < 500:
        return error_response(
            "ERR_INVALID_REQUEST",
            exc.description or "The request could not be processed.",
            400,
        )
    return error_response("ERR_INVALID_REQUEST", "The request could not be processed.", 400)


@app.after_request
def ensure_json_envelope(response):
    """Every API response carries the envelope, including framework-level ones."""
    if response.status_code >= 500 and not request.path.startswith("/health"):
        return error_response(
            "ERR_INVALID_REQUEST",
            "The request could not be processed.",
            response.status_code,
        )
    return response


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        debug=False,
        use_reloader=False,
    )