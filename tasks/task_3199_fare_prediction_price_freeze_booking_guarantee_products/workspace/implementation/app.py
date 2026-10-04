"""Entry point: blueprint registration, error rendering, launcher.

No entity is created here. The store starts empty on every boot; every test
builds its own preconditions through the declared API surface.
"""

import os

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from db import DB
from errors import ApiError
from response import error_body
from routes.fare import bp as fare_bp

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False
app.config["PROPAGATE_EXCEPTIONS"] = False
app.register_blueprint(fare_bp)


def _clock():
    return DB.clock


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return jsonify(error_body(exc, _clock())), exc.http_status


@app.errorhandler(HTTPException)
def handle_http_error(exc):
    if exc.code == 404:
        err = ApiError("ERR_RESOURCE_NOT_FOUND", "no such endpoint", 404)
    elif exc.code == 405:
        err = ApiError("ERR_INVALID_REQUEST", "method not allowed", 400)
    elif exc.code == 400:
        err = ApiError("ERR_INVALID_REQUEST", "malformed request", 400)
    else:
        err = ApiError("ERR_INVALID_REQUEST", exc.description or "request failed",
                       exc.code or 400)
    return jsonify(error_body(err, _clock())), err.http_status


@app.errorhandler(Exception)
def handle_unexpected(exc):
    err = ApiError("ERR_INVALID_REQUEST", "unexpected server error: %s" % exc, 400)
    return jsonify(error_body(err, _clock())), err.http_status


@app.before_request
def _reset_context():
    # Nothing is carried between requests; the store itself is process-local.
    pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)