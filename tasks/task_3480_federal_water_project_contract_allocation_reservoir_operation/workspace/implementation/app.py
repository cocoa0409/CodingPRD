"""Federal Water Allocation API — entry point.

Mounts every domain blueprint plus the single unprefixed logical-clock
endpoint POST /_clock/set_current_utc (PRD section 2.4). The store is pure
in-memory and starts empty on every boot; nothing is seeded.
"""
import os

from flask import Flask

from envelope import error_response, success
from errors import ApiError

app = Flask(__name__, static_folder=None)
app.url_map.strict_slashes = False

import routes_agreements
import routes_announce
import routes_compliance
import routes_deliveries
import routes_districts
import routes_releases
import routes_reservoir
import routes_revenue
import routes_reviews
import routes_transfers
import routes_years

for _module in (
        routes_districts,
        routes_years,
        routes_announce,
        routes_reservoir,
        routes_releases,
        routes_compliance,
        routes_deliveries,
        routes_revenue,
        routes_transfers,
        routes_reviews,
        routes_agreements,
):
    app.register_blueprint(_module.bp)


@app.post("/_clock/set_current_utc")
def set_logical_clock():
    """Unprefixed test-driving clock; SystemAdmin only; mutates nothing else."""
    from auth import authenticate
    from store import set_clock
    from validate import as_datetime, get_body, required

    authenticate(["SystemAdmin"])
    body = get_body()
    current = required(body, "current_utc")
    parsed = as_datetime(current, "current_utc")
    set_clock(parsed)
    return success({"current_utc": current}, 200)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_not_found(_err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "resource not found"))


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    return error_response(ApiError("ERR_INTERNAL", 500, "internal error: " + str(err)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
