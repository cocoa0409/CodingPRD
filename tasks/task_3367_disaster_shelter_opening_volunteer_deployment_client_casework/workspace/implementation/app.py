"""Disaster Shelter Opening, Volunteer Deployment & Client Casework API.

Flask entry point: blueprint registration, error envelope handlers and the
per-request lock that keeps the single-process in-memory store consistent.
The store starts empty on every boot; nothing is seeded here.
"""

import os
import sys
import threading

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import auto
import core
from core import error_response

import routes_blood
import routes_case
import routes_client
import routes_region
import routes_shelter
import routes_site
import routes_volunteer

app = Flask(__name__)
app.url_map.strict_slashes = False

_REQUEST_LOCK = threading.RLock()

for module in (routes_region, routes_site, routes_shelter, routes_volunteer,
               routes_client, routes_case, routes_blood):
    app.register_blueprint(module.bp)


@app.before_request
def _before_request():
    _REQUEST_LOCK.acquire()
    g.lock_held = True
    # Clock-driven automatic transitions are evaluated to a fixed point on
    # every read and every write (PRD 2.10).
    try:
        auto.sweep()
    except Exception as exc:  # never let the sweep break request handling
        sys.stderr.write("automatic sweep failed: %r\n" % (exc,))


@app.teardown_request
def _teardown_request(_exc):
    if getattr(g, "lock_held", False):
        g.lock_held = False
        try:
            _REQUEST_LOCK.release()
        except RuntimeError:
            pass


@app.errorhandler(core.ApiError)
def _handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def _handle_http_error(exc):
    return error_response("ERR_INVALID_REQUEST", exc.description or "invalid request",
                          exc.code or 400)


@app.errorhandler(Exception)
def _handle_unexpected(exc):
    return error_response("ERR_INVALID_REQUEST", "internal error: %s" % (exc,), 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)
