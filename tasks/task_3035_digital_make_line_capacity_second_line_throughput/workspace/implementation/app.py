"""Digital Make-Line Capacity API — Flask entry point."""

import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response
from routes.admin import bp as admin_bp
from routes.kitchen import bp as kitchen_bp
from routes.orders import bp as orders_bp
from routes.operations import bp as operations_bp

API_PREFIX = "/api/v1"


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(admin_bp, url_prefix=API_PREFIX)
    app.register_blueprint(kitchen_bp, url_prefix=API_PREFIX)
    app.register_blueprint(orders_bp, url_prefix=API_PREFIX)
    app.register_blueprint(operations_bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response("ERR_INVALID_REQUEST", "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_INVALID_REQUEST", str(err), 400)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"}), 200

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
