"""Entry point: Flask app wiring, error handlers, blueprint registration."""

import os

from flask import Flask

from errors import ApiError
from helpers import error_response

app = Flask(__name__)

import routes_municipalities
import routes_agreements
import routes_deliveries
import routes_boilers
import routes_reports
import routes_energy
import routes_metals
import routes_ash
import routes_emissions
import routes_clock_settlements

app.register_blueprint(routes_municipalities.bp)
app.register_blueprint(routes_agreements.bp)
app.register_blueprint(routes_deliveries.bp)
app.register_blueprint(routes_boilers.bp)
app.register_blueprint(routes_reports.bp)
app.register_blueprint(routes_energy.bp)
app.register_blueprint(routes_metals.bp)
app.register_blueprint(routes_ash.bp)
app.register_blueprint(routes_emissions.bp)
app.register_blueprint(routes_clock_settlements.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "resource not found"))


@app.errorhandler(405)
def handle_405(err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "resource not found"))


@app.errorhandler(Exception)
def handle_generic(err):
    return error_response(ApiError("ERR_INVALID_REQUEST", 400, str(err)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
