"""Driver Recruiting DQ File API — entry point.

Storage is entirely in-memory and starts empty on every boot: no entity is
seeded, preloaded or hardcoded anywhere in this process.
"""
import os
import threading

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import routes_a
import routes_b
import routes_c
import routes_d
from core import ApiError, error_response

# Requests are serialised so that read-modify-write sequences (optimistic
# concurrency checks, seat arithmetic, cascades) stay atomic when the harness
# fires concurrent requests at the server.
_REQUEST_LOCK = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    @app.before_request
    def _init_request_state():
        _REQUEST_LOCK.acquire()
        g.holds_lock = True
        g.touched = set()
        g.user_id = None
        g.user_role = None

    @app.teardown_request
    def _release_request_state(exc=None):
        if g.pop("holds_lock", False):
            try:
                _REQUEST_LOCK.release()
            except RuntimeError:
                pass

    routes_a.register(app)
    routes_b.register(app)
    routes_c.register(app)
    routes_d.register(app)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response("ERR_VALIDATION", "Unknown route.", 404)
        if exc.code == 405:
            return error_response("ERR_VALIDATION", "Method not allowed.", 405)
        return error_response("ERR_VALIDATION", exc.description or "Request error.",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return error_response("ERR_VALIDATION", "Unexpected server error: %s" % exc,
                              500)

    return app


application = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    application.run(host="0.0.0.0", port=port, threaded=True, debug=False,
                    use_reloader=False)
