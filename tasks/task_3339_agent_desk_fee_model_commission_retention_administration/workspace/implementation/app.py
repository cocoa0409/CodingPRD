"""App entry point: blueprint registration, clock endpoint, error handlers."""
import os

from flask import Flask, request

import clock
from clock import parse, fmt
from response import ApiError, error, ok, err_invalid_request, err_not_found
from auth import require_roles
from helpers import reevaluate

import routes_offices
import routes_schedules
import routes_agents
import routes_assignments
import routes_offers
import routes_transactions
import routes_cdas
import routes_invoices
import routes_ledger

app = Flask(__name__)

for bp in (
    routes_offices.bp,
    routes_schedules.bp,
    routes_agents.bp,
    routes_assignments.bp,
    routes_offers.bp,
    routes_transactions.bp,
    routes_cdas.bp,
    routes_invoices.bp,
    routes_ledger.bp,
):
    app.register_blueprint(bp)


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    current_utc = body.get("current_utc")
    dt = parse(current_utc)
    if dt is None:
        raise err_invalid_request("current_utc must be an ISO-8601 timestamp")
    clock.set_clock(dt)
    reevaluate()
    return ok({"current_utc": fmt(dt)})


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error(err)


@app.errorhandler(404)
def handle_404(_e):
    return error(err_not_found("Route not found"))


@app.errorhandler(405)
def handle_405(_e):
    return error(err_not_found("Method not allowed"))


@app.errorhandler(Exception)
def handle_exception(err):
    if isinstance(err, ApiError):
        return error(err)
    return error(ApiError("ERR_INVALID_REQUEST", 400, str(err)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
