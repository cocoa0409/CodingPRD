"""Flask app entry point."""

import os
from flask import Flask

from db import lock
from errors import ApiError, ERRORS
from response import error_response

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_INVALID_REQUEST", "route not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_INVALID_REQUEST", "method not allowed", 405)


@app.errorhandler(500)
def handle_500(e):
    return error_response("ERR_INVALID_REQUEST", "internal error", 500)


@app.before_request
def _serialize():
    lock().acquire()


@app.teardown_request
def _release(exc=None):
    lock().release()


import routes_core
import routes_deploy
import routes_misc
import routes_usage

app.register_blueprint(routes_core.bp)
app.register_blueprint(routes_deploy.bp)
app.register_blueprint(routes_misc.bp)
app.register_blueprint(routes_usage.bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
