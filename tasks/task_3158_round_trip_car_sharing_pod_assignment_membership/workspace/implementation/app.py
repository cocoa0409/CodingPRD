"""Flask application entry point.

The store starts empty on every boot: nothing is seeded, preloaded or
hardcoded. Every entity a test needs is constructed through the declared API
surface below.
"""

import os

from flask import Flask

from db import STORE
from errors import ApiError
from response import error_body

import routes.members as r_members
import routes.accounts as r_accounts
import routes.memberships as r_memberships
import routes.pods as r_pods
import routes.vehicles as r_vehicles
import routes.reservations as r_reservations
import routes.incidents as r_incidents
import routes.maintenance as r_maintenance
import routes.access as r_access
import routes.fuel as r_fuel
import routes.signals as r_signals
import routes.testing as r_testing

app = Flask(__name__)
app.url_map.strict_slashes = False

MODULES = (
    r_members, r_accounts, r_memberships, r_pods, r_vehicles, r_reservations,
    r_incidents, r_maintenance, r_access, r_fuel, r_signals, r_testing,
)


for module in MODULES:
    module.register(app)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_body(exc.error_id, exc.message), exc.http_status


@app.errorhandler(404)
def handle_not_found(exc):
    return error_body("ERR_INVALID_REQUEST", "No route matches this request."), 404


@app.errorhandler(405)
def handle_method(exc):
    return error_body("ERR_INVALID_REQUEST", "This method is not allowed here."), 405


@app.errorhandler(500)
def handle_server_error(exc):  # pragma: no cover - defensive
    return error_body("ERR_INVALID_REQUEST", "The server encountered an error."), 500


def boot():
    """Wipe every byte of process state so a re-invoked start.sh is a fresh boot."""
    STORE.reset()


if __name__ == "__main__":
    boot()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)