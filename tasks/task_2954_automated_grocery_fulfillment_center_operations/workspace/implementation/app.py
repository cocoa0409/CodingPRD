"""Automated Grocery Fulfillment Center Operations API.

Boots with a completely empty in-memory store: no seeding, no preloading, no
persistence of any kind. Every entity is created by callers through the
endpoints declared in the PRD.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import db as store
from errors import ApiError
import response as resp
from routes import orders, plant, slots, subs, waves


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.register_blueprint(plant.bp)
    app.register_blueprint(slots.bp)
    app.register_blueprint(orders.bp)
    app.register_blueprint(waves.bp)
    app.register_blueprint(subs.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        store.abort_request()
        return resp.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        store.abort_request()
        return resp.error_response(
            "ERR_INVALID_REQUEST", exc.description or "request could not be served",
            exc.code or 400,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        store.abort_request()
        return resp.error_response(
            "ERR_INVALID_REQUEST", "unexpected server error: %s" % exc, 422
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
