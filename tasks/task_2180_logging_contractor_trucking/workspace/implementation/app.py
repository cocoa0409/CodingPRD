"""Entry point: registers every route group and the global error handlers.

The in-memory store starts completely empty on every boot -- nothing is seeded,
preloaded or hardcoded.  Every entity a test needs is built through the declared
API surface.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, error_response
import routes_ref
import routes_tract
import routes_load
import routes_settlement


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(routes_ref.bp)
    app.register_blueprint(routes_tract.bp)
    app.register_blueprint(routes_load.bp)
    app.register_blueprint(routes_settlement.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 404:
            return error_response("ERR_VALIDATION", "no such route")
        if exc.code == 405:
            return error_response("ERR_VALIDATION", "method not allowed")
        if exc.code == 400:
            return error_response("ERR_VALIDATION", "malformed request")
        return error_response("ERR_VALIDATION", exc.description or "request failed")

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("unhandled error")
        return error_response("ERR_VALIDATION", "unexpected server error: %s" % exc)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
