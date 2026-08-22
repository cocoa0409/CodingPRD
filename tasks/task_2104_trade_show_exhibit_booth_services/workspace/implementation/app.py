"""Trade Show Exhibit Services API — Flask entry point.

The in-memory store starts empty on every boot: no entity is seeded, preloaded
or hardcoded. Every row a test needs is built through the declared API surface.
"""
import os
import threading
import traceback

from flask import Flask

import response
from errors import ApiError
from routes import (assets, booths, change_orders, claims, clock, crates, designs,
                    exhibitors, invoices, labor, leads, refurb, service_orders,
                    shipments, shows, venues, warehouses)

app = Flask(__name__)
app.url_map.strict_slashes = False

_LOCK = threading.RLock()


@app.before_request
def _acquire_lock():
    _LOCK.acquire()


@app.teardown_request
def _release_lock(exc=None):
    try:
        _LOCK.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def _handle_api_error(exc):
    return response.error(exc)


@app.errorhandler(404)
def _handle_404(exc):
    return response.error(ApiError("ERR_INVALID_REQUEST", "No such route"))


@app.errorhandler(405)
def _handle_405(exc):
    return response.error(ApiError("ERR_INVALID_REQUEST", "Method not allowed"))


@app.errorhandler(Exception)
def _handle_unexpected(exc):
    traceback.print_exc()
    return response.error(ApiError("ERR_INVALID_REQUEST", "Unexpected request failure"))


for module in (venues, warehouses, shows, exhibitors, booths, assets, designs,
               service_orders, crates, shipments, labor, change_orders, invoices,
               claims, refurb, leads, clock):
    app.register_blueprint(module.bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
