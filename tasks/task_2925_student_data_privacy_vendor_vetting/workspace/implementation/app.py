"""Student Data Privacy Vendor Vetting API -- application entry point.

Boots a stateless-on-restart Flask service: all state lives in process memory and
no entity is seeded, so every fresh process starts from an empty register.
"""
import os

from flask import Flask

from core import envelope
from core.errors import ApiError
from routes.applications import bp as applications_bp
from routes.catalog import bp as catalog_bp
from routes.clock import bp as clock_bp
from routes.commitments import bp as commitments_bp
from routes.incidents import bp as incidents_bp
from routes.people import bp as people_bp
from routes.requests import bp as requests_bp
from routes.reviews import bp as reviews_bp
from routes.subprocessors import bp as subprocessors_bp
from routes.telemetry import bp as telemetry_bp
from routes.vendors import bp as vendors_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in (vendors_bp, subprocessors_bp, applications_bp, people_bp, requests_bp,
                      reviews_bp, commitments_bp, catalog_bp, telemetry_bp, incidents_bp,
                      clock_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.err(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return envelope.err("ERR_INVALID_REQUEST", "No such route.", 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return envelope.err("ERR_INVALID_REQUEST", "Method not allowed for this route.", 405)

    @app.errorhandler(400)
    def _bad_request(exc):
        return envelope.err("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return envelope.err(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error")
        return envelope.err("ERR_INVALID_REQUEST", "The request could not be processed.", 400)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
