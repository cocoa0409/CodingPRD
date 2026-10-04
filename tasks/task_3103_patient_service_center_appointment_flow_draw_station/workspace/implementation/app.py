"""Patient Service Center Draw Station API — Flask entry point.

Boots with a completely empty store. Every entity a caller needs is created
through the declared API surface; nothing is seeded at startup.
"""

import os
import traceback

from flask import Flask, request
from werkzeug.exceptions import HTTPException

from core import (
    ApiError, ERROR_STATUS, MESSAGES, ok, _meta, db, DEFAULT_CLOCK_DT,
    require_auth, read_pagination, set_clock,
)

import routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _pagination():
        read_pagination()

    @app.route("/_health", methods=["GET"])
    def health():
        return ok({"status": "ok"})

    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_current_utc():
        require_auth({"CenterSupervisor", "LabSystem"})
        from core import parse_iso, iso
        payload = request.get_json(silent=True) or {}
        if "current_utc" not in payload:
            raise ApiError("ERR_INVALID_REQUEST", "current_utc is required")
        dt = parse_iso(payload["current_utc"])
        if dt is None:
            raise ApiError("ERR_INVALID_REQUEST", "current_utc is invalid")
        set_clock(dt)
        db.runtime["clock"] = dt
        return ok({"current_utc": iso(dt)})

    routes.register(app)

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        body = {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": err.error_id, "message": err.message},
        }
        return body, err.http_status

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        if isinstance(err, HTTPException):
            body = {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": "ERR_INVALID_REQUEST",
                         "message": err.description},
            }
            return body, err.code
        traceback.print_exc()
        body = {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_INVALID_REQUEST",
                     "message": str(err)},
        }
        return body, 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)