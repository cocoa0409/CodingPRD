"""Aluminum Can Manufacturing API — Flask entry point.

In-memory only; every start.sh relaunch boots with an empty store. Listens on
PORT (default 10000), bound to 0.0.0.0, in the foreground.
"""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_body
from routes import (agreements, clock, customers, forecasts, formats,
                    incidents, indices, lines, plants, run_actions, runs,
                    scrap)

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (clock, plants, customers, agreements, indices, lines, formats,
               runs, run_actions, forecasts, scrap, incidents):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def _api_error(err):
    return jsonify(error_body(err.error_id, err.message)), err.http_status


@app.errorhandler(404)
def _not_found(_err):
    return jsonify(error_body("ERR_NOT_FOUND", "Resource not found.")), 404


@app.errorhandler(405)
def _method_not_allowed(_err):
    return jsonify(error_body("ERR_NOT_FOUND", "Resource not found.")), 404


@app.errorhandler(Exception)
def _unhandled(_err):
    return jsonify(error_body("ERR_INTERNAL", "Internal server error.")), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
