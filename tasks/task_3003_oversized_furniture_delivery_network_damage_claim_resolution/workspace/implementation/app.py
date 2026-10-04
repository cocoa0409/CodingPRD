"""Oversize Freight Network API — Flask entry point."""
import os

from flask import Flask

import clock
from errors import APIError, err_not_found
from response import error_response, success
from services.expiry import sweep_return_authorizations

clock.init_clock()

app = Flask(__name__)
app.json.sort_keys = False

from routes import appointments, claims, clock_routes, linehauls, orders, reference, returns

PREFIX = "/oversize-freight"
app.register_blueprint(reference.bp, url_prefix=PREFIX)
app.register_blueprint(orders.bp, url_prefix=PREFIX)
app.register_blueprint(linehauls.bp, url_prefix=PREFIX)
app.register_blueprint(appointments.bp, url_prefix=PREFIX)
app.register_blueprint(claims.bp, url_prefix=PREFIX)
app.register_blueprint(returns.bp, url_prefix=PREFIX)
app.register_blueprint(clock_routes.bp, url_prefix=PREFIX)


@app.before_request
def _sweep():
    sweep_return_authorizations()


@app.errorhandler(APIError)
def _handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _handle_404(_err):
    return error_response(err_not_found())


@app.errorhandler(405)
def _handle_405(_err):
    return error_response(err_not_found())


@app.errorhandler(Exception)
def _handle_unexpected(err):
    if isinstance(err, APIError):
        return error_response(err)
    return error_response(APIError("ERR_INVALID_REQUEST", 400, str(err)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
