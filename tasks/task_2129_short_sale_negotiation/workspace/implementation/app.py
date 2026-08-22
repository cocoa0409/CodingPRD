"""Short Sale Negotiation API — Flask entry point.

Storage is entirely in-memory (see db.py): nothing is written to disk and no
entity is seeded at startup.  Every boot starts from an empty store with the
logical clock at its declared 2026-08-01T00:00:00Z default.
"""
import os
import threading

from flask import Flask, g, jsonify
from werkzeug.exceptions import HTTPException

from db import db
from envelope import error_body
from errors import ApiError
from routes.approvals import bp as approvals_bp
from routes.cases import bp as cases_bp
from routes.liens_mi import bp as liens_mi_bp
from routes.listings import bp as listings_bp
from routes.offers import bp as offers_bp
from routes.packages import bp as packages_bp
from routes.platform import bp as platform_bp
from routes.valuations import bp as valuations_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (
        platform_bp,
        cases_bp,
        packages_bp,
        listings_bp,
        offers_bp,
        valuations_bp,
        liens_mi_bp,
        approvals_bp,
    ):
        app.register_blueprint(blueprint)

    # The store's per-request version tracking is global state, so business
    # logic is serialized even though the socket layer is threaded.
    request_lock = threading.Lock()

    @app.before_request
    def _begin():
        request_lock.acquire()
        g._holds_request_lock = True
        db.begin_request()

    @app.teardown_request
    def _end(exc=None):
        if g.pop("_holds_request_lock", False):
            try:
                request_lock.release()
            except RuntimeError:  # pragma: no cover - defensive
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 405:
            return jsonify(error_body("ERR_METHOD_NOT_ALLOWED", "Method not allowed.")), 405
        if exc.code == 404:
            return jsonify(error_body("ERR_NOT_FOUND", "No such route.")), 404
        return (
            jsonify(error_body("ERR_INVALID_REQUEST", exc.description or "Bad request.")),
            exc.code or 400,
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        app.logger.exception("unhandled error")
        return jsonify(error_body("ERR_INVALID_REQUEST", str(exc))), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
