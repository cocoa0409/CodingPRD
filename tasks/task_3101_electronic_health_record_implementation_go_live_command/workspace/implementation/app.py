"""EHR Implementation & Go-Live Command Center API entry point.

The store is in-memory and starts empty: nothing is seeded, preloaded or
registered at startup.
"""

import os

from flask import Flask, request

from errors import ApiError
from response import error_response
from routes.build_items import bp as build_items_bp
from routes.command_center import bp as command_center_bp
from routes.conversion import bp as conversion_bp
from routes.departments import bp as departments_bp
from routes.facilities import bp as facilities_bp
from routes.interfaces import bp as interfaces_bp
from routes.programs import bp as programs_bp
from routes.staff import bp as staff_bp
from routes.testing import bp as testing_bp

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

for blueprint in (
    programs_bp,
    facilities_bp,
    departments_bp,
    build_items_bp,
    staff_bp,
    testing_bp,
    conversion_bp,
    interfaces_bp,
    command_center_bp,
):
    app.register_blueprint(blueprint)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_not_found(exc):
    return error_response("ERR_INVALID_REQUEST", "The requested route does not exist.", 404)


@app.errorhandler(405)
def handle_method_not_allowed(exc):
    return error_response("ERR_INVALID_REQUEST", "The method is not allowed for this route.", 405)


@app.errorhandler(500)
def handle_server_error(exc):
    return error_response("ERR_INVALID_REQUEST", "The request could not be processed.", 500)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)
    if isinstance(exc, (ValueError, TypeError, KeyError, IndexError)):
        return error_response("ERR_INVALID_REQUEST", "The request could not be processed.", 400)
    return error_response("ERR_INVALID_REQUEST", "The request could not be processed.", 500)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        debug=False,
        use_reloader=False,
    )