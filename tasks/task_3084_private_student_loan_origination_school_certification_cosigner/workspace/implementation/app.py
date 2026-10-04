"""Entry point: registers every route blueprint and the error handlers.

Boots from a fresh process with an empty in-memory store. No entity is seeded
or preloaded here.
"""

import os
import re

from flask import Flask, request
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_body
from routes import reference, applications, loans, releases

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

app.register_blueprint(reference.bp)
app.register_blueprint(applications.bp)
app.register_blueprint(loans.bp)
app.register_blueprint(releases.bp)


@app.route("/health", methods=["GET"])
def health():
    from response import object_body
    return object_body({"status": "ok"})


@app.route("/", methods=["GET"])
def root():
    from response import object_body
    return object_body({"service": "private-student-loans"})


@app.errorhandler(ApiError)
def handle_api_error(exc):
    body, status = error_body(exc.error_id, exc.message, exc.http_status)
    return body, status


@app.errorhandler(HTTPException)
def handle_http_error(exc):
    if exc.code == 405:
        body, status = error_body("ERR_INVALID_REQUEST", "method not allowed", 405)
        return body, status
    if exc.code == 404:
        body, status = error_body("ERR_INVALID_REQUEST", "resource not found", 404)
        return body, status
    body, status = error_body("ERR_INVALID_REQUEST", exc.description or "bad request",
                              exc.code or 400)
    return body, status


@app.errorhandler(Exception)
def handle_unexpected(exc):
    body, status = error_body("ERR_INVALID_REQUEST", str(exc), 500)
    return body, status


def _normalize_uuid_segment(path):
    """Replace a UUID typed in the wrong case/format is not needed; UUIDs are
    matched as plain strings by the routing rules."""
    return path


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)