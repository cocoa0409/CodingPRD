"""Campus Recruiting Marketplace API — entry point.

Binds 0.0.0.0:$PORT (default 10000) in the foreground. The store starts
empty on every boot; nothing is seeded here.
"""

import os

from flask import Flask, g

import errors
from db import REQUEST_LOCK
from errors import ApiError
from routes import BLUEPRINTS
from util import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _acquire_lock():
        REQUEST_LOCK.acquire()
        g.lock_held = True

    @app.teardown_request
    def _release_lock(_exc):
        if getattr(g, "lock_held", False):
            g.lock_held = False
            REQUEST_LOCK.release()

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def _handle_404(_err):
        return error_response("ERR_INVALID_REQUEST", "Unknown route", 404)

    @app.errorhandler(405)
    def _handle_405(_err):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def _handle_exception(err):
        return error_response("ERR_INVALID_REQUEST", "Internal error: %s" % err, 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
    )
