"""Multistate Settlement Coordination API — Flask entry point.

Mounts every resource under /multistate except the logical-clock endpoint
POST /_clock/set_current_utc (PRD §2.4). In-memory store; nothing is seeded.
"""
import os
import traceback

from flask import Flask
from werkzeug.exceptions import HTTPException

import db
import envelope
import errors
import routes_claimants
import routes_demands_responses
import routes_investigations
import routes_lines_disbursements
import routes_monitoring
import routes_offices
import routes_participations
import routes_settlement_flow
import routes_settlements


def create_app():
    app = Flask(__name__)

    # Serialize requests through one reentrant lock: pytest drives the server
    # sequentially, and this keeps cascades atomic even under threaded Flask.
    @app.before_request
    def _acquire_lock():
        db._lock.acquire()

    @app.teardown_request
    def _release_lock(_exc):
        db._lock.release()

    app.register_blueprint(routes_offices.bp_clock)  # /_clock/... (unprefixed)
    app.register_blueprint(routes_offices.bp)
    app.register_blueprint(routes_investigations.bp)
    app.register_blueprint(routes_participations.bp)
    app.register_blueprint(routes_demands_responses.bp)
    app.register_blueprint(routes_settlements.bp)
    app.register_blueprint(routes_settlement_flow.bp)
    app.register_blueprint(routes_lines_disbursements.bp)
    app.register_blueprint(routes_claimants.bp)
    app.register_blueprint(routes_monitoring.bp)

    @app.errorhandler(errors.ApiError)
    def _api_error(err):
        return envelope.error_response(err)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        # Unmatched routes / wrong methods still answer with the envelope.
        wrapped = errors.ApiError(
            "ERR_INVALID_REQUEST", err.code or 500, err.description or "HTTP error"
        )
        return envelope.error_response(wrapped)

    @app.errorhandler(Exception)
    def _unhandled(err):
        traceback.print_exc()
        wrapped = errors.ApiError("ERR_INTERNAL", 500, f"Internal error: {err}")
        return envelope.error_response(wrapped)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
