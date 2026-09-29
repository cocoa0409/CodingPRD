"""Faculty Startup Package & Lab Setup API - application entry point.

Storage is entirely in-memory (plain Python dicts in store.py).  Nothing is
seeded, preloaded or persisted: every process starts with eleven empty
collections and a logical clock pinned to 2026-08-01T00:00:00Z, and all state
is built by the client through the declared endpoints.  The test harness kills
and relaunches this process before every individual test, so a fresh boot must
always yield an identical empty world.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import envelope
import store
from errors import ApiError

import routes.units
import routes.faculty
import routes.packages
import routes.spaces
import routes.renovation
import routes.equipment
import routes.staff
import routes.clock

BLUEPRINTS = (
    routes.units.bp,
    routes.faculty.bp,
    routes.packages.bp,
    routes.spaces.bp,
    routes.renovation.bp,
    routes.equipment.bp,
    routes.staff.bp,
    routes.clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _enter_request():
        # One global lock serialises requests so that read-derived amounts and
        # the version bumps of a single cascade are never interleaved.
        store.LOCK.acquire()
        g._store_locked = True
        store.begin_request()

    @app.teardown_request
    def _leave_request(exc):
        if g.pop("_store_locked", False):
            try:
                store.LOCK.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return envelope.error_response(
            "ERR_RESOURCE_NOT_FOUND", "the requested resource does not exist", 404
        )

    @app.errorhandler(405)
    def _bad_method(exc):
        return envelope.error_response(
            "ERR_VALIDATION", "the HTTP method is not allowed for this path", 400
        )

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        status = exc.code or 500
        if status == 404:
            return envelope.error_response(
                "ERR_RESOURCE_NOT_FOUND", "the requested resource does not exist", 404
            )
        if status in (400, 405, 415):
            return envelope.error_response(
                "ERR_VALIDATION", exc.description or "the request is not valid", 400
            )
        return envelope.error_response(
            "ERR_VALIDATION", exc.description or "the request could not be handled", status
        )

    @app.errorhandler(Exception)
    def _unexpected(exc):
        app.logger.exception("unhandled error")
        return envelope.error_response(
            "ERR_VALIDATION", "the request could not be handled: %s" % exc, 500
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
