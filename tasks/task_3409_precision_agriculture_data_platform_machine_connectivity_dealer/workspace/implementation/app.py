"""Entry point: Flask app assembly, blueprint registration, error handlers.

Everything is mounted under the /agdata prefix. The server binds 0.0.0.0 and
listens on $PORT (default 10000), running in the foreground via start.sh.
"""

import os

from flask import Flask

from envelope import error_response
from errors import ERR_NOT_FOUND, ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes_agronomy import bp as agronomy_bp
    from routes_claims import bp as claims_bp
    from routes_consent import bp as consent_bp
    from routes_core import bp as core_bp
    from routes_grants import bp as grants_bp
    from routes_licenses import bp as licenses_bp
    from routes_machines import bp as machines_bp
    from routes_partners import bp as partners_bp
    from routes_plans import bp as plans_bp
    from routes_updates import bp as updates_bp

    for bp in (
        core_bp,
        machines_bp,
        plans_bp,
        agronomy_bp,
        grants_bp,
        consent_bp,
        updates_bp,
        licenses_bp,
        claims_bp,
        partners_bp,
    ):
        app.register_blueprint(bp, url_prefix="/agdata")

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.status)

    @app.errorhandler(404)
    def handle_not_found(e):
        return error_response(ERR_NOT_FOUND, "resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return error_response(ERR_NOT_FOUND, "method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.status)
        return error_response("ERR_INTERNAL", str(e), 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
