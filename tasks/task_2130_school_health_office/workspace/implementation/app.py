"""School Health Office API — Flask entry point.

Storage is in-memory only and starts completely empty on every boot; no entity
is ever seeded, preloaded or hardcoded at startup.
"""
import os
import threading

from flask import Flask, request

from envelope import error_response
from errors import ApiError
from store import db

import routes_provision
import routes_students
import routes_meds
import routes_visits
import routes_admin
import routes_records
import routes_ops


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(routes_provision.bp)
    app.register_blueprint(routes_students.bp)
    app.register_blueprint(routes_meds.bp)
    app.register_blueprint(routes_visits.bp)
    app.register_blueprint(routes_admin.bp)
    app.register_blueprint(routes_records.bp)
    app.register_blueprint(routes_ops.bp)

    request_lock = threading.Lock()

    @app.before_request
    def _begin_request():
        request_lock.acquire()
        db.touched = set()

    @app.teardown_request
    def _end_request(_exc=None):
        try:
            request_lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _not_found(_err):
        return error_response(ApiError("ERR_RESOURCE_NOT_FOUND", "Unknown route."))

    @app.errorhandler(405)
    def _method_not_allowed(_err):
        return error_response(ApiError("ERR_RESOURCE_NOT_FOUND", "Unknown route."))

    @app.errorhandler(Exception)
    def _unhandled(err):
        if isinstance(err, ApiError):
            return error_response(err)
        app.logger.exception("unhandled error")
        return error_response(ApiError("ERR_INVALID_FIELD_VALUE", str(err)))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
