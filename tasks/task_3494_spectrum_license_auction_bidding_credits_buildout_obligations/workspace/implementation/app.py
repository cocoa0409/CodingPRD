"""Spectrum License Auction API — application entry point.

Mounts all business endpoints under /spectrum-auctions plus the unprefixed
test-driving clock endpoint. The store is module-level in-memory state;
every `start.sh` invocation boots a fresh process with an empty store.
"""
import os

from flask import Flask, jsonify

from errors import ApiError, error_response
import routes_clock
import routes_band
import routes_auctions
import routes_applicants
import routes_rounds
import routes_assignment
import routes_licenses
import routes_milestones
import routes_transfers
import routes_incumbents
import routes_renewals

app = Flask(__name__)

for module in (routes_clock, routes_band, routes_auctions, routes_applicants,
               routes_rounds, routes_assignment, routes_licenses,
               routes_milestones, routes_transfers, routes_incumbents,
               routes_renewals):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_not_found(_err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Not found"))


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return error_response(ApiError("ERR_INVALID_REQUEST", 405,
                                   "Method not allowed"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    return error_response(ApiError("ERR_INVALID_REQUEST", 500,
                                   "Internal error: %s" % err))


@app.get("/")
def root():
    return jsonify({"service": "spectrum-license-auction", "status": "up"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
