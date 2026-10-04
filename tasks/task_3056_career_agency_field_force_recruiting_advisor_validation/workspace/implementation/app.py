"""Career Agency Field Force API — entry point.

Boots a Flask server on 0.0.0.0:$PORT (default 10000). The in-memory store
starts empty on every boot: no entity is seeded, preloaded or hardcoded here.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_PAGINATION_PARAMETERS
from middleware import ROLES  # noqa: F401  (import-time validation of role set)
from response import err_body

from routes import advisors, candidates, clock, contracts, licensing, offices, policies


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["PROPAGATE_EXCEPTIONS"] = True

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return err_body(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return err_body(ERR_INVALID_REQUEST, "no such route", 400)

    @app.errorhandler(405)
    def handle_method(exc):
        return err_body(ERR_INVALID_REQUEST, "method not allowed", 400)

    @app.errorhandler(400)
    def handle_bad_request(exc):
        return err_body(ERR_INVALID_REQUEST, "malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, HTTPException):
            return err_body(ERR_INVALID_REQUEST, exc.description or "request error",
                            exc.code or 400)
        app.logger.exception("unhandled error")
        return err_body(ERR_INVALID_REQUEST, str(exc), 400)

    for module in (clock, offices, advisors, candidates, contracts, licensing, policies):
        app.register_blueprint(module.bp)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)