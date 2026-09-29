"""Ballot Measure Petition Signature Verification API — entry point.

The store is entirely in memory and starts empty on every boot: no seeding,
no preloading, no on-disk persistence of any kind.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes.batches import bp as batches_bp
from routes.challenges import bp as challenges_bp
from routes.circulators import bp as circulators_bp
from routes.config import bp as config_bp
from routes.petitions import bp as petitions_bp
from routes.rounds import bp as rounds_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except AttributeError:  # pragma: no cover
        app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(config_bp)
    app.register_blueprint(petitions_bp)
    app.register_blueprint(circulators_bp)
    app.register_blueprint(batches_bp)
    app.register_blueprint(rounds_bp)
    app.register_blueprint(challenges_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error_body(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        status = exc.code or 500
        if status == 400:
            error_id = "ERR_INVALID_REQUEST"
        elif status in (404, 405):
            error_id = "ERR_NOT_FOUND"
        else:
            error_id = "ERR_INVALID_REQUEST"
        return response.error_body(error_id, exc.description or error_id, status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover
        return response.error_body("ERR_INVALID_REQUEST", str(exc), 400)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)
