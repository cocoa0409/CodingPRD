"""Application bootstrap: Flask app, error handlers, blueprint registration.

In-memory store only; every boot starts empty (per-test-server isolation).
"""
import os

from flask import Flask

import envelope
from errors import ApiError

app = Flask(__name__)

import routes_batches
import routes_campaigns
import routes_clock
import routes_comparability
import routes_deviations
import routes_inspections
import routes_master
import routes_products
import routes_seed
import routes_shipments
import routes_tests

for module in (
    routes_clock,
    routes_master,
    routes_products,
    routes_inspections,
    routes_comparability,
    routes_campaigns,
    routes_seed,
    routes_batches,
    routes_tests,
    routes_deviations,
    routes_shipments,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return envelope.error_response(exc.error_id, exc.http_status, exc.message)


@app.errorhandler(404)
def handle_not_found(_):
    return envelope.error_response("ERR_NOT_FOUND", 404, "Resource or route not found")


@app.errorhandler(405)
def handle_method_not_allowed(_):
    return envelope.error_response("ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(exc):
    return envelope.error_response("ERR_INTERNAL", 500, str(exc))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
