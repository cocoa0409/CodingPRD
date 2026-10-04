"""Veteran Disaster Response API — Flask entry point.
Mounts all /vdr blueprints and renders the PRD section 2.2 envelope for every
outcome, including framework-level errors.
"""
import os
from flask import Flask
from errors import ApiError
import envelope
from routes import (
    volunteers, certifications, incidents, operations, deployments,
    fobs, shifts, workorders, partners, training, wellness, admin,
)


def create_app():
    app = Flask(__name__)
    for module in (volunteers, certifications, incidents, operations, deployments,
                   fobs, shifts, workorders, partners, training, wellness, admin):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return envelope.error(e)

    @app.errorhandler(404)
    def handle_not_found(e):
        return envelope.error(ApiError("ERR_VALIDATION", 404, "route not found"))

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return envelope.error(ApiError("ERR_VALIDATION", 405, "method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return envelope.error(e)
        return envelope.error(ApiError("ERR_VALIDATION", 500, "internal error: %s" % e))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
