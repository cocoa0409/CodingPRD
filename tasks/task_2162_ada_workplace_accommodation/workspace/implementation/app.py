"""ADA Workplace Accommodation API - entry point."""
import os
import threading

from flask import Flask, g, jsonify

from envelope import error_response, _meta
from errors import ApiError

import r_appeals
import r_cases
import r_docs
import r_ops
import r_options
import r_trials
import r_workforce

_lock = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (r_workforce, r_cases, r_docs, r_options, r_trials, r_appeals, r_ops):
        app.register_blueprint(module.bp)

    @app.before_request
    def _acquire():
        _lock.acquire()
        g._locked = True

    @app.teardown_request
    def _release(exc=None):
        if getattr(g, "_locked", False):
            g._locked = False
            try:
                _lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _not_found(err):
        payload = {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_INVALID_REQUEST",
                     "message": "No such route."},
        }
        return jsonify(payload), 404

    @app.errorhandler(405)
    def _not_allowed(err):
        payload = {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_INVALID_REQUEST",
                     "message": "Method not allowed on this route."},
        }
        return jsonify(payload), 405

    @app.errorhandler(Exception)
    def _unhandled(err):
        if isinstance(err, ApiError):
            return error_response(err)
        payload = {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_INVALID_REQUEST", "message": str(err)},
        }
        return jsonify(payload), 400

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
