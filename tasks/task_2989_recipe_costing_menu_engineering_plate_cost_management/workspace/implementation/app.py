"""Recipe costing, menu engineering and plate cost management API.

All state lives in process memory (see core.Store); every launch of this
process therefore starts from a completely empty domain.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error
from errors import ApiError
from routes import BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 404:
            return error("ERR_INVALID_REQUEST", "No such endpoint.", 404)
        if exc.code == 405:
            return error("ERR_INVALID_REQUEST",
                         "The method is not allowed on this endpoint.", 405)
        return error("ERR_INVALID_REQUEST", exc.description or "Bad request",
                     exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error("ERR_INVALID_REQUEST", "Unhandled server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
