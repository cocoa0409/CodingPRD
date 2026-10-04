"""App entry point: Flask app, error handlers, clock control, route registration."""
import os

from flask import Flask

import errors as E
import services as S
from db import STORE
from middleware import require_roles
from response import (ok_object, error_response, parse_dt, fmt_dt,
                      require_field, get_json_body)

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.errorhandler(E.ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(_err):
    return error_response(E.not_found("Resource not found"))


@app.errorhandler(405)
def handle_405(err):
    return error_response(E.ApiError("ERR_NOT_FOUND", "Resource not found", 404))


@app.errorhandler(Exception)
def handle_generic(err):
    if isinstance(err, E.ApiError):
        return error_response(err)
    return error_response(E.invalid_request(str(err)))


@app.post("/_clock/set_current_utc")
def set_clock():
    require_roles("HouseManager")
    body = get_json_body()
    to_iso8601 = require_field(body, "to_iso8601")
    dt = parse_dt(to_iso8601, "to_iso8601")
    STORE.clock = fmt_dt(dt)
    S.evaluate_clock_transitions()
    return ok_object({"current_utc": STORE.clock})


import routes_core
import routes_bookings
import routes_licenses
import routes_royalty
import routes_orders
import routes_reports
import routes_settlements
import routes_crew_capital

for module in (routes_core, routes_bookings, routes_licenses, routes_royalty,
               routes_orders, routes_reports, routes_settlements, routes_crew_capital):
    app.register_blueprint(module.bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
