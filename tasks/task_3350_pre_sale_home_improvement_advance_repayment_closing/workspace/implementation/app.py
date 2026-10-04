"""Entry point: app factory, error handlers, blueprint registration."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_resp
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from routes import ALL_BPS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for bp in ALL_BPS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_resp(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_resp(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_resp(ERR_NOT_FOUND, "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_exception(err):
        if isinstance(err, HTTPException):
            return error_resp(ERR_INVALID_REQUEST, err.name, err.code or 400)
        return error_resp("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
