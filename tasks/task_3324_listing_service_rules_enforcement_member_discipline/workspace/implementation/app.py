"""Entry point: Flask app, error handlers, route registration.

Binds 0.0.0.0:$PORT (default 10000). Store starts empty; nothing is seeded.
"""

import os

from flask import Flask

from db import lock
from errors import ApiError
from response import error_response

app = Flask(__name__)

# Serialize request handling: the benchmark drives the API sequentially, and a
# global lock keeps cascades (billing loops, panel rulings) atomic.
@app.before_request
def _acquire_lock():
    lock().acquire()


@app.teardown_request
def _release_lock(exc):
    try:
        lock().release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_404(err):
    from errors import ERR_NOT_FOUND
    return error_response(ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(405)
def handle_405(err):
    from errors import ERR_NOT_FOUND
    return error_response(ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(Exception)
def handle_unexpected(err):
    # Never leak a bare 500 HTML page; surface as a structured error.
    from errors import ERR_INVALID_REQUEST
    return error_response(ERR_INVALID_REQUEST, 400, str(err))


def register_blueprints():
    from routes.clock import bp as clock_bp
    from routes.associations import bp as associations_bp
    from routes.members import bp as members_bp
    from routes.offices import bp as offices_bp
    from routes.dues import bp as dues_bp
    from routes.listings import bp as listings_bp
    from routes.citations import bp as citations_bp
    from routes.fines import bp as fines_bp
    from routes.ethics import bp as ethics_bp
    from routes.arbitration import bp as arbitration_bp
    from routes.panels import bp as panels_bp
    from routes.licenses import bp as licenses_bp
    from routes.policy import bp as policy_bp
    from routes.consolidation import bp as consolidation_bp
    for bp in (clock_bp, associations_bp, members_bp, offices_bp, dues_bp,
               listings_bp, citations_bp, fines_bp, ethics_bp, arbitration_bp,
               panels_bp, licenses_bp, policy_bp, consolidation_bp):
        app.register_blueprint(bp)


register_blueprints()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
