"""CCR Closure & Groundwater Monitoring API.

Storage is in-memory only and nothing is ever seeded: every process start
begins with an empty store and the logical clock at 2026-08-01T00:00:00Z.
"""
import os

from flask import Flask, Response, g

import envelope
import store
from errors import ApiError
import routes_care
import routes_closure
import routes_monitoring
import routes_read
import routes_reuse
import routes_stats
import routes_units


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.register_blueprint(routes_read.bp)
    app.register_blueprint(routes_units.bp)
    app.register_blueprint(routes_monitoring.bp)
    app.register_blueprint(routes_stats.bp)
    app.register_blueprint(routes_closure.bp)
    app.register_blueprint(routes_reuse.bp)
    app.register_blueprint(routes_care.bp)

    @app.before_request
    def _acquire():
        store.LOCK.acquire()
        g._locked = True

    @app.teardown_request
    def _release(exc=None):
        if getattr(g, "_locked", False):
            g._locked = False
            try:
                store.LOCK.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(err):
        return envelope.error(err)

    @app.errorhandler(404)
    def _not_found(err):
        return _plain("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def _not_allowed(err):
        return _plain("ERR_METHOD_NOT_ALLOWED",
                      "The method is not allowed for this resource.", 405)

    @app.errorhandler(Exception)
    def _unhandled(err):
        if isinstance(err, ApiError):
            return envelope.error(err)
        return _plain("ERR_INTERNAL", str(err) or "Unexpected server error.", 500)

    return app


def _plain(error_id, message, status):
    import json
    body = {
        "meta": {
            "api_request_id": store.request_id(),
            "api_request_timestamp": store.iso_instant(store.wall_now()),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return Response(json.dumps(body), status=status, mimetype="application/json")


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
