"""Barrel Aging Inventory Planning API — Flask entry point.

In-memory only; the store starts empty on every boot. Reads $PORT (default
10000) and binds 0.0.0.0 in the foreground.
"""

import os

from flask import Flask

import envelope
import routes_barrels
import routes_blends
import routes_capacity
import routes_programs
import routes_reports

app = Flask(__name__)

app.register_blueprint(routes_capacity.bp)
app.register_blueprint(routes_barrels.bp)
app.register_blueprint(routes_blends.bp)
app.register_blueprint(routes_programs.bp)
app.register_blueprint(routes_reports.bp)


@app.errorhandler(envelope.ApiError)
def handle_api_error(err):
    return envelope.error_response(err)


@app.errorhandler(404)
def handle_not_found(_err):
    return envelope.error_response(envelope.err_not_found("Resource not found"))


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return envelope.error_response(envelope.err_not_found("Resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, envelope.ApiError):
        return envelope.error_response(err)
    return envelope.error_response(
        envelope.ApiError("ERR_INTERNAL", str(err), 500)
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
