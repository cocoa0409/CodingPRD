"""Application entry point: blueprint registration and error handlers.

Binds 0.0.0.0:$PORT (default 10000). The in-memory store starts empty on every
boot; nothing is seeded at startup.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND


def create_app():
    app = Flask(__name__)

    from routes_core import bp as core_bp
    from routes_agreements import bp as agreements_bp
    from routes_transfers import bp as transfers_bp
    from routes_reviews import bp as reviews_bp
    from routes_allocations import bp as allocations_bp
    from routes_field import bp as field_bp
    from routes_promotions import bp as promotions_bp

    app.register_blueprint(core_bp)
    app.register_blueprint(agreements_bp)
    app.register_blueprint(transfers_bp)
    app.register_blueprint(reviews_bp)
    app.register_blueprint(allocations_bp)
    app.register_blueprint(field_bp)
    app.register_blueprint(promotions_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return envelope.error_response(err)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, HTTPException):
            status = err.code or 500
            if status == 404:
                error_id = ERR_NOT_FOUND
            elif status < 500:
                error_id = ERR_INVALID_REQUEST
            else:
                error_id = "ERR_INTERNAL"
            return envelope.error_response(
                ApiError(error_id, err.name, status))
        return envelope.error_response(
            ApiError("ERR_INTERNAL", "Internal server error", 500))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
