"""School bus manufacturing & delivery API — in-memory Flask application.

Storage is process-local and is never persisted; no entity data is seeded at
import time or at startup.  A fresh process is a completely empty system whose
logical clock reads 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import base_meta, error_response
from routes import catalog, clock, commerce, network, plant, quality, units


def envelope(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def create_app():
    app = Flask(__name__, static_folder=None)
    app.config["JSON_SORT_KEYS"] = False
    try:
        app.json.sort_keys = False
    except AttributeError:  # pragma: no cover - older Flask
        pass

    app.register_blueprint(clock.bp)
    app.register_blueprint(catalog.bp)
    app.register_blueprint(plant.bp)
    app.register_blueprint(commerce.bp)
    app.register_blueprint(units.bp)
    app.register_blueprint(quality.bp)
    app.register_blueprint(network.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        if err.code == 404:
            return envelope("ERR_NOT_FOUND", "The requested resource does not exist.", 404)
        if err.code == 405:
            return envelope("ERR_INVALID_REQUEST",
                            "The HTTP method is not allowed for this resource.", 405)
        if err.code in (400, 415):
            return envelope("ERR_INVALID_REQUEST",
                            "The request could not be parsed.", 400)
        return envelope("ERR_INVALID_REQUEST", err.description or "Request failed.",
                        err.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(err):  # pragma: no cover - defensive
        return envelope("ERR_INTERNAL", "Unexpected server error: %s" % err, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
