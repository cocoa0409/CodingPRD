"""Neighbourhood Camera Video Request & Community Safety Portal.

Flask application factory and error handlers.  All state lives in memory in
store.db and vanishes when the process exits; nothing is ever seeded.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import envelope
import routes_agency
import routes_area
import routes_consent
import routes_feed
import routes_report
import routes_request
import routes_resident
from errors import ERROR_STATUS, ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for module in (routes_agency, routes_resident, routes_area, routes_request,
                   routes_consent, routes_feed, routes_report):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        body = envelope.error_body(exc.error_id, exc.message)
        return jsonify(body), exc.http_status

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            error_id, message = "ERR_NOT_FOUND", "The requested path does not exist"
        elif exc.code == 405:
            error_id = "ERR_UNAUTHORIZED"
            message = "That method is not allowed on this path"
        elif exc.code in (400, 415):
            error_id = "ERR_INVALID_REQUEST"
            message = "The request could not be parsed"
        else:
            error_id = "ERR_INTERNAL"
            message = exc.description or "Request failed"
        body = envelope.error_body(error_id, message)
        return jsonify(body), exc.code

    @app.errorhandler(Exception)
    def _unhandled(exc):
        body = envelope.error_body("ERR_INTERNAL", str(exc) or "Internal error")
        return jsonify(body), 500

    return app


app = create_app()

# Sanity check: every error id raised by the code base resolves to a status.
assert "ERR_INVALID_REQUEST" in ERROR_STATUS


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True,
            use_reloader=False)
