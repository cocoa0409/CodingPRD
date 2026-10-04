"""Entry point: Flask app, blueprint registration, envelope error handlers.

The store lives entirely in memory (store.DB); every fresh process starts
empty — per-test-server isolation wipes state by re-invoking start.sh.
"""
import os

from flask import Flask

import routes_agencies_buildings
import routes_alterations
import routes_bills
import routes_clock
import routes_leases
import routes_oas
import routes_offers
import routes_plans
import routes_requirements
import routes_services
import routes_utilization
from envelope import error_resp
from errors import ApiError

app = Flask(__name__)

for mod in (
    routes_agencies_buildings,
    routes_requirements,
    routes_offers,
    routes_leases,
    routes_plans,
    routes_oas,
    routes_bills,
    routes_alterations,
    routes_services,
    routes_utilization,
    routes_clock,
):
    app.register_blueprint(mod.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_resp(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_not_found(e):
    return error_resp("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return error_resp("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_resp(e.error_id, e.http_status, e.message)
    return error_resp("ERR_INTERNAL", 500, str(e))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
