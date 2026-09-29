"""EPLI underwriting & claims API — application entry point.

Storage is in-memory only and starts empty on every boot; the harness relaunches
this process before each test, so no state may outlive the process.
"""

import os
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError
from routes.claims import bp as claims_bp
from routes.defense import bp as defense_bp
from routes.reference import bp as reference_bp
from routes.underwriting import bp as underwriting_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(reference_bp)
app.register_blueprint(underwriting_bp)
app.register_blueprint(claims_bp)
app.register_blueprint(defense_bp)


@app.errorhandler(ApiError)
def handle_api_error(error):
    return error_response(error.error_id, error.message, error.http_status)


@app.errorhandler(HTTPException)
def handle_http_error(error):
    status = error.code or 500
    if status == 404:
        return error_response("ERR_INVALID_REQUEST",
                              "The requested resource path does not exist.",
                              404)
    if status == 405:
        return error_response("ERR_INVALID_REQUEST",
                              "The HTTP method is not allowed on this path.",
                              405)
    return error_response("ERR_INVALID_REQUEST",
                          error.description or "Malformed request.", status)


@app.errorhandler(Exception)
def handle_unexpected(error):
    return error_response("ERR_INVALID_REQUEST",
                          "Unexpected server error: %s" % (error,), 500)


class _SerializedApp(object):
    """One request at a time: the domain logic mutates shared dicts."""

    def __init__(self, wsgi_app):
        self._wsgi_app = wsgi_app
        self._lock = threading.Lock()

    def __call__(self, environ, start_response):
        with self._lock:
            return self._wsgi_app(environ, start_response)


app.wsgi_app = _SerializedApp(app.wsgi_app)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False,
            threaded=True)
