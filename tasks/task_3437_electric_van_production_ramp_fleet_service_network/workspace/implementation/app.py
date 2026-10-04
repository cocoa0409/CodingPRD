"""Electric Van Fleet Ops API — entry point.

Mounts every resource under /evfleet except the logical-clock test-driving
endpoint POST /_clock/set_current_utc, which is deliberately unprefixed.
"""

import os

from flask import Flask

import store
import util
from errors import ApiError
import errors as E

app = Flask(__name__)
app.json.sort_keys = False


@app.post("/_clock/set_current_utc")
def set_current_utc():
    """Advance the server's logical clock; mutates no entity. Returns 200."""
    _, role = util.auth()
    util.require_role(role, {"PlatformAdmin"})
    b = util.body()
    raw = util.as_str(util.req_field(b, "to_iso8601"), "to_iso8601")
    dt = util.parse_dt(raw, "to_iso8601")
    store.DB.clock = dt
    return util.ok({"current_utc": store.fmt_dt(dt)}, 200)


from routes_customers import bp as customers_bp
from routes_depots_charging import bp as depots_charging_bp
from routes_suppliers_modules import bp as suppliers_modules_bp
from routes_orders import bp as orders_bp
from routes_vehicles import bp as vehicles_bp
from routes_service import bp as service_bp
from routes_visits import bp as visits_bp
from routes_software import bp as software_bp
from routes_warranty import bp as warranty_bp
from routes_uptime import bp as uptime_bp

for _bp in (customers_bp, depots_charging_bp, suppliers_modules_bp, orders_bp,
            vehicles_bp, service_bp, visits_bp, software_bp, warranty_bp,
            uptime_bp):
    app.register_blueprint(_bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return util.err_response(e)


@app.errorhandler(404)
def handle_not_found(e):
    return util.err_response(ApiError(E.ERR_NOT_FOUND, 404, "resource not found"))


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return util.err_response(ApiError(E.ERR_NOT_FOUND, 404, "resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(e):
    return util.err_response(ApiError("ERR_INTERNAL", 500, str(e)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
