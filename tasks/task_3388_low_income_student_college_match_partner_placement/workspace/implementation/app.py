"""Application entry point: create_app wiring and error handlers only.

All endpoints live in per-domain modules under routes/. The store is
in-memory and starts empty on every boot (no seeding of any kind).
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import clock
from errors import ApiError
from response import error_response
from routes import register_blueprints


def create_app():
    app = Flask(__name__)
    register_blueprints(app)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return error_response(error)

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        # Unmatched paths and wrong methods surface in the standard error
        # envelope rather than Flask's HTML pages.
        status = error.code if error.code and 400 <= error.code < 600 else 500
        body = {
            "meta": {
                "api_request_id": "req_" + os.urandom(10).hex(),
                "api_request_timestamp": clock.fmt(clock.now()),
            },
            "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "resource not found"},
        }
        return jsonify(body), status

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        body = {
            "meta": {
                "api_request_id": "req_" + os.urandom(10).hex(),
                "api_request_timestamp": clock.fmt(clock.now()),
            },
            "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": "internal server error"},
        }
        return jsonify(body), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
