"""Wholesale Auction Arbitration API — Flask application entry point.

Storage is in-memory only and starts completely empty on every boot: no rows are
seeded, preloaded or hardcoded anywhere. The logical clock starts at its declared
startup default and only an AuctionAdmin can move it.
"""
import os

from flask import Flask, g, jsonify
from werkzeug.exceptions import HTTPException

import r_adjudication
import r_cases
import r_negotiation
import r_ops
import r_psi
import r_registry
import r_sales
from envelope import error
from errors import ApiError
from store import store


class _Serialize(object):
    """One request at a time, so cascades stay atomic under a threaded server."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        with store.lock:
            return self.wsgi_app(environ, start_response)


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False
    app.url_map.strict_slashes = False
    app.wsgi_app = _Serialize(app.wsgi_app)

    for module in (r_registry, r_sales, r_psi, r_cases, r_negotiation,
                   r_adjudication, r_ops):
        app.register_blueprint(module.bp)

    @app.before_request
    def _reset_touch_set():
        g._touched = set()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        return error("ERR_INVALID_REQUEST", exc.description, exc.code or 400)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        return jsonify({
            "meta": {},
            "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(exc)},
        }), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
