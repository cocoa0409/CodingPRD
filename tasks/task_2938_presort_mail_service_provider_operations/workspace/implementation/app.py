"""Presort mail service provider operations API.

Boots a completely empty in-memory store on every process start: nothing is
seeded, nothing is persisted, and the logical clock reads its documented
default until a BureauAdmin moves it.
"""

import os
import sys
import threading
import traceback

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import routes_batches
import routes_clients
import routes_facilities
import routes_jobs
import routes_misc
import routes_permits
import routes_shipments
import routes_statements
from envelope import error_body
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

for module in (
    routes_clients,
    routes_permits,
    routes_jobs,
    routes_facilities,
    routes_batches,
    routes_misc,
    routes_shipments,
    routes_statements,
):
    app.register_blueprint(module.bp)


# One writer at a time: every request is a serialized transaction over the
# in-memory store, so no partial cascade can ever be observed.
_LOCK = threading.Lock()


@app.before_request
def _acquire_lock():
    _LOCK.acquire()
    g._store_lock_held = True


@app.teardown_request
def _release_lock(_exception=None):
    if g.pop("_store_lock_held", False):
        _LOCK.release()


@app.errorhandler(ApiError)
def _handle_api_error(error):
    return error_body(error.error_id, error.message), error.http_status


@app.errorhandler(HTTPException)
def _handle_http_exception(error):
    return (
        error_body("ERR_INVALID_REQUEST", error.description or "Invalid request."),
        400,
    )


@app.errorhandler(Exception)
def _handle_unexpected(error):  # pragma: no cover - defensive
    traceback.print_exc(file=sys.stderr)
    return error_body("ERR_INVALID_REQUEST", "Unhandled server error: %s" % error), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
