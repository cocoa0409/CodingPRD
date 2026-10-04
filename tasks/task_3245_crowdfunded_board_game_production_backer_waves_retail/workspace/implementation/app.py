"""Entry point: Flask app, error handlers, route registration."""
import os

from flask import Flask

from db import db
from errors import ApiError
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "resource not found")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "resource not found")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.http_status, e.message)
    return error_response("ERR_INVALID_REQUEST", 400, str(e))


import campaign_routes
import pledge_routes
import quote_routes
import run_routes
import freight_routes
import wave_routes
import allocation_routes
import replacement_routes
import localization_routes
import reprint_routes

app.register_blueprint(campaign_routes.bp)
app.register_blueprint(pledge_routes.bp)
app.register_blueprint(quote_routes.bp)
app.register_blueprint(run_routes.bp)
app.register_blueprint(freight_routes.bp)
app.register_blueprint(wave_routes.bp)
app.register_blueprint(allocation_routes.bp)
app.register_blueprint(replacement_routes.bp)
app.register_blueprint(localization_routes.bp)
app.register_blueprint(reprint_routes.bp)
app.register_blueprint(reprint_routes.clock_bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
