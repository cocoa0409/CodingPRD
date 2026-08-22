"""Credit Balance & Refund Management API — entry point."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import ALL_BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return response.error("ERR_NOT_FOUND", "No such route.", 404)
        if exc.code == 405:
            return response.error("ERR_METHOD_NOT_ALLOWED", "Method not allowed.", 405)
        if exc.code == 400:
            return response.error("ERR_INVALID_REQUEST", "Malformed request.", 400)
        return response.error("ERR_INTERNAL", exc.description or "Error.", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return response.error("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
