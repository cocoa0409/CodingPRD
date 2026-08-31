"""Food Recall Execution & Effectiveness Check API — entry point.

Storage is entirely in-memory and starts EMPTY on every boot. No entity is
seeded, preloaded or hardcoded here; every row is created by a client through
the declared endpoints.
"""
import os
import threading

from flask import Flask, g

from core import ApiError, error_response
import routes_recall
import routes_hazard
import routes_notify
import routes_report
import routes_cost

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

_LOCK = threading.RLock()

app.register_blueprint(routes_recall.bp)
app.register_blueprint(routes_hazard.bp)
app.register_blueprint(routes_notify.bp)
app.register_blueprint(routes_report.bp)
app.register_blueprint(routes_cost.bp)


@app.before_request
def _acquire():
    _LOCK.acquire()
    g.holds_lock = True
    g.dirty_rows = {}
    g.fresh_rows = set()


@app.teardown_request
def _release(exc=None):
    if getattr(g, "holds_lock", False):
        g.holds_lock = False
        try:
            _LOCK.release()
        except RuntimeError:
            pass


@app.errorhandler(ApiError)
def _api_error(exc):
    return error_response(exc.error_id, exc.message)


@app.errorhandler(404)
def _not_found(exc):
    return error_response("ERR_SUBRESOURCE_NOT_FOUND", "The requested resource does not exist")


@app.errorhandler(405)
def _bad_method(exc):
    return error_response("ERR_INVALID_REQUEST", "Method not allowed for this path")


@app.errorhandler(400)
def _bad_request(exc):
    return error_response("ERR_INVALID_REQUEST", "The request could not be understood")


@app.errorhandler(Exception)
def _unhandled(exc):
    if isinstance(exc, ApiError):
        return error_response(exc.error_id, exc.message)
    app.logger.exception("unhandled error")
    return error_response("ERR_INVALID_REQUEST", "Unhandled server error: %s" % exc)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
