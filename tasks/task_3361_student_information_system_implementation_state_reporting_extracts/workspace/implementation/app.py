"""SIS implementation & state reporting extracts — Flask entry point.

Boots with completely empty in-memory state; the logical clock starts at
exactly 2026-09-01T00:00:00Z and only moves via POST /_clock/set_current_utc.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_body


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.clock import bp as clock_bp
    from routes.districts import bp as districts_bp
    from routes.enrollments import bp as enrollments_bp
    from routes.extracts import bp as extracts_bp
    from routes.feeds import bp as feeds_bp
    from routes.incidents import bp as incidents_bp
    from routes.portal import bp as portal_bp
    from routes.rollover import bp as rollover_bp
    from routes.school_years import bp as years_bp
    from routes.sections import bp as sections_bp
    from routes.specs import bp as specs_bp
    from routes.students import bp as students_bp
    from routes.courses import bp as courses_bp

    for bp in (clock_bp, districts_bp, years_bp, specs_bp, students_bp,
               courses_bp, sections_bp, enrollments_bp, incidents_bp,
               extracts_bp, portal_bp, feeds_bp, rollover_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(e):
        return error_body(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def _handle_404(e):
        return error_body("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def _handle_405(e):
        return error_body("ERR_NOT_FOUND", 405, "Method not allowed")

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        return error_body("ERR_INTERNAL", 500, "Internal server error")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
