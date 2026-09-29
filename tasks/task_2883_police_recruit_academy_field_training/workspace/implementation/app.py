"""Police Recruit Academy & Field Training service (Flask, in-memory)."""
import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from core import ApiError, authenticate, error_response, store

from routes.standards import bp as standards_bp
from routes.classes import bp as classes_bp
from routes.recruits import bp as recruits_bp
from routes.screenings import bp as screenings_bp
from routes.instructors import bp as instructors_bp
from routes.plans import bp as plans_bp
from routes.sessions import bp as sessions_bp
from routes.exams import bp as exams_bp
from routes.rotations import bp as rotations_bp
from routes.records import bp as records_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    app.json.ensure_ascii = False

    for blueprint in (
        standards_bp,
        classes_bp,
        recruits_bp,
        screenings_bp,
        instructors_bp,
        plans_bp,
        sessions_bp,
        exams_bp,
        rotations_bp,
        records_bp,
    ):
        app.register_blueprint(blueprint)

    @app.before_request
    def _before():
        store.lock.acquire()
        g._locked = True
        g._touched = set()
        authenticate()

    @app.teardown_request
    def _teardown(exc):
        if getattr(g, "_locked", False):
            g._locked = False
            try:
                store.lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err.error_id, err.message, err.status)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        return error_response("ERR_INVALID_REQUEST", err.description or "invalid request",
                              err.code or 400)

    @app.errorhandler(Exception)
    def _unexpected(err):
        return error_response("ERR_INVALID_REQUEST", "unexpected error: %s" % err, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False, debug=False)
