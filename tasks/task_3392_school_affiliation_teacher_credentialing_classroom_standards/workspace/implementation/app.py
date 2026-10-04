"""Flask entry point: error handlers and route registration.

All routes are mounted under /society. The server binds 0.0.0.0:$PORT
(default 10000) and runs in the foreground per INSTRUCTION.md.
"""

import os

from flask import Flask

from envelope import error_body
from errors import ApiError
from routes_clock import bp as clock_bp
from routes_catalogs import bp as catalogs_bp
from routes_schools import bp as schools_bp
from routes_classrooms import bp as classrooms_bp
from routes_programs import bp as programs_bp
from routes_placements import bp as placements_bp
from routes_credentials import bp as credentials_bp
from routes_applications import bp as applications_bp
from routes_studies import bp as studies_bp
from routes_visits import bp as visits_bp
from routes_plans import bp as plans_bp
from routes_events import bp as events_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

for bp in (
    clock_bp,
    catalogs_bp,
    schools_bp,
    classrooms_bp,
    programs_bp,
    placements_bp,
    credentials_bp,
    applications_bp,
    studies_bp,
    visits_bp,
    plans_bp,
    events_bp,
):
    app.register_blueprint(bp, url_prefix="/society")


@app.errorhandler(ApiError)
def handle_api_error(err):
    from envelope import error_response
    return error_response(err)


@app.errorhandler(404)
def handle_not_found(err):
    return (error_body("ERR_NOT_FOUND", "The requested resource was not found."), 404)


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return (error_body("ERR_NOT_FOUND", "Method not allowed on this path."), 405)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        from envelope import error_response
        return error_response(err)
    return (error_body("ERR_INTERNAL", "Internal server error."), 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
