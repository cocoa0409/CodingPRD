"""Application entry point: Flask app, error handlers, route registration."""
import os

from flask import Flask

from errors import APIError, err_not_found, err_invalid_request
from response import error_response


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    from routes import (
        rights_grants, seasons, markets, games, week_slates, offers,
        accounts, student_verifications, venue_licenses, subscriptions,
        territory_checks, game_entitlements, complaint_cases,
        entitlement_overrides, multiview_sessions, clock,
    )
    for mod in (
        clock, rights_grants, seasons, markets, games, week_slates, offers,
        accounts, student_verifications, venue_licenses, subscriptions,
        territory_checks, game_entitlements, complaint_cases,
        entitlement_overrides, multiview_sessions,
    ):
        app.register_blueprint(mod.bp)

    @app.errorhandler(APIError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(_err):
        return error_response(err_not_found("Resource not found"))

    @app.errorhandler(405)
    def handle_405(_err):
        return error_response(err_not_found("Resource not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(err)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
