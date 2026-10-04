"""Entry point: Flask app, error handlers, blueprint registration."""
import os

from flask import Flask

from common import ApiError, error_response
from services import tick_clock


def create_app():
    app = Flask(__name__)

    from routes.core import bp as core_bp
    from routes.memberships import bp as memberships_bp
    from routes.scholarships import bp as scholarships_bp
    from routes.programs import bp as programs_bp
    from routes.facilities import bp as facilities_bp
    from routes.campaigns import bp as campaigns_bp
    from routes.lists import bp as lists_bp

    for blueprint in (core_bp, memberships_bp, scholarships_bp, programs_bp,
                      facilities_bp, campaigns_bp, lists_bp):
        app.register_blueprint(blueprint)

    @app.before_request
    def _advance_clock_driven_state():
        # Only tick on API requests; the clock itself triggers a full tick too.
        from flask import request as _req
        if _req.path.startswith("/_clock"):
            return None
        tick_clock()
        return None

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ApiError("ERR_NOT_FOUND", "Resource not found"))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ApiError("ERR_NOT_FOUND", "Method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        return error_response(ApiError("ERR_INVALID_REQUEST", str(err)))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
