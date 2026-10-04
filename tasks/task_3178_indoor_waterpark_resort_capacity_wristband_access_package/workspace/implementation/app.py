"""Waterpark Resort Capacity API - Flask entry point.

Every process boot starts from an empty store: nothing is seeded, preloaded
or registered here.  All state a caller observes is produced by endpoints.
"""

import os

from flask import Flask, jsonify

import db as _db
import errors
import response
import routes

# Guarantee a clean slate for every fresh process.
_db.store().reset()

app = Flask(__name__)
app.url_map.strict_slashes = False
routes.register(app)


@app.errorhandler(errors.ApiError)
def handle_api_error(exc):
    return jsonify(response.error_body(exc.error_id, exc.message)), exc.http_status


@app.errorhandler(404)
def handle_not_found(exc):
    return jsonify(response.error_body(
        "ERR_NOT_FOUND", "The requested resource does not exist."
    )), 404


@app.errorhandler(405)
def handle_method_not_allowed(exc):
    return jsonify(response.error_body(
        "ERR_INVALID_REQUEST", "The requested method is not supported for this path."
    )), 400


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, errors.ApiError):
        return jsonify(response.error_body(exc.error_id, exc.message)), exc.http_status
    return jsonify(response.error_body(
        "ERR_INVALID_REQUEST", "The request could not be processed as submitted."
    )), 400


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))