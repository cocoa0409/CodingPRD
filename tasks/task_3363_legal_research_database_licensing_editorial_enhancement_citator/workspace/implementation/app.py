"""Legal Research Citator API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). The store starts empty on every boot;
per-test-server isolation re-launches this process before every test.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from middleware import authenticate_request
from response import error_envelope
from routes.billing import bp as billing_bp
from routes.clock import bp as clock_bp
from routes.commercial import bp as commercial_bp
from routes.documents import bp as documents_bp
from routes.headnotes import bp as headnotes_bp
from routes.licensing import bp as licensing_bp
from routes.removal import bp as removal_bp
from routes.usage import bp as usage_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.before_request(authenticate_request)

    for blueprint in (
        clock_bp,
        documents_bp,
        headnotes_bp,
        commercial_bp,
        usage_bp,
        billing_bp,
        licensing_bp,
        removal_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_envelope(err.error_id, err.message, err.status)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        return error_envelope("ERR_INVALID_REQUEST", err.description or "request failed", err.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_envelope("ERR_INVALID_REQUEST", "internal error: %s" % err, 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
