"""Entry point: Flask app, error handlers and route registration.

Nothing is seeded here. The store is born empty on every process start, so a
fresh `bash start.sh` wipes every byte of state.
"""

import os

from flask import Flask, jsonify

import db
import response as R
import routes
from errors import ApiError
from services import community as community_svc


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(R.error(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return jsonify(R.error("ERR_NOT_FOUND", "the requested path does not resolve")), 404

    @app.errorhandler(405)
    def handle_method(_exc):
        return jsonify(R.error("ERR_INVALID_REQUEST", "method not allowed")), 405

    @app.errorhandler(400)
    def handle_bad_request(_exc):
        return jsonify(R.error("ERR_INVALID_REQUEST", "malformed request")), 400

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return jsonify(R.error(exc.error_id, exc.message)), exc.http_status
        app.logger.exception("unhandled error")
        return jsonify(R.error("ERR_INVALID_REQUEST", "the request could not be processed")), 400

    routes.register(app)
    db.reset()

    @app.before_request
    def _settle_time_driven():
        # Every window (handover deadline, watchdog, negotiation lapse) is
        # measured against the logical clock, so the sweep runs whenever the
        # clock has advanced past the last settled value.
        community_svc.settle_if_clock_moved()

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)