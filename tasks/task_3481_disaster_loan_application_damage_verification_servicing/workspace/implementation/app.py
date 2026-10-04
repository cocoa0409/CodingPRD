"""Entry point: Flask app, error handlers, the unprefixed clock endpoint."""

import os
import traceback

from flask import Flask

import clock as clock_mod
from auth import require_roles
from body import json_body, req_dt
from envelope import error_response, success
from errors import ApiError
from sweep import run_sweep
from timeutil import fmt_dt

import routes_applicants
import routes_applications
import routes_credit
import routes_decision
import routes_declarations
import routes_grants
import routes_loans
import routes_milestones
import routes_modifications
import routes_payments
import routes_receivables
import routes_servicing
import routes_settlements
import routes_tranches
import routes_verifications

app = Flask(__name__)

for module in (routes_applicants, routes_applications, routes_credit, routes_decision,
               routes_declarations, routes_grants, routes_loans, routes_milestones,
               routes_modifications, routes_payments, routes_receivables, routes_servicing,
               routes_settlements, routes_tranches, routes_verifications):
    app.register_blueprint(module.bp)


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
    traceback.print_exc()
    return error_response(ApiError("ERR_INVALID_REQUEST", 500, "internal error: %s" % err))


@app.post("/_clock/set_current_utc")
@require_roles("SystemAdmin")
def set_current_utc():
    """Set the logical clock and run the full time-driven sweep (PRD 2.4)."""
    data = json_body()
    dt = req_dt(data, "current_utc")
    clock_mod.set_current(dt)
    run_sweep()
    return success({"current_utc": fmt_dt(dt)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
