"""Flask entry point: blueprint registration, error handlers, server main."""
import os

from flask import Flask

from db import STORE
from errors import ApiError, ERR_NOT_FOUND, ERR_INTERNAL
from envelope import error_response

import routes_clock
import routes_applicants
import routes_applications
import routes_centers
import routes_programs
import routes_enrollments
import routes_dorm
import routes_conduct
import routes_credentials
import routes_wbl
import routes_transition
import routes_contracts

BLUEPRINTS = (
    routes_clock.bp,
    routes_applicants.bp,
    routes_applications.bp,
    routes_centers.bp,
    routes_programs.bp,
    routes_enrollments.bp,
    routes_dorm.bp,
    routes_conduct.bp,
    routes_credentials.bp,
    routes_wbl.bp,
    routes_transition.bp,
    routes_contracts.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    @app.before_request
    def _acquire_store_lock():
        STORE.lock.acquire()

    @app.teardown_request
    def _release_store_lock(exc):
        try:
            STORE.lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _handle_404(err):
        return error_response(
            ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Resource not found")
        )

    @app.errorhandler(405)
    def _handle_405(err):
        return error_response(
            ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Resource not found")
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        return error_response(ApiError(ERR_INTERNAL[0], ERR_INTERNAL[1], str(err)))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        use_reloader=False,
    )
