"""Preschool Special Education Child Find & Evaluation API."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from middleware import require_identity
from response import error_response
from routes.children import bp as children_bp
from routes.clock import bp as clock_bp
from routes.consent import bp as consent_bp
from routes.evaluation import bp as evaluation_bp
from routes.plans import bp as plans_bp
from routes.providers import bp as providers_bp
from routes.referrals import bp as referrals_bp
from routes.screening import bp as screening_bp
from routes.sites import bp as sites_bp

API_PREFIX = "/child-find"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for blueprint in (
        clock_bp,
        children_bp,
        sites_bp,
        providers_bp,
        screening_bp,
        referrals_bp,
        consent_bp,
        evaluation_bp,
        plans_bp,
    ):
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.before_request
    def _authenticate():
        # Rung 1 runs before path resolution, so a bogus path with no identity
        # header still answers 401.
        require_identity()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found", 404)
        if exc.code == 405:
            return error_response("ERR_NOT_FOUND", "Method not allowed for this path", 404)
        if exc.code and exc.code >= 500:
            return error_response("ERR_INVALID_REQUEST", "Internal error", 500)
        return error_response("ERR_INVALID_REQUEST", exc.description or "Bad request", 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return error_response("ERR_INVALID_REQUEST", "Unhandled error: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
