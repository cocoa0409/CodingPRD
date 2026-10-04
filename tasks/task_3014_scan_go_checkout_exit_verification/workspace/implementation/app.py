"""Entry point: Flask app, error handlers, route registration."""

import os

from flask import Flask, jsonify

from errors import ApiError, ERR_INVALID_REQUEST
from response import error_response
from routes import catalog, clock, clubs, curbside, intercepts, lp_cases, members, offers, sessions, verifications

app = Flask(__name__)

for module in (clubs, catalog, offers, members, sessions, intercepts,
               verifications, lp_cases, curbside, clock):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ApiError(ERR_INVALID_REQUEST, "Resource not found.", 404))


@app.errorhandler(405)
def handle_405(err):
    return error_response(ApiError(ERR_INVALID_REQUEST, "Method not allowed.", 405))


@app.errorhandler(500)
def handle_500(err):
    return error_response(ApiError(ERR_INVALID_REQUEST, "Internal server error.", 500))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
