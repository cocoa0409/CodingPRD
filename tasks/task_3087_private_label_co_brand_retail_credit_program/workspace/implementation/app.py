"""Private-label retail credit program servicing API — application entry point.

Everything lives in memory; nothing is seeded at boot. The server binds
0.0.0.0:$PORT (default 10000) and runs in the foreground.
"""
import os

from flask import Flask, jsonify, request

from core.envelope import _meta
from core.errors import ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND, ApiError
from routes import register_routes

app = Flask(__name__)
app.url_map.strict_slashes = False
register_routes(app)


def _error_body(error_id: str, message: str):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


@app.errorhandler(ApiError)
def handle_api_error(error: ApiError):
    return jsonify(_error_body(error.error_id, error.message)), error.http_status


@app.errorhandler(404)
def handle_not_found(_):
    return jsonify(_error_body(ERR_RESOURCE_NOT_FOUND,
                               "The requested path does not resolve to a resource.")), 404


@app.errorhandler(405)
def handle_method_not_allowed(_):
    return jsonify(_error_body(ERR_INVALID_REQUEST,
                               "The HTTP method is not supported for this path.")), 400


@app.errorhandler(Exception)
def handle_unexpected(error: Exception):
    if isinstance(error, ApiError):
        return jsonify(_error_body(error.error_id, error.message)), error.http_status
    return jsonify(_error_body(ERR_INVALID_REQUEST,
                               f"Malformed request: {error}")), 400


@app.before_request
def _reject_malformed_json():
    """A body that is not well-formed JSON is a malformed request (PRD §3.4)."""
    if request.method in ("POST", "PUT", "PATCH") and request.content_length:
        if request.get_json(silent=True) is None:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "The request body must be well-formed JSON.")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)