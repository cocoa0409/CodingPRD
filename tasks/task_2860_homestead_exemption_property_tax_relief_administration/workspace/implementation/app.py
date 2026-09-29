"""Homestead Exemption & Property Tax Relief Administration API.

A single Flask process holding every byte of state in memory.  Nothing is
seeded: a fresh process starts with empty collections and the logical
assessment clock pinned to 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope as env
import routes_appeals
import routes_applications
import routes_fraud
import routes_grants
import routes_roll
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(routes_roll.bp)
    app.register_blueprint(routes_applications.bp)
    app.register_blueprint(routes_grants.bp)
    app.register_blueprint(routes_fraud.bp)
    app.register_blueprint(routes_appeals.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return env.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        status = exc.code or 500
        if status == 404:
            return env.error("ERR_INVALID_REQUEST", "No such resource path.", 404)
        if status == 405:
            return env.error("ERR_INVALID_REQUEST", "Method not allowed for this path.", 405)
        if status == 400:
            return env.error("ERR_INVALID_REQUEST", "Malformed request.", 400)
        return env.error("ERR_INVALID_REQUEST", exc.description or "Request failed.", status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return env.error("ERR_INVALID_REQUEST", "Unexpected server condition: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
