"""Renewable Land Origination API — application entry point.

Storage is in-memory only and nothing is ever seeded: every collection starts
empty on every boot and all state is created through the declared endpoints.
"""

import os
import threading

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from envelope import error
from errors import ERR_INVALID_REQUEST, ApiError
from routes import (
    bookings,
    clock,
    consents,
    corridors,
    crossings,
    curative,
    invoices,
    landowners,
    leases,
    options,
    parcels,
    payments,
    setback_rules,
)

# Registration order is immaterial: every rule lives on an explicit path.
BLUEPRINTS = (
    landowners.bp,
    parcels.bp,
    setback_rules.bp,
    consents.bp,
    curative.bp,
    options.bp,
    payments.bp,
    corridors.bp,
    crossings.bp,
    bookings.bp,
    leases.bp,
    invoices.bp,
    clock.bp,
)

_LOCK = threading.Lock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _serialise_request():
        # One request at a time: every cascade in this API reads and writes
        # several collections and must not interleave with another writer.
        _LOCK.acquire()
        g._lock_held = True

    @app.teardown_request
    def _release_request(exc=None):
        if g.pop("_lock_held", False):
            try:
                _LOCK.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        return error(ERR_INVALID_REQUEST, exc.description or exc.name,
                     exc.code or 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return error(ERR_INVALID_REQUEST, "Unexpected server error: %s" % exc,
                     500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
