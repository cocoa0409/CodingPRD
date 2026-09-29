"""GPO Rebate Administration API - Flask application factory and entry point.

State lives in process memory only (see store.py): every boot starts empty and
nothing is seeded, so re-invoking start.sh wipes every byte of state.
"""

import os
import traceback

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import store
from envelope import error
from errors import ApiError
from routes_deals import bp as deals_bp
from routes_feed import bp as feed_bp
from routes_rebate import bp as rebate_bp
from routes_reference import bp as reference_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    app.register_blueprint(reference_bp)
    app.register_blueprint(deals_bp)
    app.register_blueprint(feed_bp)
    app.register_blueprint(rebate_bp)

    @app.before_request
    def _begin():
        # One request at a time: every cascade in this system must be fully
        # visible to the next read, so requests are serialized on a single lock.
        store.LOCK.acquire()
        g._store_lock_held = True
        store.begin_request()

    @app.teardown_request
    def _end(exc):
        if g.pop("_store_lock_held", False):
            try:
                store.LOCK.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error(err.error_id, err.message, err.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        return error("ERR_INVALID_REQUEST", err.description or "Invalid request",
                     err.code or 400)

    @app.errorhandler(Exception)
    def _unhandled(err):
        # Genuine defects must be loud, not disguised as a declared error.
        traceback.print_exc()
        return error("ERR_INTERNAL", "%s: %s" % (type(err).__name__, err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
