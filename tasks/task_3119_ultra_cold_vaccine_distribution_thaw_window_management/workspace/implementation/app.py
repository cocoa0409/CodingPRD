"""Ultra Cold Vaccine Distribution API - entry point.

The store is in-memory and process-local.  Nothing is persisted, nothing is
seeded: every entity is created by a client call against a declared endpoint.
"""
import os
import sys
import uuid

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from errors import ApiError, HTTP_BY_ERROR  # noqa: E402
import response as R  # noqa: E402
from routes import (  # noqa: E402
    reference, supply, allocation, custody, review, ops,
)

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

for module in (reference, supply, allocation, custody, review, ops):
    app.register_blueprint(module.bp, url_prefix="/vaccine-distribution")


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return R.fail(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def handle_http_error(exc):
    if exc.code == 404:
        return R.fail("ERR_RESOURCE_NOT_FOUND", "The requested route does not exist.", 404)
    return R.fail("ERR_INVALID_REQUEST", exc.description or "Bad request.", exc.code or 400)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    app.logger.exception("unhandled error")
    return R.fail("ERR_INVALID_REQUEST", "The request could not be completed.", 400)


@app.route("/", methods=["GET"])
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)