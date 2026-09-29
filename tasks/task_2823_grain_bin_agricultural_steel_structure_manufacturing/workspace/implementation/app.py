"""Grain Bin Manufacturing API. Entry point, request lock, error handlers."""
import os
import threading

from flask import Flask, g

from envelope import error_body
from errors import ApiError, ERROR_HTTP_STATUS
import routes_config
import routes_designs
import routes_failures
import routes_freight
import routes_orders
import routes_parties
import routes_production

app = Flask(__name__)
app.url_map.strict_slashes = False

# The plant runs an immediate-consistency model with multi-row cascades, so one
# request at a time mutates the store.
_request_lock = threading.Lock()


@app.before_request
def _begin_request():
    _request_lock.acquire()
    g._locked = True
    # Request-scoped set: a row touched several times in one request still
    # advances its version by exactly 1.
    g.touched = set()


@app.teardown_request
def _end_request(_exception=None):
    if getattr(g, "_locked", False):
        g._locked = False
        try:
            _request_lock.release()
        except RuntimeError:
            pass


def _emit(error_id, message, status):
    body = error_body(error_id, message)
    return app.response_class(
        response=app.json.dumps(body) + "\n",
        status=status,
        mimetype="application/json",
    )


@app.errorhandler(ApiError)
def _handle_api_error(error):
    return _emit(error.error_id, error.message, error.http_status)


@app.errorhandler(404)
def _handle_404(_error):
    return _emit("ERR_INVALID_REQUEST", "The requested resource does not exist.", 404)


@app.errorhandler(405)
def _handle_405(_error):
    return _emit("ERR_INVALID_REQUEST", "The method is not allowed for this path.", 405)


@app.errorhandler(400)
def _handle_400(_error):
    return _emit("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)


@app.errorhandler(Exception)
def _handle_unexpected(error):
    if isinstance(error, ApiError):
        return _handle_api_error(error)
    status = getattr(error, "code", None)
    if isinstance(status, int) and 400 <= status < 600:
        return _emit("ERR_INVALID_REQUEST", str(error), status)
    return _emit("ERR_INVALID_REQUEST", "Unexpected server error: %s" % error, 500)


for blueprint in (
    routes_config.bp,
    routes_parties.bp,
    routes_designs.bp,
    routes_production.bp,
    routes_orders.bp,
    routes_freight.bp,
    routes_failures.bp,
):
    app.register_blueprint(blueprint)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
