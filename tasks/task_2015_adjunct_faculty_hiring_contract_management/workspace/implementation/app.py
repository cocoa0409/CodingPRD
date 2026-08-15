"""Entry point: Flask app, error handlers, route registration."""

import os

from flask import Flask, jsonify

import errors
import helpers
import routes_core
import routes_hiring
import routes_ops
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(routes_core.bp, url_prefix="/adjunct-hr")
app.register_blueprint(routes_hiring.bp, url_prefix="/adjunct-hr")
app.register_blueprint(routes_ops.bp, url_prefix="/adjunct-hr")


@app.errorhandler(ApiError)
def handle_api_error(err):
    return helpers.error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return helpers.error_response(errors.not_found("Route not found"))


@app.errorhandler(405)
def handle_405(err):
    return helpers.error_response(errors.not_found("Method not allowed"))


@app.errorhandler(500)
def handle_500(err):
    return helpers.error_response(
        ApiError("ERR_INTERNAL", 500, "Internal server error")
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
