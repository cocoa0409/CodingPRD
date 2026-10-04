"""App factory: error handlers, request lock, blueprint registration."""
import os
import traceback

from flask import Flask

from db import LOCK
from errors import ApiError
from routes import ALL_BLUEPRINTS
from util import error_body


def create_app():
    app = Flask(__name__, static_folder=None)
    app.json.sort_keys = False

    @app.before_request
    def _acquire_lock():
        LOCK.acquire()

    @app.teardown_request
    def _release_lock(_exc=None):
        LOCK.release()

    @app.errorhandler(ApiError)
    def _api_error(e):
        return error_body(e)

    @app.errorhandler(404)
    def _not_found(_e):
        return error_body(ApiError("ERR_NOT_FOUND", 404, "route not found"))

    @app.errorhandler(405)
    def _method_not_allowed(_e):
        return error_body(ApiError("ERR_METHOD_NOT_ALLOWED", 405, "method not allowed"))

    @app.errorhandler(Exception)
    def _unhandled(e):
        traceback.print_exc()
        return error_body(ApiError("ERR_INTERNAL", 500, str(e)))

    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
