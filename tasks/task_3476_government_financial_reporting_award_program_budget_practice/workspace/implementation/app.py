"""GFOA award-program API — Flask entry point.

Boots with an EMPTY in-memory store (no seeding) and the logical clock pinned
at 2026-09-01T00:00:00Z. Reads PORT (default 10000), binds 0.0.0.0, runs in
the foreground under start.sh.
"""

import os

from flask import Flask

import routes_admin
import routes_assignments
import routes_publications
import routes_reviewers
import routes_scholarships
import routes_submissions
from envelope import error_response
from errors import ApiError


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False

    routes_admin.register(app)
    routes_reviewers.register(app)
    routes_submissions.register(app)
    routes_assignments.register(app)
    routes_publications.register(app)
    routes_scholarships.register(app)

    @app.errorhandler(ApiError)
    def _handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def _handle_404(e):
        return error_response("ERR_NOT_FOUND", 404, "route not found")

    @app.errorhandler(405)
    def _handle_405(e):
        return error_response("ERR_METHOD_NOT_ALLOWED", 405, "method not allowed")

    @app.errorhandler(Exception)
    def _handle_500(e):
        import traceback

        traceback.print_exc()
        return error_response("ERR_INTERNAL", 500, "internal server error")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
