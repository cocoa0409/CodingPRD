"""Executive Protection & Travel Risk Management API.

A Flask application whose entire state lives in process memory.  Nothing is
seeded: every row a caller observes was created through a declared endpoint.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_core
import routes_ops
import routes_risk
import routes_trips
from envelope import error_response
from errors import ApiError

app = Flask(__name__, static_folder=None)
app.url_map.strict_slashes = False

app.register_blueprint(routes_core.bp)
app.register_blueprint(routes_core.clock_bp)
app.register_blueprint(routes_risk.bp)
app.register_blueprint(routes_trips.bp)
app.register_blueprint(routes_ops.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def handle_http_exception(exc):
    status = exc.code or 500
    if status == 404:
        error_id = "ERR_NOT_FOUND"
        message = "No route matches the requested path."
    elif status == 405:
        error_id = "ERR_METHOD_NOT_ALLOWED"
        message = "That method is not allowed on this path."
    else:
        error_id = "ERR_INVALID_REQUEST"
        message = exc.description or "The request could not be processed."
    return error_response(error_id, message, status)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    return error_response("ERR_INTERNAL", "Unexpected server error.", 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False)
