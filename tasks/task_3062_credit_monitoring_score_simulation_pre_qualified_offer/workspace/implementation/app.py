"""Flask entry point: blueprint registration and the error envelope."""

import os
import traceback
from datetime import datetime

from flask import Flask, jsonify
from flask.json.provider import DefaultJSONProvider

import store
from envelope import error_body, timestamp
from errors import ApiError


class IsoJSONProvider(DefaultJSONProvider):
    """Serialise every datetime as ISO 8601 UTC with three fractional digits."""

    @staticmethod
    def default(obj):
        if isinstance(obj, datetime):
            return timestamp(obj)
        return DefaultJSONProvider.default(obj)

import consumers
import monitoring
import simulation
import catalog
import lenders
import prequal
import consent
import offers
import referrals
import disputes
import opsrun

PREFIX = "/credit"

BLUEPRINTS = (
    consumers.bp,
    monitoring.bp,
    simulation.bp,
    catalog.bp,
    lenders.bp,
    prequal.bp,
    consent.bp,
    offers.bp,
    referrals.bp,
    disputes.bp,
    opsrun.bp,
)


def create_app():
    app = Flask(__name__)
    app.json = IsoJSONProvider(app)
    app.url_map.strict_slashes = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message, store.now())), exc.http_status

    @app.errorhandler(404)
    def handle_404(exc):
        return jsonify(error_body("ERR_CONSUMER_NOT_FOUND",
                                  "The requested path did not resolve.", store.now())), 404

    @app.errorhandler(405)
    def handle_405(exc):
        return jsonify(error_body("ERR_INVALID_REQUEST",
                                  "The HTTP method is not allowed on this path.", store.now())), 405

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        traceback.print_exc()
        return jsonify(error_body("ERR_INVALID_REQUEST",
                                  "The request could not be processed.", store.now())), 400

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))