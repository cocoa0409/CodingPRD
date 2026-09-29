import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from common import ApiError, envelope_error
from routes import BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return envelope_error("ERR_NOT_FOUND", "Resource not found", 404)
        if exc.code == 405:
            return envelope_error("ERR_NOT_FOUND", "Method not allowed", 404)
        if exc.code in (400, 415):
            return envelope_error("ERR_INVALID_REQUEST",
                                  exc.description or "Malformed request", 400)
        return envelope_error("ERR_VALIDATION", exc.description or "Request failed",
                              exc.code or 500)

    @app.errorhandler(Exception)
    def _unexpected(exc):  # pragma: no cover - defensive
        return envelope_error("ERR_VALIDATION", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=False)
