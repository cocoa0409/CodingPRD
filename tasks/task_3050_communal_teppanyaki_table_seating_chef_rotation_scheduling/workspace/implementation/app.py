"""Entry point: error handlers and route registration.

Storage is in-memory only (see db.py) and nothing is seeded at startup: the
store boots empty so that every re-invocation of start.sh is a clean process.
"""
import os
import uuid

from flask import Flask
from werkzeug.exceptions import HTTPException

import db
import services as svc
from errors import APIError
from response import error_response

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------
@app.errorhandler(APIError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(exc):
    if isinstance(exc, HTTPException) and exc.description and exc.code == 404:
        return error_response("ERR_INVALID_REQUEST", "Unknown route.", 404)
    return error_response("ERR_INVALID_REQUEST", "Unknown route.", 404)


@app.errorhandler(405)
def handle_405(exc):
    return error_response("ERR_INVALID_REQUEST", "Method not allowed.", 405)


@app.errorhandler(HTTPException)
def handle_http_exception(exc):
    return error_response("ERR_INVALID_REQUEST", exc.description or "Bad request.",
                          exc.code or 400)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    return error_response("ERR_INVALID_REQUEST", str(exc), 400)


# ---------------------------------------------------------------------------
# Per-request deadline sweep so state reads consistently from any entry point
# ---------------------------------------------------------------------------
@app.before_request
def _before():
    try:
        svc.sweep_deadlines()
    except APIError:
        raise
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
import routes as route_package  # noqa: E402
route_package.register(app)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)