"""Design Firm Project Accounting API -- Flask application entry point.

Storage is in-memory only (see db.py): every boot of this process starts from a
completely empty store with the logical clock at its documented default.
"""
import os
import sys
import traceback

from flask import Flask

import response as resp
from errors import ApiError
from routes_billing import bp as billing_bp
from routes_charges import bp as charges_bp
from routes_consultants import bp as consultants_bp
from routes_core import bp as core_bp


def _error(error_id, message, status):
    body, _ = resp.error_body(error_id, message)
    return body, status


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(core_bp)
    app.register_blueprint(charges_bp)
    app.register_blueprint(consultants_bp)
    app.register_blueprint(billing_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return _error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return _error("ERR_INVALID_REQUEST", "No such resource path.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return _error("ERR_INVALID_REQUEST", "Method not allowed on this path.", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return _error(exc.error_id, exc.message, exc.http_status)
        traceback.print_exc(file=sys.stderr)
        return _error("ERR_INVALID_REQUEST", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
