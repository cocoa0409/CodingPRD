"""Entry point: Flask app, error handlers, route registration."""

from __future__ import annotations

import os

from flask import Flask

from errors import ApiError
from response import error_body
from routes import refdata, lots, sales


def create_app() -> Flask:
    app = Flask(__name__)
    app.register_blueprint(refdata.bp)
    app.register_blueprint(lots.bp)
    app.register_blueprint(sales.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_body(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_body("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_body("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        import traceback
        traceback.print_exc()
        return error_body("ERR_INVALID_REQUEST", "Unexpected server error: %s" % err, 400)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
