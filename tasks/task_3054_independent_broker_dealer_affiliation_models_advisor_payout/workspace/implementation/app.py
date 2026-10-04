"""Broker Dealer Advisor Payout API - application entry point.

In-memory only: no database file, no JSON dump, no cache.  Every store starts
empty on each boot, so re-invoking start.sh wipes all state.
"""

import os
import uuid

import flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error as error_response


def create_app():
    app = flask.Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    import routes
    routes.register(app)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        return error_response("ERR_NOT_FOUND", "The addressed resource does not exist.",
                              exc.code or 404)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        app.logger.exception("Unhandled error: %s", exc)
        return error_response("ERR_INVALID_REQUEST",
                              "The request could not be processed.", 400)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False)