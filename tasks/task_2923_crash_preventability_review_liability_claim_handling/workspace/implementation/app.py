"""Crash Preventability Review and Liability Claim Handling API.

Flask application factory and error plumbing. All state lives in process
memory (see store.py); nothing is seeded at boot.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from envelope import error_body
from errors import ApiError
from routes.claims import bp as claims_bp
from routes.core import bp as core_bp
from routes.crashes import bp as crashes_bp
from routes.demands import bp as demands_bp
from routes.discipline import bp as discipline_bp
from routes.review import bp as review_bp
from routes.subrogation import bp as subrogation_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    app.json.ensure_ascii = False

    for blueprint in (core_bp, crashes_bp, review_bp, discipline_bp, claims_bp,
                      demands_bp, subrogation_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        status = exc.code or 500
        if status == 404:
            error_id = "ERR_INVALID_REQUEST"
            message = "The requested resource path does not exist"
        elif status == 405:
            error_id = "ERR_INVALID_REQUEST"
            message = "The HTTP method is not allowed for this path"
        elif status == 400:
            error_id = "ERR_INVALID_REQUEST"
            message = "The request could not be understood"
        else:
            error_id = "ERR_INVALID_REQUEST"
            message = exc.description or "Request failed"
        return jsonify(error_body(error_id, message)), status

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return jsonify(error_body("ERR_INVALID_REQUEST", str(exc))), 400

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
