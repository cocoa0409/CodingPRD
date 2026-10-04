"""Entry point: Flask app assembly, error handlers, server bootstrap."""

import os

from errors import ApiError, ERR_NOT_FOUND
from flask import Flask
from response import err
from routes_campus import bp_campus
from routes_clock import bp_clock
from routes_cohorts import bp_cohorts
from routes_offers import bp_offers
from routes_partnership import bp_partnership
from routes_recruitment import bp_recruitment
from routes_scholars import bp_scholars

app = Flask(__name__)

for bp in (
    bp_clock,
    bp_recruitment,
    bp_partnership,
    bp_cohorts,
    bp_offers,
    bp_scholars,
    bp_campus,
):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return err(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def _handle_404(_e):
    return err(ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(405)
def _handle_405(_e):
    return err(ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(Exception)
def _handle_unexpected(e):
    if isinstance(e, ApiError):
        return err(e.error_id, e.http_status, e.message)
    return err("ERR_INTERNAL", 500, "Internal server error")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
