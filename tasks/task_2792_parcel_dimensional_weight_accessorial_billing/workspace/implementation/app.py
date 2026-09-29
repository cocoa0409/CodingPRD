"""Flask application entry point.

Storage is in-memory only and nothing is ever seeded: every record is built by
an API call, so a fresh process starts completely empty (PRD 2.4 pins the
logical clock at 2026-08-01T00:00:00Z until a test sets it).
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import routes_admin
import routes_billing
import routes_claims
import routes_shipments
from errors import ApiError
from response import error_body


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_admin.bp)
    app.register_blueprint(routes_shipments.bp)
    app.register_blueprint(routes_billing.bp)
    app.register_blueprint(routes_claims.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        body = error_body(error.error_id, error.message)
        return jsonify(body), error.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        if error.code == 404:
            body = error_body("ERR_INVALID_REQUEST", "Resource not found.")
            return jsonify(body), 404
        if error.code == 405:
            body = error_body("ERR_INVALID_REQUEST", "Method not allowed.")
            return jsonify(body), 405
        if error.code == 400:
            body = error_body("ERR_INVALID_REQUEST", "Malformed request.")
            return jsonify(body), 400
        body = error_body("ERR_INVALID_REQUEST", error.description or "Request failed.")
        return jsonify(body), error.code

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        body = error_body("ERR_INVALID_REQUEST", "Unexpected server error: %s" % error)
        return jsonify(body), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
