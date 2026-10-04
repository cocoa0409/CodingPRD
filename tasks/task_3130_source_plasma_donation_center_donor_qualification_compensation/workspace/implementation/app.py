"""Entry point: Flask app, error handlers, route registration."""
import os

from flask import Flask

import response
from errors import ApiError
import routes_centers
import routes_donations
import routes_donors
import routes_screenings

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(routes_centers.bp)
app.register_blueprint(routes_donors.bp)
app.register_blueprint(routes_screenings.bp)
app.register_blueprint(routes_donations.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return response.error_response(err)


@app.errorhandler(404)
def handle_not_found(err):
    return response.error_response(
        ApiError("ERR_NOT_FOUND", "Resource not found", 404)
    )


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return response.error_response(
        ApiError("ERR_NOT_FOUND", "Resource not found", 404)
    )


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return response.error_response(err)
    return response.error_response(
        ApiError("ERR_INVALID_REQUEST", "Unexpected server error", 400)
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
