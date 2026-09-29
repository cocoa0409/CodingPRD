"""Reentry Employment Services API — Flask application entry point.

Storage is in-memory only and nothing is ever seeded: every boot starts with ten
empty collections and the logical clock parked at 2026-08-01T00:00:00Z.
"""

import os
import sys
import threading
import traceback

from flask import Flask, g, request
from werkzeug.exceptions import HTTPException

from envelope import error_response, ok
from errors import ApiError
from store import begin_request, db, fmt_instant
from validation import body, req_instant

from routes_participants import bp as participants_bp
from routes_supervision import bp as supervision_bp
from routes_partnerships import bp as partnerships_bp
from routes_grants import bp as grants_bp
from routes_placements import bp as placements_bp
from routes_sessions import bp as sessions_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

_request_lock = threading.RLock()

CLOCK_PATH = "/_clock/set_current_utc"


@app.before_request
def _serialize_and_authenticate():
    _request_lock.acquire()
    g._holds_lock = True
    begin_request()
    if request.path.rstrip("/") == CLOCK_PATH:
        return None
    user_id = request.headers.get("X-User-ID")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED",
                       "A recognised X-User-ID header is required")
    return None


@app.teardown_request
def _release(_exception=None):
    if getattr(g, "_holds_lock", False):
        g._holds_lock = False
        try:
            _request_lock.release()
        except RuntimeError:
            pass


@app.errorhandler(ApiError)
def _handle_api_error(error):
    return error_response(error.error_id, error.message, error.http_status)


@app.errorhandler(HTTPException)
def _handle_http_error(error):
    status = error.code or 500
    if status == 404:
        return error_response("ERR_VALIDATION", "Unknown resource path", 404)
    if status == 405:
        return error_response("ERR_VALIDATION",
                              "Method not allowed on this path", 405)
    return error_response("ERR_VALIDATION", error.description or "Bad request",
                          status)


@app.errorhandler(Exception)
def _handle_unexpected(error):
    traceback.print_exc(file=sys.stderr)
    return error_response("ERR_VALIDATION", "Unexpected server error: %s" % error,
                          500)


@app.post(CLOCK_PATH)
def set_current_utc():
    payload = body()
    instant = req_instant(payload, "current_utc")
    db.clock = instant
    return ok({"current_utc": fmt_instant(instant)})


app.register_blueprint(participants_bp)
app.register_blueprint(supervision_bp)
app.register_blueprint(partnerships_bp)
app.register_blueprint(grants_bp)
app.register_blueprint(placements_bp)
app.register_blueprint(sessions_bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
