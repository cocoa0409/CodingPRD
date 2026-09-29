"""CMAR / GMP administration API.

Flask application factory and error plumbing.  All state lives in memory only
(see db.py); nothing is seeded at startup — every entity is created via the API.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response as resp
from errors import ApiError
from routes.bids import bp as bids_bp
from routes.change_events import bp as change_events_bp
from routes.cost_reports import bp as cost_reports_bp
from routes.draws import bp as draws_bp
from routes.estimates import bp as estimates_bp
from routes.projects import bp as projects_bp
from routes.proposals import bp as proposals_bp
from routes.qualification_items import bp as qualification_items_bp
from routes.subcontracts import bp as subcontracts_bp
from routes.work_packages import bp as work_packages_bp

BLUEPRINTS = (
    projects_bp,
    estimates_bp,
    proposals_bp,
    qualification_items_bp,
    work_packages_bp,
    bids_bp,
    subcontracts_bp,
    change_events_bp,
    draws_bp,
    cost_reports_bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return resp.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return resp.error("ERR_RESOURCE_NOT_FOUND", "the requested route does not exist", 404)

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return resp.error(
            "ERR_INVALID_REQUEST", "the HTTP method is not allowed on this route", 405
        )

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        status = exc.code or 500
        error_id = "ERR_INVALID_REQUEST" if status < 500 else "ERR_INTERNAL"
        return resp.error(error_id, exc.description or "request failed", status)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return resp.error("ERR_INTERNAL", "unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
