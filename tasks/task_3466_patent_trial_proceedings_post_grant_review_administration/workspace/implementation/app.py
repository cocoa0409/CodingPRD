"""PTAB docket API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000) in the foreground. The store starts empty
on every boot; all state is in-memory and constructed through the API.
"""

import os

from flask import Flask

from db import store
from errors import ApiError
from helpers import error_response
from routes import ALL_BLUEPRINTS

app = Flask(__name__)
app.url_map.strict_slashes = False

for bp in ALL_BLUEPRINTS:
    app.register_blueprint(bp)


@app.before_request
def _acquire_store_lock():
    store.lock.acquire()


@app.teardown_request
def _release_store_lock(exc):
    try:
        store.lock.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _handle_404(err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "route not found"))


@app.errorhandler(405)
def _handle_405(err):
    return error_response(
        ApiError("ERR_METHOD_NOT_ALLOWED", 405, "method not allowed"))


@app.errorhandler(Exception)
def _handle_unexpected(err):
    app.logger.exception("unexpected error")
    return error_response(ApiError("ERR_INTERNAL", 500, str(err)))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
