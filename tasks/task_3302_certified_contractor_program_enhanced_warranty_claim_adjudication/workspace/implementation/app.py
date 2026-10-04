"""Entry point: Flask app, error handlers, route registration."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND
from response import error_response
from routes import core, training, certifications, registrations, claims, inspections, complaints, distribution

app = Flask(__name__)

for module in (core, training, certifications, registrations, claims,
               inspections, complaints, distribution):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ERR_RESOURCE_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(405)
def handle_405(err):
    return error_response(ERR_RESOURCE_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.http_status, err.message)
    return error_response(ERR_INVALID_REQUEST, 400, str(err))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
