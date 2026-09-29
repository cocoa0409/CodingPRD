"""Build-To-Rent Leaseup API.

The store is process-local and in-memory. It starts completely empty on every boot:
nothing is seeded, preloaded or hardcoded here or in any module. Every entity a
caller needs is created through the endpoints declared in PRD section 4.
"""
from __future__ import annotations

import os
import sys
import traceback

from flask import Flask, g, jsonify
from werkzeug.exceptions import HTTPException

from db import store
from errors import ApiError
from response import error_envelope
from routes import (clock, communities, homesites, households, leases, phases, pricing_routes,
                    reads, turns)

DEFAULT_PORT = "10000"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(reads.bp)
    app.register_blueprint(communities.bp)
    app.register_blueprint(phases.bp)
    app.register_blueprint(homesites.bp)
    app.register_blueprint(pricing_routes.bp)
    app.register_blueprint(households.bp)
    app.register_blueprint(leases.bp)
    app.register_blueprint(turns.bp)
    app.register_blueprint(clock.bp)

    @app.before_request
    def _serialize_requests():
        # One request at a time: every cascade in this specification completes
        # inside its originating request, so requests never interleave.
        store.lock.acquire()
        g.holds_store_lock = True

    @app.teardown_request
    def _release(exception=None):
        if g.pop("holds_store_lock", False):
            try:
                store.lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _handle_api_error(error):
        return jsonify(error_envelope(error.error_id, error.message)), error.http_status

    @app.errorhandler(HTTPException)
    def _handle_http_error(error):
        return (jsonify(error_envelope("ERR_INVALID_REQUEST", error.description)),
                error.code or 400)

    @app.errorhandler(Exception)
    def _handle_unexpected(error):
        traceback.print_exc(file=sys.stderr)
        return (jsonify(error_envelope("ERR_INTERNAL_SERVER_ERROR", str(error))), 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", DEFAULT_PORT)),
            threaded=True, use_reloader=False)
