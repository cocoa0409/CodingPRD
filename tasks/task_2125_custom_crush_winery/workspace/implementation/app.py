"""Custom Crush & Bonded Winery Services API.

All state is held in memory for the life of this process; nothing is persisted
and nothing is seeded at startup. Every entity is built through the declared
API surface.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import respond_error
from errors import ApiError, ERR_INVALID_REQUEST
from routes import BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return respond_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        return respond_error(ERR_INVALID_REQUEST,
                             exc.description or "Request could not be handled.",
                             exc.code or 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return respond_error("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
