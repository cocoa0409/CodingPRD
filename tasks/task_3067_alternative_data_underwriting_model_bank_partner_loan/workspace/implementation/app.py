"""Entry point: Flask app, error handlers, route registration."""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response, success_object
from routes import bp


def create_app():
    app = Flask(__name__)
    app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ApiError("ERR_NOT_FOUND", "Resource not found", 404))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ApiError("ERR_NOT_FOUND", "Resource not found", 404))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(ApiError("ERR_VALIDATION", str(err), 400))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
