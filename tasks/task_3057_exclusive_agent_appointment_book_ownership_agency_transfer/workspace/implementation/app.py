"""Application entry point.

Boots the exclusive-agency-appointment API.  The store starts EMPTY: nothing is
seeded, preloaded, registered or hardcoded here or anywhere else at import time.
Every entity a client needs is created by that client through the declared API.

Start-up also resets the logical clock to 2026-09-01T00:00:00Z; the server never
consults wall-clock time before the first /_clock/set_current_utc call.
"""

import os

from flask import Flask, request
from werkzeug.exceptions import HTTPException

import clock
import db
from errors import ApiError
from response import error_response

from routes import (
    agencies, agents, agreements, applications, claims, policies, records, staff,
    system,
)


def create_app():
    # Fresh process -> empty store, clock back to its startup instant.
    db.reset()
    clock.install()

    app = Flask(__name__)
    app.url_map.strict_slashes = False

    system.register(app)
    agencies.register(app)
    applications.register(app)
    agents.register(app)
    agreements.register(app)
    staff.register(app)
    policies.register(app)
    claims.register(app)
    records.register(app)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        error_id = "ERR_HTTP_%d" % exc.code if exc.code else "ERR_HTTP_ERROR"
        return error_response(error_id, exc.description or str(exc), exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INTERNAL", str(exc), 500)

    @app.route("/agency-network/_health", methods=["GET"])
    def health():
        return {"status": "ok"}, 200

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)