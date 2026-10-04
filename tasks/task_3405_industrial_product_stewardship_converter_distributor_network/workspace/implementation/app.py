"""Application entrypoint: blueprint registration and error handlers.

Binds 0.0.0.0:$PORT (default 10000) in the foreground. The store is in-memory
and starts empty on every boot (per-test-server isolation re-invokes
start.sh before every test)."""

import os

from flask import Flask

import envelope
import errors as errmod
import routes_cases
import routes_clearances
import routes_clock
import routes_converters
import routes_counterfeit
import routes_formulations
import routes_orders
import routes_phaseout
import routes_pricing
import routes_rebates
import routes_reference

app = Flask(__name__)

for module in (routes_clock, routes_reference, routes_formulations,
               routes_clearances, routes_converters, routes_cases,
               routes_pricing, routes_orders, routes_rebates,
               routes_phaseout, routes_counterfeit):
    app.register_blueprint(module.bp)


@app.errorhandler(errmod.ApiError)
def handle_api_error(err):
    return envelope.error_response(err)


@app.errorhandler(404)
def handle_not_found(_err):
    return envelope.error_response(
        errmod.api_err("ERR_NOT_FOUND", "Resource not found"))


@app.errorhandler(500)
def handle_internal_error(_err):
    return envelope.error_response(
        errmod.ApiError("ERR_INTERNAL_ERROR", 500, "Internal server error"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
