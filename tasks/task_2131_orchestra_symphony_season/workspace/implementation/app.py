"""Orchestra Symphony Season API — entry point.

Storage is in-memory only and starts completely empty on every boot; no entity
is ever seeded, preloaded or hardcoded at startup.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error
from routes import (adbookings, clock, concerts, contracts, engagements,
                    musicians, patrons, rehearsals, seasons, subscriptions,
                    tickets, union, venues)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (seasons, venues, union, concerts, contracts, musicians,
                   rehearsals, engagements, patrons, subscriptions, tickets,
                   adbookings, clock):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error("ERR_INVALID_REQUEST", "Resource not found.", 404)
        if exc.code == 405:
            return error("ERR_INVALID_REQUEST", "Method not allowed.", 405)
        if exc.code and 400 <= exc.code < 500:
            return error("ERR_INVALID_REQUEST", exc.description or "Bad request.", 422)
        return error("ERR_INVALID_REQUEST", "Internal error.", 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        app.logger.exception("unhandled error")
        return error("ERR_INVALID_REQUEST", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
