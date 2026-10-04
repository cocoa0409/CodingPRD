"""Entry point: blueprint registration, error handling and the WSGI bootstrap."""
from __future__ import annotations

import os
import sys
import traceback

from flask import Flask, jsonify, request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from errors import ApiError  # noqa: E402
from response import err_response  # noqa: E402
from util import fmt_ts, new_id, now  # noqa: E402

from routes import claims, clinicians, continuity, patients, payers, payouts, sessions  # noqa: E402


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    app.register_blueprint(clinicians.bp, url_prefix="/network")
    app.register_blueprint(payers.bp, url_prefix="/network")
    app.register_blueprint(patients.bp, url_prefix="/network")
    app.register_blueprint(sessions.bp, url_prefix="/network")
    app.register_blueprint(claims.bp, url_prefix="/network")
    app.register_blueprint(payouts.bp, url_prefix="/network")
    app.register_blueprint(continuity.bp, url_prefix="/network")

    @app.errorhandler(ApiError)
    def _api_error(exc: ApiError):
        return err_response(exc.error_id, exc.status, exc.message)

    @app.errorhandler(404)
    def _not_found(_exc):
        return err_response("ERR_INVALID_REQUEST", 400, f"No route matches {request.path}.")

    @app.errorhandler(405)
    def _not_allowed(_exc):
        return err_response("ERR_INVALID_REQUEST", 400, f"Method not allowed on {request.path}.")

    @app.errorhandler(Exception)
    def _unexpected(exc: Exception):
        traceback.print_exc()
        return err_response("ERR_INVALID_REQUEST", 400, "The request could not be processed.")

    @app.get("/health")
    def _health():
        return jsonify({"status": "ok", "api_request_id": new_id(), "timestamp": fmt_ts(now())}), 200

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)