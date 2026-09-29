"""Early intervention service coordination API.

In-memory only: the store is empty on every boot and every entity is created
through the declared API surface.
"""
import os

from flask import Flask

from envelope import error_body
from errors import ApiError, CATALOG
from routes import (assessments, authorizations, children, clock, contact_logs,
                    coordinators, cost_shares, ifsp_services, ifsps, providers,
                    referrals, transition_plans, visits)

BLUEPRINTS = (
    clock.bp,
    children.bp,
    coordinators.bp,
    referrals.bp,
    contact_logs.bp,
    assessments.bp,
    ifsps.bp,
    ifsp_services.bp,
    providers.bp,
    authorizations.bp,
    visits.bp,
    cost_shares.bp,
    transition_plans.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_body(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(400)
    def handle_bad_request(exc):
        return error_body("ERR_INVALID_REQUEST",
                          "The request body could not be parsed.", 400)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return error_body("ERR_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return error_body("ERR_METHOD_NOT_ALLOWED",
                          "That method is not allowed on this route.", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_body(exc.error_id, exc.message, exc.http_status)
        status = getattr(exc, "code", None)
        if isinstance(status, int):
            return error_body("ERR_INVALID_REQUEST", str(exc), status)
        return error_body("ERR_INTERNAL", "Unexpected server error: %s" % exc,
                          500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False)
