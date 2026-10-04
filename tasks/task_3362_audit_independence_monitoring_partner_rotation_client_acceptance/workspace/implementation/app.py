"""Audit independence monitoring API — application entry point.

The store is in-memory and starts empty on every boot; nothing is seeded.
"""

import os
import threading

from flask import Flask, jsonify, request

from core.errors import ERR_INVALID_REQUEST, ApiError
from core.response import error_body
from routes import (
    acceptances,
    assignments,
    attestations,
    clock,
    engagements,
    findings,
    naf,
    reference,
    reviews,
    threats,
)

BLUEPRINTS = (
    reference.bp,
    engagements.bp,
    acceptances.bp,
    assignments.bp,
    findings.bp,
    threats.bp,
    naf.bp,
    attestations.bp,
    reviews.bp,
    clock.bp,
)

_store_lock = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except Exception:
        pass

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix="/audit")

    @app.before_request
    def _serialize_requests():
        _store_lock.acquire()

    @app.teardown_request
    def _release_requests(exception=None):
        try:
            _store_lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _handle_api_error(error):
        return jsonify(error_body(error.error_id, error.message)), error.http_status

    @app.errorhandler(404)
    def _handle_not_found(error):
        return jsonify(error_body(ERR_INVALID_REQUEST, "No such endpoint.")), 404

    @app.errorhandler(405)
    def _handle_method_not_allowed(error):
        return jsonify(error_body(ERR_INVALID_REQUEST, "Method not allowed.")), 405

    @app.errorhandler(Exception)
    def _handle_unexpected(error):
        if isinstance(error, ApiError):
            return jsonify(error_body(error.error_id, error.message)), error.http_status
        return jsonify(error_body(ERR_INVALID_REQUEST, "Unexpected server error.")), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        debug=False,
        use_reloader=False,
    )
