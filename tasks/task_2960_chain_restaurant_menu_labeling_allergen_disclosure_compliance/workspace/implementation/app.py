"""Chain-restaurant menu labeling and allergen disclosure compliance API.

Entry point: builds the Flask app, installs the request lifecycle (per-request
version bookkeeping, whole-store snapshot for atomic rollback, global
serialisation lock) and registers every route module.  The in-memory store
starts completely empty on every boot -- nothing is ever seeded.
"""

import os

from flask import Flask, g, request
from werkzeug.exceptions import HTTPException

import routes_board
import routes_enf
import routes_menu
import routes_read
import routes_registry
from core import LOCK, S, ApiError, error_envelope

app = Flask(__name__)
app.url_map.strict_slashes = False
try:
    app.json.sort_keys = False
except Exception:  # pragma: no cover - older Flask
    app.config["JSON_SORT_KEYS"] = False


# ---------------------------------------------------------------------------
# Request lifecycle
# ---------------------------------------------------------------------------

@app.before_request
def _begin_request():
    g.fresh_rows = set()
    g.marked = {}
    g.forced = set()
    g.lock_held = False
    g.snapshot = None
    LOCK.acquire()
    g.lock_held = True
    if request.method != "GET":
        g.snapshot = S.snapshot()


def _rollback():
    """PRD section 2.7: a rejected request leaves no partial state behind."""
    snapshot = getattr(g, "snapshot", None)
    if snapshot is not None:
        S.restore(snapshot)
        g.snapshot = None
    g.marked = {}
    g.forced = set()
    g.fresh_rows = set()


@app.teardown_request
def _end_request(exc):
    if getattr(g, "lock_held", False):
        g.lock_held = False
        try:
            LOCK.release()
        except RuntimeError:  # pragma: no cover
            pass


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def _handle_api_error(err):
    _rollback()
    return error_envelope(err.error_id, err.message, err.status)


@app.errorhandler(HTTPException)
def _handle_http_error(err):
    _rollback()
    if err.code == 404:
        return error_envelope("ERR_NOT_FOUND", "resource not found", 404)
    if err.code == 405:
        return error_envelope("ERR_METHOD_NOT_ALLOWED",
                              "method not allowed for this path", 405)
    if err.code == 400:
        return error_envelope("ERR_VALIDATION", "malformed request", 400)
    return error_envelope("ERR_REQUEST_FAILED", err.description or "request failed",
                          err.code or 500)


@app.errorhandler(Exception)
def _handle_unexpected(err):  # pragma: no cover
    _rollback()
    return error_envelope("ERR_INTERNAL", "internal server error", 500)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

routes_registry.register(app)
routes_menu.register(app)
routes_board.register(app)
routes_enf.register(app)
routes_read.register(app)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
