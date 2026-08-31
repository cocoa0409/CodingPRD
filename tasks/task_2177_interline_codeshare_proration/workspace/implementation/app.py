"""Interline & Codeshare Revenue Proration API — entry point.

The in-memory store starts empty on every boot; no entity is ever seeded.
"""

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from errors import ApiError  # noqa: E402
from responses import error_response  # noqa: E402
from routes.agreements import bp as agreements_bp  # noqa: E402
from routes.audits import bp as audits_bp  # noqa: E402
from routes.carriers import bp as carriers_bp  # noqa: E402
from routes.coupons import bp as coupons_bp  # noqa: E402
from routes.invoices import bp as invoices_bp  # noqa: E402
from routes.memos import bp as memos_bp  # noqa: E402
from routes.periods import bp as periods_bp  # noqa: E402
from routes.tickets import bp as tickets_bp  # noqa: E402


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except Exception:  # pragma: no cover - older Flask
        app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(carriers_bp)
    app.register_blueprint(agreements_bp)
    app.register_blueprint(periods_bp)
    app.register_blueprint(tickets_bp)
    app.register_blueprint(coupons_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(memos_bp)
    app.register_blueprint(audits_bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found.", 404)
        if exc.code == 405:
            return error_response("ERR_METHOD_NOT_ALLOWED",
                                  "Method not allowed.", 405)
        if exc.code in (400, 415):
            return error_response("ERR_INVALID_REQUEST",
                                  "The request payload is malformed.", 400)
        return error_response("ERR_INTERNAL", exc.description or "Error.",
                              exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        app.logger.exception("unhandled error")
        return error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
