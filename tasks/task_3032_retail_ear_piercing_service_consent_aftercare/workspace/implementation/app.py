"""Ear-Piercing Service Consent & Aftercare API.

Entry point: registers the blueprints, installs the error handlers and starts
the server on 0.0.0.0:$PORT (default 10000). The store is process-local and
starts empty; no entity is ever seeded at startup (PRD 2.5).
"""

import os

from flask import Flask, request
from werkzeug.exceptions import HTTPException

import errors as E
import response as R

API_PREFIX = "/piercing-services"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.json.sort_keys = False

    from routes.jurisdictions import bp as jurisdictions_bp
    from routes.certifications import bp as certifications_bp
    from routes.sterilization import bp as sterilization_bp
    from routes.customers import bp as customers_bp
    from routes.consents import bp as consents_bp
    from routes.appointments import bp as appointments_bp
    from routes.incidents import bp as incidents_bp
    from routes.clock import bp as clock_bp

    for blueprint in (jurisdictions_bp, certifications_bp, sterilization_bp,
                      customers_bp, consents_bp, appointments_bp, incidents_bp,
                      clock_bp):
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.errorhandler(E.ApiError)
    def handle_api_error(exc):
        return R.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return R.error_response(E.ERR_NOT_FOUND[0],
                                    "No resource is mounted at this path",
                                    E.ERR_NOT_FOUND[1])
        if exc.code == 405:
            return R.error_response(E.ERR_NOT_FOUND[0],
                                    "Method not allowed for this path",
                                    E.ERR_NOT_FOUND[1])
        return R.error_response(E.ERR_INVALID_REQUEST[0], exc.description,
                                exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("Unhandled error: %s", exc)
        return R.error_response(E.ERR_INVALID_REQUEST[0], str(exc),
                                E.ERR_INVALID_REQUEST[1])

    @app.route("/health", methods=["GET"])
    def health():
        return R.success({"status": "ok"}, "object", 200)

    @app.before_request
    def _guard_unknown_prefix():
        # Only the API mount is served; anything else falls through to Flask's
        # 404 handler so the envelope is still produced.
        if request.path == "/health":
            return None
        return None

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False)