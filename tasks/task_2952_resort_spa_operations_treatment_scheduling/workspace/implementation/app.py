"""Resort Spa Operations API — Flask application entry point.

State lives entirely in module-level Python dicts (see store.py): nothing is
persisted, nothing is seeded, and every fresh process starts empty with the
logical clock reading 2026-08-01T00:00:00Z.
"""

import os
import threading

from flask import Flask

import envelope
import errors
import routes_appointments
import routes_catalog
import routes_credentials
import routes_guests
import routes_reports
from errors import ApiError


class Serialize(object):
    """Serialise requests so the in-memory store never races itself."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app
        self.lock = threading.Lock()

    def __call__(self, environ, start_response):
        with self.lock:
            return self.wsgi_app(environ, start_response)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except Exception:
        app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_catalog.bp)
    app.register_blueprint(routes_credentials.bp)
    app.register_blueprint(routes_guests.bp)
    app.register_blueprint(routes_appointments.bp)
    app.register_blueprint(routes_reports.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return envelope.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return envelope.error(errors.ERR_INVALID_REQUEST,
                              "The requested resource path does not exist.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return envelope.error(errors.ERR_INVALID_REQUEST,
                              "The HTTP method is not allowed on this path.", 405)

    @app.errorhandler(400)
    def handle_bad_request(exc):
        return envelope.error(errors.ERR_INVALID_REQUEST,
                              "The request could not be understood.", 422)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return envelope.error(exc.error_id, exc.message, exc.http_status)
        return envelope.error("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    app.wsgi_app = Serialize(app.wsgi_app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
