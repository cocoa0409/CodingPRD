"""Entry point: Flask app, error handlers, route registration."""
import os

from flask import Flask

import envelope
from errors import ApiError
from routes import register_routes


def create_app():
    app = Flask(__name__)
    register_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return envelope.error(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return envelope.error("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return envelope.error("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return envelope.error(e.error_id, e.http_status, e.message)
        return envelope.error("ERR_INTERNAL", 500, "Internal server error")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0",
            port=int(os.environ.get("PORT", "10000")),
            threaded=True)
