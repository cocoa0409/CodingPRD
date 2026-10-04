"""Flask app entry point: error handlers + route registration."""

import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes.campaigns import bp as campaigns_bp
from routes.channels import bp as channels_bp
from routes.core import bp as core_bp
from routes.devices import bp as devices_bp
from routes.grants import bp as grants_bp
from routes.statements import bp as statements_bp
from routes.units import bp as units_bp
from routes.viewers import bp as viewers_bp

app = Flask(__name__)

for bp in (core_bp, channels_bp, viewers_bp, grants_bp, campaigns_bp,
           devices_bp, units_bp, statements_bp):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(err):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_generic(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.message, err.http_status)
    return error_response("ERR_INVALID_REQUEST", str(err), 400)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
