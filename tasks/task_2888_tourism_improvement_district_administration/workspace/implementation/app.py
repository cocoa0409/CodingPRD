"""Tourism Improvement District Administration API.

A single Flask process holding every byte of its state in memory: re-invoking
start.sh wipes the store completely.  Nothing is seeded anywhere.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import envelope
import store
from errors import ApiError

from routes import (
    businesses,
    clock,
    disputes,
    districts,
    periods,
    petitions,
    programs,
    statements,
    transparency,
    workplans,
)

BLUEPRINTS = (
    districts.bp,
    businesses.bp,
    petitions.bp,
    periods.bp,
    statements.bp,
    disputes.bp,
    workplans.bp,
    programs.bp,
    transparency.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _begin_request():
        store.begin_request()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return jsonify(envelope.error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        return (jsonify(envelope.error_body("ERR_INVALID_REQUEST",
                                            exc.description or exc.name)),
                exc.code)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        return jsonify(envelope.error_body("ERR_INVALID_REQUEST", str(exc))), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            debug=False, use_reloader=False, threaded=True)
