"""The Flask application object and its error handlers.

This lives in its own module so that every route module imports exactly the
same app instance whether the server is started as `python3 app.py` or imported
programmatically.  Creating the Flask object inside `app.py` would give it the
module name "__main__" when run as a script and register a *second* app object
whose routes the running server never sees.
"""

from flask import Flask, jsonify

import response
from errors import ApiError, ERR_INVALID_REQUEST

app = Flask(__name__)
# PRD section 4: paths under /api are also reachable with a trailing slash.
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def handle_api_error(err):
    return jsonify(response.error_body(err, err.http_status)), err.http_status


@app.errorhandler(404)
def handle_not_found(err):
    # The mount point serves its default error shape as a JSON envelope rather
    # than as an HTML document.
    body = response.error_body(
        ApiError(ERR_INVALID_REQUEST, "No route matches the requested URL"), 404
    )
    return jsonify(body), 404


@app.errorhandler(405)
def handle_method_not_allowed(err):
    body = response.error_body(
        ApiError(ERR_INVALID_REQUEST, "HTTP method not allowed for this URL"), 405
    )
    return jsonify(body), 405


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return handle_api_error(err)
    body = response.error_body(
        ApiError(ERR_INVALID_REQUEST, str(err) or "invalid request"), 400
    )
    return jsonify(body), 400


@app.route("/health", methods=["GET"])
def health():
    """Liveness probe used by the boot smoke test."""
    return jsonify({"meta": {"status": "ok"}, "response_type": "object", "data": {}}), 200