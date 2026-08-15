"""Flask entry point: app factory, error handlers, request serialization lock.

State lives entirely in process memory (store.py); every boot starts pristine.
"""

import os
import threading

from flask import Flask

from envelope import error_response
from errors import ApiError
from routes import ALL_BLUEPRINTS

_LOCK = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)

    @app.before_request
    def _acquire_lock():
        # Serialize requests so derived fields and OCC checks are consistent.
        _LOCK.acquire()

    @app.teardown_request
    def _release_lock(exc):
        _LOCK.release()

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def _not_found(err):
        return error_response("ERR_NOT_FOUND", 404, "resource not found")

    @app.errorhandler(405)
    def _method_not_allowed(err):
        return error_response("ERR_NOT_FOUND", 405, "method not allowed")

    @app.errorhandler(Exception)
    def _unhandled(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.http_status, err.message)
        app.logger.exception("unhandled error")
        return error_response("ERR_INTERNAL", 500, "internal server error: %s" % err)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
