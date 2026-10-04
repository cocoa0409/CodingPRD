"""Entry point: Flask app, blueprint registration, error handlers."""
import os

from flask import Flask

from errors import ApiError
from helpers import error_response
import routes_agreements
import routes_clock
import routes_growers
import routes_harvest_lots
import routes_harvest_windows
import routes_plant_lots
import routes_plantings
import routes_pools
import routes_recall
import routes_statements
import routes_varieties

app = Flask(__name__)

for module in (
    routes_clock,
    routes_varieties,
    routes_growers,
    routes_agreements,
    routes_plant_lots,
    routes_plantings,
    routes_harvest_windows,
    routes_harvest_lots,
    routes_pools,
    routes_statements,
    routes_recall,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(Exception)
def handle_unexpected(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e
    return error_response(ApiError("ERR_INTERNAL", 500, "Internal server error: %s" % e))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
