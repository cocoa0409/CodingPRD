"""Store Rebate Certificate Program & Store-Credit Liability API.

Python + Flask, in-memory storage only.  The store is empty on every boot:
no entity is seeded, preloaded, registered or hardcoded at startup.
"""

import os
from decimal import Decimal

from flask import Flask
from werkzeug.exceptions import HTTPException
from werkzeug.serving import WSGIRequestHandler

from errors import ApiError
from response import error_response

from routes.accounts import bp as accounts_bp
from routes.certificates import bp as certificates_bp
from routes.clock import bp as clock_bp
from routes.ops import bp as ops_bp
from routes.programs import bp as programs_bp
from routes.receipts import bp as receipts_bp
from routes.stores import bp as stores_bp
from routes.submissions import bp as submissions_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    try:  # Flask >= 2.2 JSON provider
        from flask.json.provider import DefaultJSONProvider

        class DomainJSONProvider(DefaultJSONProvider):
            sort_keys = False

            @staticmethod
            def default(obj):
                if isinstance(obj, Decimal):
                    return float(obj)
                return DefaultJSONProvider.default(obj)

        app.json = DomainJSONProvider(app)
    except Exception:  # pragma: no cover - older Flask
        app.config["JSON_SORT_KEYS"] = False

    for blueprint in (
        clock_bp,
        stores_bp,
        programs_bp,
        accounts_bp,
        receipts_bp,
        submissions_bp,
        certificates_bp,
        ops_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found", 404)
        if exc.code == 405:
            return error_response("ERR_INVALID_REQUEST",
                                  "Method not allowed for this route", 405)
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST",
                                  "Request could not be parsed", 400)
        return error_response("ERR_INVALID_REQUEST",
                              exc.description or "Request failed",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover
        app.logger.exception("Unhandled error: %s", exc)
        return error_response("ERR_INVALID_REQUEST",
                              "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


class _SequentialHandler(WSGIRequestHandler):
    """The benchmark drives this server one request at a time.  Serving each
    request with 'Connection: close' (HTTP/1.0 semantics) removes the
    keep-alive window in which the dev server could hold an idle connection
    whose client end has already gone away (which surfaces as ECONNRESET on
    the next request under heavy parallel load)."""

    protocol_version = "HTTP/1.0"

    def send_headers(self):
        super().send_headers()
        # No-op for 1.0 semantics; header added explicitly for clarity.
        # (HTTP/1.0 defaults to closing the connection.)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False,
            request_handler=_SequentialHandler)
