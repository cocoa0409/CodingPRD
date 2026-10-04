"""Entry point: Flask app assembly, blueprint registration, error handlers."""

import os

from flask import Flask

from errors import ApiError
from resp import error_response
from routes_clock import bp as clock_bp
from routes_chapters import bp as chapters_bp
from routes_volunteers import bp as volunteers_bp
from routes_referrals import bp as referrals_bp
from routes_children import bp as children_bp
from routes_teams import bp as teams_bp
from routes_visits import bp as visits_bp
from routes_wishes import bp as wishes_bp
from routes_offers import bp as offers_bp
from routes_plans import bp as plans_bp
from routes_plan_governance import bp as governance_bp
from routes_clearances import bp as clearances_bp
from routes_events import bp as events_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        clock_bp, chapters_bp, volunteers_bp, referrals_bp, children_bp,
        teams_bp, visits_bp, wishes_bp, offers_bp, plans_bp,
        governance_bp, clearances_bp, events_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(e):
        return error_response(e.error_id, e.message, e.status)

    @app.errorhandler(404)
    def _not_found(_e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(Exception)
    def _unhandled(_e):
        return error_response("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
