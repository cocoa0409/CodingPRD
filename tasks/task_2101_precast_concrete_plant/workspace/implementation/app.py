"""Precast Concrete Plant API - Flask entry point.

In-memory only: the store is empty on every process boot. Nothing is seeded,
preloaded or hardcoded; every row is created by a client through the declared
API surface.
"""
import os
from decimal import Decimal

from flask import Flask
from flask.json.provider import DefaultJSONProvider

import db
import errors
from response import error_response
from routes.plant import bp as plant_bp
from routes.mix import bp as mix_bp
from routes.runs import bp as runs_bp
from routes.cylinders import bp as cylinders_bp
from routes.pieces import bp as pieces_bp
from routes.yard import bp as yard_bp
from routes.shipping import bp as shipping_bp
from routes.repairs import bp as repairs_bp


class PlantJSONProvider(DefaultJSONProvider):
    """Decimals are emitted as JSON numbers, never as strings."""

    @staticmethod
    def default(obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return DefaultJSONProvider.default(obj)


def create_app():
    app = Flask(__name__)
    app.json = PlantJSONProvider(app)
    app.json.sort_keys = False
    app.url_map.strict_slashes = False

    app.register_blueprint(plant_bp)
    app.register_blueprint(mix_bp)
    app.register_blueprint(runs_bp)
    app.register_blueprint(cylinders_bp)
    app.register_blueprint(pieces_bp)
    app.register_blueprint(yard_bp)
    app.register_blueprint(shipping_bp)
    app.register_blueprint(repairs_bp)

    @app.before_request
    def _serialise_requests():
        # One request at a time: every handler mutates the shared in-memory
        # store, and the envelope's derived counters must never observe a
        # half-applied cascade.
        db.store.lock.acquire()

    @app.teardown_request
    def _release_request_lock(_exc=None):
        try:
            db.store.lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_unknown_route(_exc):
        return error_response("ERR_NOT_FOUND", "Unknown route.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_exc):
        return error_response("ERR_NOT_FOUND", "Unknown route.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, errors.ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
