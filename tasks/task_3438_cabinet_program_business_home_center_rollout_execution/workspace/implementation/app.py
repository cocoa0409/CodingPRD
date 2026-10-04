"""Cabinet Program Rollout API — Flask entry point.

Mounts every cabinet-domain blueprint plus the unprefixed logical-clock
endpoint (PRD 2.4), and renders the PRD 2.2 envelope for all errors.
"""
import os

from flask import Flask

from auth import get_body, require_roles
from db import store
from envelope import err, ok
from errors import ApiError, api_error
from routes_accounts import bp as accounts_bp
from routes_claims import bp as claims_bp
from routes_design import bp as design_bp
from routes_finishes import bp as finishes_bp
from routes_orders import bp as orders_bp
from routes_programs import bp as programs_bp
from routes_resets import bp as resets_bp
from routes_shipments import bp as shipments_bp
from routes_slots import bp as slots_bp
from util import format_clock, parse_dt

app = Flask(__name__)

for blueprint in (accounts_bp, programs_bp, finishes_bp, slots_bp, design_bp,
                  orders_bp, shipments_bp, claims_bp, resets_bp):
    app.register_blueprint(blueprint)


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    """The sole endpoint outside the /cabinet prefix; PlatformAdmin only."""
    require_roles("PlatformAdmin")
    body = get_body()
    to_iso = body.get("to_iso8601")
    if to_iso is None:
        raise api_error("ERR_INVALID_REQUEST", "to_iso8601 is required")
    parsed = parse_dt(to_iso)
    if parsed is None:
        raise api_error("ERR_INVALID_REQUEST",
                        "to_iso8601 must be an ISO 8601 datetime")
    store.clock = parsed
    return ok({"current_utc": format_clock(store.clock)})


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return err(exc.error_id, exc.status, exc.message)


@app.errorhandler(404)
def handle_not_found(_exc):
    return err("ERR_NOT_FOUND", 404, "resource not found")


@app.errorhandler(405)
def handle_method_not_allowed(_exc):
    return err("ERR_NOT_FOUND", 404, "resource not found")


@app.errorhandler(Exception)
def handle_unexpected(exc):
    return err("ERR_INTERNAL", 500, "internal error: {}".format(exc))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
