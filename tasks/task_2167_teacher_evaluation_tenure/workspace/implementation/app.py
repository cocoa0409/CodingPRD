"""Teacher Evaluation & Tenure Progression API.

In-memory only.  Nothing is seeded at startup: every entity is created by
clients through the declared endpoints.
"""
import os
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_config
import routes_cycles
import routes_disputes
import routes_growth
import routes_observations
import routes_plans
import routes_reports
from errors import ApiError
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False
try:
    app.json.sort_keys = False
except Exception:  # pragma: no cover
    pass

# The store is a plain set of dicts; serialise request handling so that
# concurrent writes (optimistic-concurrency probes in particular) observe a
# consistent view.
_REQUEST_LOCK = threading.Lock()


@app.before_request
def _acquire_lock():
    _REQUEST_LOCK.acquire()


@app.teardown_request
def _release_lock(_exc=None):
    try:
        _REQUEST_LOCK.release()
    except RuntimeError:  # pragma: no cover - never acquired
        pass

routes_config.register(app)
routes_cycles.register(app)
routes_observations.register(app)
routes_growth.register(app)
routes_plans.register(app)
routes_disputes.register(app)
routes_reports.register(app)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.http_status, exc.message)


@app.errorhandler(HTTPException)
def handle_http_exception(exc):
    if exc.code == 404:
        return error_response("ERR_RESOURCE_NOT_FOUND", 404, "The requested route does not exist.")
    if exc.code in (400, 405, 415):
        return error_response("ERR_INVALID_REQUEST", 400, "The request could not be processed.")
    return error_response("ERR_INVALID_REQUEST", exc.code or 500,
                          exc.description or "Request failed.")


@app.errorhandler(Exception)
def handle_unexpected(exc):  # pragma: no cover - defensive
    return error_response("ERR_INVALID_REQUEST", 500, "Internal error: %s" % exc)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
