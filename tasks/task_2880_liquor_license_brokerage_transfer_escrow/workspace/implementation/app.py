"""Liquor License Brokerage & Transfer Escrow API.

Entry point: route registration, the standard error envelope and the launcher.
The in-memory store starts empty on every boot; nothing is ever seeded.
"""

import os
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_body
from errors import ERROR_CATALOG, ApiError, default_message
import routes_agreements
import routes_applications
import routes_disclosures
import routes_listings
import routes_premises
import routes_reference
import routes_safekeeping


class SerializedMiddleware(object):
    """Serialise request handling so cascades stay atomic under a threaded server."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app
        self.lock = threading.Lock()

    def __call__(self, environ, start_response):
        with self.lock:
            return self.wsgi_app(environ, start_response)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.json.sort_keys = False

    app.register_blueprint(routes_reference.bp)
    app.register_blueprint(routes_premises.bp)
    app.register_blueprint(routes_listings.bp)
    app.register_blueprint(routes_agreements.bp)
    app.register_blueprint(routes_disclosures.bp)
    app.register_blueprint(routes_applications.bp)
    app.register_blueprint(routes_safekeeping.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_body(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        status = exc.code or 500
        if status == 404:
            error_id = "ERR_NOT_FOUND"
        elif status == 405:
            error_id = "ERR_INVALID_REQUEST"
            status = 405
        elif status == 500:
            error_id = "ERR_INTERNAL"
        else:
            error_id = "ERR_INVALID_REQUEST"
        message = getattr(exc, "description", None) or default_message(error_id)
        return error_body(error_id, message, status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_body("ERR_INTERNAL", "An unexpected error occurred: %s" % exc, 500)

    app.wsgi_app = SerializedMiddleware(app.wsgi_app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
