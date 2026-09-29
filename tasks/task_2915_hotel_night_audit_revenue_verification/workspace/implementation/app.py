"""Night audit revenue verification API.

Storage is in-memory only and starts empty on every boot: no seeding,
no preloading, no fixtures.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return response.error("ERR_NOT_FOUND", 404, "Unknown route.")
        if exc.code == 405:
            return response.error("ERR_INVALID_REQUEST", 405, "Method not allowed.")
        if exc.code in (400, 415):
            return response.error(
                "ERR_INVALID_REQUEST", 400, "The request could not be parsed."
            )
        return response.error("ERR_INTERNAL", exc.code or 500, str(exc))

    @app.errorhandler(Exception)
    def _unhandled(exc):
        app.logger.exception("unhandled error")
        return response.error("ERR_INTERNAL", 500, str(exc))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
